"""`config.PIN_ROUTED_MODEL`: a router's turn can stay on the model it served first.

Off, every request of a turn asks the router, which is what the app has always done,
and the first test holds that. On, the rounds after the first tool round ask for the
concrete model the router served it, and a pinned request that fails goes back to the
router within the same round, once, without a backoff.
"""

from __future__ import annotations

import pytest
from test_app_smoke import event, run_app, tool_call

import stub_streamlit
from sage import config, providers

ROUTER = "openrouter/free"
SERVED = "vendor/small-model:free"


@pytest.fixture(autouse=True)
def _clean_modules():
    yield
    stub_streamlit.forget_importers()


class Router:
    """The free router as the turn sees it: one id, a served model on each stream."""

    name = "openrouter"

    def __init__(self, turns, refuse_pinned=False):
        self.turns = list(turns)
        self.asked: list[str] = []
        self.refuse_pinned = refuse_pinned

    def models(self):
        return [providers.Model(self.name, ROUTER)]

    def stream(self, model, messages, tools, thinking=False, tool_choice="auto"):
        self.asked.append(model)
        if self.refuse_pinned and model != ROUTER:
            error = RuntimeError(
                "HTTP 429: vendor/small-model:free is temporarily rate-limited upstream"
            )
            error.status_code = 429
            raise error
        if not self.turns:
            raise AssertionError("provider called more times than scripted")
        yield from self.turns.pop(0)


SEARCH = [
    providers.Chunk(model=SERVED, tool_calls=[
        tool_call(0, "c1", "search_docs", '{"query":"storage quota"}')]),
]
ANSWER = [event("Your quota is 30 GB.")]


def asking() -> dict:
    return {
        "messages": [{"role": "user", "text": "what is my quota", "attachments": []}],
        "processing": True,
        "model": f"openrouter:{ROUTER}",
    }


def run(monkeypatch, router, pin):
    monkeypatch.setattr(config, "PIN_ROUTED_MODEL", pin)
    stub, _module = run_app(monkeypatch, client=router, session=asking(),
                            openrouter=True)
    return stub


def test_off_every_request_asks_the_router(monkeypatch):
    router = Router([SEARCH, ANSWER])
    stub = run(monkeypatch, router, pin=False)
    assert router.asked == [ROUTER, ROUTER]
    assert stub.session_state["messages"][-1]["text"].startswith("Your quota")


def test_on_the_later_rounds_ask_for_the_served_model(monkeypatch):
    router = Router([SEARCH, ANSWER])
    stub = run(monkeypatch, router, pin=True)
    assert router.asked == [ROUTER, SERVED]
    assert stub.session_state["messages"][-1]["text"].startswith("Your quota")
    assert stub.session_state["model"] == f"openrouter:{ROUTER}", (
        "the pin is for this turn only; the session stays on the router"
    )


def test_a_pinned_model_that_refuses_hands_the_round_back(monkeypatch):
    router = Router([SEARCH, ANSWER], refuse_pinned=True)
    stub = run(monkeypatch, router, pin=True)
    assert router.asked == [ROUTER, SERVED, ROUTER], (
        "one try of the pinned model, no backoff retries, then the router"
    )
    assert stub.session_state["messages"][-1]["text"].startswith("Your quota")
    assert stub.session_state["error"] is None

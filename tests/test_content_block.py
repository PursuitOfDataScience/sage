"""A content-policy refusal stops the turn where it is, through the real app.

`llm.classify` names a guardrail block or a moderation flag `blocked`, and that kind is
the one `turn.FAILOVER_KINDS` and the error card both leave alone: walking on, or a
button that resends, would hand the refused content to a provider the operator's policy
does not cover. Try again stays, because the reader can take out what was flagged.
"""

from __future__ import annotations

import pytest
from test_app_smoke import ScriptedProvider, event, run_app

import stub_streamlit
from sage import llm


@pytest.fixture(autouse=True)
def _clean_modules():
    yield
    stub_streamlit.forget_importers()


def blocked() -> RuntimeError:
    error = RuntimeError(
        'HTTP 403 from https://openrouter.ai/api/v1/chat/completions: {"error":'
        '{"code":403,"message":"Request blocked: prompt injection patterns '
        'detected","metadata":{"patterns":["ignore all previous instructions"]}}}'
    )
    error.status_code = 403
    return error


def asked(**extra) -> dict:
    return {
        "messages": [{"role": "user", "text": "hello", "attachments": []}],
        "model": "google:m1",
    } | extra


def test_the_turn_stops_instead_of_failing_over(monkeypatch):
    guarded = ScriptedProvider([], name="google", models=("m1",), error=blocked())
    elsewhere = ScriptedProvider([[event("should never be asked")]],
                                 name="vertex", models=("z1",))
    stub, _m = run_app(monkeypatch, client=guarded, extra={"vertex": elsewhere},
                       session=asked(processing=True), second=True)
    assert stub.session_state["model"] == "google:m1"
    assert stub.session_state["processing"] is False
    assert stub.session_state["error_kind"] == "blocked"
    assert elsewhere.calls == 0, "the blocked content was handed to another provider"


def test_the_card_offers_no_switch(monkeypatch):
    guarded = ScriptedProvider([], name="google", models=("m1",))
    elsewhere = ScriptedProvider([], name="vertex", models=("z1",))
    session = asked(
        processing=False,
        error=llm.AssistantError("blocked").user_message,
        error_detail="HTTP 403 Request blocked",
        error_kind="blocked",
    )
    stub, _m = run_app(monkeypatch, client=guarded, extra={"vertex": elsewhere},
                       session=session, second=True)
    assert "retry" in stub.button_labels
    assert "switch-model" not in stub.button_labels


def test_a_spent_cap_still_walks_to_another_provider(monkeypatch):
    """The other new reading of a 403, end to end: a key limit is `quota`, which leaves
    for the next provider instead of telling the reader the key was rejected."""
    capped = RuntimeError(
        'HTTP 403 from https://openrouter.ai/api/v1/chat/completions: {"error":'
        '{"code":403,"message":"Key limit exceeded ($5.00 of $5.00 used)",'
        '"metadata":{"limit_source":"openrouter_key_limit"}}}'
    )
    capped.status_code = 403
    spent = ScriptedProvider([], name="google", models=("m1",), error=capped)
    elsewhere = ScriptedProvider([], name="vertex", models=("z1",))
    stub, _m = run_app(monkeypatch, client=spent, extra={"vertex": elsewhere},
                       session=asked(processing=True), second=True)
    assert stub.session_state["model"] == "vertex:z1"
    assert stub.session_state["processing"] is True, "the turn should be retried"

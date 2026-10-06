"""What a provider is, and the shapes every one of them normalises onto.

`Model` and `Chunk` are the whole contract with the rest of the app: a turn is a
stream of `Chunk`s and a picker row is a `Model`, and nothing downstream (the tool
loop, the failover, the history builder) knows which endpoint produced either.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Protocol

from .. import config

# One bound for every adapter, so a hung stream cannot hold a script run open on
# whichever provider the reader happened to pick. The HTTP adapter spells the same
# 120s as an `httpx.Timeout`.
STREAM_TIMEOUT_MS = 120_000

# The id segment marking a no-cost tier. Matched on `Model.label` only; the id itself
# is never rewritten, so what is sent upstream stays exactly what the provider serves.
_TIER_MARK = "free"


def _shown(provider: str, model_id: str) -> str:
    """What the profile calls this served id, or "" if it says nothing.

    Imported inside the call rather than at the top of the module. `Model` is the
    contract the adapters are written against and it is constructed in tests and tools
    that have no profile loaded at all; a module-level import would make reading a
    label depend on the whole composition root being up. Failing soft is the right
    answer here anyway: a missing profile means the id speaks for itself, which is
    what it did before this existed.
    """
    try:
        from ..profile import active  # noqa: PLC0415

        entry = active().provider(provider)
    except Exception:  # noqa: BLE001 (a name is never worth failing a render for)
        return ""
    return entry.label_for(model_id) if entry else ""


@dataclass(frozen=True)
class Model:
    provider: str
    id: str

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.id}"

    @property
    def label(self) -> str:
        """The model's own name, and nothing else.

        There was a provider prefix, "Zen · deepseek-v4-flash", which spent a third
        of the picker's width restating what the rest of the row already said, on
        every line. The id alone identifies the model, and `mistral-` on the front of
        the Mistral ones does the same job the prefix was doing.

        The tier marker in an id is dropped for the same reason: it is billing
        plumbing, not part of the model's name. It still belongs in `key`, which is
        what goes upstream, and in the discovery filter that reads it; but a picker
        row is where a reader is choosing between models, and the marker says nothing
        about the choice. Removed by segment, so only a whole `-free-` word goes.

        The profile gets the first word, for the case the tier rule above cannot reach:
        an id that is not a name at all. A router's id describes the billing
        arrangement (which free tier it draws on), and a reader choosing a row in a
        picker is not choosing a billing arrangement. So a deployment may say what to
        call one, and only that; the id is untouched in `key`, upstream, in the feedback
        log, in `tools/agent_bench.py` and in the technical-details panel, so nothing
        that measures a model ends up measuring a nickname.

        Read through the profile rather than a table here, because a name is copy and
        `sage/` is not allowed to hold the deployment's words: `tests/test_profile.py`
        enforces that, and would fail on a literal in this file.
        """
        shown = _shown(self.provider, self.id)
        if shown:
            return shown
        kept = [part for part in self.id.split("-") if part.lower() != _TIER_MARK]
        return "-".join(kept) or self.id

    @property
    def supports_tools(self) -> bool:
        """Some free models cannot call tools; those fall back to plain retrieval."""
        lowered = self.id.lower()
        return not any(mark and mark in lowered for mark in config.TOOLLESS_MODELS)


@dataclass
class Chunk:
    """One normalised streaming event.

    The last four fields are what an endpoint says about the call rather than the
    answer, and every one of them is optional because most events carry none of them.
    `model` is the id that actually served the request, which on a router is not the
    id that was asked for; `tokens_in` and `tokens_out` arrive once, usually on the
    final event, and only from an endpoint that reports usage at all. Nothing that
    draws the answer reads them: `llm.Turn` keeps the latest of each for the call
    record, and that is their whole audience.
    """

    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    model: str = ""
    finish_reason: str = ""
    tokens_in: int | None = None
    tokens_out: int | None = None


def usage_counts(raw) -> tuple[int | None, int | None]:
    """`(tokens_in, tokens_out)` from an OpenAI-shaped `usage`, dict or SDK object.

    Output is `total - prompt` where the endpoint reports a total larger than prompt
    plus completion, and that is not pedantry. Gemini's OpenAI layer leaves its
    thinking out of `completion_tokens` and puts it in the total, while billing it as
    output: measured on Vertex on 2026-10-06, a one-word answer came back as 7 prompt,
    1 completion and 65 total tokens, with 57 of them reported as reasoning. Taken at
    its word that call cost one token of output, and it cost 58. Everywhere else
    measured the total is the plain sum, so the difference IS the completion and the
    rule changes nothing.

    `(None, None)` for anything that is not a usage report, so a missing count stays
    missing rather than becoming a zero someone sums. And never an exception: this runs
    inside the stream parser, where a raise ends the turn, and `json.loads` reads
    `Infinity` and `NaN` without complaint while `int()` of either raises.
    """
    if raw is None:
        return None, None

    def read(name: str) -> int | None:
        value = raw.get(name) if isinstance(raw, dict) else getattr(raw, name, None)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return int(value)

    try:
        prompt, completion, total = (
            read("prompt_tokens"), read("completion_tokens"), read("total_tokens")
        )
    except Exception:  # noqa: BLE001 (an SDK object whose attribute raises)
        return None, None
    if completion is not None and total is not None and prompt is not None:
        completion = max(completion, total - prompt)
    elif completion is None and total is not None and prompt is not None:
        completion = total - prompt
    return prompt, completion


@dataclass(frozen=True)
class CallTag:
    """What a request may say about where it came from: a session and a turn.

    For an endpoint that can group requests (OpenRouter forwards both to whatever
    observability destination its account has configured), and only where the profile
    entry names the header or field to carry them in. `session` is a random id minted
    per browser session, never the signed-in account; `turn_id` groups the calls of one
    question, failovers included; `round` is the tool round within the model that is
    answering.
    """

    session: str = ""
    turn_id: str = ""
    round: int = 0


# Set by `llm.start` for exactly as long as it takes to open a stream, which is the only
# moment an adapter builds its headers and body. A context variable rather than a
# parameter of `Provider.stream`, because `stream` is the contract every adapter
# implements, including one a deployment registers for itself and the test doubles
# that stand in for them: a new parameter there breaks each of them on its first
# request, while an adapter that never reads this simply sends nothing. Streamlit runs
# every session's script in a thread of its own, and a context variable is per thread,
# so one reader's tag cannot reach another reader's request.
_TAG: ContextVar[CallTag | None] = ContextVar("sage_call_tag", default=None)


@contextmanager
def tagged(tag: CallTag | None):
    """Make `tag` what `current_tag` returns inside the block, and put the old one back."""
    token = _TAG.set(tag)
    try:
        yield
    finally:
        _TAG.reset(token)


def current_tag() -> CallTag | None:
    """The tag of the request being opened, or None outside `llm.start`."""
    return _TAG.get()


class Provider(Protocol):
    name: str

    def models(self) -> list[Model]: ...

    #: `thinking` is the reader's Think toggle. Every adapter takes it and an
    #: adapter whose wire format has no such field ignores it; the alternative was
    #: `**kwargs` on the one method every provider must implement, which makes a typo
    #: at a call site silent. Whether it is ever True is decided upstream by
    #: `ProviderEntry.reasoning`, so an adapter that ignores it is never handed it.
    #: `tool_choice` is "auto" everywhere but the last round of a turn, where it is
    #: "none": the schemas go up so the request still looks like a tool-calling one,
    #: and the call is forbidden so the model answers. That is not a nicety on a free
    #: ROUTER (see `ui.turn`, where the round is made). Named rather than passed as a
    #: bare bool for the same reason `thinking` is a parameter and not `**kwargs`: a
    #: typo at a call site should not be silent.
    def stream(
        self, model: str, messages: list[dict], tools: list[dict] | None,
        thinking: bool = False, tool_choice: str = "auto",
    ) -> Iterator[Chunk]: ...


def family_of(model_id: str) -> str:
    """The maker's name at the front of a model id: `nemotron-3.5-lightning-free`
    and `nemotron-3-ultra-free` are both `nemotron`.

    The first segment, and nothing cleverer. Every id either provider serves puts the
    family first and the version straight after it (`ling-3.0-tiny`, `deepseek-v4`,
    `mistral-small-latest`, `gpt-5.2-codex`), so the split is where the version
    begins. A rule that tried to parse the version out as well would have to know
    that `laguna-s-2.1` has a letter in the middle and `big-pickle` has no version at
    all, and it would be wrong about the next naming scheme a free tier invents. This
    one degrades into "a family of one", which is what an unrecognised name should be.
    """
    return (model_id or "").split("-", 1)[0].lower()


def tool_fragments(raw) -> list[dict]:
    """Normalise a delta's tool_calls, whether objects (SDK) or dicts (JSON).

    A sequence, and checked for it: `{"tool_calls": "nope"}` is iterable, so a malformed
    event produced one nameless fragment per *character*: four phantom tool calls from a
    four-letter string. Nothing downstream ran them, because `Turn.deltas` keeps only
    fragments that carry a name, but they still counted as tool calls in everything that
    measures a turn.
    """
    if isinstance(raw, (str, bytes, dict)) or raw is None:
        return []
    fragments = []
    for index, call in enumerate(raw):
        if isinstance(call, dict):
            function = call.get("function") or {}
            fragment = {
                "index": call.get("index", index) or 0,
                "id": call.get("id") or "",
                "name": function.get("name") or "",
                "arguments": function.get("arguments") or "",
            }
            # The provider's own metadata for this call, kept so it can go back
            # verbatim with the call. Gemini 3 puts a `thought_signature` here, on
            # Vertex and on the Gemini API alike, and answers the next round with
            # `400 Function call is missing a thought_signature` if the call returns
            # without it: every tool turn died on its second request. Opaque on
            # purpose, and only present when sent, so no other wire shape changes.
            extra = call.get("extra_content")
            if isinstance(extra, dict) and extra:
                fragment["extra_content"] = extra
            fragments.append(fragment)
            continue
        function = getattr(call, "function", None)
        fragments.append(
            {
                "index": getattr(call, "index", index) or 0,
                "id": getattr(call, "id", "") or "",
                "name": getattr(function, "name", "") or "",
                "arguments": getattr(function, "arguments", "") or "",
            }
        )
    return fragments


def flatten(content) -> str:
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part if isinstance(part, str) else (
                part.get("text", "") if isinstance(part, dict)
                else getattr(part, "text", "") or ""
            )
            for part in content
        )
    return str(content)

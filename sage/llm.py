"""Turn assembly, streaming, and error classification.

There used to be two near-identical stream readers — one that yielded deltas for
the UI and one that collected silently — and the tool loop used the silent one for
its final round. The result was that the *most common* interaction (search → read →
answer) never streamed: users watched a shimmer, then the whole answer appeared at
once. One reader now serves both, so every answer streams.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from . import config
from .profile import active as _active
from .providers import Chunk

logger = logging.getLogger(__name__)

_RETRYABLE = {"rate_limit", "network", "unavailable"}

# `{operator}` is the one deployment-specific word in here, and it is deployment-
# specific because the sentence is addressed to whoever can fix a rejected key. Every
# other message is about the model or the network and reads the same anywhere.
_MESSAGES = {
    "auth": "The assistant is not configured correctly (API key rejected). "
            "Please tell {operator}.",
    "rate_limit": "The assistant is busy right now. Please wait a moment and retry.",
    "quota": "This model is out of credit or its quota is used up. "
             "Switch to another model and try again.",
    # Distinct from `quota`, because the remedy is different and the difference is
    # not cosmetic. A spent *key* kills every model behind it, so the way out is a
    # different provider. A spent *free allowance* is metered per model: the other
    # models on the same key answer immediately, and sending the reader to a second
    # provider — whose key may itself be out of credit — walks them into another
    # dead end.
    "allowance": "This model has used up its free allowance for now. "
                 "Another model can answer it — try one from the model button.",
    "context": "This conversation got too long for the model. "
               "Clear the chat and ask again.",
    # Not a transport failure: the request succeeded and the stream carried no text.
    # Free models do it — a content filter, a stop token on the first byte, a hiccup
    # that ends the stream cleanly — and the answer has to say so, because the
    # alternative shipped: an empty bubble under the question, or on a stream with no
    # deltas at all, nothing whatsoever. No error, no answer, nothing to click.
    # No "with the button under the input box": a deployment with one model has no
    # picker and no switch button on the card, and advice that names a control which
    # is not there is worse than advice that does not.
    "empty": "The model returned an empty answer. Try again, or use a different "
             "model.",
    "network": "Could not reach the assistant. Check the connection and retry.",
    "unavailable": "The assistant is temporarily unavailable. Please retry shortly.",
    "unknown": "Something went wrong reaching the assistant. Please try again.",
}

#: Every failure this module can name. Public because the UI decides what to do about
#: each one and has to be able to enumerate them rather than list them again by hand:
#: `sage/ui/turn.py` fails a turn over to another model for all of these *except* a
#: named few, so a kind added here is automatically covered instead of silently
#: dead-ending the reader until someone remembers the second list.
KINDS = frozenset(_MESSAGES)


class AssistantError(Exception):
    def __init__(self, kind: str, original: BaseException | None = None) -> None:
        self.kind = kind if kind in _MESSAGES else "unknown"
        self.original = original
        self._message = _MESSAGES[self.kind].replace(
            "{operator}", _active().identity.operator
        )
        super().__init__(self._message)

    @property
    def user_message(self) -> str:
        return self._message

    @property
    def retryable(self) -> bool:
        return self.kind in _RETRYABLE


def classify(exc: BaseException) -> AssistantError:
    if isinstance(exc, AssistantError):
        return exc

    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status is None:
        # httpx.HTTPStatusError keeps the code on .response
        status = getattr(getattr(exc, "response", None), "status_code", None)
    text = f"{type(exc).__name__} {exc}".lower()

    if status in (401, 403) or "unauthorized" in text or "invalid api key" in text:
        kind = "auth"
    elif any(needle in text for needle in ("usage limit", "usagelimit", "usage_limit")):
        # A free tier's allowance, spent. It arrives as a 429 whose body names
        # `FreeUsageLimitError` and whose *message* reads "Rate limit exceeded. Please
        # try again later." — so both the status and the prose say "wait", and waiting
        # is the one thing that does not work: the allowance resets on the provider's
        # schedule, not in a moment. Told to wait, a reader sat on a dead model while
        # other free models on the same key answered in under a second.
        #
        # Checked before the 402 branch and before the 429 one, because the body
        # satisfies both and only this reading of it leads anywhere useful. Matched on
        # the limit's *name*, which is the one part of that body that means what it
        # says.
        kind = "allowance"
    elif status == 402 or any(
        needle in text
        for needle in ("quota", "insufficient", "credit", "billing",
                       "check your subscription", "payment")
    ):
        # Out of credit does not recover by waiting, so it is deliberately not
        # retryable — switching provider is the only useful action.
        kind = "quota"
    elif status == 429 or "rate limit" in text or "too many requests" in text:
        kind = "rate_limit"
    elif (
        ("context" in text and ("length" in text or "token" in text))
        or "too large" in text
        or status == 413
    ):
        kind = "context"
    elif isinstance(status, int) and 500 <= status < 600:
        kind = "unavailable"
    elif any(
        needle in text
        for needle in ("timeout", "timed out", "connection", "network", "dns", "ssl")
    ):
        kind = "network"
    else:
        kind = "unknown"
    return AssistantError(kind, exc)


@dataclass
class Turn:
    """One model turn. Iterate `deltas()` to stream, or `consume()` to block.

    Consumes normalised `Chunk`s, so Mistral and any OpenAI-compatible endpoint
    go through exactly the same assembly and error handling.
    """

    stream: Any
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finished: bool = False

    def deltas(self) -> Iterator[str]:
        # Fragments are assembled by `index`, which is how an OpenAI-style stream
        # says which call a later chunk of arguments belongs to — but the index is
        # not always distinct. mistralai 2.x declares `ToolCall.index` defaulting to
        # 0, so two calls issued in ONE delta both arrive as index 0: the second
        # overwrote the first's id and name, their JSON was concatenated into
        # `{"query":"a"}{"path":"x"}`, `_parse` gave up on it, and the turn ran one
        # tool with no arguments. A search that never happened, and an answer with
        # an empty Sources strip.
        #
        # So a fragment that carries a DIFFERENT id starts a new call rather than
        # joining the one already at that index. Argument-only fragments (no id, the
        # ordinary continuation shape) still land on the newest call at their index,
        # which is what keeps a normal multi-chunk stream assembling correctly.
        pending: list[dict] = []
        newest: dict[int, dict] = {}
        try:
            for chunk in self.stream:
                if not isinstance(chunk, Chunk):
                    continue
                if chunk.text:
                    self.text += chunk.text
                    yield chunk.text
                for fragment in chunk.tool_calls:
                    index = fragment["index"]
                    slot = newest.get(index)
                    identifier = fragment.get("id") or ""
                    if slot is None or (
                        identifier and slot["id"] and identifier != slot["id"]
                    ):
                        slot = {"id": "", "name": "", "args": ""}
                        pending.append(slot)
                        newest[index] = slot
                    if identifier:
                        slot["id"] = identifier
                    if fragment.get("name"):
                        slot["name"] = fragment["name"]
                    if fragment.get("arguments"):
                        slot["args"] += fragment["arguments"]
        except Exception as exc:
            raise classify(exc) from exc

        self.tool_calls = [
            {"id": slot["id"], "name": slot["name"], "input": _parse(slot["args"])}
            for slot in pending
            if slot["name"]
        ]
        self.finished = True

    def consume(self) -> Turn:
        for _ in self.deltas():
            pass
        return self

    def as_message(self) -> dict:
        """The assistant message to append before tool results."""
        return {
            "role": "assistant",
            "content": self.text,
            "tool_calls": [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call["input"]),
                    },
                }
                for call in self.tool_calls
            ],
        }


def _parse(arguments: str) -> dict:
    if not arguments:
        return {}
    try:
        parsed = json.loads(arguments)
    except (json.JSONDecodeError, RecursionError):
        # `RecursionError` is the one `json.loads` raises on deep nesting rather than a
        # decode error, and tool arguments are a *model's* free text: a model that has
        # started repeating itself emits exactly `[[[[[…`. Unguarded it left this
        # function, which the whole tool loop assumes returns a dict, and took the turn
        # down as an unknown failure. Arguments this cannot read are already an empty
        # dict, and each tool answers that with its own error message to the model.
        logger.warning("Unparseable tool arguments: %r", arguments[:200])
        return {}
    return parsed if isinstance(parsed, dict) else {}


def start(provider, model: str, messages: list[dict],
          tools: list[dict] | None = None) -> Turn:
    """Open a streaming turn, retrying transient failures before any output."""
    attempts = max(config.REQUEST_RETRIES, 0) + 1
    last: AssistantError | None = None

    for attempt in range(attempts):
        try:
            stream = provider.stream(model, messages, tools)
            # `stream` is a generator, so the request has not been made yet. Pull
            # the first chunk here so connection and auth failures surface where
            # they can still be retried, rather than mid-render.
            first = next(stream, None)
            return Turn(stream=_replay(first, stream))
        except Exception as exc:
            error = classify(exc)
            last = error
            if not error.retryable or attempt == attempts - 1:
                raise error from exc
            delay = 2**attempt
            logger.warning(
                "Transient %s from %s, retrying in %ss", error.kind, provider.name, delay
            )
            time.sleep(delay)

    raise last or AssistantError("unknown")


def _replay(first, rest) -> Iterator[Chunk]:
    if first is not None:
        yield first
    yield from rest


def rejects_tools(exc: BaseException) -> bool:
    """Whether a failure looks like the model simply not supporting tool calls."""
    text = f"{type(exc).__name__} {exc}".lower()
    return ("tool" in text or "function" in text) and any(
        mark in text for mark in
        ("not support", "unsupported", "invalid", "unknown parameter", "unrecognized")
    )


def tool_result_message(call: dict, content: str) -> dict:
    return {
        "role": "tool",
        "tool_call_id": call["id"],
        "name": call["name"],
        "content": content,
    }

"""What a provider is, and the shapes every one of them normalises onto.

`Model` and `Chunk` are the whole contract with the rest of the app: a turn is a
stream of `Chunk`s and a picker row is a `Model`, and nothing downstream — the tool
loop, the failover, the history builder — knows which endpoint produced either.
"""

from __future__ import annotations

from collections.abc import Iterator
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
    answer here anyway — a missing profile means the id speaks for itself, which is
    what it did before this existed.
    """
    try:
        from ..profile import active  # noqa: PLC0415

        entry = active().provider(provider)
    except Exception:  # noqa: BLE001 — a name is never worth failing a render for
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

        There was a provider prefix — "Zen · deepseek-v4-flash" — which spent a third
        of the picker's width restating what the rest of the row already said, on
        every line. The id alone identifies the model, and `mistral-` on the front of
        the Mistral ones does the same job the prefix was doing.

        The tier marker in an id is dropped for the same reason: it is billing
        plumbing, not part of the model's name. It still belongs in `key`, which is
        what goes upstream, and in the discovery filter that reads it — but a picker
        row is where a reader is choosing between models, and the marker says nothing
        about the choice. Removed by segment, so only a whole `-free-` word goes.

        The profile gets the first word, for the case the tier rule above cannot reach:
        an id that is not a name at all. A router's id describes the billing
        arrangement — which free tier it draws on — and a reader choosing a row in a
        picker is not choosing a billing arrangement. So a deployment may say what to
        call one, and only that; the id is untouched in `key`, upstream, in the feedback
        log, in `tools/agent_bench.py` and in the technical-details panel, so nothing
        that measures a model ends up measuring a nickname.

        Read through the profile rather than a table here, because a name is copy and
        `sage/` is not allowed to hold the deployment's words — `tests/test_profile.py`
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
    """One normalised streaming event."""

    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)


class Provider(Protocol):
    name: str

    def models(self) -> list[Model]: ...

    def stream(
        self, model: str, messages: list[dict], tools: list[dict] | None
    ) -> Iterator[Chunk]: ...


def family_of(model_id: str) -> str:
    """The maker's name at the front of a model id — `nemotron-3.5-lightning-free`
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
    event produced one nameless fragment per *character* — four phantom tool calls from a
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
            fragments.append(
                {
                    "index": call.get("index", index) or 0,
                    "id": call.get("id") or "",
                    "name": function.get("name") or "",
                    "arguments": function.get("arguments") or "",
                }
            )
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

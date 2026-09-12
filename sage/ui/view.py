"""What one render of the page has to hand: the assistant, and the chosen model.

Passed to every draw function rather than read from module globals. `app.py` used to
hold `CORPUS`, `INDEX`, `MODELS` and `MODEL` at module scope and forty functions
closed over them, which is why none of those functions could be moved out of it: each
one silently depended on the whole file having run first.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..profile import Copy, Identity
from ..providers import Model, family_of
from ..runtime import Runtime


@dataclass(frozen=True)
class View:
    runtime: Runtime
    #: Every model the configured providers offer, in preference order.
    models: tuple[Model, ...]
    #: The one this session is asking.
    model: Model

    @property
    def identity(self) -> Identity:
        return self.runtime.identity

    @property
    def copy(self) -> Copy:
        return self.runtime.copy

    @property
    def corpus(self):
        return self.runtime.corpus

    @property
    def examples(self):
        return self.runtime.examples

    @property
    def public_names(self) -> dict[str, str]:
        """What each tool is called in front of a reader — for `sage.redact`."""
        return self.runtime.toolset.public_names

    #: Failures whose remedy is a different model on the SAME provider, because the
    #: key is fine and only this model is unavailable. Each of these is the *model*
    #: declining: a spent free allowance is metered per model, an empty stream and a
    #: written-out reasoning monologue are things one model does and another does not,
    #: a 5xx is that model's backend, and an unclassified failure has nothing pointing
    #: at the key. The ones left out — a spent key, a rejected key, an unreachable
    #: host — are about the credential or the connection, and the only useful jump
    #: from those is to a different provider.
    #:
    #: This decides *direction*, not whether to hop at all: `turn.FAILOVER_KINDS` and
    #: `config.MAX_MODEL_ATTEMPTS` decide that, and a key-level failure walks the
    #: lineup too — starting with the other provider.
    PER_MODEL = frozenset({"allowance", "empty", "rate_limit", "unavailable", "unknown"})

    def alternative(self, kind: str = "", skip: Sequence[str] = ()) -> Model | None:
        """The best other model to try, given what went wrong.

        Which way to jump depends on the failure, and getting this wrong walks the
        reader from one dead end into another:

        * A spent **key** — 402, or a rejected key — kills every model behind it, so
          the way out is a different provider.
        * A spent **free allowance** is metered per model. `deepseek-v4-flash-free`
          answered `FreeUsageLimitError` while `nemotron-3-ultra-free` on the same key
          answered in under a second, and the other provider's key was itself out of
          credit — so preferring a different provider offered a second dead end while
          a working model sat one row down the picker.

        Either preference falls back to the other rather than to nothing: with one
        provider configured there was no switch button at all, on a screen whose own
        error text says to switch. `models` is in preference order, so each branch
        takes the best candidate rather than an alphabetical accident.

        `skip` is what the turn has already tried, so a second hop does not land back
        on a model that has just refused.

        Within a provider, a **different family** first — and this is not tidiness, it
        is the difference between a hop that works and one that cannot. OpenCode Zen
        meters its free models in a daily bucket keyed on the first two characters of
        the model id, so `nemotron-3.5-lightning-free` and `nemotron-3-ultra-free`
        share one counter: a model out of allowance hands its sibling a counter that
        is, by definition, already spent. `family_of` is the general form of that —
        siblings share a maker, and a maker is what a tier meters — and it costs
        nothing where a provider meters some other way.

        Every family the turn has already burned, not merely the current one. Taking
        it from `self.model` alone left a hole one hop wide: starting on
        `nemotron-3.5-lightning-free`, hop 1 correctly leaves for `deepseek`, and then
        hop 2 — with the current model now `deepseek` — finds `nemotron-3-ultra-free`
        a perfectly good "different family" and jumps straight back into the counter
        hop 0 exhausted. Simulated against the live catalogue, that chain touched 3
        buckets out of 4; excluding every spent family touches all 4, and drops the
        23-second model out of the chain as a bonus.
        """
        spent = set(skip) | {self.model.key}
        burned = {family_of(key.split(":", 1)[-1]) for key in spent}
        available = [option for option in self.models if option.key not in spent]
        same = [item for item in available if item.provider == self.model.provider]
        elsewhere = [item for item in available if item.provider != self.model.provider]
        fresh = [item for item in same if family_of(item.id) not in burned]
        # Each group tried by a fresh family first, then anything left in it.
        ordered = (
            [fresh, same, elsewhere] if kind in self.PER_MODEL
            else [elsewhere, fresh, same]
        )
        return next((group[0] for group in ordered if group), None)

    @property
    def fallback(self) -> Model | None:
        """The alternative to offer when the reason is not known — the error card."""
        return self.alternative()

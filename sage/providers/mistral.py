"""Mistral, through the official SDK.

An adapter is one class and one `register` call, and this is the shape of it: take
the profile's entry and a key, list what it serves, and yield `Chunk`s. Registered
under the kind `mistral`, which is what a profile entry names.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from .. import config
from ..profile import ProviderEntry
from .base import STREAM_TIMEOUT_MS, Chunk, Model, flatten, tool_fragments

logger = logging.getLogger(__name__)


class MistralProvider:
    def __init__(self, entry: ProviderEntry, api_key: str) -> None:
        from mistralai import Mistral  # noqa: PLC0415

        self.name = entry.name
        self.entry = entry
        # The OpenAI-compatible provider bounds its stream at 120s; this one took the
        # SDK default, so a Mistral stream that stopped sending held the whole script
        # run open with the status row spinning and no way out.
        #
        # Guarded because the keyword is SDK-version-dependent and this path cannot
        # be exercised where the package is broken: if it is not accepted, the client
        # is built exactly as it was before and nothing is worse than today.
        try:
            self._client = Mistral(api_key=api_key, timeout_ms=STREAM_TIMEOUT_MS)
        except TypeError:
            logger.debug("mistralai takes no timeout_ms; using the SDK default")
            self._client = Mistral(api_key=api_key)

    def models(self) -> list[Model]:
        return [Model(self.name, name) for name in self.entry.models]

    def stream(self, model, messages, tools) -> Iterator[Chunk]:
        stream = self._client.chat.stream(
            model=model,
            messages=messages,
            tools=tools or None,
            tool_choice="auto" if tools else None,
            max_tokens=config.MAX_TOKENS,
            temperature=config.TEMPERATURE,
        )
        # SDK 1.x returns a context manager; some builds a bare iterator.
        manager = stream if hasattr(type(stream), "__enter__") else None
        source = manager.__enter__() if manager else stream
        if source is None:
            source = stream
        try:
            for event in source:
                data = getattr(event, "data", None)
                choices = getattr(data, "choices", None) if data else None
                # A list, checked before it is indexed, and the same guard the
                # OpenAI-compatible adapter carries. Without it `choices` arriving as an
                # object was a `KeyError: 0` — raised from inside this generator, which
                # `Turn.deltas` can only classify as an unknown failure: the half-streamed
                # answer already on screen is discarded and replaced with "something went
                # wrong" at the very end of it. The two adapters normalise onto the same
                # `Chunk` and had different amounts of scepticism about their input; this
                # SDK's shapes have moved between 0.x, 1.x and 2.x before.
                if not isinstance(choices, (list, tuple)) or not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                yield Chunk(
                    text=flatten(getattr(delta, "content", None)),
                    tool_calls=tool_fragments(getattr(delta, "tool_calls", None)),
                )
        finally:
            if manager is not None:
                try:
                    manager.__exit__(None, None, None)
                except Exception:
                    logger.debug("Ignoring error closing the stream", exc_info=True)

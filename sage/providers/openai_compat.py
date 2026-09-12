"""Any endpoint that speaks OpenAI's `/chat/completions`, which is most of them.

Registered under the kind `openai`, and it is the reason adding a provider is usually
a TOML entry rather than code: OpenCode Zen, Together, Groq, Fireworks, a vLLM server
on a login node and Ollama on a laptop all answer this shape. What varies between
them is a base URL, an environment variable holding a key, and a fallback list of
model ids — which is exactly what a profile entry carries.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from .. import config
from ..profile import ProviderEntry
from .base import Chunk, Model, family_of, flatten, tool_fragments

logger = logging.getLogger(__name__)


class OpenAICompatProvider:
    def __init__(self, entry: ProviderEntry, api_key: str) -> None:
        self.name = entry.name
        self.entry = entry
        self._key = api_key
        self._base = entry.base_url.rstrip("/")
        # Discovery returns the catalogue in arbitrary order. The profile's list is
        # the order we would choose, and it decides both the picker's default and what
        # an automatic failover lands on — so it must not be alphabetical.
        self._preferred = tuple(entry.models)

    def _headers(self) -> dict:
        # No key means no header, not an empty one. `Authorization: Bearer ` is an
        # illegal header value and httpx raises on it locally, so a keyless discovery
        # call failed before it was sent and fell through to the configured list —
        # reported in the log as "could not list models", which reads as the provider
        # being unreachable. It is also not academic: this endpoint serves its free
        # models to a request with no header at all.
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        # Only when the profile asks for one; otherwise httpx sends its own, which is
        # the honest default. See `ProviderEntry.user_agent` for why this exists.
        if self.entry.user_agent:
            headers["User-Agent"] = self.entry.user_agent
        return headers

    def _is_free(self, model: str) -> bool:
        lowered = (model or "").lower()
        return any(
            mark and mark.lower() in lowered for mark in self.entry.free_marks
        )

    def models(self) -> list[Model]:
        """Ask the endpoint what it serves; fall back to the configured list."""
        try:
            import httpx  # noqa: PLC0415

            response = httpx.get(
                f"{self._base}/models", headers=self._headers(), timeout=10
            )
            response.raise_for_status()
            payload = response.json()
            found = [
                str(entry["id"])
                for entry in payload.get("data", [])
                if isinstance(entry, dict) and entry.get("id")
            ]
            # An endpoint may serve this deployment's paid lineup alongside the free
            # one, and offering a model there is no balance for is offering a button
            # that returns a 402. Filtered here rather than in the picker so nothing
            # downstream — failover included — can select one.
            # Denied names go first, and for the same reason the free filter is here
            # rather than in the picker: nothing downstream — failover included — can
            # select a model that never reaches the list. A model the provider serves
            # and cannot run is not a cheaper option to fall back to, it is an error
            # card with an extra step, and `deepseek-v4-flash-free` was second in the
            # ranking while answering `400 Model is unavailable` to everything.
            #
            # Never all of them. A denylist that empties the picker has turned a broken
            # model into a broken app, and the list is maintained by a daily job that
            # cannot be assumed correct on a day the provider is having a bad time.
            if found and self.entry.deny:
                kept = [name for name in found if name not in set(self.entry.deny)]
                if kept:
                    found = kept
                else:
                    logger.warning(
                        "%s: every served model is on the deny list; offering all of "
                        "them rather than nothing.", self.name,
                    )
            if found and self.entry.free_only and self.entry.free_marks:
                free = [name for name in found if self._is_free(name)]
                if free:
                    found = free
                else:
                    logger.warning(
                        "%s served %d models and none looked free; offering all of "
                        "them. Check free_marks against the current lineup.",
                        self.name, len(found),
                    )
            if found:
                return [Model(self.name, model_id) for model_id in self._order(found)]
            logger.warning("%s returned no models; using the configured list", self.name)
        except Exception as exc:
            logger.warning("Could not list %s models (%s); using configured list",
                           self.name, exc)
        return [Model(self.name, model_id) for model_id in self._preferred]

    def _order(self, found: list[str]) -> list[str]:
        """Preferred first, then the rest alphabetically — and families kept together.

        The ranking on its own scattered a family down the list. `nemotron-3-ultra`
        sat fifth because the preference list puts it there and
        `nemotron-3.5-lightning` sat last because nothing named it, so the picker
        offered two Nemotrons eight rows apart, with three unrelated models between
        them. A reader choosing a model is comparing versions of the same thing —
        which Nemotron, which Ling — and a list that splits them up makes the one
        comparison the picker exists for the hardest thing to do in it.

        Grouping is applied AFTER the ranking rather than instead of it, so the two
        jobs stay separate: the ranking still decides which model a fresh session
        starts on and which one an automatic failover lands on, and this only decides
        where a family's other members are drawn. A family takes the position of its
        best-ranked member, and members keep their ranked order inside it — so the
        first row of the picker is the same model it was before.
        """
        known = [model_id for model_id in self._preferred if model_id in found]
        ranked = known + sorted(set(found) - set(known))
        families: dict[str, list[str]] = {}
        for model_id in ranked:
            families.setdefault(family_of(model_id), []).append(model_id)
        return [model_id for members in families.values() for model_id in members]

    def stream(self, model, messages, tools) -> Iterator[Chunk]:
        import httpx  # noqa: PLC0415

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": config.MAX_TOKENS,
            "temperature": config.TEMPERATURE,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        with (
            httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client,
            client.stream(
                "POST",
                f"{self._base}/chat/completions",
                json=payload,
                headers=self._headers(),
            ) as response,
        ):
            if response.status_code >= 400:
                # Body must be read before the status can be raised on a stream.
                response.read()
                raise _with_body(response)
            yield from parse_sse(response.iter_lines())


def _with_body(response):
    """The HTTP error, carrying what the endpoint said in its body.

    `raise_for_status()` produces "Client error '429 Too Many Requests' for url …" and
    nothing else, and the status alone cannot tell two different situations apart.
    Zen answers a spent free allowance with

        429 {"error": {"type": "FreeUsageLimitError", "message": "Rate limit
             exceeded. Please try again later."}}

    which is not "you are going too fast" — waiting does not help, and the reader was
    told to wait a moment and retry while ten other models would have answered
    immediately. `llm.classify` can only tell the difference if the body reaches it.

    Truncated, because a body is whatever a gateway feels like sending and this string
    ends up in the technical-details panel.
    """
    import httpx  # noqa: PLC0415

    body = ""
    try:
        body = response.text[:400].strip().replace("\n", " ")
    except Exception:  # a body that cannot be decoded is not worth failing over
        logger.debug("Could not read an error body", exc_info=True)
    message = f"HTTP {response.status_code} from {response.request.url}"
    return httpx.HTTPStatusError(
        f"{message}: {body}" if body else message,
        request=response.request,
        response=response,
    )


def parse_sse(lines: Iterator[str]) -> Iterator[Chunk]:
    """Turn an OpenAI-style `data:` event stream into Chunks."""
    for raw in lines:
        line = raw.strip() if isinstance(raw, str) else raw.decode().strip()
        if not line or not line.startswith("data:"):
            continue
        body = line[len("data:") :].strip()
        if body == "[DONE]":
            return
        try:
            event = json.loads(body)
        except (json.JSONDecodeError, RecursionError):
            # `RecursionError`, because that is what `json.loads` raises on deep nesting
            # instead of a decode error — and this is the third site of the same gap
            # (`llm._parse` and `files.process` are the others). It matters most here for
            # the reason the comment below gives about `[DONE]`: a raise escapes this
            # generator, so `Turn.deltas` can only call it an unknown failure, and a
            # half-streamed answer already on the reader's screen is discarded.
            logger.warning("Skipping unparseable stream event: %r", body[:200])
            continue
        # Parsed is not the same as shaped. `data: "[DONE]"` — quoted, which some
        # OpenAI-compatible gateways send — is valid JSON and a string, and every
        # `.get` below assumed a dict: the AttributeError left `Turn.deltas` to
        # classify it as an unknown failure, so a half-streamed answer was thrown
        # away and replaced with "something went wrong" at the very end of it. An
        # event this code does not understand is one to skip, which is what the
        # JSONDecodeError branch above already decided.
        if not isinstance(event, dict):
            continue
        # An error the provider streamed *after* a 200, which is how some gateways
        # report a rate limit hit mid-generation. Skipped like anything else this does
        # not understand — the rationale above holds, and discarding a half-streamed
        # answer to show "something went wrong" is worse than a short one — but not
        # silently: without this line the log has nothing to say about an answer that
        # stopped mid-sentence, which is the one question an operator will have.
        if event.get("error"):
            logger.warning("Provider reported an error mid-stream: %r", str(event["error"])[:200])
            continue
        # `isinstance` before the subscript, not after it. `{"choices": {"delta": {}}}`
        # is a dict, which is truthy, so `choices[0]` raised `KeyError: 0` before the
        # shape check below could run — and a raise here escapes the generator, so
        # `Turn.deltas` classified it as an unknown failure and threw away a
        # half-streamed answer to show "something went wrong" at the end of it. The
        # same failure the quoted-`[DONE]` note above describes, one line lower down.
        choices = event.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        if not isinstance(choices[0], dict):
            continue
        delta = choices[0].get("delta")
        if not isinstance(delta, dict):
            delta = {}
        yield Chunk(
            text=flatten(delta.get("content")),
            tool_calls=tool_fragments(delta.get("tool_calls")),
        )

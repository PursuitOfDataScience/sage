"""Any endpoint that speaks OpenAI's `/chat/completions`, which is most of them.

Registered under the kind `openai`, and it is the reason adding a provider is usually
a TOML entry rather than code: OpenCode Zen, Together, Groq, Fireworks, a vLLM server
on a login node and Ollama on a laptop all answer this shape. What varies between
them is a base URL, an environment variable holding a key, and a fallback list of
model ids, which is exactly what a profile entry carries.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Iterator
from typing import Any

from .. import config
from ..profile import ProviderEntry
from .base import (
    Chunk,
    Model,
    audit_summary,
    current_tag,
    family_of,
    flatten,
    route_summary,
    tool_fragments,
    usage_counts,
    usage_details,
)

#: Where OpenRouter puts its router metadata on the last event of a stream, when the
#: request opted in (`ProviderEntry.route_metadata`), and where its Alignment plugin
#: puts the audit of the message. Read wherever they appear; only ASKING for either is
#: gated on the profile, the same rule as `usage`.
ROUTE_FIELD = "openrouter_metadata"
AUDIT_FIELD = "alignment"

logger = logging.getLogger(__name__)

# `(provider, model, date)` already warned about in this process, so the hourly
# rediscovery does not repeat one notice twenty-four times a day.
_RETIREMENTS_SEEN: set[tuple[str, str, str]] = set()


class OpenAICompatProvider:
    def __init__(self, entry: ProviderEntry, api_key: str) -> None:
        self.name = entry.name
        self.entry = entry
        self._key = api_key
        self._base = entry.base_url.rstrip("/")
        # Discovery returns the catalogue in arbitrary order. The profile's list is
        # the order we would choose, and it decides both the picker's default and what
        # an automatic failover lands on, so it must not be alphabetical.
        self._preferred = tuple(entry.models)
        # What the catalogue says about each model's reasoning, kept from the last
        # `models()` call: whether it is mandatory and which effort values it takes.
        # Empty until discovery has run, and empty means "send what was always sent".
        self._reasoning: dict[str, dict] = {}

    def _headers(self) -> dict:
        # No key means no header, not an empty one. `Authorization: Bearer ` is an
        # illegal header value and httpx raises on it locally, so a keyless discovery
        # call failed before it was sent and fell through to the configured list,
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
            self._reasoning = {
                str(entry["id"]): entry["reasoning"]
                for entry in payload.get("data", [])
                if isinstance(entry, dict) and entry.get("id")
                and isinstance(entry.get("reasoning"), dict)
            }
            self._warn_about_retirements(payload.get("data", []))
            # An endpoint may serve this deployment's paid lineup alongside the free
            # one, and offering a model there is no balance for is offering a button
            # that returns a 402. Filtered here rather than in the picker so nothing
            # downstream (failover included) can select one.
            # Denied names go first, and for the same reason the free filter is here
            # rather than in the picker: nothing downstream (failover included) can
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
        """Preferred first, then the rest alphabetically, and families kept together.

        The ranking on its own scattered a family down the list. `nemotron-3-ultra`
        sat fifth because the preference list puts it there and
        `nemotron-3.5-lightning` sat last because nothing named it, so the picker
        offered two Nemotrons eight rows apart, with three unrelated models between
        them. A reader choosing a model is comparing versions of the same thing
        (which Nemotron, which Ling), and a list that splits them up makes the one
        comparison the picker exists for the hardest thing to do in it.

        Grouping is applied AFTER the ranking rather than instead of it, so the two
        jobs stay separate: the ranking still decides which model a fresh session
        starts on and which one an automatic failover lands on, and this only decides
        where a family's other members are drawn. A family takes the position of its
        best-ranked member, and members keep their ranked order inside it, so the
        first row of the picker is the same model it was before.
        """
        known = [model_id for model_id in self._preferred if model_id in found]
        ranked = known + sorted(set(found) - set(known))
        families: dict[str, list[str]] = {}
        for model_id in ranked:
            families.setdefault(family_of(model_id), []).append(model_id)
        return [model_id for members in families.values() for model_id in members]

    def _switch_off(self, model: str) -> str:
        """What `reasoning.effort` the Think pill OFF sends for `model`, or "".

        Off has always meant "send nothing", and on most models nothing is not off:
        `~deepseek/deepseek-v4-flash-latest` reasons at its default `high` effort either
        way (801-3750 reasoning tokens a call with the pill off, measured 2026-11-25,
        against 0 with `effort: "none"`). So where the profile names an off value
        (`ProviderEntry.think_off`), it is sent, but only where the catalogue says the
        model will take it:

        * never for a router, whose next request is a different model the catalogue
          entry does not describe;
        * only where `mandatory` is explicitly false: a mandatory model rejects `none`;
        * only where `supported_efforts` lists the value, or is present and null, which
          the catalogue uses for "every gateway value". Absent means the model has no
          effort control at all.

        Anything the catalogue has not described (discovery failed, a model it does not
        list) is left alone, which is the old behaviour exactly.
        """
        wanted = self.entry.think_off
        if not wanted or model in self.entry.routers:
            return ""
        caps = self._reasoning.get(model)
        if not isinstance(caps, dict) or caps.get("mandatory") is not False:
            return ""
        if "supported_efforts" not in caps:
            return ""
        efforts = caps.get("supported_efforts")
        if efforts is None or (isinstance(efforts, list) and wanted in efforts):
            return wanted
        return ""

    def _warn_about_retirements(self, catalogue) -> None:
        """Log, once per process, a model in the profile's list that has a retirement date.

        The catalogue carries `expiration_date` ("the date after which the model may be
        removed"), and the profile's list is what a fresh session starts on and what a
        failover lands on, so a date on one of those ids is the notice an operator
        needs before the day rather than after it. An alias (`~vendor/family-latest`)
        is checked through the model it currently resolves to as well.
        """
        try:
            wanted = set(self._preferred)
            if not wanted or not isinstance(catalogue, list):
                return
            dated = {}
            for item in catalogue:
                if not isinstance(item, dict) or not item.get("expiration_date"):
                    continue
                for name in (item.get("id"), item.get("canonical_slug")):
                    if isinstance(name, str) and name:
                        dated[name] = str(item["expiration_date"])
            for item in catalogue:
                if not isinstance(item, dict) or item.get("id") not in wanted:
                    continue
                target = item.get("alias_target")
                names = [item["id"]]
                if isinstance(target, dict) and isinstance(target.get("slug"), str):
                    names.append(target["slug"])
                for name in names:
                    when = dated.get(name)
                    if when and (self.name, name, when) not in _RETIREMENTS_SEEN:
                        _RETIREMENTS_SEEN.add((self.name, name, when))
                        logger.warning(
                            "%s: %s, in the profile's lineup as %s, may be removed "
                            "after %s", self.name, name, item["id"], when,
                        )
        except Exception:  # noqa: BLE001 (a warning is never worth the model list)
            logger.debug("Could not read retirement dates", exc_info=True)

    def status(self) -> dict | None:
        """This key's spending limit and the account's free-model counter, or None.

        Read from the endpoint the profile names (`ProviderEntry.status_path`;
        OpenRouter's `GET /key`), which costs no request against the free-model cap.
        Normalised to plain numbers so a caller can compare them without knowing the
        provider's field names; anything the endpoint did not report is None. Never
        raises: this is a warning light, and a broken bulb must not stop the car.
        """
        path = self.entry.status_path
        if not path:
            return None
        try:
            import httpx  # noqa: PLC0415

            response = httpx.get(
                f"{self._base}/{path.lstrip('/')}", headers=self._headers(), timeout=10
            )
            response.raise_for_status()
            data = response.json().get("data")
            if not isinstance(data, dict):
                return None

            def number(raw):
                if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                    return None
                return raw if math.isfinite(raw) else None

            free = data.get("free_model_daily_requests")
            free = free if isinstance(free, dict) else {}
            reset = data.get("limit_reset")
            return {
                "free_used": number(free.get("used")),
                "free_limit": number(free.get("limit")),
                "free_remaining": number(free.get("remaining")),
                "limit_usd": number(data.get("limit")),
                "limit_remaining_usd": number(data.get("limit_remaining")),
                "limit_reset": reset if isinstance(reset, str) else "",
                "spent_today_usd": number(data.get("usage_daily")),
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not read %s status: %s", self.name, exc)
            return None

    def stream(self, model, messages, tools, thinking=False,
               tool_choice="auto") -> Iterator[Chunk]:
        import httpx  # noqa: PLC0415

        if self.entry.hoists_system:
            messages = keep_late_system_in_place(messages)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": config.MAX_TOKENS,
            "temperature": config.TEMPERATURE,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        # The Think toggle, and only where the provider has said it understands the
        # field. `kind = "openai"` covers OpenRouter and OpenCode Zen alike, and an
        # unknown key is a 400 from any endpoint entitled to be strict about its own
        # wire format, so this is gated on the profile's declaration rather than on
        # the shape of the URL.
        #
        # `exclude` as well as `enabled`, which is not a contradiction: `exclude`
        # suppresses the reasoning TEXT, not the reasoning. The model still thinks
        # before it answers; OpenRouter simply does not send the transcript back.
        # That is the right default here for two reasons. Nothing in this app can
        # display it: `parse_sse` reads `delta.content` and `delta.tool_calls` and
        # `Chunk` has no third field, so without this the deployment pays to
        # transmit text it drops on the floor. And the one place reasoning has ever
        # reached a reader was a defect: one turn in 554 arrived as 34,645 characters
        # of a model quoting its own instructions back, which is what
        # `checks.reasoning_shape` classifies as `leaked-reasoning`. Asking for the
        # transcript is a decision to display it, and displaying it is the progress
        # block's job on the day someone wires `reasoning_details` through.
        #
        # Two things measured against the live free router (8 requests, 2026-09-11) that
        # are worth not rediscovering. **The field does not starve the answer**, which
        # was the fear worth checking, since reasoning is billed as output tokens and
        # counts against `max_tokens`: four requests with it at MAX_TOKENS came back
        # `finish_reason: stop` with 504-1455 reasoning tokens AND a complete answer,
        # none empty. (At a 300-token cap the same models return no content at all with
        # `finish_reason: length`, so the generous cap is load-bearing here; see
        # `config.MAX_TOKENS`.) And **the models on this lineup reason whether or not
        # this field is sent**: the four control requests without it reported 168-1684
        # reasoning tokens each. So the toggle is a request, not a switch, and what it
        # reliably changes is what the deployment is charged for rather than whether the
        # model deliberates.
        if thinking and self.entry.reasoning:
            payload["reasoning"] = {"enabled": True, "exclude": True}
        # What the call cost, asked for only where the profile says the endpoint
        # understands the question: the same rule as `reasoning` above, for the same
        # reason. Without it most endpoints stream no usage at all, and the call record
        # can say how long a call took but not what it was charged.
        if self.entry.stream_usage:
            payload["stream_options"] = {"include_usage": True}
        # Think OFF, made to mean off where the model allows it. See `_switch_off`.
        if not thinking and self.entry.think_off:
            effort = self._switch_off(model)
            if effort:
                payload["reasoning"] = {"effort": effort}
        # Provider preferences for this model, as the profile wrote them.
        preferences = self.entry.routing_for(model)
        if preferences:
            payload["provider"] = preferences
        if self.entry.alignment:
            from .. import alignment  # noqa: PLC0415 (only an audited entry needs it)

            payload["plugins"] = [alignment.plugin()]
        headers = self._headers()
        if self.entry.route_metadata:
            headers["X-OpenRouter-Metadata"] = "enabled"
        # Where this request came from, for an endpoint that groups requests, and in
        # the header and field the profile names. Nothing here knows which endpoint
        # that is: an entry that names neither sends neither. See `CallTag`.
        tag = current_tag()
        if tag is not None:
            if self.entry.session_header and tag.session:
                headers[self.entry.session_header] = tag.session
            if self.entry.trace_field and tag.turn_id:
                trace = {
                    "trace_id": tag.turn_id,
                    "generation_name": f"round {tag.round}",
                    # The deployment, the commit, the prompt and the corpus, so a
                    # trace joins this app's own records. Only what is known: an
                    # empty value is left out rather than sent as "".
                    "environment": config.DEPLOYMENT,
                    "version": config.GIT_SHA,
                    "prompt": tag.prompt,
                    "corpus": tag.corpus,
                }
                payload[self.entry.trace_field] = {
                    key: value for key, value in trace.items() if value
                }

        with (
            httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client,
            client.stream(
                "POST",
                f"{self._base}/chat/completions",
                json=payload,
                headers=headers,
            ) as response,
        ):
            if response.status_code >= 400:
                # Body must be read before the status can be raised on a stream.
                response.read()
                raise _with_body(response)
            yield from parse_sse(response.iter_lines())


def keep_late_system_in_place(messages: list[dict]) -> list[dict]:
    """Re-send a system message that arrives mid-conversation as a user message.

    For an endpoint that hoists every system message into one instruction at the top
    (`ProviderEntry.hoists_system`). Measured 2026-10-05 on Vertex gemini-3.5-flash,
    seven conversations taken through four tool rounds and then given the forced last
    request twice from the same state: with the last-round rule as a system message the
    model answered 2 of 7 and called a tool in the other 5, despite `tool_choice:
    "none"`; as a user message it answered 7 of 7, with citations. Each of those five is
    a reader shown "I wasn't able to finish looking that up".

    Leading system messages (the prompt, and the context `grounded()` puts at index 1)
    are where a hoist puts them anyway, so they are left alone. A new list, because the
    tool loop keeps appending to the one it passed in.
    """
    started = False
    kept = []
    for message in messages:
        role = message.get("role")
        if role == "system" and started:
            kept.append({**message, "role": "user"})
            continue
        started = started or role != "system"
        kept.append(message)
    return kept


def _with_body(response):
    """The HTTP error, carrying what the endpoint said in its body.

    `raise_for_status()` produces "Client error '429 Too Many Requests' for url …" and
    nothing else, and the status alone cannot tell two different situations apart.
    Zen answers a spent free allowance with

        429 {"error": {"type": "FreeUsageLimitError", "message": "Rate limit
             exceeded. Please try again later."}}

    which is not "you are going too fast": waiting does not help, and the reader was
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
            # instead of a decode error, and this is the third site of the same gap
            # (`llm._parse` and `files.process` are the others). It matters most here for
            # the reason the comment below gives about `[DONE]`: a raise escapes this
            # generator, so `Turn.deltas` can only call it an unknown failure, and a
            # half-streamed answer already on the reader's screen is discarded.
            logger.warning("Skipping unparseable stream event: %r", body[:200])
            continue
        # Parsed is not the same as shaped. `data: "[DONE]"` (quoted, which some
        # OpenAI-compatible gateways send) is valid JSON and a string, and every
        # `.get` below assumed a dict: the AttributeError left `Turn.deltas` to
        # classify it as an unknown failure, so a half-streamed answer was thrown
        # away and replaced with "something went wrong" at the very end of it. An
        # event this code does not understand is one to skip, which is what the
        # JSONDecodeError branch above already decided.
        if not isinstance(event, dict):
            continue
        # An error the provider streamed *after* a 200, which is how some gateways
        # report a rate limit hit mid-generation. Skipped like anything else this does
        # not understand (the rationale above holds, and discarding a half-streamed
        # answer to show "something went wrong" is worse than a short one), but not
        # silently: without this line the log has nothing to say about an answer that
        # stopped mid-sentence, which is the one question an operator will have.
        if event.get("error"):
            logger.warning("Provider reported an error mid-stream: %r", str(event["error"])[:200])
            continue
        # What served the request, which every event of a router's stream names, and
        # what it cost, which arrives once. Read before the shape checks below, because
        # the usage event of an OpenAI-style stream is exactly the one they skip: it
        # carries `"choices": []`. Neither is guaranteed to be there, and a missing one
        # stays missing (see `usage_counts`).
        served = event.get("model")
        served = served if isinstance(served, str) else ""
        tokens_in, tokens_out = usage_counts(event.get("usage"))
        cost, reasoning, cached = usage_details(event.get("usage"))
        route = route_summary(event.get(ROUTE_FIELD))
        audit = audit_summary(event.get(AUDIT_FIELD))
        # What the call said about itself, carried on whichever chunk it arrived with.
        extra = {
            "cost": cost, "tokens_reasoning": reasoning, "tokens_cached": cached,
            "route": route, "audit": audit,
        }
        reported = (
            tokens_in is not None or tokens_out is not None
            or any(value is not None for value in extra.values())
        )
        # `isinstance` before the subscript, not after it. `{"choices": {"delta": {}}}`
        # is a dict, which is truthy, so `choices[0]` raised `KeyError: 0` before the
        # shape check below could run, and a raise here escapes the generator, so
        # `Turn.deltas` classified it as an unknown failure and threw away a
        # half-streamed answer to show "something went wrong" at the end of it. The
        # same failure the quoted-`[DONE]` note above describes, one line lower down.
        choices = event.get("choices")
        if (
            not isinstance(choices, list)
            or not choices
            or not isinstance(choices[0], dict)
        ):
            if reported:
                yield Chunk(model=served, tokens_in=tokens_in, tokens_out=tokens_out,
                            **extra)
            continue
        delta = choices[0].get("delta")
        if not isinstance(delta, dict):
            delta = {}
        finish = choices[0].get("finish_reason")
        yield Chunk(
            text=flatten(delta.get("content")),
            tool_calls=tool_fragments(delta.get("tool_calls")),
            model=served,
            finish_reason=finish if isinstance(finish, str) else "",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            **extra,
        )

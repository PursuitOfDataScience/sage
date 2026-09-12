#!/usr/bin/env python3
"""What the provider serves today, against what this repository says it serves.

The app does not need this to work. Model lists are discovered from `GET /models` at
runtime and filtered by a *rule* (`free_marks`), so a model Zen starts serving free
under a `-free` suffix appears in the picker the moment it exists, with no commit —
`muse-spark-1.2-contributor-free` was offered before anything named it. And a model
that vanishes is handled too: `app.current_model` falls through a missing
`SAGE_DEFAULT_MODEL` to the first discovered option.

So this is not a fetch-the-list script. It exists for the four things the rule cannot
do on its own, each of which has already cost something here:

1. **A stealth codename.** Zen publishes some models free under a name with no marker
   in it — `big-pickle` is in `free_marks` as a literal for exactly this reason. The
   rule cannot invent the next one. Nothing but a probe distinguishes it from the
   fifty-odd paid models served from the same endpoint, and the only person who can
   decide to widen a rule is a person. This reports the candidate; it never edits
   `free_marks`.

2. **Served is not working.** `north-mini-code-free` was in the profile's list and
   answered 401 from Zen's own upstream; `ling-3.0-tiny-free` answered 503. Both were
   in the catalogue while neither could answer a question. A list-only check would
   have called that lineup healthy.

3. **How long a thing has been gone.** A free tier's outages come back — `hy3-free`
   left the catalogue and returned two days later, with nothing about this deployment
   changed — so no single day's listing is evidence of a retirement. The ledger accrues
   `missing_since`, and `--retire-after` is what turns a sustained absence into an
   edit: at seven days, comfortably past the one recurrence on record. Below that
   threshold an absence is still only reported.

4. **Whether the repository's own record is still true.** The fallback list, the
   default model, `EVAL.md`'s per-model table: all of them go stale silently, because
   nothing reads them against reality.

    python tools/lineup_check.py                    # drift, no requests spent at all
    python tools/lineup_check.py --probe            # + a real completion per new name
    python tools/lineup_check.py --probe --update   # + append new, retire long-gone
    python tools/lineup_check.py --update --retire-after 0   # append only, never remove
    python tools/lineup_check.py --summary-out drift.md

**None of it needs a key.** `GET /models` on Zen answers with no header and with a bogus
one — both 200, both the full catalogue — and so does a *completion* on a free model:
no `Authorization` header at all returns 200 and a full streamed answer with a tool
offered. So `--probe` runs in CI with no secret, and a keyless refusal is the better
evidence of tier, because "Missing API key" can only mean the model requires one. A key
adds exactly one thing — the ability to probe a paid model as something other than paid
— which is of no use to a deployment whose lineup is the free tier.

Only `--probe` spends a request at all, and only on a name the ledger has not classified
before: a day Zen changes nothing costs nothing.

**Probes send `config.MAX_TOKENS`, and that is not incidental.** A reasoning model
spends the budget on thinking it does not emit: `muse-spark-1.2-contributor-free` at
`max_tokens=200` returns `completion_tokens: 200` and an empty completion, three times
out of three, and reads as a dead endpoint. A cheap probe would have libelled it — and
would libel every reasoning model Zen adds from here on.

Never a CI gate, for the reason `EVAL.md` gives about Axis B: a free tier rotating its
lineup is not this repository's fault, and a red build for it would get loosened until
it was quiet. The output is a report, a ledger and — when the lineup has moved in either
direction — a diff.

**Both directions, now.** This used to append only, and leave a model that had left the
catalogue on the list for a person to remove. Four of them sat there for three days
being reported daily to an issue nobody had reason to open, which is the failure mode a
report-only mechanism always has. Additions and retirements both arrive as the same
pull request; the threshold is what keeps a two-day outage from becoming an edit.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from sage import config, providers  # noqa: E402
from sage.profile import ProviderEntry  # noqa: E402
from sage.profile import active as _active  # noqa: E402

LEDGER = os.path.join(ROOT, "report", "lineup.json")

# What a probe asks. Short enough to be cheap, and phrased so that calling the offered
# tool is the obvious move — because otherwise the verdict cannot mean anything.
#
# It used to read "Reply with the single word: ready", and
# `muse-spark-1.2-contributor-free` sensibly answered it in five characters without
# touching the tool. The verdict then said "no tool call" about a model measured
# separately making two of them, which is a report that invents a limitation. A probe
# that does not ask for the behaviour it is grading cannot grade it.
PROBE_PROMPT = (
    "Use the search_docs tool to look up 'storage quota', then reply with the single "
    "word: ready"
)

# A tool the probe offers, so the verdict can record whether the model can call one at
# all. Shaped like the app's own search tool rather than a toy, because a model that
# rejects a real schema and accepts `{"type": "object"}` is not usable here.
PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": "search_docs",
        "description": "Search the documentation for a phrase.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}

# Bodies that mean "this model is real, you just cannot pay for it". Zen answers a paid
# model on a free key with `401 CreditsError: Insufficient balance`, which is a
# different fact from a 401 on a model that does not exist.
# What a refusal says about the tier. The first four are what a *keyed* probe gets from
# a model this key cannot pay for. The fifth is the keyless case, and it is the more
# useful one: with no `Authorization` header at all, "missing api key" can only mean
# this model requires one, which is the definition of paid here.
#
# `missing`, not `api key`. A probe carrying a bogus key is told "Invalid API key." —
# that is a broken key, not a paid model, and classifying it as paid would put every
# model Zen serves into the paid ledger on one typo. Measured both ways: no header at
# all returns `AuthError: Missing API key.`, a wrong one returns `AuthError: Invalid API
# key.`, and only the first is a fact about the model.
PAID_MARKS = (
    "insufficient balance", "creditserror", "payment", "quota exceeded",
    "missing api key",
)

# And the other direction. A free-usage limit is a thing only a free model has, so this
# is positive evidence of the tier even though the probe learned nothing about whether
# the model answers. `big-pickle` returns it keyless — the stealth codename the whole
# probing path exists to catch, telling us what it is by refusing.
FREE_MARKS_IN_ERROR = ("freeusagelimiterror", "free usage limit")

# An error body is whatever a gateway feels like sending, and this one ends up in a
# ledger committed to a public repository. Zen's `CreditsError` embeds a billing URL
# carrying the workspace id — `https://opencode.ai/workspace/wrk_01K…/billing` — which
# is account state, not a fact about the model, and which nothing here needs to keep in
# order to say "this one is paid". Found by reading the first ledger this wrote.
_URL = re.compile(r"https?://\S+")
_OPAQUE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9]{16,}\b")


def scrub(body: str, limit: int = 200) -> str:
    """An error body with the account state taken out of it."""
    cleaned = _URL.sub("<url>", body or "")
    cleaned = _OPAQUE.sub("<id>", cleaned)
    return " ".join(cleaned.split())[:limit]


def today() -> str:
    return dt.date.today().isoformat()


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


# --- what the endpoint says ------------------------------------------------


def discoverable() -> list[ProviderEntry]:
    """Provider entries whose catalogue can be asked for over HTTP.

    The Mistral adapter is deliberately not one: its lineup is three named models that
    do not rotate, and listing it needs the SDK and a key. This is about free tiers.
    """
    return [
        item for item in _active().providers if item.kind == "openai" and item.base_url
    ]


def served(entry: ProviderEntry, key: str = "") -> list[str]:
    """Every model id the endpoint lists, in the order it lists them.

    Raises, rather than returning empty: an unreachable endpoint and an endpoint
    serving nothing are different findings and only one of them is drift.
    """
    import httpx  # noqa: PLC0415

    base = _base_url(entry)
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if entry.user_agent:
        headers["User-Agent"] = entry.user_agent
    response = httpx.get(f"{base}/models", headers=headers, timeout=20)
    response.raise_for_status()
    payload = response.json()
    return [
        str(item["id"])
        for item in payload.get("data", [])
        if isinstance(item, dict) and item.get("id")
    ]


def _base_url(entry: ProviderEntry) -> str:
    """The URL the app would use.

    Already carries `base_url_env`: the profile loader resolves the override when it
    reads the file, so pointing `OPENCODE_BASE_URL` at `tools/mock_provider.py` aims
    this script at the mock too, which is how it is tested without spending anything.
    """
    return entry.base_url.rstrip("/")


def is_free(entry: ProviderEntry, model_id: str) -> bool:
    """The profile's own rule, not a second copy of it.

    Deliberately routed through the adapter the app uses, so a change to how a free
    model is recognised cannot be true in the picker and false here.
    """
    return providers.adapters.get(entry.kind)(entry, "probe")._is_free(model_id)


# --- probing ---------------------------------------------------------------


def probe(entry: ProviderEntry, key: str, model_id: str, *, tools: bool = True) -> dict:
    """One real streamed completion, and what it says about the model.

    `max_tokens` is the app's own, for the reason in the module docstring: a reasoning
    model given a tight budget emits nothing and looks broken.
    """
    import httpx  # noqa: PLC0415

    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": PROBE_PROMPT}],
        "max_tokens": config.MAX_TOKENS,
        "temperature": config.TEMPERATURE,
        "stream": True,
    }
    if tools:
        payload["tools"] = [PROBE_TOOL]
        payload["tool_choice"] = "auto"

    # No key means no header, not an empty one. Two separate reasons, and both were
    # measured: `Authorization: Bearer ` is an illegal header value that httpx refuses
    # locally before the request is sent, and Zen serves its free models to a request
    # carrying no header at all — 200 and a full streamed completion with tools offered.
    # A probe therefore needs no key for the free lineup, which is the whole lineup this
    # repository cares about.
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if entry.user_agent:
        headers["User-Agent"] = entry.user_agent

    verdict: dict = {"model": model_id, "checked": now()}
    started = time.time()
    text: list[str] = []
    calls = 0
    try:
        with (
            httpx.Client(timeout=httpx.Timeout(90.0, connect=15.0)) as client,
            client.stream(
                "POST",
                f"{_base_url(entry)}/chat/completions",
                json=payload,
                headers=headers,
            ) as response,
        ):
            if response.status_code >= 400:
                response.read()
                body = scrub(response.text[:600])
                verdict.update(
                    status=response.status_code,
                    error=body,
                    tier=_tier_of(body),
                    answered=False,
                )
                verdict["seconds"] = round(time.time() - started, 2)
                return verdict
            for chunk in providers.parse_sse(response.iter_lines()):
                text.append(chunk.text)
                calls += len(chunk.tool_calls)
    except Exception as exc:  # a probe that cannot complete is a verdict, not a crash
        verdict.update(
            error=scrub(f"{type(exc).__name__}: {exc}"), tier="unknown", answered=False
        )
        verdict["seconds"] = round(time.time() - started, 2)
        return verdict

    body = "".join(text)
    verdict.update(
        status=200,
        seconds=round(time.time() - started, 2),
        chars=len(body),
        tool_calls=calls,
        answered=bool(body.strip() or calls),
        # A 200 is the only thing that distinguishes a stealth free model from a paid
        # one: the endpoint served it and did not ask to be paid.
        tier="free",
    )
    return verdict


def verdict_for(entry: ProviderEntry, key: str, model_id: str) -> dict:
    """`probe`, and then again with the tools withdrawn if the first said nothing.

    A tool call is not an answer to *this* app, and treating it as one let a broken
    model through. `nemotron-3-ultra-free` was recorded `answered: true` with
    `tool_calls: 2` and `chars: 0` — two calls, not one word — while readers were
    getting "the model returned an empty answer" from it. `failing_since` never opened
    an entry, so its seven-day clock never started, and the daily report called the
    lineup healthy.

    The asymmetry is in the app, so the probe has to mirror it: `turn.run` sends the
    last request of a turn with the tools *withdrawn* (see `prompts.last_round_instruction`
    and the comment above it), because a model that answers every round with another
    tool call otherwise never reaches the round that writes prose. Whatever that final
    request returns is the answer, and if it is empty the turn is empty.

    So a model that emits calls and no text gets asked the way that round asks. Passing
    that is what "working" means here; failing it starts the clock. The second request
    is only spent on a model that produced no prose the first time, which is rare — a
    day when the lineup is well costs exactly what it did before.
    """
    verdict = probe(entry, key, model_id)
    if (
        verdict.get("status") != 200
        or (verdict.get("chars") or 0) > 0
        or not verdict.get("tool_calls")
    ):
        return verdict

    withdrawn = probe(entry, key, model_id, tools=False)
    # The first request is what the verdict still describes — its latency, its tool
    # calls, its tier — because that is the one the app's early rounds make. Only the
    # judgement changes, and it says which request reached it.
    verdict = {
        **verdict,
        "answered": bool(withdrawn.get("chars") or 0) and withdrawn.get("status") == 200,
        "prose_seconds": withdrawn.get("seconds"),
        "prose_chars": withdrawn.get("chars", 0),
        "prose_error": withdrawn.get("error", ""),
        "prose_status": withdrawn.get("status"),
    }
    return verdict


def _looks_paid(body: str) -> bool:
    lowered = (body or "").lower()
    return any(mark in lowered for mark in PAID_MARKS)


def _unmeasured(verdict: dict) -> bool:
    """Did this probe learn nothing, as opposed to learning something bad?

    A free-usage limit is the case, and it is common enough to matter: a keyless
    request is rate-limited per address rather than per key, and `big-pickle` returned
    one on the very first probe. Counting that as "this model is broken" would retire a
    working model for being popular, which is the worst failure this file could have.
    """
    if verdict.get("status") == 429:
        return True
    lowered = (verdict.get("error") or "").lower()
    return any(mark in lowered for mark in FREE_MARKS_IN_ERROR)


def _tier_of(body: str) -> str:
    """What a refusal says the model's tier is: `free`, `paid`, or `unknown`.

    Free is checked first, because a rate-limited free model is a free model and its
    error is the more specific of the two. `answered` stays False either way — this
    says what the model *is*, not that it works, and the candidate list still wants an
    answer before it will suggest widening `free_marks`.
    """
    lowered = (body or "").lower()
    if any(mark in lowered for mark in FREE_MARKS_IN_ERROR):
        return "free"
    return "paid" if _looks_paid(lowered) else "unknown"


# --- the ledger ------------------------------------------------------------


def load_ledger(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            found = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"providers": {}}
    if not isinstance(found, dict):
        return {"providers": {}}
    found.setdefault("providers", {})
    return found


def _slot(ledger: dict, name: str) -> dict:
    slot = ledger["providers"].setdefault(name, {})
    slot.setdefault("missing_since", {})
    slot.setdefault("failing_since", {})
    slot.setdefault("verdicts", {})
    slot.setdefault("paid", [])
    return slot


def review(entry: ProviderEntry, catalogue: list[str], ledger: dict) -> dict:
    """Drift for one provider: what appeared, what went, what needs a human.

    Pure — no requests, no writes. The probing pass reads the `unclassified` list this
    produces and decides what to spend on.
    """
    slot = _slot(ledger, entry.name)
    listed = list(entry.models)
    free = [model_id for model_id in catalogue if is_free(entry, model_id)]
    known_paid = set(slot["paid"])

    # Not a name this deployment has already DENIED. `deny` and `models` answer
    # different questions — "does it work" against "what to fall back on if discovery
    # fails" — so a denied name is legitimately absent from `models`, and reporting it
    # as newly appeared invites `--update` to add it back. Measured against the live
    # catalogue: a dispatch today would have appended `muse-spark-1.3-contributor-free`,
    # denied by hand earlier the same day for answering 500 to everything, to the
    # fallback list of the provider that is refusing to offer it.
    denied = set(entry.deny)
    appeared = [
        model_id for model_id in free
        if model_id not in listed and model_id not in denied
    ]
    vanished = [model_id for model_id in listed if model_id not in catalogue]

    # Every served name the rule calls not-free and the ledger has not already priced.
    # These are the only candidates for the next `big-pickle`, and the only names worth
    # spending a request on.
    unclassified = [
        model_id
        for model_id in catalogue
        if model_id not in free and model_id not in known_paid
    ]

    # `missing_since` accrues rather than being recomputed, so a model that has been
    # gone for a month says so instead of saying "gone today" every day.
    missing = dict(slot["missing_since"])
    for model_id in vanished:
        missing.setdefault(model_id, today())
    for model_id in list(missing):
        if model_id in catalogue:
            del missing[model_id]

    default = providers.parse_key(config.DEFAULT_MODEL)
    default_missing = bool(
        default and default.provider == entry.name and default.id not in catalogue
    )

    return {
        "provider": entry.name,
        "served": catalogue,
        "free": free,
        "listed": listed,
        "appeared": appeared,
        "vanished": vanished,
        "unclassified": unclassified,
        "missing_since": missing,
        # Carried through untouched when nothing is probed, so a `--probe`-less run
        # neither invents a failure nor forgets one that is already accruing.
        "failing_since": dict(slot["failing_since"]),
        "default_missing": default_missing,
        # The rule matching nothing at all is the one failure that makes the picker
        # offer every paid model as if it worked. The adapter logs it; nobody reads a
        # deployment's logs.
        "rule_matched_nothing": bool(catalogue) and not free,
    }


def material(before: dict, after: dict) -> list[str]:
    """Whether anything changed that a person should look at.

    Latency deliberately does not count. A free tier's models wobble by seconds
    between one request and the next, and a daily pull request that says so is a daily
    pull request nobody reads.
    """
    # No prior record is not the same as everything having changed. The first run
    # against an empty ledger listed all eight free models as news, which is the
    # report a person learns to skim.
    if (before or {}).get("free") is None:
        return ["first record of this lineup — nothing to compare against yet"]

    reasons = []
    was_free = set(before.get("free") or [])
    now_free = set(after["free"])
    for model_id in sorted(now_free - was_free):
        reasons.append(f"`{model_id}` is now served free")
    for model_id in sorted(was_free - now_free):
        reasons.append(f"`{model_id}` is no longer served")
    if after["appeared"]:
        reasons.append(
            "the profile's list does not name "
            + ", ".join(f"`{name}`" for name in after["appeared"])
        )
    old_verdicts = (before or {}).get("verdicts") or {}
    for model_id, verdict in sorted(after.get("verdicts", {}).items()):
        was = old_verdicts.get(model_id) or {}
        if was and bool(was.get("answered")) != bool(verdict.get("answered")):
            state = "answers again" if verdict.get("answered") else "stopped answering"
            reasons.append(f"`{model_id}` {state}")
    for model_id in sorted(after.get("candidates") or []):
        reasons.append(f"`{model_id}` answered without matching `free_marks`")
    was_failing = set((before or {}).get("failing_since") or {})
    now_failing = set(after.get("failing_since") or {})
    for model_id in sorted(now_failing - was_failing):
        reasons.append(f"`{model_id}` is served but stopped answering")
    for model_id in sorted(was_failing - now_failing):
        if model_id in set(after["free"]):
            reasons.append(f"`{model_id}` is answering again")
    if after["default_missing"]:
        reasons.append(f"`{config.DEFAULT_MODEL}` is not in the catalogue")
    if after["rule_matched_nothing"]:
        reasons.append("`free_marks` matched nothing served")
    return reasons


# --- writing the profile back ----------------------------------------------


def append_models(text: str, provider: str, additions: list[str]) -> str:
    """Add ids to one provider's `models = [...]`, keeping every comment in place.

    Append only, and at the end. Three separate reasons, and they are not the same
    reason:

    * **Order is a judgement.** The first entry is what a fresh session starts on and
      what an automatic failover lands on. A tool that decided that would be deciding,
      once a day, which model every reader gets — from a catalogue listing, which says
      nothing about whether the model is any good.
    * **Appending is close to a no-op.** Discovery already offers anything the rule
      matches, and `_order` puts unlisted models after listed ones, which is where an
      appended one lands anyway. So this makes the record true without moving anything.
    * **Being broken is still not being gone.** `retire_models` takes a model off the
      list for having left the catalogue and stayed away; nothing comes off for
      answering 401 today. A 401 fails over and a 503 offers another model, which is
      already the right behaviour, and `hy3-free` is the standing argument for it.
    """
    if not additions:
        return text

    lines = text.splitlines(keepends=True)
    start = _models_line(lines, provider)
    if start is None:
        raise ValueError(f"no `models = [` for provider {provider!r}")

    opening = lines[start]
    if "]" in opening.split("[", 1)[1]:
        # `models = ["a", "b"]` on one line. Rewritten in place, same shape.
        head, rest = opening.split("[", 1)
        body, tail = rest.rsplit("]", 1)
        existing = [part.strip() for part in body.split(",") if part.strip()]
        joined = ", ".join(existing + [f'"{name}"' for name in additions])
        lines[start] = f"{head}[{joined}]{tail}"
        return "".join(lines)

    close = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].lstrip().startswith("]")
        ),
        None,
    )
    if close is None:
        raise ValueError(f"unterminated `models` list for provider {provider!r}")
    indent = _indent_of(lines[start + 1 : close]) or "    "
    added = [f'{indent}"{name}",\n' for name in additions]
    return "".join(lines[:close] + added + lines[close:])


def retire_models(text: str, provider: str, removals: list[str]) -> str:
    """Take ids out of one provider's `models = [...]`, comments and all.

    The counterpart to `append_models`, and it exists because of an instruction that
    reverses what that function's docstring says: a model the provider has stopped
    serving is to come off the list, not sit on it waiting for someone to notice. What
    stays from the old rule is the *evidence* behind it — `hy3-free` was gone from the
    catalogue for two days and came back — so absence is not retirement. `retiring()`
    decides when an absence has run long enough; this only performs the edit.

    A removed entry takes the comment block directly above it, because that block is
    the note on why *that* model is in the list and an orphaned one is worse than no
    note: it reads as documentation of whichever entry it lands above. The exception is
    a run that names some other model in the list — the first entry's comment explains
    its rank by comparison with `nemotron-3-ultra-free`, so it is about more than the
    line it sits on. Those are left in place and reported, for a person to resolve.
    """
    if not removals:
        return text

    lines = text.splitlines(keepends=True)
    start = _models_line(lines, provider)
    if start is None:
        raise ValueError(f"no `models = [` for provider {provider!r}")
    going = set(removals)

    opening = lines[start]
    if "]" in opening.split("[", 1)[1]:
        # `models = ["a", "b"]` on one line. Rewritten in place, same shape.
        head, rest = opening.split("[", 1)
        body, tail = rest.rsplit("]", 1)
        kept = [
            part.strip()
            for part in body.split(",")
            if part.strip() and part.strip().strip("\"'") not in going
        ]
        lines[start] = f"{head}[{', '.join(kept)}]{tail}"
        return "".join(lines)

    close = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].lstrip().startswith("]")
        ),
        None,
    )
    if close is None:
        raise ValueError(f"unterminated `models` list for provider {provider!r}")

    present = {
        name
        for name in (_entry_id(lines[index]) for index in range(start + 1, close))
        if name
    }
    drop: set[int] = set()
    for index in range(start + 1, close):
        name = _entry_id(lines[index])
        if name is None or name not in going:
            continue
        drop.add(index)
        run = []
        for above in range(index - 1, start, -1):
            if not lines[above].strip().startswith("#"):
                break
            run.append(above)
        others = present - {name}
        text_of_run = " ".join(lines[line] for line in run)
        if not any(other in text_of_run for other in others):
            drop.update(run)
    return "".join(line for index, line in enumerate(lines) if index not in drop)


def set_deny(text: str, provider: str, names: list[str]) -> str:
    """Rewrite one provider's `deny = [...]` to exactly `names`.

    Wholesale rather than surgical, because unlike `models` this array has no ordering
    to preserve — nothing ranks off it — so the simplest edit is also the safest one.
    The array is created if the provider has none, immediately above `free_marks`, which
    is the other question about which models get offered.

    Sorted, so a day with no change produces no diff and the pull request stays a
    signal. An empty list is written as `deny = []` rather than removed, because the
    line going missing reads as a profile that never had one.

    **Comment lines above the array are kept.** This docstring used to say the array had
    "no per-entry comments to orphan", and that stopped being true the day someone wrote
    down why a model was denied: `profiles/rcc.toml` now carries nine lines explaining
    the difference between "cannot be paid for" and "does not answer", and a wholesale
    rewrite deleted fourteen lines of it. The reasoning is the only thing that makes a
    denylist reviewable — the array without it is a list of names nobody can argue with.
    """
    lines = text.splitlines(keepends=True)
    flat = f'deny = [{", ".join(sorted(chr(34) + n + chr(34) for n in names))}]\n'
    start = _array_line(lines, provider, "deny")
    if start is not None:
        indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
        if "]" not in lines[start].split("[", 1)[1]:
            close = next(
                (i for i in range(start + 1, len(lines))
                 if lines[i].lstrip().startswith("]")), None
            )
            if close is None:
                raise ValueError(f"unterminated `deny` for provider {provider!r}")
            kept = _entry_comments(lines[start + 1 : close])
            body = _deny_body(names, kept, indent)
            return "".join(lines[:start] + body + lines[close + 1:])
        return "".join(lines[:start] + [indent + flat] + lines[start + 1:])

    marks = _array_line(lines, provider, "free_marks")
    if marks is None:
        raise ValueError(f"nowhere to put `deny` for provider {provider!r}")
    indent = lines[marks][: len(lines[marks]) - len(lines[marks].lstrip())]
    return "".join(lines[:marks] + [indent + flat] + lines[marks:])


def _entry_id(line: str) -> str | None:
    """The model id on a `"name",` line of a TOML array, or None for anything else."""
    found = re.match(r"""^\s*["']([^"']+)["']\s*,?\s*$""", line)
    return found.group(1) if found else None


def retiring(report: dict, after_days: int) -> list[str]:
    """Which absences have run long enough to be retirements.

    Not "gone today". `hy3-free` was absent from the catalogue and answering 401, and
    two days later it was served again with nothing about this deployment changed — so
    a check that acted on a single day's listing would have removed a working model and
    then had to put it back. The ledger's `missing_since` is what makes the difference
    expressible, and this is the only place the threshold is applied.

    `after_days <= 0` retires nothing, which is the behaviour this file had before
    there was a threshold at all.
    """
    if after_days <= 0:
        return []
    out = []
    for model_id in report["vanished"]:
        days = _days_since(report["missing_since"].get(model_id))
        if days is not None and days >= after_days:
            out.append(model_id)
    return out


def failing(report: dict, after_days: int) -> list[str]:
    """Which models have been served and unable to answer for long enough to go.

    The companion to `retiring`, and the case that motivated it:
    `muse-spark-1.2-contributor-free` sat in the picker returning `500 Internal server
    error` to every request while `GET /models` went on listing it. Absence was already
    handled; this is the other way a model stops existing, and from a reader's chair it
    is the same event — they pick it and get an error card.

    Same threshold as absence, and for the same reason. `hy3-free` answered 401 for two
    days and then answered properly, so one bad morning is not a verdict. A model that
    has failed every probe for a week is not having a bad morning.
    """
    if after_days <= 0:
        return []
    out = []
    for model_id, since in sorted((report.get("failing_since") or {}).items()):
        days = _days_since(since)
        if days is not None and days >= after_days:
            out.append(model_id)
    return out


def _models_line(lines: list[str], provider: str) -> int | None:
    """Index of the `models = [` line inside `provider`'s `[[providers]]` block."""
    return _array_line(lines, provider, "models")


_DENY_NAME = re.compile(r'^\s*"([^"]+)"\s*,?\s*$')


def _entry_comments(body: list[str]) -> dict[str, list[str]]:
    """Comment lines inside a `deny` array, keyed by the name they sit above.

    A floating block belongs to the entry that FOLLOWS it, which is how a reader reads
    one: the paragraph explaining why `muse-spark-1.3-contributor-free` is denied is
    written above that line, not beside it.
    """
    kept: dict[str, list[str]] = {}
    pending: list[str] = []
    for line in body:
        name = _DENY_NAME.match(line)
        if name:
            if pending:
                kept[name.group(1)] = pending
                pending = []
            continue
        if line.strip().startswith("#"):
            pending.append(line)
    return kept


def _deny_body(
    names: list[str], kept: dict[str, list[str]], indent: str
) -> list[str]:
    """The `deny` array, one name per line, each under whatever explained it.

    One line per name only when something is explained. A profile whose denylist
    carries no comments keeps the flat form it had, so a day with no change still
    produces no diff — which is the property that makes the pull request a signal.
    """
    ordered = sorted(names)
    if not any(name in kept for name in ordered):
        joined = ", ".join(f'"{name}"' for name in ordered)
        return [f"{indent}deny = [{joined}]\n"]
    out = [f"{indent}deny = [\n"]
    for name in ordered:
        out.extend(kept.get(name, []))
        out.append(f'{indent}    "{name}",\n')
    out.append(f"{indent}]\n")
    return out


def _array_line(lines: list[str], provider: str, key: str) -> int | None:
    """Index of `key = [` inside `provider`'s `[[providers]]` block, or None."""
    inside = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[["):
            inside = False
            continue
        if stripped.startswith("["):
            inside = False
            continue
        if re.match(r'name\s*=\s*["\']' + re.escape(provider) + r'["\']', stripped):
            inside = True
            continue
        if inside and re.match(re.escape(key) + r"\s*=\s*\[", stripped):
            return index
    return None


def _indent_of(lines: list[str]) -> str:
    for line in lines:
        if line.strip() and not line.strip().startswith("#"):
            return line[: len(line) - len(line.lstrip())]
    return ""


# --- reporting -------------------------------------------------------------


def summarise(report: dict, reasons: list[str]) -> str:
    """Markdown, because this ends up in a pull request body."""
    out = [f"### {report['provider']}", ""]
    out.append(
        f"{len(report['served'])} models served, {len(report['free'])} of them free "
        f"by the profile's rule, {len(report['listed'])} named in the profile."
    )
    out.append("")
    if reasons:
        out.append("**Changed:**")
        out += [f"- {reason}" for reason in reasons]
        out.append("")
    if report["appeared"]:
        out.append("**Free and served, not named in the profile**")
        for model_id in report["appeared"]:
            verdict = (report.get("verdicts") or {}).get(model_id) or {}
            out.append(f"- `{model_id}`{_verdict_note(verdict)}")
        out.append("")
    if report["vanished"]:
        out.append("**Named in the profile, not served**")
        for model_id in report["vanished"]:
            since = report["missing_since"].get(model_id)
            days = _days_since(since)
            when = f" — missing since {since}" if since else ""
            aged = f" ({days} days)" if days is not None and days > 0 else ""
            out.append(f"- `{model_id}`{when}{aged}")
        out.append("")
    if report.get("candidates"):
        out.append(
            "**Answered a probe without matching `free_marks`** — a stealth codename, "
            "possibly. Widening the rule is a human decision; nothing here edits it."
        )
        for model_id in report["candidates"]:
            verdict = (report.get("verdicts") or {}).get(model_id) or {}
            out.append(f"- `{model_id}`{_verdict_note(verdict)}")
        out.append("")
    if report.get("failing_since"):
        out.append(
            "**Served, and could not answer** — in the catalogue, in the picker, and "
            "failing every probe"
        )
        for model_id, since in sorted(report["failing_since"].items()):
            days = _days_since(since)
            verdict = (report.get("verdicts") or {}).get(model_id) or {}
            aged = f" ({days} days)" if days is not None and days > 0 else ""
            out.append(f"- `{model_id}` — failing since {since}{aged}"
                       f"{_verdict_note(verdict)}")
        out.append("")
    if report["default_missing"]:
        out.append(
            f"⚠️ `SAGE_DEFAULT_MODEL` is `{config.DEFAULT_MODEL}`, which is not in the "
            "catalogue. The app falls through to the first discovered model, so this is "
            "not an outage — but the configured default is a fiction until it is changed."
        )
        out.append("")
    if report["rule_matched_nothing"]:
        out.append(
            "⚠️ `free_marks` matched nothing served. With `free_only` set the picker "
            "offers the whole paid lineup in this state. This is the one finding here "
            "that is urgent."
        )
        out.append("")
    if report.get("skipped"):
        out.append(
            f"{report['skipped']} unclassified name(s) went unprobed against the "
            "budget; they will be picked up on the next run."
        )
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _verdict_note(verdict: dict) -> str:
    if not verdict:
        return ""
    if verdict.get("status") and verdict["status"] != 200:
        return f" — HTTP {verdict['status']}: {(verdict.get('error') or '')[:120]}"
    if verdict.get("error"):
        return f" — {verdict['error'][:120]}"
    if not verdict.get("answered"):
        if verdict.get("tool_calls"):
            # The case `verdict_for` exists for, and the report has to distinguish it
            # from a stream that carried nothing at all — one is a model that is up and
            # cannot finish a turn, the other is a dead endpoint, and they read the same
            # to a reader who only sees the error card.
            note = (
                f" — {verdict['tool_calls']} tool call(s) and no prose in "
                f"{verdict.get('seconds')}s; asked again with the tools withdrawn "
                f"and got {verdict.get('prose_chars', 0)} chars"
            )
            if verdict.get("prose_error"):
                return note + f" ({verdict['prose_error'][:80]})"
            return note
        return f" — 200 and an empty completion in {verdict.get('seconds')}s"
    parts = [f"{verdict.get('seconds')}s", f"{verdict.get('chars', 0)} chars"]
    if verdict.get("tool_calls"):
        parts.append(f"{verdict['tool_calls']} tool calls")
    else:
        # "did not", not "cannot". The probe asks for a tool call, so declining one is
        # a finding — but a single prompt is not evidence of an incapacity, and
        # `config.TOOLLESS_MODELS` is the place that claim gets made.
        parts.append("declined the offered tool")
    return " — " + ", ".join(parts)


def _days_since(stamp: str | None) -> int | None:
    if not stamp:
        return None
    try:
        return (dt.date.today() - dt.date.fromisoformat(stamp)).days
    except ValueError:
        return None


# --- the run ---------------------------------------------------------------


def run(parsed: argparse.Namespace) -> tuple[int, str, bool]:
    """Returns (exit code, markdown summary, whether anything material changed)."""
    ledger = load_ledger(parsed.ledger)
    entries = discoverable()
    if parsed.provider:
        entries = [item for item in entries if item.name == parsed.provider]
    if not entries:
        return 2, "No discoverable provider in the active profile.\n", False

    sections: list[str] = []
    changed = False
    failed = False

    for entry in entries:
        key = providers.api_key(entry.name)
        try:
            catalogue = served(entry, key)
        except Exception as exc:
            failed = True
            sections.append(
                f"### {entry.name}\n\nCould not list models: "
                f"{scrub(f'{type(exc).__name__}: {exc}')}\n"
            )
            continue

        report = review(entry, catalogue, ledger)
        slot = _slot(ledger, entry.name)
        before = {
            "free": slot.get("free"),
            "verdicts": slot.get("verdicts"),
            "failing_since": dict(slot.get("failing_since") or {}),
        }

        verdicts: dict = {}
        candidates: list[str] = []
        skipped = 0
        if parsed.probe:
            # A key is not required, and this used to think it was. Absent, it skipped
            # the probing pass and said so, which turned the two findings that need a
            # completion — a stealth codename, and a model that is served but answers
            # nothing — into features only a deployment with a secret ever got. The
            # workflow has no secret, so in practice they were never checked at all.
            #
            # Zen serves a free model to a request with no `Authorization` header:
            # measured, 200 and a full streamed completion with a tool offered. So the
            # key is an option, not a prerequisite, and the only thing it changes is
            # whether a *paid* model can be probed as anything but paid. Said out loud
            # either way, because "probed" and "probed keyless" are different evidence.
            if not key:
                # No heading: `summarise` writes one for this provider a few lines
                # down, and two in a row reads as two providers.
                sections.append(
                    f"No key in `{entry.key_env}`, so the probes below carried no "
                    "`Authorization` header. The free lineup answers without one; a "
                    "paid model replies `Missing API key`, which is what prices it.\n"
                )
            # Three groups, in the order they are worth a request.
            #
            # New free models, because served is not working. Then **the free lineup
            # itself**, which is the group this queue used to omit and the omission that
            # made finding #2 unreachable: a model both named in the profile and free by
            # the rule was in neither list, so the only models ever probed were the ones
            # nothing knew about yet. `muse-spark-1.2-contributor-free` returned `500
            # Internal server error` to every request for as long as anyone had been
            # watching, was listed by `GET /models` throughout, and no run ever asked it
            # a question. Then the unclassified names, which are the stealth-codename
            # hunt and the only group that can afford to wait.
            #
            # Budgeted together so a day Zen rewrites its catalogue cannot spend sixty
            # requests, and what the budget dropped is reported rather than silently
            # omitted. Ordering is the priority: the lineup a reader can actually pick
            # gets checked before the catalogue is trawled for the next `big-pickle`.
            queue = report["appeared"] + report["free"] + report["unclassified"]
            queue = list(dict.fromkeys(queue))
            budget = parsed.probe_budget if parsed.probe_budget > 0 else len(queue)
            skipped = max(0, len(queue) - budget)
            for model_id in queue[:budget]:
                verdict = verdict_for(entry, key, model_id)
                verdicts[model_id] = verdict
                if verdict.get("tier") == "paid":
                    if model_id not in slot["paid"]:
                        slot["paid"].append(model_id)
                elif (
                    model_id in report["unclassified"]
                    and verdict.get("tier") == "free"
                    and verdict.get("answered")
                ):
                    candidates.append(model_id)

        # A served free model that could not answer, for how long. Only the free
        # lineup: a paid model refusing a keyless request is the expected answer, not a
        # fault, and a name nobody has classified yet has no place on this list either.
        #
        # Accrued like `missing_since` rather than recomputed, because one bad morning
        # is not a verdict and the whole question is how many mornings there have been.
        # Cleared the moment a probe answers, so a model that comes back starts again
        # from nothing — `hy3-free` did exactly that.
        health = dict(slot.get("failing_since") or {})
        for model_id, verdict in verdicts.items():
            if model_id not in report["free"] or _unmeasured(verdict):
                continue
            if verdict.get("answered"):
                health.pop(model_id, None)
            else:
                health.setdefault(model_id, today())
        for model_id in list(health):
            # Gone from the catalogue is a different finding with its own clock, and a
            # model on both lists would be reported and retired twice.
            if model_id not in catalogue:
                del health[model_id]
        report["failing_since"] = health

        report["verdicts"] = {**(slot.get("verdicts") or {}), **verdicts}
        report["candidates"] = candidates
        report["skipped"] = skipped

        reasons = material(before, report)
        if reasons:
            changed = True
        sections.append(summarise(report, reasons))

        slot.update(
            served=catalogue,
            free=report["free"],
            listed=report["listed"],
            missing_since=report["missing_since"],
            failing_since=report["failing_since"],
            verdicts=report["verdicts"],
            candidates=candidates,
            checked=now(),
        )

        if parsed.update and report["appeared"]:
            # A model the profile does not name, that the rule calls free, and that no
            # probe has contradicted. A probe that came back empty or errored holds it
            # back — the whole point of #2 in the docstring.
            additions = [
                model_id
                for model_id in report["appeared"]
                if verdicts.get(model_id, {}).get("answered", True)
            ]
            held = [name for name in report["appeared"] if name not in additions]
            path = _active().origin
            if additions and not path:
                # A deployment running on the built-in defaults has no file to edit.
                # Worth saying rather than raising on `open("")`, because this runs
                # unattended and a traceback in a scheduled job is read as a bug in the
                # job.
                sections.append(
                    "Nothing to update: this profile is the built-in defaults, so "
                    "there is no file to append to. Set `SAGE_PROFILE`.\n"
                )
                additions = []
            if additions:
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
                updated = append_models(text, entry.name, additions)
                if updated != text:
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write(updated)
                    sections.append(
                        f"Appended to `{os.path.relpath(path, ROOT)}`: "
                        + ", ".join(f"`{name}`" for name in additions)
                        + "\n"
                    )
            if held:
                sections.append(
                    "Held back, because a probe did not get an answer: "
                    + ", ".join(f"`{name}`" for name in held)
                    + "\n"
                )

        if parsed.update:
            # The other half, and the one this workflow used only to report. A model
            # absent from the catalogue for `--retire-after` days comes off the list.
            #
            # Two guards, and neither is style. The list must not be emptied — an empty
            # fallback is what the app falls back *to* when discovery fails, and a
            # provider with no names at all offers nothing at all — so a catalogue that
            # came back short of every listed model is a provider-side fault and gets
            # reported instead of committed. And the first entry is the default and the
            # failover target, so retiring it moves both; that is a real edit and the
            # right one when the anchor is a dead model, but it is not a thing to slip
            # into a diff unannounced.
            path = _active().origin
            # Two ways a model stops existing, and they need opposite edits.
            #
            # Gone from the catalogue: take it out of `models`, which is the stale
            # record. It is already absent from the picker, because the picker's
            # membership comes from discovery.
            #
            # Served and dead: `models` is the wrong lever entirely — removing a name
            # from it only demotes it in the ranking, and the provider goes on serving
            # it, so it goes on being offered. That was the bug behind the error card:
            # the profile had been corrected and the reader still met the model. The
            # lever is `deny`, which the adapter applies to the discovered list.
            retirements = retiring(report, parsed.retire_after)
            denied = failing(report, parsed.retire_after)
            if retirements and not path:
                sections.append(
                    "Nothing to retire: this profile is the built-in defaults, so "
                    "there is no file to edit. Set `SAGE_PROFILE`.\n"
                )
                retirements = []
            surviving = [name for name in report["listed"] if name not in retirements]
            if retirements and not surviving:
                sections.append(
                    "⚠️ Every model named in the profile has been absent for "
                    f"{parsed.retire_after} days or more. Nothing was removed: an "
                    "empty fallback list is what a failed discovery call falls back "
                    "to. This reads as a provider-side outage, not a retirement.\n"
                )
                retirements = []
            if retirements:
                anchor_going = report["listed"][:1] and report["listed"][0] in retirements
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
                updated = retire_models(text, entry.name, retirements)
                if updated != text:
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write(updated)
                    why = {
                        **dict.fromkeys(report["vanished"], "absent"),
                        **dict.fromkeys(
                            report.get("failing_since") or {}, "not answering"
                        ),
                    }
                    sections.append(
                        f"Removed from `{os.path.relpath(path, ROOT)}`, "
                        f"{parsed.retire_after} days or more: "
                        + ", ".join(
                            f"`{name}` ({why.get(name, 'gone')})"
                            for name in retirements
                        )
                        + "\n"
                    )
                    if anchor_going:
                        sections.append(
                            f"⚠️ `{report['listed'][0]}` was the first entry, so this "
                            f"moves the default and the failover target to "
                            f"`{surviving[0]}`. Worth agreeing with before merging.\n"
                        )

            # The deny list, rewritten to what is true today. Additions are models that
            # have failed every probe for the threshold; removals are models on the
            # list that answered this run, and they matter more — a blocklist that
            # cannot let go is the failure mode the profile warns about, and `hy3-free`
            # is the standing proof that a dead free model can come back.
            if path:
                was = list(entry.deny)
                recovered = [
                    name for name in was
                    if (verdicts.get(name) or {}).get("answered")
                ]
                now_denied = sorted(
                    {name for name in was if name not in recovered} | set(denied)
                )
                if now_denied != sorted(was):
                    with open(path, encoding="utf-8") as handle:
                        text = handle.read()
                    updated = set_deny(text, entry.name, now_denied)
                    if updated != text:
                        with open(path, "w", encoding="utf-8") as handle:
                            handle.write(updated)
                        added = [n for n in now_denied if n not in was]
                        if added:
                            sections.append(
                                "Taken out of the picker, failing for "
                                f"{parsed.retire_after} days or more: "
                                + ", ".join(f"`{n}`" for n in added) + "\n"
                            )
                        if recovered:
                            sections.append(
                                "Put back in the picker, answering again: "
                                + ", ".join(f"`{n}`" for n in recovered) + "\n"
                            )

    ledger["checked"] = now()
    os.makedirs(os.path.dirname(parsed.ledger) or ".", exist_ok=True)
    with open(parsed.ledger, "w", encoding="utf-8") as handle:
        json.dump(ledger, handle, indent=2, sort_keys=True)
        handle.write("\n")

    body = "\n".join(sections)
    if failed:
        return 2, body, changed
    if changed and parsed.fail_on_drift:
        return 1, body, changed
    return 0, body, changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="", help="just this one")
    parser.add_argument("--ledger", default=LEDGER)
    parser.add_argument(
        "--probe",
        action="store_true",
        help="spend one real completion per new or unclassified model id",
    )
    parser.add_argument(
        "--probe-budget",
        type=int,
        default=12,
        help="most probes one run may spend; 0 for no cap",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="append served free models the profile does not name",
    )
    parser.add_argument(
        "--retire-after",
        type=int,
        default=7,
        metavar="DAYS",
        help=(
            "with --update, remove profile entries absent from the catalogue for this "
            "many days (0 keeps them for ever, which was the old behaviour). Seven "
            "because `hy3-free` came back after two"
        ),
    )
    parser.add_argument("--summary-out", default="", help="write the markdown here")
    parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="exit 1 when something material changed. Not for CI — see the docstring",
    )
    parsed = parser.parse_args()

    code, body, changed = run(parsed)
    print(body)
    if parsed.summary_out:
        with open(parsed.summary_out, "w", encoding="utf-8") as handle:
            handle.write(body)
    # Read by the workflow to decide whether there is anything worth a pull request.
    step_output = os.getenv("GITHUB_OUTPUT")
    if step_output:
        with open(step_output, "a", encoding="utf-8") as handle:
            handle.write(f"changed={'true' if changed else 'false'}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())

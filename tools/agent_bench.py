#!/usr/bin/env python3
"""Axis B: how each model behaves inside this app's loop, measured rather than assumed.

The default model was chosen from a latency anecdote written into a profile comment —
"answers in 2.2s" against "23s when it answers at all". That is the seat-of-the-pants
decision this file replaces. Every question goes through `app.py` itself under a
stubbed Streamlit (see `evals/harness.py`), so what is measured is the real tool loop,
the real history budget, the real failover and the real citation post-processing.

    python tools/agent_bench.py --models default --limit 6
    python tools/agent_bench.py --models all --out report/
    OPENCODE_BASE_URL=http://127.0.0.1:8799/v1 python tools/agent_bench.py --models all

The last line points the whole benchmark at `tools/mock_provider.py`: no key, no
network, deterministic — which is how to check the harness before spending a free
tier's allowance on it.

**This is never a CI gate.** A free tier's lineup rotates without notice and its
models are nondeterministic; a ratchet here would go red for reasons that are not this
repository's fault, and somebody would loosen it to make the build quiet. The output is
a dated report and a diff against the last one. What belongs in `pytest` is Axis A —
whether the app survives a model behaving badly — and that is already there.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import evals  # noqa: E402
from evals import checks, harness  # noqa: E402
from sage import corpus as corpus_mod  # noqa: E402
from sage import normalize, providers, retrieval  # noqa: E402
from sage.profile import active as _active  # noqa: E402


def lineup(names: list[str]) -> list[str]:
    """Model keys this deployment can actually reach, in the profile's order."""
    found: list[str] = []
    for name in providers.names():
        key = providers.api_key(name)
        if not key:
            continue
        if names and name not in names:
            continue
        try:
            found.extend(model.key for model in providers.build(name, key).models())
        except Exception as exc:  # a provider that cannot be listed is a finding
            print(f"   {name}: could not list models ({type(exc).__name__}: {exc})",
                  file=sys.stderr)
    return found


def percentile(values: list[float], fraction: float) -> float | None:
    kept = sorted(value for value in values if value is not None)
    if not kept:
        return None
    index = min(len(kept) - 1, int(round(fraction * (len(kept) - 1))))
    return round(kept[index], 2)


def query_quality(index, records: list[dict]) -> dict:
    """Did the model's own search query retrieve better than the question did?

    The one place a documentation agent can help or hurt retrieval on purpose: it
    rewrites the reader's question before searching. Scored on the cases that have a
    gold page, by asking the same index both ways — so this isolates the model's
    contribution from the ranking's.
    """
    better = worse = same = 0
    for record in records:
        pages = set(record.get("pages") or ())
        queries = record.get("queries") or []
        if not pages or not queries:
            continue
        asked = {result.chunk.path for result in index.search(record["question"], 5)}
        theirs: set[str] = set()
        for query in queries:
            theirs |= {result.chunk.path for result in index.search(query, 5)}
        hit_asked = bool(pages & asked)
        hit_theirs = bool(pages & theirs)
        if hit_theirs and not hit_asked:
            better += 1
        elif hit_asked and not hit_theirs:
            worse += 1
        else:
            same += 1
    return {"better": better, "worse": worse, "same": same}


#: Failures of the *key*, not of the model. A free tier says no in three different ways
#: and none of them is an answer the model got wrong: `rate_limit` is "too fast",
#: `allowance` is "this model's free quota is spent", `quota` is "this key has no
#: credit". Charged to the instrument the way `unfinished` is, because a row that folds
#: them into `answered` reports a rate limiter as a model that would not answer.
BUDGET_KINDS = ("rate_limit", "allowance", "quota")


def served_tally(records: list[dict]) -> dict:
    """Which models a ROUTER actually served, and how often.

    The measurement a router makes different in kind from a pinned model. `openrouter/`
    `free` is one id that resolves to a different model per request, so every
    answer-shaped cell in this row — defects, refusals, gold pages — is an average over
    whatever was behind it, and the average is unreadable on its own. `0.1 defects/`
    `answer` over fourteen models is a fact about a lineup; the same number over one
    model is a fact about a model.

    Two tallies, because they answer different questions. `requests` counts every call
    the turns made, which is what the router's mix looks like. `answers` counts only the
    request that produced the text — on a tool loop the earlier rounds were served by
    other models, and the cells above are about the last one.

    Empty for a pinned model: nothing is served but the id that was asked for, and this
    prints nothing rather than a one-row table saying so.
    """
    per_request: dict[str, int] = {}
    per_answer: dict[str, int] = {}
    upstreams: dict[str, int] = {}
    for row in records:
        for call in row.get("requests") or ():
            for name in call.get("served") or ():
                per_request[name] = per_request.get(name, 0) + 1
            for host in call.get("upstream") or ():
                upstreams[host] = upstreams.get(host, 0) + 1
        answered_by = str(row.get("served_answer") or "")
        if answered_by and row.get("outcome") == "answered":
            per_answer[answered_by] = per_answer.get(answered_by, 0) + 1
    if not per_request:
        return {}
    return {
        "distinct": len(per_request),
        "requests": dict(sorted(per_request.items(), key=lambda item: -item[1])),
        "answers": dict(sorted(per_answer.items(), key=lambda item: -item[1])),
        "upstream": dict(sorted(upstreams.items(), key=lambda item: -item[1])),
    }


def refused_shapes(records: list[dict]) -> dict:
    """The three answers `ui.turn` will not ship, counted where they still exist.

    Each of them raises `empty`, so the delivered `text` is blank and
    `checks.inspect` — which returns no findings for an empty answer — cannot see any of
    them. `checks.reasoning_shape`, `typed_out_tool_call` and `moderation_verdict` are
    therefore scored on text that by construction never contains what they look for,
    which is the trap EVAL.md describes for `leaked-reasoning` and which the fix to the
    app reopened. `harness` keeps the last request's own stream for this reason, and
    these counts are read off that rather than off the answer.

    `blank` is the rest of the empties: the stream really did carry nothing, which is a
    different fact about a free router and worth telling apart from the three shapes.
    """
    counts = {
        "moderation_verdict": 0,
        "deliberation": 0,
        "written_out_tool_call": 0,
        "blank": 0,
    }
    for row in records:
        # Only where the app produced no answer. A record that answered was not one of
        # these — `ui.turn` raises before it can be — and scoring the shapes over a
        # delivered answer is what `checks` already does.
        if row.get("outcome") == "answered":
            continue
        streamed = str(row.get("streamed_final") or "")
        if normalize.is_moderation_verdict(streamed):
            counts["moderation_verdict"] += 1
        elif normalize.opens_with_deliberation(streamed):
            counts["deliberation"] += 1
        elif normalize.is_written_out_tool_call(streamed):
            counts["written_out_tool_call"] += 1
        elif row.get("error_kind") == "empty":
            counts["blank"] += 1
    return counts


def summarise(model: str, records: list[dict], index) -> dict:
    total = len(records) or 1
    # Which of the app's two answering paths these turns went down. Recorded rather than
    # assumed, and computed from the records rather than passed in, so a row that somehow
    # covers both says so instead of averaging them: `srch 50%  rnd 2.0` over three tool
    # turns and three grounded ones is true of neither, and reads as a model that searches
    # half the time. Missing on transcripts written before the field existed, and those
    # were all tool-path runs.
    paths = {str(row.get("path") or "tools") for row in records}
    arm = next(iter(paths)) if len(paths) == 1 else "mixed"
    answered = [row for row in records if row["outcome"] == "answered"]
    positives = [row for row in answered if row["expect"] == "answer"]
    negatives = [row for row in answered if row["expect"] == "caveat"]

    kinds: dict[str, int] = {}
    for row in records:
        if row["error_kind"]:
            kinds[row["error_kind"]] = kinds.get(row["error_kind"], 0) + 1

    tool_calls = [call for row in records for call in row["tool_calls"]]
    bad_args = sum(1 for call in tool_calls if not call["arguments"])

    def tally_of(key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in answered:
            for kind in row.get(key, []):
                counts[kind] = counts.get(kind, 0) + 1
        return counts

    tally = tally_of("defects")
    warnings = tally_of("warnings")

    with_gold = [row for row in positives if row["pages"]]
    return {
        "model": model,
        "path": arm,
        "n": len(records),
        "answered": len(answered) / total,
        "empty": sum(1 for row in records if row["error_kind"] == "empty") / total,
        "refused": sum(1 for row in records if row["outcome"] == "refused") / total,
        "crashed": sum(1 for row in records if row["outcome"] == "crashed") / total,
        # The harness running out of script runs, not the model failing. Kept separate so
        # a bound of the instrument is never charged to the thing being measured.
        "unfinished": sum(
            1 for row in records if row["outcome"] == "unfinished"
        ) / total,
        "error_kinds": kinds,
        "searched": (
            sum(1 for row in answered if row["searches"]) / (len(answered) or 1)
        ),
        "read": sum(1 for row in answered if row["reads"]) / (len(answered) or 1),
        "rounds": round(statistics.mean([row["rounds"] for row in records]), 2),
        "calls": round(statistics.mean([row["provider_calls"] for row in records]), 2),
        "read_errors": sum(row["read_errors"] for row in records),
        "bad_tool_args": bad_args,
        # What the reader can click: the pages the turn read *or* the answer links to. The
        # Sources strip is built from `read_doc` alone, so a model that cites a page from a
        # search snippet without reading it hands over a working link — and this column,
        # labelled `cited_gold` on the card, scored six of 157 recorded answers as having
        # cited nothing. 94.3% became 98.1% when the links were counted.
        "cited_gold": (
            sum(
                1 for row in with_gold
                if set(row["pages"]) & (
                    set(row["source_pages"]) | set(row.get("cited_pages") or [])
                )
            )
            / (len(with_gold) or 1)
        ),
        # And the stricter reading, kept because the prompt asks the model to *read* before
        # answering: citing a page off a snippet is weaker evidence than having read it,
        # and a model that stops reading altogether should be visible.
        "read_gold": (
            sum(1 for row in with_gold if set(row["pages"]) & set(row["source_pages"]))
            / (len(with_gold) or 1)
        ),
        "first_text_p50": percentile([row["first_text"] for row in records], 0.5),
        "first_text_p95": percentile([row["first_text"] for row in records], 0.95),
        "seconds_p50": percentile([row["seconds"] for row in records], 0.5),
        "seconds_p95": percentile([row["seconds"] for row in records], 0.95),
        "defects_per_answer": round(
            sum(row.get("defect_count", 0) for row in answered) / (len(answered) or 1), 2
        ),
        "defect_kinds": tally,
        "warning_kinds": warnings,
        "refusal_correct": (
            sum(1 for row in negatives if "no-refusal" not in row.get("findings", []))
            / (len(negatives) or 1)
        ),
        "n_negatives_answered": len(negatives),
        "query_quality": query_quality(index, positives),
        # Whether this row is a whole run. FALSE the moment the provider refused a turn
        # for its own reasons, and it is not a detail: a set that stopped two thirds of
        # the way through is a different measurement from the one it was asked for, and
        # a partial run read as a full one is worse than no row at all. Derived rather
        # than declared, so it survives `--rescore` — which recomputes every row from
        # the transcripts and would drop any note written by hand.
        "complete": not any(
            row.get("error_kind") in BUDGET_KINDS for row in records
        ),
        # A free tier saying no, kept out of every rate above for the reason `unfinished`
        # is: it is the key's bound, not the model's behaviour. Counted rather than
        # rated, because the denominator a reader wants here is the turn, not the set.
        "budget_refused": sum(
            1 for row in records if row.get("error_kind") in BUDGET_KINDS
        ),
        "budget_kinds": {
            kind: sum(1 for row in records if row.get("error_kind") == kind)
            for kind in BUDGET_KINDS
            if any(row.get("error_kind") == kind for row in records)
        },
        # Only populated where the id is a router. See `served_tally`.
        "served": served_tally(records),
        "refused_shapes": refused_shapes(records),
        # Turns a READER's app would have asked the router again for, and this one did
        # not. `ui.turn` re-rolls on `REROLL_KINDS` — `empty`, which is every shape
        # above — but only when `config.MAX_MODEL_ATTEMPTS != 1`, and `harness.prepare`
        # sets it to 1 so the row is about the model that was asked rather than about
        # whatever a second roll landed on. So this is the count the re-roll would have
        # rescued, measured with the re-roll switched off: the gap between this row and
        # what a reader sees, stated rather than left to be inferred from its absence.
        "reroll_eligible": sum(
            1 for row in records if row.get("error_kind") == "empty"
        ),
        "forbidden_tool_calls": sum(
            int(row.get("forbidden_tool_calls") or 0) for row in records
        ),
        # Requests that went out with the schemas attached and the call forbidden — the
        # last round of every tool turn. The denominator for the count above.
        "forbidden_rounds": sum(
            1 for row in records for call in row.get("requests") or ()
            if call.get("tool_choice") == "none"
        ),
    }


def crashed_record(question, model, expect, must, pages, exc, started,
                   toolless=False) -> dict:
    """A turn that took the harness down with it. Recorded, not raised.

    One model in seven does something no other does, and a benchmark that stops on the
    first of them measures the six that ran before it.
    """
    return {
        "question": question, "model": model, "expect": expect,
        "outcome": "crashed", "fatal": f"{type(exc).__name__}: {exc}",
        # The arm asked for, not the arm observed — the only record where those can
        # differ, because a crash may come before any request reached the provider.
        # Absent entirely, a crashed grounded turn would be summarised as a tool one.
        "path": "grounded" if toolless else "tools",
        "unfinished": False,
        "error": "", "error_kind": "", "text": "", "raw": "",
        "sources": [], "source_pages": [], "evidence": {},
        "pages": list(pages), "must_mention": list(must),
        "tool_calls": [], "searches": 0, "reads": 0, "queries": [],
        "read_errors": 0, "rounds": 0, "provider_calls": 0,
        "seconds": round(time.monotonic() - started, 3),
        "first_text": None, "first_byte": None, "stream_chunks": [],
    }


def one_turn(question, model, expect, must, pages, sage, haystack, contact,
             internals=None, toolless=False) -> dict:
    started = time.monotonic()
    try:
        record = harness.run_turn(
            question, model, expect=expect, must_mention=must, pages=pages,
            toolless=toolless,
        )
    except BaseException as exc:  # noqa: BLE001 — one bad turn is data, not an exit
        record = crashed_record(
            question, model, expect, must, pages, exc, started, toolless=toolless
        )

    found = checks.inspect(
        record, sage.corpus, haystack, contact=contact, internals=internals
    )
    record["findings"] = [item.kind for item in found]
    record["defects"] = [item.kind for item in checks.defects(found)]
    record["warnings"] = [
        item.kind for item in found if item.severity == checks.WARNING
    ]
    record["defect_count"] = len(record["defects"])
    record["finding_detail"] = [str(item) for item in found]
    return record


def run(
    models: list[str],
    cases: list[tuple],
    *,
    sleep: float,
    out: str,
    conversations: bool = False,
    injections: bool = False,
    meta: bool = False,
    toolless: bool = False,
) -> dict:
    """Every phase asked for, over one prepared harness and one transcript stream."""
    sage = harness.prepare()
    haystack = checks.Haystack(sage.corpus)
    contact = _active().identity.contact
    # The toolset's own names rather than `DEFAULT_TOOLS`, so a deployment that registered
    # a third tool has that name checked for too without editing anything here.
    internals = checks.Internals(tool_names=tuple(sage.toolset.by_name))

    summary: dict = {"models": [], "conversations": [], "injections": [], "meta": []}
    # Written and flushed per turn rather than dumped at the end: a long run over a free
    # tier gets interrupted, and the turns it already paid for should survive that.
    with contextlib.ExitStack() as stack:
        stream = None
        if out:
            os.makedirs(out, exist_ok=True)
            stream = stack.enter_context(
                open(os.path.join(out, "transcripts.jsonl"), "a", encoding="utf-8")
            )
        for model in models:
            if not cases:
                break
            records = []
            print(f"\n{model}", flush=True)
            for question, expect, must, pages in cases:
                record = one_turn(
                    question, model, expect, must, pages, sage, haystack, contact,
                    internals=internals, toolless=toolless,
                )
                records.append(record)
                if stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                    stream.flush()
                mark = {
                    "answered": "ok", "refused": "refused",
                    "nothing": "nothing", "crashed": "CRASH",
                    "unfinished": "UNFIN",
                }.get(record["outcome"], record["outcome"])
                print(f"   {mark:8s} {record['seconds']:6.1f}s "
                      f"r{record['rounds']} s{record['searches']} d{record['reads']} "
                      f"{record['defect_count']}def  {question[:52]!r}", flush=True)
                if sleep:
                    time.sleep(sleep)
            summary["models"].append(summarise(model, records, sage.retriever))

        if conversations:
            summary["conversations"] = run_conversations(
                models, sage, haystack, contact, stream, internals, toolless=toolless
            )
        if injections:
            summary["injections"] = run_injections(
                models, sage, haystack, contact, stream, internals, toolless=toolless
            )
        if meta:
            summary["meta"] = run_meta(
                models, sage, haystack, contact, stream, internals, toolless=toolless,
                label=_active().identity.contact_label,
            )
    return summary


def run_conversations(models, sage, haystack, contact, stream, internals=None,
                      toolless=False) -> list[dict]:
    """Multi-turn, one session per case. What a single-question benchmark cannot see."""
    out = []
    for model in models:
        print(f"\n{model} — conversations", flush=True)
        rows = []
        for case in evals.conversations():
            records = harness.run_conversation(
                list(case.turns), model, toolless=toolless
            )
            for position, record in enumerate(records):
                found = checks.inspect(
                    record, sage.corpus, haystack, contact=contact, internals=internals
                )
                record["defects"] = [item.kind for item in checks.defects(found)]
                record["warnings"] = [
                    item.kind for item in found if item.severity == checks.WARNING
                ]
                record["findings"] = [item.kind for item in found]
                record["defect_count"] = len(record["defects"])
                record["conversation"] = case.name
                if stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                    stream.flush()
                kept = (
                    bool(set(record["pages"]) & set(record["source_pages"]))
                    if record["pages"] else None
                )
                print(f"   turn {position + 1}  {record['outcome']:8s} "
                      f"gold={'-' if kept is None else ('yes' if kept else 'NO ')}  "
                      f"{record['defect_count']}def  {record['question'][:46]!r}",
                      flush=True)
            rows.extend(records)

        out.append(_conversation_summary(model, rows))
    return out


def _read_rate(rows: list[dict]) -> float:
    """The stricter half of `_gold_rate`: pages the turn actually read."""
    if not rows:
        return 0.0
    hits = sum(1 for row in rows if set(row["pages"]) & set(row["source_pages"] or []))
    return hits / len(rows)


def _conversation_summary(model: str, rows: list[dict]) -> dict:
    """`first_turn_gold` against `follow_up_gold` is the multi-turn measurement.

    A model that puts the right page in front of the reader on the opening question and
    stops doing it on the follow-up has lost the thread, and the failure is quiet: a
    plausible answer to a question nobody asked, cited to a real page.

    Both rates count a page the answer *links to* as well as one the turn read — see
    `_gold_rate`. Scoring `read_doc` calls alone put the follow-up rate at 83.3% over 36
    recorded follow-ups where the reader-visible figure is 100%, and that gap was published
    as a finding about models losing the thread. `read_gold` keeps the strict reading, which
    is the one that says whether a follow-up went back to the documentation at all.
    """
    follow_ups = [row for row in rows if row.get("turn_index", 0) > 0 and row["pages"]]
    first_turns = [row for row in rows if row.get("turn_index", 0) == 0 and row["pages"]]
    return {
        "model": model,
        "turns": len(rows),
        "first_turn_gold": _gold_rate(first_turns),
        "follow_up_gold": _gold_rate(follow_ups),
        "first_turn_read": _read_rate(first_turns),
        "follow_up_read": _read_rate(follow_ups),
        "answered": sum(1 for row in rows if row["outcome"] == "answered")
        / (len(rows) or 1),
        "question_always_sent": all(row.get("question_sent", True) for row in rows),
        "peak_request_chars": max((row.get("sent_chars", 0) for row in rows), default=0),
        "defects": sum(row["defect_count"] for row in rows),
        # A conversation on a router is answered by a different model every turn, so "did the
        # follow-up keep the thread?" is asked of a lineup rather than of a model. Empty
        # on a pinned id.
        "served": served_tally(rows),
    }


def _gold_rate(rows: list[dict]) -> float:
    """Turns that put a gold page in front of the reader, read or linked.

    The same correction as `cited_gold` in `summarise`, and it matters more here: a
    follow-up is exactly the turn that answers from what it already has, so scoring only
    `read_doc` calls understates the number this set exists to produce. Two of the six
    recorded turns the old rule missed were follow-ups.
    """
    if not rows:
        return 0.0
    hits = sum(
        1 for row in rows
        if set(row["pages"]) & (
            set(row["source_pages"]) | set(row.get("cited_pages") or [])
        )
    )
    return hits / len(rows)


def run_injections(models, sage, haystack, contact, stream, internals=None,
                   toolless=False) -> list[dict]:
    """An instruction hidden in an uploaded file, which the app promises to ignore."""
    from sage import files  # noqa: PLC0415 — only this phase needs it

    out = []
    for model in models:
        print(f"\n{model} — injections", flush=True)
        rows = []
        for case in evals.injections():
            # Through `files.process`, not `Attachment(...)` by hand. The harness's whole
            # claim is that it measures the app rather than a copy of it, and building the
            # attachment directly skipped the upload path — including the filename
            # sanitising that stops a name forging the `--- END ---` frame, which is what
            # the `forged frame` case exists to check.
            attachment, refused = files.process(
                case.filename, case.content.encode("utf-8")
            )
            if attachment is None:
                print(f"   SKIPPED {case.name}: the app refused it ({refused})",
                      flush=True)
                continue
            record = harness.run_turn(
                case.question, model, attachments=[attachment], toolless=toolless
            )
            found = checks.inspect(
                record, sage.corpus, haystack, contact=contact, internals=internals
            )
            found += checks.injection_findings(
                record["text"], case.canary, case.leaks,
                verbatim=checks.said(record),
            )
            record["injection"] = case.name
            record["findings"] = [item.kind for item in found]
            record["defects"] = [item.kind for item in checks.defects(found)]
            record["defect_count"] = len(record["defects"])
            rows.append(record)
            if stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
            verdict = (
                "OBEYED" if "obeyed-injection" in record["findings"]
                else "LEAKED" if "leaked-prompt" in record["findings"]
                else "held"
            )
            print(f"   {verdict:7s} {record['outcome']:8s} {case.name}", flush=True)
        out.append(
            {
                "model": model,
                "n": len(rows),
                "obeyed": sum(
                    1 for row in rows if "obeyed-injection" in row["findings"]
                ),
                "leaked": sum(1 for row in rows if "leaked-prompt" in row["findings"]),
                "answered": sum(1 for row in rows if row["outcome"] == "answered"),
                # `held` on a router is six cases spread over six different models, so
                # the row is only as strong as the names behind it. Empty on a pinned id.
                "served": served_tally(rows),
            }
        )
    return out


def meta_findings(record: dict, case, sage, haystack, contact, internals) -> list:
    """Score one answer about the assistant itself. Shared with `--rescore`.

    The probe's own `leaks` go through `injection_findings` with no canary: a phrase from
    the system prompt in an answer is the same defect whether a file asked for it or a
    reader did, and it is already tested there.
    """
    found = checks.inspect(
        record, sage.corpus, haystack, contact=contact, internals=internals
    )
    return found + checks.injection_findings(
        record["text"], "", case.leaks, verbatim=checks.said(record)
    )


def meta_row(case, contact: str, contact_label: str = "") -> dict:
    """What one case asks of the answer: the arm, and the tokens it must contain.

    A `contact = true` case is satisfied by the address *or* the desk's name, because
    either sends the reader somewhere — see `checks.missing_any`. Both come from the
    profile rather than from the file, so the case ports to a deployment with a different
    handover.
    """
    handover = tuple(item for item in (contact, contact_label) if item)
    return {
        "expect": checks.SELF,
        "must_mention": tuple(case.must_mention),
        "must_mention_any": handover if case.contact else (),
    }


def run_meta(models, sage, haystack, contact, stream, internals=None,
             toolless=False, label: str = "") -> list[dict]:
    """Asked about itself: does it answer without narrating the machinery?

    The two halves are scored separately and reported side by side, because the failures
    point in opposite directions and a single number over both would hide either one. A
    probe fails by naming an internal name or reciting a line of the prompt; an
    `answerable` case fails by deflecting a question that has a good answer.
    """
    out = []
    for model in models:
        print(f"\n{model} — asked about itself", flush=True)
        rows = []
        for case in evals.meta():
            asked = meta_row(case, contact, label)
            record = harness.run_turn(
                case.text, model,
                expect=asked["expect"], must_mention=asked["must_mention"],
                toolless=toolless,
            )
            # Not a `run_turn` argument: the harness passes `must_mention` through to the
            # record and nothing else, and this is the only case shape that needs a second
            # kind of requirement. Set on the record, which is what the checks read.
            record["must_mention_any"] = asked["must_mention_any"]
            found = meta_findings(record, case, sage, haystack, contact, internals)
            record["meta"] = case.text
            record["meta_kind"] = case.kind
            record["findings"] = [item.kind for item in found]
            record["defects"] = [item.kind for item in checks.defects(found)]
            record["warnings"] = [
                item.kind for item in found if item.severity == checks.WARNING
            ]
            record["defect_count"] = len(record["defects"])
            record["finding_detail"] = [str(item) for item in found]
            rows.append(record)
            if stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
            print(f"   {_meta_verdict(record):9s} {record['outcome']:8s} "
                  f"{case.kind:10s} {case.text[:46]!r}", flush=True)
        out.append(_meta_summary(model, rows))
    return out


def _meta_verdict(record: dict) -> str:
    """What happened to one answer, worst thing first.

    `CAUGHT` sits between the two ends on purpose: the reader got a clean answer, so it is
    not a disclosure — and the model still tried, which is not the same as `held`.
    """
    findings = record.get("findings") or []
    if "disclosed-internals" in findings or "leaked-prompt" in findings:
        return "DISCLOSED"
    if "caught-internals" in findings:
        return "CAUGHT"
    if "stonewalled" in findings:
        return "WALLED"
    if "missing-required-token" in findings:
        return "thin"
    if "narrated-machinery" in findings:
        return "narrated"
    return "held"


def _meta_summary(model: str, rows: list[dict]) -> dict:
    probes = [row for row in rows if row.get("meta_kind") != evals.ANSWERABLE]
    plain = [row for row in rows if row.get("meta_kind") == evals.ANSWERABLE]

    def rate(subset: list[dict], bad: tuple[str, ...]) -> float | None:
        """Over the turns that produced an answer, not over the turns attempted.

        `hy3-free` spent its free allowance twelve turns into a run: twelve refusals from
        the provider, scored as a model that stopped answering questions about itself —
        62% held, 0% kept, and neither number was about the model at all. A bound of the
        instrument must never be charged to the thing being measured, which is the same
        rule `unfinished` exists for in `summarise`. `answered` below is where a run like
        that shows up.
        """
        answered = [row for row in subset if row["outcome"] == "answered"]
        if not answered:
            # Not 0.0. Nothing was measured, and a rate of zero reads as a model that
            # failed every one of them — the same mistake the card's `unmeasured` cells
            # exist to prevent, one level down.
            return None
        clean = [
            row for row in answered
            if not set(bad) & set(row.get("findings") or [])
        ]
        return len(clean) / len(answered)

    named = [
        detail.split(": ", 1)[-1].replace(" (removed before display)", "")
        for row in rows for detail in row.get("finding_detail") or []
        if detail.startswith(("defect:disclosed-internals", "warning:caught-internals"))
    ]
    return {
        "model": model,
        "n": len(rows),
        "n_probes": len(probes),
        "n_answerable": len(plain),
        # The denominators the two rates are actually over, so a run that lost half its
        # turns to a provider cannot be read as a run that measured them.
        "probes_answered": sum(1 for row in probes if row["outcome"] == "answered"),
        "answerable_answered": sum(1 for row in plain if row["outcome"] == "answered"),
        # The headline pair, and they measure different things on purpose. `held` is what
        # the reader got — a name `sage.redact` removed was never disclosed, so it counts.
        # `kept` is whether the ordinary questions still got an answer: a fix that raises
        # the first by lowering the second has not worked.
        "held": rate(probes, ("disclosed-internals", "leaked-prompt")),
        "kept": rate(plain, ("stonewalled", "missing-required-token")),
        # And the third: what the model managed on its own, with the app's backstop taken
        # away. This is the number the prompt moves, and the only one worth quoting when
        # comparing two models.
        "unaided": rate(
            probes, ("disclosed-internals", "leaked-prompt", "caught-internals")
        ),
        "caught": sum(
            1 for row in rows if "caught-internals" in (row.get("findings") or [])
        ),
        "disclosed": sum(
            1 for row in rows if "disclosed-internals" in (row.get("findings") or [])
        ),
        "leaked": sum(
            1 for row in rows if "leaked-prompt" in (row.get("findings") or [])
        ),
        "stonewalled": sum(
            1 for row in rows if "stonewalled" in (row.get("findings") or [])
        ),
        "narrated": sum(
            1 for row in rows if "narrated-machinery" in (row.get("findings") or [])
        ),
        "answered": sum(1 for row in rows if row["outcome"] == "answered") / (len(rows) or 1),
        # Which names came up, not only how many times — whether removed before display or
        # not. A count says the check fired; the names say whether it was a tool, the model
        # or the profile's own filenames, and those are three different holes.
        "names": sorted(set(named)),
        # The same two router columns as `summarise`, and they matter more here: `held`
        # over a router is the discretion of a dozen models averaged, and one of them
        # reciting a line of the prompt is a fact about that model rather than about the
        # row. Empty on a pinned id.
        "served": served_tally(rows),
        "budget_refused": sum(
            1 for row in rows if row.get("error_kind") in BUDGET_KINDS
        ),
        "refused_shapes": refused_shapes(rows),
    }


def _pct(value) -> str:
    """A rate, or a dash where there was nothing to measure. Never 0% for "no data"."""
    return "-" if value is None else f"{value:.0%}"


def report_meta(rows: list[dict]) -> None:
    print("\nasked about itself — what it does, not what it is made of")
    print(f"   {'model':34s} {'held':>6s} {'alone':>6s} {'kept':>6s} {'disc':>5s} "
          f"{'held✂':>5s} {'leak':>5s} {'wall':>5s} {'narr':>5s} {'n':>9s}")
    for row in rows:
        # The denominators, because they are not always the set size: a model that spends
        # its free allowance mid-run answers fewer, and both rates are over what answered.
        seen = (f"{row.get('probes_answered', row['n_probes'])}"
                f"/{row.get('answerable_answered', row['n_answerable'])}")
        print(f"   {row['model'][:34]:34s} {_pct(row['held']):>5s} "
              f"{_pct(row.get('unaided')):>5s} {_pct(row['kept']):>5s} "
              f"{row['disclosed']:5d} {row.get('caught', 0):5d} {row['leaked']:5d} "
              f"{row['stonewalled']:5d} {row['narrated']:5d} {seen:>9s}")
        if row["names"]:
            print("      names it reached for: " + ", ".join(row["names"]))
        if row["answered"] < 1.0:
            print(f"      {row['answered']:.0%} of its turns produced an answer at all — "
                  "the rest are the provider, not the model")
        served = row.get("served") or {}
        if served:
            # The names, not only the count: `held` over a router is an average over
            # these, and which model leaked is the actionable half of it.
            print(f"      served by {served['distinct']} models: " + ", ".join(
                f"{name} x{count}" for name, count in served["requests"].items()
            ))
        if row.get("budget_refused"):
            print(f"      {row['budget_refused']} turns refused by the key, not the "
                  "model")
    print(f"   held = of {rows[0]['n_probes']} probes (n = the two answered counts), the "
          "answer as delivered gave nothing away")
    print("   alone = the same without the app's backstop, which is what the prompt "
          "moves")
    print(f"   kept = of {rows[0]['n_answerable']} ordinary questions about itself, "
          "still answered")
    print("   held✂ = answers `sage.redact` had to take a name out of")


def report_conversations(rows: list[dict]) -> None:
    print("\nmulti-turn — did the follow-up keep the thread?")
    print(f"   {'model':34s} {'turns':>6s} {'first':>7s} {'follow':>7s} "
          f"{'read':>7s} {'ans':>5s} {'def':>4s} {'peak req':>9s}")
    for row in rows:
        print(f"   {row['model'][:34]:34s} {row['turns']:6d} "
              f"{row['first_turn_gold']:6.0%} {row['follow_up_gold']:6.0%} "
              f"{row.get('follow_up_read', 0.0):6.0%} "
              f"{row['answered']:4.0%} {row['defects']:4d} "
              f"{row['peak_request_chars']:9d}")
        if not row["question_always_sent"]:
            print("      the question did not survive the history budget on some turn")
    print("   first/follow = a gold page reached the reader, read or linked; read = the "
          "follow-ups that went back to the documentation for it")


def report_injections(rows: list[dict]) -> None:
    print("\nuploads — an instruction inside a file is data, not a command")
    for row in rows:
        # "held" over zero answers is the false pass this whole card is built against: a
        # run where the provider refused all five turns obeyed nothing because it said
        # nothing. Measured the day a spent free allowance produced exactly that row.
        if not row.get("answered"):
            print(f"   {row['model'][:34]:34s} no answers — nothing was measured "
                  f"(0 of {row['n']} turns answered)")
            continue
        verdict = "held" if not (row["obeyed"] or row["leaked"]) else "FAILED"
        print(f"   {row['model'][:34]:34s} {verdict:7s} obeyed {row['obeyed']}/{row['n']}"
              f"   prompt leaked {row['leaked']}/{row['n']}"
              + ("" if row["answered"] == row["n"]
                 else f"   ({row['answered']} of {row['n']} answered)"))
        served = row.get("served") or {}
        if served:
            print(f"      served by {served['distinct']} models: " + ", ".join(
                f"{name} x{count}" for name, count in served["requests"].items()
            ))


def rescore(path: str) -> dict:
    """Recompute every finding from stored transcripts. No network, no model, seconds.

    The checks improve — and they must, because a check with false positives is one
    somebody switches off. Validated against the first 75 real answers, `invented-token`
    dropped from 31 reports to 1 and `damaging-strip` from 8 to 0 once the extractor
    stopped reading `Midway2/3/SSD` as a filesystem path and the diff stopped reading a
    re-linked citation as a deletion. Every one of those 31 was scored by a run already
    paid for, so re-scoring the transcripts is how the correction reaches the card
    without asking a free tier for the same answers again.
    """
    built = corpus_mod.build()
    index = retrieval.build(built)
    haystack = checks.Haystack(built)
    contact = _active().identity.contact
    internals = checks.Internals()
    canaries = {case.name: case for case in evals.injections()}
    asked_about_itself = {case.text: case for case in evals.meta()}

    single: dict[str, list] = {}
    talks: dict[str, list] = {}
    uploads: dict[str, list] = {}
    selves: dict[str, list] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if "cited_pages" not in record and record.get("text"):
                # Recomputed rather than defaulted to empty: every transcript written
                # before this field existed would otherwise be scored by the old rule
                # while the card claimed the new one.
                from sage import links as links_mod  # noqa: PLC0415

                record["cited_pages"] = sorted(
                    links_mod.cited_pages(record["text"], built)
                )
            found = checks.inspect(
                record, built, haystack, contact=contact, internals=internals
            )
            if record.get("injection") in canaries:
                case = canaries[record["injection"]]
                found += checks.injection_findings(
                    record["text"], case.canary, case.leaks,
                    verbatim=checks.said(record),
                )
            elif record.get("meta") in asked_about_itself:
                # Re-scored through the same function the live phase uses, so a correction
                # to the checks reaches a run already paid for — which is the whole point
                # of this mode, and the reason the scoring is a function rather than a
                # block inside the loop.
                found += checks.injection_findings(
                    record["text"], "", asked_about_itself[record["meta"]].leaks,
                    verbatim=checks.said(record),
                )
            record["findings"] = [item.kind for item in found]
            record["defects"] = [item.kind for item in checks.defects(found)]
            record["warnings"] = [
                item.kind for item in found if item.severity == checks.WARNING
            ]
            record["defect_count"] = len(record["defects"])
            record["finding_detail"] = [str(item) for item in found]
            bucket = (
                uploads if record.get("injection")
                else selves if record.get("meta")
                else talks if record.get("conversation")
                else single
            )
            # Keyed by arm as well as model. `transcripts.jsonl` is opened in append
            # mode, so one file accumulates every run written to that directory — and
            # once two of them are different paths through the app, one row averaged
            # over both is a number about nothing.
            key = (record["model"], str(record.get("path") or "tools"))
            bucket.setdefault(key, []).append(record)

    summary: dict = {"models": [], "conversations": [], "injections": [], "meta": []}
    for (model, _arm), records in single.items():
        summary["models"].append(summarise(model, records, index))
    for (model, arm), records in talks.items():
        summary["conversations"].append(_conversation_summary(model, records) | {"path": arm})
    for (model, arm), records in selves.items():
        summary["meta"].append(_meta_summary(model, records) | {"path": arm})
    for (model, arm), records in uploads.items():
        summary["injections"].append(
            {
                "model": model,
                "path": arm,
                "n": len(records),
                "obeyed": sum(
                    1 for row in records if "obeyed-injection" in row["findings"]
                ),
                "leaked": sum(
                    1 for row in records if "leaked-prompt" in row["findings"]
                ),
                "answered": sum(
                    1 for row in records if row["outcome"] == "answered"
                ),
                "served": served_tally(records),
            }
        )
    return summary


def report(summary: dict) -> None:
    if summary.get("conversations"):
        report_conversations(summary["conversations"])
    if summary.get("injections"):
        report_injections(summary["injections"])
    if summary.get("meta"):
        report_meta(summary["meta"])
    rows = summary.get("models") or []
    if not rows:
        return
    print("\n" + "=" * 118)
    print(f"{'model':34s} {'n':>3s} {'ans':>6s} {'empty':>6s} {'srch':>5s} "
          f"{'read':>5s} {'gold':>5s} {'rnd':>4s} {'call':>5s} {'ttft':>6s} "
          f"{'p95':>6s} {'def':>5s} {'refus':>6s}")
    print("-" * 118)
    for row in rows:
        # The arm, only when it is not the tool loop, so a run of the default path prints
        # exactly what it printed before there was a second path to confuse it with.
        arm = str(row.get("path") or "tools")
        label = row["model"] if arm == "tools" else f"{row['model']} [{arm}]"
        print(f"{label[:34]:34s} {row['n']:3d} {row['answered']:5.0%} "
              f"{row['empty']:5.0%} {row['searched']:4.0%} {row['read']:4.0%} "
              f"{row['cited_gold']:4.0%} {row['rounds']:4.1f} {row['calls']:5.1f} "
              f"{str(row['first_text_p50'] or '-'):>6s} "
              f"{str(row['seconds_p95'] or '-'):>6s} "
              f"{row['defects_per_answer']:5.2f} {row['refusal_correct']:5.0%}")
    print("-" * 118)
    print("ans=answered  srch/read=of answered turns  gold=cited a gold page  "
          "rnd=rounds  ttft=first text s (p50)")
    print("def=defects per answer  refus=correct refusals on the unanswerable split")

    for row in rows:
        print(f"\n{row['model']}")
        if row["error_kinds"]:
            print("   failures: " + ", ".join(
                f"{kind} x{count}" for kind, count in sorted(row["error_kinds"].items())
            ))
        for label, key in (("defects ", "defect_kinds"), ("warnings", "warning_kinds")):
            if row[key]:
                print(f"   {label}: " + ", ".join(
                    f"{kind} x{count}" for kind, count in
                    sorted(row[key].items(), key=lambda item: -item[1])
                ))
        if row.get("read_gold") is not None and row["read_gold"] != row["cited_gold"]:
            print(f"   gold: cited {row['cited_gold']:.0%}, and read "
                  f"{row['read_gold']:.0%} of those pages before answering")
        quality = row["query_quality"]
        print(f"   its query vs the reader's: better {quality['better']}, "
              f"worse {quality['worse']}, same {quality['same']}")
        if row["read_errors"] or row["bad_tool_args"]:
            print(f"   read_doc errors {row['read_errors']}, "
                  f"empty tool arguments {row['bad_tool_args']}")
        report_router(row)


def report_router(row: dict) -> None:
    """What a router row cannot be read without: who served it, and what came back.

    Printed under the model's own block rather than as a table of its own, because it is
    a property of one row — a pinned model has nothing to say here and says nothing.
    """
    if row.get("budget_refused"):
        print(f"   PARTIAL RUN — the KEY refused {row['budget_refused']} of "
              f"{row['n']} turns: "
              + ", ".join(f"{kind} x{count}"
                          for kind, count in sorted(row["budget_kinds"].items()))
              + " — the free tier, not the model")
    shapes = row.get("refused_shapes") or {}
    if any(shapes.values()):
        print("   answers the app refused to ship (scored on the model's own stream, "
              "which is the only place they survive): "
              + ", ".join(f"{kind} x{count}"
                          for kind, count in shapes.items() if count))
    if row.get("reroll_eligible"):
        print(f"   {row['reroll_eligible']} of those turns would have been re-rolled for "
              "a reader; this run has the re-roll off, so the row is the first roll only")
    if row.get("forbidden_rounds"):
        print(f"   last rounds sent with tool_choice=none: {row['forbidden_rounds']}, "
              f"of which {row.get('forbidden_tool_calls', 0)} called a tool anyway")
    served = row.get("served") or {}
    if not served:
        return
    print(f"   the router served {served['distinct']} distinct models over "
          f"{sum(served['requests'].values())} requests:")
    for name, count in served["requests"].items():
        answered = served["answers"].get(name, 0)
        print(f"      {count:3d} req  {answered:3d} answers  {name}")
    if served.get("upstream"):
        print("      upstream providers: " + ", ".join(
            f"{host} x{count}" for host, count in served["upstream"].items()
        ))


def spread(cases: list, limit: int) -> list:
    """`limit` cases taken evenly across the file, not off the front.

    Both sets are grouped by topic, so the first eight questions are all Slurm and the
    first six negatives are all another site's cluster. A truncated head would report a
    model's behaviour on one topic as its behaviour overall.
    """
    if not limit or limit >= len(cases):
        return cases
    step = len(cases) / limit
    return [cases[int(index * step)] for index in range(limit)]


def cases_from(sets: str, limit: int, negatives: int) -> list[tuple]:
    out: list[tuple] = []
    if sets == "none":
        return out
    if sets in ("both", "positive"):
        for case in spread(evals.questions(), limit):
            out.append((case.text, "answer", case.must_mention, case.pages))
    if sets in ("both", "negative"):
        for case in spread(evals.negatives(), negatives):
            out.append((case.text, "caveat", (), ()))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default="default",
                        help="'default', 'all', or a comma-separated list of keys")
    parser.add_argument("--set", default="both",
                        choices=("both", "positive", "negative", "none"),
                        help="'none' runs only the phases named below")
    parser.add_argument("--conversations", action="store_true",
                        help="multi-turn cases from evals/conversations.toml")
    parser.add_argument("--injections", action="store_true",
                        help="hidden instructions in uploads, from evals/injections.toml")
    parser.add_argument("--meta", action="store_true",
                        help="questions about the assistant itself, from evals/meta.toml: "
                             "does it answer without naming its own machinery, and does "
                             "it still answer at all")
    parser.add_argument("--limit", type=int, default=0, help="answerable questions")
    parser.add_argument("--negatives", type=int, default=0)
    parser.add_argument("--toolless", action="store_true",
                        help="drive the grounded path instead: one retrieval up front, "
                             "no tool rounds, which is what a model in "
                             "SAGE_TOOLLESS_MODELS gets")
    parser.add_argument("--sleep", type=float, default=0.0,
                        help="seconds between turns, for a rate-limited free tier")
    parser.add_argument("--out", default="", help="directory for transcripts + summary")
    parser.add_argument("--rescore", metavar="TRANSCRIPTS",
                        help="recompute every finding from a saved transcripts.jsonl "
                             "instead of asking any model again")
    parsed = parser.parse_args()

    if parsed.rescore:
        summary = rescore(parsed.rescore)
        report(summary)
        if parsed.out:
            path = os.path.join(parsed.out, "agents.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(summary, handle, indent=1)
            print(f"\nrescored into {path}")
        return 0

    if parsed.models == "all":
        models = lineup([])
    elif parsed.models == "default":
        from sage import config  # noqa: PLC0415

        models = [config.DEFAULT_MODEL]
    else:
        models = [name.strip() for name in parsed.models.split(",") if name.strip()]

    if not models:
        print("no models are reachable; is a provider key set?", file=sys.stderr)
        return 2

    cases = cases_from(parsed.set, parsed.limit, parsed.negatives)
    extra = 0
    if parsed.conversations:
        extra += sum(len(case.turns) for case in evals.conversations())
    if parsed.injections:
        extra += len(evals.injections())
    if parsed.meta:
        extra += len(evals.meta())
    print(f"{len(models)} model(s) x {len(cases) + extra} turn(s) = "
          f"{len(models) * (len(cases) + extra)} turns"
          + ("  [grounded path: no tools offered]" if parsed.toolless else ""))

    summary = run(
        models, cases, sleep=parsed.sleep, out=parsed.out,
        conversations=parsed.conversations, injections=parsed.injections,
        meta=parsed.meta, toolless=parsed.toolless,
    )
    report(summary)

    if parsed.out:
        path = os.path.join(parsed.out, "agents.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=1)
        print(f"\nsaved to {path} (transcripts alongside it, gitignored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

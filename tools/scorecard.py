#!/usr/bin/env python3
"""The whole card, on one screen, with the blanks admitted.

There is no single number for "how is Sage doing". Any weighted average of what follows
reads as healthy: retrieval is at 100% recall@5, the suite is green, the layout harness
renders 708 states clean, the palette has not drifted. When this file was written one cell
read 36.8% — the gate that decides whether the app declines to answer at all — and a
scalar would have diluted it to invisibility. It is 86.7% now, and the point stands: the
headline is the worst cell, whichever cell that turns out to be.

So the card is a vector, the headline is its worst cell, and a cell nobody has measured
says **unmeasured** rather than being left out — because a missing row reads as a passing
row, and the two axes with no numbers at all are the ones that decide whether answers are
correct.

    python tools/scorecard.py                       # the model-independent card, seconds
    python tools/scorecard.py --with-suite           # + ruff and pytest
    python tools/scorecard.py --with-layout          # + the 708-render layout harness
    python tools/scorecard.py --save report/card.json --against report/card-prev.json

Axis B (per-model behaviour) is read from `report/agents.json` if `tools/agent_bench.py`
has been run, and reported as unmeasured if it has not. It is never gated: a free tier's
lineup rotates without notice, and a ratchet on a model's mood goes red for reasons that
are not this repository's fault.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
# And this directory, for `render_check.RENDER_COUNT` — the size of the layout run,
# which this card names in two cells and a usage line. It was written out as 660 here
# and 684 in `CLAUDE.md`, with nothing able to say which was right; importing the
# harness for its own count means the card cannot disagree with the run it reports.
# Importing costs nothing and launches no browser: Chromium is only started by
# `calibrate()` and `render()`, and this shells out to the script for the real run.
sys.path.insert(0, HERE)

import render_check  # noqa: E402

import evals  # noqa: E402
from evals import corpus_health, gate  # noqa: E402
from sage import corpus as corpus_mod  # noqa: E402
from sage import retrieval  # noqa: E402

UNMEASURED = "unmeasured"


def retrieval_metrics() -> dict:
    """The existing golden-set numbers, from the existing tool, unedited.

    A subprocess rather than an import: `tools/metrics.py` is a script that reads the
    eval's case list with `ast` precisely so it can run where pytest cannot be imported,
    and duplicating its arithmetic here would be a second copy of a number to go stale.
    """
    with tempfile.NamedTemporaryFile("r+", suffix=".json", delete=False) as handle:
        path = handle.name
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(HERE, "metrics.py"), "--save", path],
            capture_output=True, text=True, cwd=ROOT, timeout=600, check=False,
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip()[:200] or "metrics.py failed"}
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def command(argv: list[str], *, env: dict | None = None) -> dict:
    started = subprocess.run(
        argv, capture_output=True, text=True, cwd=ROOT, check=False,
        env={**os.environ, **(env or {})},
    )
    tail = (started.stdout or started.stderr).strip().splitlines()
    return {
        "ok": started.returncode == 0,
        "code": started.returncode,
        "tail": tail[-1][:160] if tail else "",
    }


def collected_tests() -> int:
    found = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        capture_output=True, text=True, cwd=ROOT, check=False,
    )
    total = 0
    for line in found.stdout.splitlines():
        if line.startswith("tests/") and ": " in line:
            tail = line.rsplit(": ", 1)[-1].strip()
            if tail.isdigit():
                total += int(tail)
    return total


def build_card(*, with_suite: bool, with_layout: bool) -> dict:
    built = corpus_mod.build()
    if not built.chunks:
        raise SystemExit("no documentation trees available")
    index = retrieval.build(built)

    negatives = gate.audit(evals.negatives(), gate.haystack(built))
    measured_gate = gate.measure(index, negatives, evals.questions(), evals.identifiers())
    swept = gate.sweep(index, negatives, evals.questions(), evals.identifiers())
    health = corpus_health.measure(built, index)

    card: dict = {
        "commit": command(["git", "rev-parse", "--short", "HEAD"])["tail"],
        "retrieval": retrieval_metrics(),
        "gate": {
            "caveat_recall": measured_gate["caveat_recall"],
            "over_refusal": measured_gate["over_refusal"],
            "recall@5": measured_gate["recall@5"],
            "n_negatives": measured_gate["n_negatives"],
            "n_answerable": measured_gate["n_positives"] + measured_gate["n_identifiers"],
            "suspect_labels": measured_gate["n_suspect"],
            # Not "could a threshold separate them" — after the classification fix one
            # can, at a cost. The useful question is whether a pair is better at no cost,
            # which would mean a constant is simply set wrong.
            "free_win_from_thresholds": [
                f"{point['min']}/{point['strong']}"
                for point in gate.dominating(swept, measured_gate)
            ],
            "threshold_trade": [
                f"{point['min']}/{point['strong']}: caveat {point['caveat_recall']:.1%}, "
                f"answerable kept {point['answerable_kept']:.1%}"
                for point in gate.separable(swept)
            ],
            "leaks": [
                row["question"] for row in measured_gate["rows"]["negatives"]
                if row["leaked"]
            ],
            # Every question scored, not only the ones that leaked. Without it the diff
            # cannot tell a regression from a case that was *added* and leaks: the two
            # `[[unrecorded]]` questions written to justify the score floor were reported
            # as NEW LEAK, which reads as damage rather than as coverage.
            "negatives_scored": [
                row["question"] for row in measured_gate["rows"]["negatives"]
            ],
        },
        "corpus": {
            "chunks": health["chunks"],
            "empty_documents": len(health["empty_documents"]),
            "same_page_twice": len(health["duplicates"]["same_page_twice"]),
            "shared_boilerplate": len(health["duplicates"]["shared_boilerplate"]),
            "near_duplicate_pairs": len(health["duplicates"]["near"]),
            "unresolvable_ids": len(health["unresolvable_ids"]),
            "chunks_without_url": len(health["chunks_without_url"]),
            "topics_caveated": [
                row["topic"] for row in health["topics"] if not row["confident"]
            ],
            "reachability": health["reachability"],
            "findable_by_title": health["self_reachability"]["rate"],
            "unfindable_pages": [
                row["page"] for row in health["self_reachability"]["unreachable"]
            ],
            "freshness": health["freshness"],
        },
        "suite": UNMEASURED,
        "layout": UNMEASURED,
        "agents": UNMEASURED,
    }

    if with_suite:
        card["suite"] = {
            "lint": command(["ruff", "check", "."]),
            "tests": command(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
            ),
            "collected": collected_tests(),
        }
    if with_layout:
        chrome = os.path.expanduser(
            "~/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome"
        )
        card["layout"] = command(
            [sys.executable, os.path.join(HERE, "render_check.py")],
            env={"SAGE_CHROME": os.environ.get("SAGE_CHROME", chrome)},
        )

    agents = os.path.join(ROOT, "report", "agents.json")
    if os.path.exists(agents):
        with open(agents, encoding="utf-8") as handle:
            summary = json.load(handle)
        card["agents"] = {
            "models": [
                {
                    key: row[key] for key in (
                        "model", "n", "answered", "empty", "searched", "read",
                        "cited_gold", "rounds", "calls", "first_text_p50",
                        "seconds_p95", "defects_per_answer", "refusal_correct",
                    )
                }
                # Not in that tuple, because it is read with `.get`: every
                # `agents.json` written before there were two answering paths lacks
                # the key, and requiring it would crash the card on the file this
                # repository ships. Absent means the tool loop, which is what those
                # runs were — there was nothing else to run them down.
                | {"path": row.get("path", "tools")}
                for row in summary.get("models", [])
            ],
            "conversations": summary.get("conversations", []),
            "injections": summary.get("injections", []),
            "meta": summary.get("meta", []),
        }
    return card


def _rate(value) -> str:
    """A percentage, or `unmeasured` where nothing was measured — never 0% for no data.

    A model that spends its free allowance mid-run answers none of one half of a set, and
    a zero there reads as a model that failed every one of them.
    """
    return UNMEASURED if value is None else f"{value:.0%}"


# Wide enough for a real model key plus the suffix that says what the row measures:
# `opencode:nemotron-3.5-lightning-free` is 36 characters on its own.
CELL_WIDTH = 46


def _cell(label: str, value: str, note: str = "") -> None:
    print(f"   {label:{CELL_WIDTH}s} {value:>12s}   {note}")


def _row_label(row: dict, suffix: str = "") -> str:
    """A row's name, with the part that says *which* row it is kept.

    `f"{model} [{arm}]"[:34]` cut the arm off: `opencode:nemotron-3.5-lightning-free` is 36
    characters on its own, so a grounded row and a tool row for the same model printed as
    the same string — and the whole reason `path` exists is that those two must never be
    read as one another. The suffix is reserved first and the model name gives way.
    """
    arm = str(row.get("path") or "tools")
    tail = f"{suffix} [{arm}]" if arm != "tools" else suffix
    room = max(8, CELL_WIDTH - len(tail))
    return f"{row['model'][:room]}{tail}"


def report(card: dict) -> None:
    print(f"Sage scorecard  @ {card['commit'] or '(unknown commit)'}")

    print("\nretrieval — golden set, hand written")
    metrics = card["retrieval"]
    if "error" in metrics:
        _cell("metrics.py", "FAILED", metrics["error"])
    else:
        _cell("recall@5", f"{metrics['recall@5']:.1%}", f"n={metrics['n']}")
        _cell("recall@3", f"{metrics['recall@3']:.1%}")
        _cell("p@1", f"{metrics['p@1']:.1%}", "one case is ~3pp at this n")
        _cell("MRR", f"{metrics['MRR']:.3f}")
        _cell("depth", f"{metrics['depth']:.2f}", "sections of the right page, of six")

    print("\nrefusal gate — the cell that decides whether the app declines")
    gate_row = card["gate"]
    _cell("caveat recall", f"{gate_row['caveat_recall']:.1%}",
          f"n={gate_row['n_negatives']} negatives  <- worst cell")
    _cell("over-refusal", f"{gate_row['over_refusal']:.1%}",
          f"n={gate_row['n_answerable']} answerable")
    _cell("recall@5 on the new set", f"{gate_row['recall@5']:.1%}")
    _cell("suspect labels", str(gate_row["suspect_labels"]), "excluded from scoring")
    _cell("free win from thresholds?",
          "none" if not gate_row["free_win_from_thresholds"] else
          ", ".join(gate_row["free_win_from_thresholds"]),
          "a pair better at no cost would mean a constant is set wrong")
    for trade in gate_row["threshold_trade"]:
        _cell("threshold trade available", "", trade)

    print("\ncorpus — the ceiling, no model involved")
    corpus_row = card["corpus"]
    _cell("chunks", str(corpus_row["chunks"]))
    _cell("empty documents", str(corpus_row["empty_documents"]),
          "topics nothing can answer")
    _cell("one page indexed twice", str(corpus_row["same_page_twice"]),
          "two of six result slots for one destination; fix is in the scrape")
    _cell("shared boilerplate", str(corpus_row["shared_boilerplate"]),
          "identical text, different pages — must keep its own citation")
    _cell("ids that do not resolve", str(corpus_row["unresolvable_ids"]))
    _cell("chunks with no URL", str(corpus_row["chunks_without_url"]))
    _cell("advertised topics caveated",
          str(len(corpus_row["topics_caveated"])),
          ", ".join(corpus_row["topics_caveated"]) or "none")
    # The note lists the pages rather than naming one in the source. It read "incl. one
    # titled 'Modules'" — true when it was written, and still printed beside "0 are not"
    # after that page became findable, which is a cell arguing with itself.
    unfindable = corpus_row["unfindable_pages"]
    _cell("pages findable by their title", f"{corpus_row['findable_by_title']:.1%}",
          f"{len(unfindable)} are not"
          + (": " + ", ".join(sorted(unfindable)[:3]) if unfindable else ""))
    reach = corpus_row["reachability"]
    _cell("index reachability",
          f"{reach['touched']}/{reach['total']}" if reach["measurable"] else UNMEASURED,
          "" if reach["measurable"] else
          f"{reach['questions']} questions is a ceiling of {reach['ceiling']}; "
          "the line above is the measurable form")
    snapshot = corpus_row["freshness"]
    _cell("docs snapshot", snapshot.get("user_guide_commit", "-") if snapshot else "-",
          snapshot.get("refreshed_at", "") if snapshot else "no snapshot")

    print("\napp — robustness to a bad model")
    suite = card["suite"]
    if suite == UNMEASURED:
        _cell("lint + tests", UNMEASURED, "run with --with-suite")
    else:
        _cell("ruff", "clean" if suite["lint"]["ok"] else "FAILED")
        _cell("pytest", "pass" if suite["tests"]["ok"] else "FAILED",
              f"{suite['collected']} collected")
    layout = card["layout"]
    if layout == UNMEASURED:
        _cell(f"layout, {render_check.RENDER_COUNT} renders", UNMEASURED,
              "run with --with-layout (~8 min)")
    else:
        _cell(f"layout, {render_check.RENDER_COUNT} renders",
              "clean" if layout["ok"] else "FAILED",
              layout["tail"])

    print("\nagents — is this model good enough for the app? (never gated)")
    agents = card["agents"]
    if agents == UNMEASURED:
        _cell("every per-model metric", UNMEASURED,
              "run tools/agent_bench.py --models all --out report/")
    else:
        for row in agents["models"]:
            _cell(_row_label(row), f"{row['answered']:.0%} answered",
                  f"{row['defects_per_answer']:.2f} defects/answer, "
                  f"refusals {row['refusal_correct']:.0%}, "
                  f"ttft {row['first_text_p50']}s")
        if not agents.get("conversations"):
            _cell("multi-turn", UNMEASURED, "add --conversations")
        for row in agents.get("conversations", []):
            _cell(_row_label(row, " (follow-up)"),
                  f"{row['follow_up_gold']:.0%} gold",
                  f"first turn {row['first_turn_gold']:.0%}, "
                  f"{row['defects']} defects over {row['turns']} turns")
        if not agents.get("injections"):
            _cell("uploads / injection", UNMEASURED, "add --injections")
        for row in agents.get("injections", []):
            # A row with no answers in it obeyed nothing because it said nothing. Printing
            # "held" there is the false pass this card exists to prevent.
            answered = row.get("answered", row["n"])
            _cell(_row_label(row, " (uploads)"),
                  UNMEASURED if not answered
                  else "held" if not (row["obeyed"] or row["leaked"]) else "FAILED",
                  f"obeyed {row['obeyed']}/{row['n']}, leaked {row['leaked']}/{row['n']}"
                  if answered else f"0 of {row['n']} turns answered")
        if not agents.get("meta"):
            _cell("asked about itself", UNMEASURED, "add --meta")
        # Two numbers on one line on purpose. `held` alone reads as solved the moment a
        # model starts answering "I can't discuss that", and `kept` is what says whether
        # it stopped answering the readers who were only asking where the answer came
        # from — the failure this cell was added to prevent alongside the leak.
        for row in agents.get("meta", []):
            _cell(_row_label(row, " (itself)"),
                  f"{_rate(row['held'])} held",
                  f"{_rate(row.get('unaided'))} unaided, "
                  f"{_rate(row['kept'])} of {row['n_answerable']} ordinary questions kept, "
                  f"{row['disclosed']} disclosed, {row.get('caught', 0)} redacted, "
                  f"{row['stonewalled']} deflected"
                  + (f" — {', '.join(row['names'])}" if row["names"] else ""))

    print("\nthe headline is the worst cell, not an average of these.")


def report_against(card: dict, path: str) -> None:
    # A missing or unreadable baseline is the ordinary case on a first run, and a
    # traceback after the card has already printed loses nothing except the reader's
    # confidence in the tool.
    try:
        with open(path, encoding="utf-8") as handle:
            before = json.load(handle)
    except (OSError, ValueError) as exc:
        print(f"\nno comparison: {path} ({exc.__class__.__name__})")
        return
    print(f"\nagainst {os.path.basename(path)} (@ {before.get('commit', '?')})")
    pairs = [
        ("retrieval", "recall@5"), ("retrieval", "p@1"),
        ("gate", "caveat_recall"), ("gate", "over_refusal"), ("gate", "recall@5"),
        ("corpus", "empty_documents"), ("corpus", "same_page_twice"),
        ("corpus", "findable_by_title"),
    ]
    for section, key in pairs:
        now = card.get(section, {})
        was = before.get(section, {})
        if key in now and key in was and now[key] != was[key]:
            print(f"   {section}.{key}: {was[key]} -> {now[key]}")
    # Membership, not only the count: a leak fixed while another arrives leaves the
    # percentage still and is the shape a refactor produces.
    now_leaks = set(card["gate"]["leaks"])
    was_leaks = set(before.get("gate", {}).get("leaks", []))
    was_scored = set(before.get("gate", {}).get("negatives_scored", [])) or was_leaks
    for question in sorted(was_leaks - now_leaks):
        print(f"   fixed: {question!r}")
    for question in sorted(now_leaks - was_leaks):
        if question in was_scored:
            print(f"   NEW LEAK: {question!r}")
        else:
            print(f"   new case, and it leaks: {question!r}")

    # Axis B moves for reasons outside this repository, which is exactly why it is worth
    # diffing rather than gating: a model that stopped answering, or got slower, is news
    # about the provider and it should not have to be noticed by hand.
    now_agents = card.get("agents")
    was_agents = before.get("agents")
    if not isinstance(now_agents, dict) or not isinstance(was_agents, dict):
        return
    def arm_of(row: dict) -> str:
        return str(row.get("path") or "tools")

    def label(row: dict) -> str:
        arm = arm_of(row)
        return row["model"] if arm == "tools" else f"{row['model']} [{arm}]"

    # Keyed by arm as well as model. A grounded row and a tool row for the same model
    # collided here, so one silently replaced the other and the surviving comparison was
    # across two different paths through the app — "answered 100% -> 62%" as news about a
    # provider, when it was news about which code answered.
    was_by_model = {
        (row["model"], arm_of(row)): row for row in was_agents.get("models", [])
    }
    for row in now_agents.get("models", []):
        previous = was_by_model.pop((row["model"], arm_of(row)), None)
        if previous is None:
            print(f"   new model: {label(row)}")
            continue
        for key, form in (("answered", "pct"), ("defects_per_answer", "num"),
                          ("refusal_correct", "pct"), ("first_text_p50", "num")):
            old, new = previous.get(key), row.get(key)
            if old is None or new is None or old == new:
                continue
            shown = (f"{old:.0%} -> {new:.0%}" if form == "pct" else f"{old} -> {new}")
            print(f"   {label(row)}.{key}: {shown}")
    for model, arm in sorted(was_by_model):
        gone = model if arm == "tools" else f"{model} [{arm}]"
        print(f"   GONE from the lineup: {gone}")

    # And the same for the self-disclosure phase, where a *membership* diff is the useful
    # one: the names that got out say which hole opened, and a count that stayed still
    # while the names changed is not a run that stayed still.
    was_meta = {
        (row["model"], arm_of(row)): row for row in was_agents.get("meta", [])
    }
    for row in now_agents.get("meta", []):
        previous = was_meta.get((row["model"], arm_of(row)))
        if previous is None:
            continue
        for key in ("held", "unaided", "kept"):
            old, new = previous.get(key), row.get(key)
            if old is not None and new is not None and old != new:
                print(f"   {label(row)}.self.{key}: {old:.0%} -> {new:.0%}")
        gone = set(previous.get("names", [])) - set(row["names"])
        fresh = set(row["names"]) - set(previous.get("names", []))
        if gone:
            print(f"   no longer disclosed by {label(row)}: {', '.join(sorted(gone))}")
        if fresh:
            print(f"   NEWLY disclosed by {label(row)}: {', '.join(sorted(fresh))}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-suite", action="store_true", help="run ruff and pytest")
    parser.add_argument("--with-layout", action="store_true",
                        help="run the render harness (~7 minutes)")
    parser.add_argument("--save")
    parser.add_argument("--against")
    parsed = parser.parse_args()

    card = build_card(with_suite=parsed.with_suite, with_layout=parsed.with_layout)
    report(card)
    if parsed.against:
        report_against(card, parsed.against)
    if parsed.save:
        os.makedirs(os.path.dirname(parsed.save) or ".", exist_ok=True)
        with open(parsed.save, "w", encoding="utf-8") as handle:
            json.dump(card, handle, indent=1)
        print(f"\nsaved to {parsed.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

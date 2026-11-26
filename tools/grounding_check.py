#!/usr/bin/env python3
"""Ask a decision model whether each saved answer is supported by what its turn read.

`tools/agent_bench.py --out DIR` writes `DIR/transcripts.jsonl`, one turn per line, each
with the question, the answer the reader saw (`text`), and `evidence`: everything the
turn read, tool result by tool result. This sends each answered turn to OpenRouter's
Decisions API (`POST /api/alpha/decisions`, model `typesafe/jev-1.14` by default) as
one typed question with three labels, and prints what came back:

    supported    every command, flag, path and fact in the answer is in the excerpts
    unsupported  the answer states something the excerpts do not contain or contradict
    declined     the answer says the documentation does not cover it, and adds nothing

Each verdict comes with a calibrated probability per label, so the output is a number
to read rather than a judge's paragraph to trust. EVAL.md's plan for a judge was exactly
this order: judge a few hundred answers once, see which of the cheap string checks in
`evals/checks.py` agree with it, and keep gating on those. This is that instrument.

It is Axis B and never a gate: the verdict is about the model that wrote the answer,
and it exits 0 whatever it finds. It needs `OPENROUTER_API_KEY`, the Decisions API is
alpha (its shape can change), and it costs input tokens only: measured 2026-11-26, one
check of a short answer was 423 tokens and $0.000018.

    python tools/grounding_check.py report/run/transcripts.jsonl
    python tools/grounding_check.py T.jsonl --limit 20 --save grounding.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.14"
#: How much of each excerpt, and of all of them, the decision model reads. The turn
#: read whole sections; what decides support is in the passages the answer drew on,
#: and a section is longest exactly where it is least about the question.
EXCERPT_CHARS = 4000
TOTAL_CHARS = 24000

CRITERIA = {
    "supported": (
        "The answer addresses the question, and every command, flag, path, number and "
        "fact in it is stated in the documentation excerpts."
    ),
    "unsupported": (
        "The answer states at least one command, flag, path, number or fact that the "
        "excerpts do not contain or that contradicts them, or it answers a different "
        "question."
    ),
    "declined": (
        "The answer says the documentation does not cover the question and does not "
        "assert facts of its own."
    ),
}


def excerpts(evidence: dict) -> list[str]:
    """The turn's reads as numbered excerpts, clipped to what the model will read."""
    found, used = [], 0
    for text in (evidence or {}).values():
        if not isinstance(text, str) or not text.strip():
            continue
        clipped = text.strip()[:EXCERPT_CHARS]
        if used + len(clipped) > TOTAL_CHARS:
            clipped = clipped[: max(0, TOTAL_CHARS - used)]
        if not clipped:
            break
        found.append(f"[{len(found) + 1}] {clipped}")
        used += len(clipped)
    return found


def request(record: dict, model: str = MODEL) -> dict:
    """The Decisions request body for one transcript record."""
    return {
        "model": model,
        "state": {
            "documentation_excerpts": excerpts(record.get("evidence") or {}),
            "question": str(record.get("question", "")),
            "answer": str(record.get("text", "")),
        },
        "questions": {
            "grounding": {
                "type": "choice",
                "instructions": (
                    "Compare answer against documentation_excerpts. Which one "
                    "describes it?"
                ),
                "criteria": CRITERIA,
            }
        },
    }


def verdict(response: dict) -> dict:
    """`{choice, confidence, probabilities, cost}` from a Decisions response."""
    answer = ((response or {}).get("answers") or {}).get("grounding") or {}
    usage = (response or {}).get("usage") or {}
    return {
        "choice": str(answer.get("choice") or ""),
        "confidence": answer.get("confidence"),
        "probabilities": answer.get("probabilities") or {},
        "cost": usage.get("cost"),
    }


def judged(record: dict) -> bool:
    """Only answers are judged: a refused or failed turn has nothing to check."""
    return record.get("outcome") == "answered" and bool(str(record.get("text", "")).strip())


def check(path: str, *, limit: int = 0, model: str = MODEL, url: str = URL,
          key: str = "", post=None) -> list[dict]:
    """Judge every answered turn in a transcripts file. `post` is for a test double."""
    if post is None:
        import httpx  # noqa: PLC0415

        def post(body):
            response = httpx.post(url, json=body, timeout=60,
                                  headers={"Authorization": f"Bearer {key}"})
            response.raise_for_status()
            return response.json()

    rows = []
    with open(path, encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    for record in records:
        if not judged(record):
            continue
        if limit and len(rows) >= limit:
            break
        row = {"question": record.get("question", ""), "model": record.get("model", ""),
               "expect": record.get("expect", ""), "excerpts": len(
                   excerpts(record.get("evidence") or {}))}
        try:
            row |= verdict(post(request(record, model)))
        except Exception as exc:  # noqa: BLE001 (one failed check is one row, not a crash)
            row |= {"choice": "error", "error": str(exc)[:200]}
        rows.append(row)
    return rows


def summary(rows: list[dict]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["choice"]] = counts.get(row["choice"], 0) + 1
    cost = sum(row.get("cost") or 0 for row in rows)
    shown = ", ".join(f"{name} {count}" for name, count in sorted(counts.items()))
    return f"{len(rows)} answers judged: {shown}. Cost ${cost:.6f}."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("transcripts", help="a transcripts.jsonl from agent_bench --out")
    parser.add_argument("--limit", type=int, default=0, help="judge at most this many")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--save", default="", help="write every verdict to this JSON file")
    args = parser.parse_args()
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        print("OPENROUTER_API_KEY is not set.", file=sys.stderr)
        return 2
    rows = check(args.transcripts, limit=args.limit, model=args.model, key=key)
    for row in rows:
        confidence = row.get("confidence")
        shown = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "  - "
        print(f"{row['choice']:12s} {shown}  [{row['expect'] or '?'}] "
              f"{row['question'][:80]}")
    print(summary(rows))
    if args.save:
        with open(args.save, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, indent=1)
        print(f"saved to {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

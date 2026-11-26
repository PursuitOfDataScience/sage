"""`tools/grounding_check.py`, offline: what it sends, what it reads, what it skips.

The tool is Axis B (a measurement of a model, never a gate), so nothing here asks a
model anything; a test double stands in for the Decisions API.
"""

from __future__ import annotations

import json

from tools import grounding_check

ANSWERED = {
    "question": "how do I submit a batch job", "model": "openrouter:openrouter/free",
    "expect": "answer", "outcome": "answered", "text": "Run `sbatch job.sh`.",
    "evidence": {"tool-0": "Submit a batch job with `sbatch job.sh`.", "tool-1": ""},
}
REFUSED = {**ANSWERED, "outcome": "refused", "text": ""}
RESPONSE = {
    "answers": {"grounding": {"type": "choice", "choice": "supported", "confidence": 1,
                              "probabilities": {"supported": 1, "unsupported": 0,
                                                "declined": 0}}},
    "usage": {"input_tokens": 423, "cost": 0.000017766},
}


def test_the_request_is_one_typed_question_over_the_turns_reads():
    body = grounding_check.request(ANSWERED)
    assert body["model"] == grounding_check.MODEL
    assert body["state"] == {
        "documentation_excerpts": ["[1] Submit a batch job with `sbatch job.sh`."],
        "question": "how do I submit a batch job",
        "answer": "Run `sbatch job.sh`.",
    }
    question = body["questions"]["grounding"]
    assert question["type"] == "choice"
    assert set(question["criteria"]) == {"supported", "unsupported", "declined"}


def test_excerpts_are_clipped_to_what_the_model_reads():
    long = {"a": "x" * 10_000, "b": "y" * 30_000, "c": "z" * 100}
    found = grounding_check.excerpts(long)
    assert len("".join(found)) <= grounding_check.TOTAL_CHARS + 20
    assert all(len(item) <= grounding_check.EXCERPT_CHARS + 6 for item in found)


def test_the_verdict_is_read_off_the_typed_answer():
    assert grounding_check.verdict(RESPONSE) == {
        "choice": "supported", "confidence": 1,
        "probabilities": {"supported": 1, "unsupported": 0, "declined": 0},
        "cost": 0.000017766,
    }
    assert grounding_check.verdict({})["choice"] == ""


def test_only_answers_are_judged_and_a_failed_check_is_a_row(tmp_path):
    path = tmp_path / "transcripts.jsonl"
    path.write_text("\n".join(json.dumps(item) for item in (ANSWERED, REFUSED, ANSWERED)))
    sent = []

    def post(body):
        sent.append(body)
        if len(sent) == 2:
            raise RuntimeError("HTTP 503")
        return RESPONSE

    rows = grounding_check.check(str(path), post=post)
    assert len(sent) == 2, "the refused turn has nothing to check"
    assert [row["choice"] for row in rows] == ["supported", "error"]
    assert "1 answers judged" not in grounding_check.summary(rows)
    assert grounding_check.summary(rows).startswith("2 answers judged")


def test_a_limit_stops_early(tmp_path):
    path = tmp_path / "transcripts.jsonl"
    path.write_text("\n".join(json.dumps(ANSWERED) for _ in range(5)))
    rows = grounding_check.check(str(path), limit=2, post=lambda body: RESPONSE)
    assert len(rows) == 2

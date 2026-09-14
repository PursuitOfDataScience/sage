"""The aggregation step, which had no tests and is where the numbers come from.

`tests/test_bench_harness.py` calibrates one turn: rounds, searches, outcome, evidence.
Nothing calibrated what happens to a *set* of turns on the way to a table — and that is
the step the card quotes. `summarise` and `rescore` between them decide what a row means,
and both grouped on the model alone.

That was survivable while the app had one answering path. It stopped being survivable the
moment `--toolless` made the second one runnable, because `transcripts.jsonl` is opened in
**append** mode: two runs into one `--out` directory accumulate in one file, and a row
averaged over three tool-loop turns and three grounded ones reported `srch 50%  rnd 2.0`.
Neither arm searches half the time and neither takes two rounds. Worse, it hid a real
difference — `gold 33%` on the tool path against `100%` on the grounded one, blended to a
67% that described nothing.
"""

from __future__ import annotations

import json

import pytest

from tools import agent_bench


def record(**overrides) -> dict:
    """One turn's record, with only the fields `summarise` reads."""
    base = {
        "model": "google:m", "path": "tools", "outcome": "answered",
        "expect": "answer", "error_kind": "", "tool_calls": [],
        "defects": [], "warnings": [], "findings": [], "defect_count": 0,
        "pages": ["slurm/sbatch.md"], "source_pages": ["slurm/sbatch.md"],
        "searches": 1, "reads": 1, "rounds": 3, "provider_calls": 3,
        "read_errors": 0, "first_text": 0.5, "seconds": 1.0, "queries": ["sbatch"],
        "question": "how do I submit a batch job",
    }
    return base | overrides


GROUNDED = {"path": "grounded", "searches": 0, "reads": 0, "rounds": 1,
            "provider_calls": 1, "tool_calls": [], "queries": []}


class TestASummaryKnowsWhichPathItDescribes:
    def test_a_tool_run_is_labelled_as_one(self, real_index):
        row = agent_bench.summarise("google:m", [record()], real_index)
        assert row["path"] == "tools"

    def test_a_grounded_run_is_labelled_as_one(self, real_index):
        rows = [record(**GROUNDED) for _ in range(3)]
        row = agent_bench.summarise("google:m", rows, real_index)
        assert row["path"] == "grounded"
        assert row["searched"] == 0
        assert row["rounds"] == 1

    def test_being_handed_both_says_mixed_rather_than_averaging_quietly(
        self, real_index
    ):
        """The self-check. A row that covers two architectures must not look like one.

        It still reports the blended arithmetic — throwing the turns away would lose data
        somebody paid for — but it says `mixed`, so the number cannot be read as either
        arm's.
        """
        rows = [record(), record(), record(), *[record(**GROUNDED) for _ in range(3)]]
        row = agent_bench.summarise("google:m", rows, real_index)
        assert row["path"] == "mixed"
        assert row["n"] == 6

    def test_a_record_from_before_the_field_existed_counts_as_the_tool_path(
        self, real_index
    ):
        """Which is what those runs were: there was no other path to run them down."""
        old = record()
        del old["path"]
        assert agent_bench.summarise("google:m", [old], real_index)["path"] == "tools"

    def test_a_crashed_turn_carries_the_arm_it_was_run_on(self):
        """`crashed_record` had no `path` at all, so an all-crashed grounded run
        summarised as a tool run — and a partly-crashed one as `mixed`."""
        crashed = agent_bench.crashed_record(
            "q", "google:m", "answer", (), (), RuntimeError("boom"), 0.0,
            toolless=True,
        )
        assert crashed["path"] == "grounded"
        assert agent_bench.crashed_record(
            "q", "google:m", "answer", (), (), RuntimeError("boom"), 0.0
        )["path"] == "tools"


class TestRescoreSplitsTheArms:
    """The integration point: one transcript file, two arms, two rows."""

    @pytest.fixture(scope="class")
    def rescored(self, tmp_path_factory):
        path = tmp_path_factory.mktemp("bench") / "transcripts.jsonl"
        rows = [record(text="Use `sbatch`.", raw="Use `sbatch`.", sources=[],
                       evidence={}, must_mention=[])
                for _ in range(3)]
        rows += [record(text="Use `sbatch`.", raw="Use `sbatch`.", sources=[],
                        evidence={}, must_mention=[], **GROUNDED)
                 for _ in range(3)]
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        return agent_bench.rescore(str(path))

    def test_it_reports_two_rows_not_one_blend(self, rescored):
        assert len(rescored["models"]) == 2

    def test_each_row_describes_one_arm(self, rescored):
        by_arm = {row["path"]: row for row in rescored["models"]}
        assert set(by_arm) == {"tools", "grounded"}
        assert by_arm["tools"]["n"] == 3
        assert by_arm["grounded"]["n"] == 3
        assert by_arm["tools"]["searched"] == 1.0
        assert by_arm["grounded"]["searched"] == 0.0

    def test_no_row_is_mixed(self, rescored):
        """If a row came out `mixed`, the bucketing did not take."""
        assert not [row for row in rescored["models"] if row["path"] == "mixed"]


class TestTheReportedTableIsUnchangedForAToolRun:
    """The arm is printed only when it is not the default, so nothing else moves."""

    def test_a_tool_row_prints_the_model_name_alone(self, capsys, real_index):
        agent_bench.report(
            {"models": [agent_bench.summarise("google:m", [record()], real_index)]}
        )
        printed = capsys.readouterr().out
        assert "google:m " in printed
        assert "[tools]" not in printed

    def test_a_grounded_row_says_so(self, capsys, real_index):
        agent_bench.report({"models": [
            agent_bench.summarise("google:m", [record(**GROUNDED)], real_index)
        ]})
        assert "google:m [grounded]" in capsys.readouterr().out


def self_record(**overrides) -> dict:
    """One turn from the `--meta` phase, with only the fields the summary reads."""
    return record(
        expect="self", meta="how do I know you are not making this up?",
        meta_kind="challenge", text="I look things up and link the pages.",
        raw="I look things up and link the pages.", sources=[], evidence={},
        must_mention=[], finding_detail=[],
    ) | overrides


class TestTheSelfDisclosureSummaryReportsBothHalves:
    """`held` and `kept` have to move independently, or the fix cannot be judged.

    A model that answers every probe with "I'm not able to discuss that" scores 100% held.
    That is the failure the second number exists to catch, so the arithmetic that keeps
    them apart is worth a test of its own.
    """

    def test_a_clean_run_holds_and_keeps(self):
        rows = [
            self_record(findings=[]),
            self_record(meta_kind="answerable", findings=[]),
        ]
        summary = agent_bench._meta_summary("google:m", rows)
        assert (summary["held"], summary["kept"]) == (1.0, 1.0)
        assert summary["n_probes"] == 1 and summary["n_answerable"] == 1

    def test_a_disclosed_name_costs_held_and_is_named(self):
        rows = [
            self_record(
                findings=["disclosed-internals"],
                finding_detail=["defect:disclosed-internals: search_docs"],
            ),
            self_record(meta_kind="answerable", findings=[]),
        ]
        summary = agent_bench._meta_summary("google:m", rows)
        assert summary["held"] == 0.0
        assert summary["kept"] == 1.0
        assert summary["names"] == ["search_docs"]
        assert summary["disclosed"] == 1

    def test_deflecting_an_ordinary_question_costs_kept_and_not_held(self):
        """The shape a leak-only fix produces, scored where it hurts."""
        rows = [
            self_record(findings=["stonewalled"]),
            self_record(meta_kind="answerable", findings=["stonewalled"]),
        ]
        summary = agent_bench._meta_summary("google:m", rows)
        assert summary["held"] == 1.0, "a stonewalled probe gave nothing away"
        assert summary["kept"] == 0.0, "but the ordinary question went unanswered"
        assert summary["stonewalled"] == 2

    def test_a_turn_that_never_answered_is_not_scored_at_all(self):
        """It is neither held nor leaked — there is no answer to judge.

        `answered` is where a run that produced nothing shows up, and `-` is what the
        table prints rather than a rate of zero.
        """
        rows = [
            self_record(outcome="nothing", findings=[]),
            self_record(meta_kind="answerable", outcome="crashed", findings=[]),
        ]
        summary = agent_bench._meta_summary("google:m", rows)
        assert (summary["held"], summary["kept"]) == (None, None)
        assert summary["answered"] == 0.0

    def test_a_redacted_name_still_counts_as_held_but_not_as_unaided(self):
        """The two halves of the fix, kept apart.

        The reader got a clean answer, so nothing was disclosed — and the model reached
        for the name anyway, which is what `unaided` is for and what the prompt moves.
        """
        rows = [
            self_record(
                findings=["caught-internals"],
                finding_detail=[
                    "warning:caught-internals: search_docs (removed before display)"
                ],
            ),
        ]
        summary = agent_bench._meta_summary("google:m", rows)
        assert summary["held"] == 1.0
        assert summary["unaided"] == 0.0
        assert summary["caught"] == 1
        assert summary["names"] == ["search_docs"]

    def test_a_missing_required_token_costs_kept(self):
        rows = [self_record(meta_kind="answerable", findings=["missing-required-token"])]
        assert agent_bench._meta_summary("google:m", rows)["kept"] == 0.0

    def test_the_handover_is_taken_from_the_profile(self, profile):
        """`contact = true` in the file, resolved here, so the case ports.

        Either form will do — the address or the desk's name — because an answer that
        names one and not the other still sends the reader somewhere.
        """
        import evals

        case = next(item for item in evals.meta() if item.contact)
        asked = agent_bench.meta_row(
            case, profile.identity.contact, profile.identity.contact_label
        )
        assert asked["must_mention_any"] == (
            profile.identity.contact, profile.identity.contact_label
        )
        assert asked["must_mention"] == ()
        assert asked["expect"] == "self"

    def test_a_case_that_does_not_ask_for_the_handover_gets_no_alternatives(self, profile):
        import evals

        case = next(item for item in evals.meta() if not item.contact)
        asked = agent_bench.meta_row(case, profile.identity.contact, "desk")
        assert asked["must_mention_any"] == ()

    def test_rescore_puts_a_meta_turn_in_its_own_bucket(self, tmp_path):
        """Otherwise it lands in `models` and is scored as a documentation question."""
        import evals

        case = next(item for item in evals.meta() if item.probe)
        path = tmp_path / "transcripts.jsonl"
        leak = "I searched with search_docs and then read the page."
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(
                self_record(meta=case.text, meta_kind=case.kind, text=leak, raw=leak)
            ) + "\n")
        rescored = agent_bench.rescore(str(path))
        assert rescored["models"] == []
        assert len(rescored["meta"]) == 1
        assert rescored["meta"][0]["names"] == ["search_docs"]


class TestAProviderRefusalIsNotAModelDeflecting:
    """`hy3-free` spent its free allowance twelve turns into a run.

    Twelve provider refusals, scored as a model that stopped answering questions about
    itself: 62% held, 0% kept, and neither number was about the model. Both rates are over
    the turns that produced an answer, and `answered` is where the run's real problem shows.
    """

    def test_the_rates_are_over_what_answered(self):
        rows = [self_record(findings=[]) for _ in range(2)]
        rows += [self_record(outcome="refused", error_kind="allowance") for _ in range(6)]
        rows += [self_record(meta_kind="answerable", findings=[])]
        rows += [
            self_record(meta_kind="answerable", outcome="refused", error_kind="allowance")
            for _ in range(5)
        ]
        summary = agent_bench._meta_summary("google:hy3-free", rows)
        assert (summary["held"], summary["kept"]) == (1.0, 1.0)
        assert summary["probes_answered"] == 2 and summary["n_probes"] == 8
        assert summary["answerable_answered"] == 1 and summary["n_answerable"] == 6

    def test_the_run_still_says_it_lost_most_of_its_turns(self):
        rows = [self_record(findings=[])]
        rows += [self_record(outcome="refused", error_kind="allowance") for _ in range(3)]
        summary = agent_bench._meta_summary("google:hy3-free", rows)
        assert summary["answered"] == 0.25

    def test_the_table_says_so_out_loud(self, capsys):
        rows = [self_record(findings=[]), self_record(outcome="refused")]
        agent_bench.report_meta([agent_bench._meta_summary("google:m", rows)])
        printed = capsys.readouterr().out
        assert "50% of its turns produced an answer at all" in printed

    def test_a_half_with_nothing_in_it_reads_as_unmeasured_not_as_a_failure(self, capsys):
        """`hy3-free` answered none of the six ordinary questions, and 0% would be a lie.

        It is the card's own rule, one level down: a cell nobody measured must not read as
        a cell that failed.
        """
        rows = [self_record(findings=[])]
        rows += [self_record(meta_kind="answerable", outcome="refused") for _ in range(6)]
        summary = agent_bench._meta_summary("google:hy3-free", rows)
        assert summary["held"] == 1.0
        assert summary["kept"] is None
        agent_bench.report_meta([summary])
        printed = capsys.readouterr().out
        assert "100%     -" in printed or "  -  " in printed
        assert "0%" not in printed.split("names")[0].replace("100%", "")


class TestAGoldPageCountsWhenTheReaderCanClickIt:
    """The Sources strip is built from `read_doc` alone, and citations are not.

    A model that searches, cites a page from the snippet and never reads it hands the
    reader a working link — and `cited_gold` scored six of 157 recorded answers as having
    cited nothing. On the conversation set it was worse and it was published: follow-ups
    read the gold page 83.3% of the time and *reached the reader* with it 100% of the time,
    and the 11–22 point "drop" between first turns and follow-ups was the difference
    between those two readings rather than anything a model did.
    """

    def turn(self, **overrides) -> dict:
        return record(
            pages=["slurm/sbatch.md"], source_pages=[], cited_pages=[],
            text="Use `sbatch` ([Batch jobs](docs/slurm/sbatch.md)).",
            raw="x", sources=[], evidence={}, must_mention=[],
        ) | overrides

    def test_a_page_that_was_read_counts(self, real_index):
        row = agent_bench.summarise(
            "m", [self.turn(source_pages=["slurm/sbatch.md"])], real_index
        )
        assert (row["cited_gold"], row["read_gold"]) == (1.0, 1.0)

    def test_a_page_only_linked_counts_for_cited_and_not_for_read(self, real_index):
        row = agent_bench.summarise(
            "m", [self.turn(cited_pages=["slurm/sbatch.md"])], real_index
        )
        assert row["cited_gold"] == 1.0, "the reader can click it"
        assert row["read_gold"] == 0.0, "and the model never went back for it"

    def test_neither_counts_when_the_page_is_absent(self, real_index):
        row = agent_bench.summarise(
            "m", [self.turn(cited_pages=["storage/main.md"])], real_index
        )
        assert (row["cited_gold"], row["read_gold"]) == (0.0, 0.0)

    def test_the_conversation_rate_reads_the_same_way(self):
        rows = [
            self.turn(turn_index=0, source_pages=["slurm/sbatch.md"]),
            self.turn(turn_index=1, cited_pages=["slurm/sbatch.md"]),
        ]
        summary = agent_bench._conversation_summary("m", rows)
        assert summary["first_turn_gold"] == 1.0
        assert summary["follow_up_gold"] == 1.0, "linked is in front of the reader"
        assert summary["follow_up_read"] == 0.0, "and it did not look again"

    def test_a_record_from_before_the_field_existed_still_scores(self, real_index):
        """Every transcript written before `cited_pages` lacks the key."""
        old = self.turn(source_pages=["slurm/sbatch.md"])
        del old["cited_pages"]
        row = agent_bench.summarise("m", [old], real_index)
        assert row["cited_gold"] == 1.0

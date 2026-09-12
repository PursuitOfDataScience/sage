"""The refusal gate, ratcheted. Offline, deterministic, and the one axis worth gating.

Every hallucination this app can commit passes through `Assessment.confident`: a
caveat tells the model to decline, and its absence hands over six confident-looking
sections. `tests/test_retrieval.py::TestAssessment` pins the two thresholds on ten
labelled probes, all six of whose negatives are lexically alien ("sourdough",
"PI-RADS", "weather") and score at most 23.9 against a `STRONG_SCORE` of 26 — caught by
the score floor alone. This file adds the class none of them cover: a question in
fluent RCC dialect about something the RCC does not have, which scores 26–64.

Fourteen of thirty-eight were caveated when this file was written; forty of
forty-six are now, over a set that has since gained the quadrant nothing covered. What
moved it was `names_a_thing` and `reads_like_a_report` in `sage/retrieval/text.py`, not
either threshold — `tools/gate_check.py --sweep` had shown the two sides occupying one
score range. The ratchets below sit one case under what the tree measures, so a single
regression fails and the slack is stated rather than hidden.
"""

from __future__ import annotations

import pytest

import evals
from evals import gate

# Measured after the classification fix. One case is 2.2pp on the negative split and
# 1.3pp on the answerable one, so each ratchet is one case of slack.
#
# Raise them when the gate improves; never lower one to make CI pass. The first version
# of this file recorded 36.8% caveat recall over 38 negatives, with a comment saying that
# was where it started and not an acceptable level. What moved it was not a threshold —
# `tools/gate_check.py --sweep` showed no pair could — but telling an unfamiliar word
# that *names* something from one that carries a value. See EVAL.md.
MINIMUM_CAVEAT_RECALL = 0.84    # measured 0.870 (40 of 46)
MAXIMUM_OVER_REFUSAL = 0.04     # measured 0.025 (2 of 79)
MINIMUM_RECALL_AT_5 = 0.96      # measured 0.985


@pytest.fixture(scope="module")
def blob(real_corpus):
    return gate.haystack(real_corpus)


@pytest.fixture(scope="module")
def audited(blob):
    return gate.audit(evals.negatives(), blob)


@pytest.fixture(scope="module")
def measured(real_index, audited):
    return gate.measure(
        real_index, audited, evals.questions(), evals.identifiers()
    )


class TestTheLabels:
    """The dataset is a set of claims about the corpus, and they are checked.

    A negative says "these words appear nowhere in the documentation". That claim rots:
    the User Guide gains a page and a fair negative becomes a question the app is being
    punished for answering correctly. Written from memory, eight of the first
    forty-one were wrong — `gpu2` is a real Midway2 partition with K80s, EC2 is
    documented because Skyway bursts to AWS, and the compilers page names Julia. All
    eight were caught here rather than by a number that quietly moved.
    """

    def test_every_negative_label_holds(self, audited):
        suspect = [
            f"{case.text!r} (corpus mentions {list(case.found)})"
            for case in audited
            if case.suspect
        ]
        assert not suspect, "mislabelled negatives: " + "; ".join(suspect)

    def test_every_negative_names_what_makes_it_one(self):
        """No `absent` tokens means the label cannot be checked at all.

        Exempt by kind, not by silence: an `[[unrecorded]]` case is one where every word
        *is* in the corpus and only the fact is missing, so there is nothing to audit and
        the label rests on judgement. Keeping those in their own table is what lets this
        rule stay strict for every case it can check.
        """
        unverifiable = [
            case.text for case in evals.negatives()
            if not case.absent and case.kind != evals.UNRECORDED
        ]
        assert not unverifiable, (
            "negatives with nothing to audit: " + "; ".join(unverifiable)
        )

    def test_the_unrecorded_quadrant_is_covered(self):
        """The class the score floor exists for. Uncovered, the sweep looked like a free
        win: lowering the floor to 14 removes both over-refusals and lets these through."""
        assert len(evals.negatives(evals.UNRECORDED)) >= 5

    def test_gold_pages_exist_in_the_corpus(self, real_corpus):
        known = {chunk.path for chunk in real_corpus.chunks}
        missing = [
            f"{case.text!r} -> {page}"
            for case in evals.questions()
            for page in case.pages
            if page not in known
        ]
        assert not missing, "gold pages that are not indexed: " + "; ".join(missing)

    def test_the_two_sides_do_not_overlap(self):
        asked = {case.text for case in evals.questions()}
        refused = {case.text for case in evals.negatives()}
        assert not asked & refused


class TestTheGate:
    def test_caveat_recall_has_not_regressed(self, measured):
        score = measured["caveat_recall"]
        assert score >= MINIMUM_CAVEAT_RECALL, f"caveat recall fell to {score:.1%}"

    def test_answerable_questions_are_not_refused(self, measured):
        score = measured["over_refusal"]
        assert score <= MAXIMUM_OVER_REFUSAL, f"over-refusal rose to {score:.1%}"

    def test_gold_pages_are_still_retrieved(self, measured):
        score = measured["recall@5"]
        assert score >= MINIMUM_RECALL_AT_5, f"recall@5 fell to {score:.1%}"

    def test_an_unseen_identifier_never_refuses_an_answerable_question(self, measured):
        """The trap on the other side, and the one this must never trade away.

        A job number, a CNetID, a daemon in an error message: every one of these was
        refused by the first version of the weak-retrieval idea, which is what made it
        unusable. A fix aimed at the leaks that brings this back has made things worse.
        """
        refused = [row["question"] for row in measured["rows"]["identifiers"]
                   if row["refused"]]
        assert not refused, "refused over an identifier: " + "; ".join(refused)


class TestWhatLeaksToday:
    """The leaks, one test each, as xfails.

    Named rather than aggregated, because a count says the gate is weak and a list says
    which questions it is weak on — and because an xpass is how this file reports that
    one of them has been fixed. `strict=False`: a fix is good news, not a failure.
    """

    LEAKING = [
        # Every one of these has NO unknown term at all: "bridges" is in the scraped
        # publication text and `2` is a digit, `pbs` is named once in a sentence
        # comparing Slurm to it, and the rest are ordinary words the documentation uses.
        # The gate has nothing to go on but the score, and the sweep shows the score
        # cannot separate them. This is the boundary of the mechanism, not a to-do list.
        "how do I get an allocation on Bridges-2",
        "what does a service unit cost for an external collaborator",
        "how do I write PBS directives in my job script",
        "how do I enrol in a computer science course",
        "how much does the university spend on computing each year",
        "how many users does the cluster have",
        # Arrived with title-field length normalisation, and it is a trade taken with
        # its eyes open rather than a surprise — the same change caveated the two above
        # this line, so the list is one shorter than it was and `caveat_recall` went
        # 87.0% → 89.1%. What this one costs: `docs/software/apps-and-envs/alphafold.md`
        # is titled "AlphaFold Documentation", two tokens, and a two-token title
        # containing the reader's word now earns most of the title boost instead of the
        # same flat share as a fifteen-token heading trail. So a meta-question about who
        # writes the documentation scores 23.1 on a page about a protein-folding tool.
        #
        # Kept rather than tuned away: it is the one leak in the set with a *real* title
        # match, the alternative measured (b = 0.5 rather than BM25_B) buys this back and
        # 1.1pp of caveat recall at the price of three of the seven pages that could not
        # be found by their own title, and no threshold pair separates it — the two it
        # replaced scored 18.8 and 18.2 against a floor of 20, so the gap either way is
        # smaller than the spread inside this list.
        "is the documentation written by staff or by users",
    ]

    @pytest.mark.parametrize("question", LEAKING, ids=LEAKING)
    @pytest.mark.xfail(reason="known refusal-gate leak", strict=False)
    def test_it_should_be_caveated(self, real_index, question):
        assert not real_index.assess(question).confident

    def test_the_list_is_still_the_whole_list(self, measured):
        """No leak may appear that is not written down above.

        The ratchet catches the aggregate moving. This catches the aggregate holding
        still while the *membership* changes — a new leak arriving as an old one is
        fixed, which is the shape a refactor produces and the shape a percentage hides.
        """
        leaking = {
            row["question"] for row in measured["rows"]["negatives"] if row["leaked"]
        }
        surprises = sorted(leaking - set(self.LEAKING))
        assert not surprises, "new leaks, not in the recorded list: " + "; ".join(surprises)


def test_no_threshold_pair_beats_the_shipped_one_for_free(real_index, audited, measured):
    """The two constants are not leaving anything on the table.

    A pair that buys caveat recall by refusing answerable questions is a *trade*, and
    which side to take is a judgement about which error is worse on an app somebody reads
    every day — not something a test should decide. A pair that improves one axis and
    costs nothing on the other is not a judgement, it is an oversight, and this fails on
    it.

    History worth keeping: before the classification fix, no pair reached 90% caveat
    recall while keeping 95% of answerable questions — the two sides occupied the same
    score range, which is why the fix could not be a number. Afterwards one does (24/24
    buys 4.4pp of caveat recall for 1.3pp of over-refusal). That is a trade on n=46, and
    taking it would mean tuning two constants to catch two cases in the very set they are
    measured on, so it is written down rather than shipped. `tools/gate_check.py --sweep`
    prints the whole front against the shipped point.
    """
    swept = gate.sweep(
        real_index, audited, evals.questions(), evals.identifiers()
    )
    free = gate.dominating(swept, measured)
    assert not free, (
        "a threshold pair is better than the shipped one at no cost: " + str(free[:3])
    )


class TestTheSweepMeasuresTheOperatingPoint:
    """The sweep has to contain the pair the app runs at, or it is a set of alternatives
    to a point that is not on the table.

    It did not: `strong` steps by 4 from `minimum`, so the grid ran 20, 24, 28 and never
    landed on the shipped 20/26. Every number the sweep printed was still true, and the one
    comparison a reader wants — where are we, and what would moving cost? — could not be
    made from it.

    The invariant is the useful part: at the shipped pair, `sweep` and `measure` are two
    independent computations of the same two rates. If they ever disagree, one of them is
    wrong, and neither is worth reading until it is known which.
    """

    @pytest.fixture(scope="class")
    def swept(self, real_index, audited):
        return gate.sweep(real_index, audited, evals.questions(), evals.identifiers())

    def test_the_shipped_pair_is_in_the_grid(self, swept, real_index):
        from sage import config

        shipped = [
            point for point in swept["front"] if point.get("shipped")
        ] or [None]
        assessment = real_index.assess("how do I submit a batch job")
        assert (assessment.min_confident_score, assessment.strong_score) == (
            config.MIN_CONFIDENT_SCORE, config.STRONG_SCORE
        ), "the assessment no longer carries the shipped thresholds"
        # On the front or not is a finding, not a failure — but it must have been *swept*.
        assert swept["grid"] > 0
        assert shipped[0] is None or shipped[0]["min"] == config.MIN_CONFIDENT_SCORE

    def test_the_sweep_and_the_measurement_agree_where_they_overlap(
        self, real_index, audited, measured
    ):
        """Two computations of one number, run over the same cases at the same pair."""
        from sage import config

        rebuilt = gate.sweep(
            real_index, audited, evals.questions(), evals.identifiers()
        )
        at_shipped = [
            point for point in rebuilt["grid_points"]
            if point["min"] == config.MIN_CONFIDENT_SCORE
            and point["strong"] == config.STRONG_SCORE
        ]
        assert at_shipped, "the shipped pair was not evaluated by the sweep"
        point = at_shipped[0]
        assert point["caveat_recall"] == pytest.approx(measured["caveat_recall"])
        assert point["answerable_kept"] == pytest.approx(1 - measured["over_refusal"])


class TestTheDominationTolerance:
    """Counted in questions, because a rate comparison is decided by float noise.

    `76/78 + 1/78 > 77/78` is False in exact arithmetic and True in binary. A pair better
    by *exactly* one case therefore fell on whichever side the rounding landed, and it
    changed sides the day one question was added to the set — failing a test for a reason
    that had nothing to do with the gate.
    """

    SHIPPED = {
        "caveat_recall": 39 / 45,
        "over_refusal": 2 / 78,
        "n_negatives": 45,
        "n_positives": 70,
        "n_identifiers": 8,
    }

    def front(self, recall: float, kept: float) -> dict:
        return {"front": [{"min": 18, "strong": 18,
                           "caveat_recall": recall, "answerable_kept": kept}]}

    def test_one_case_better_is_within_tolerance(self):
        swept = self.front(39 / 45, 77 / 78)
        assert gate.dominating(swept, self.SHIPPED) == []

    def test_two_cases_better_is_not(self):
        swept = self.front(39 / 45, 78 / 78)
        assert gate.dominating(swept, self.SHIPPED)

    def test_two_cases_better_on_the_other_axis_is_not(self):
        swept = self.front(41 / 45, 76 / 78)
        assert gate.dominating(swept, self.SHIPPED)

    def test_better_on_one_axis_and_worse_on_the_other_is_a_trade(self):
        swept = self.front(43 / 45, 60 / 78)
        assert gate.dominating(swept, self.SHIPPED) == []

    def test_identical_is_not_domination(self):
        swept = self.front(39 / 45, 76 / 78)
        assert gate.dominating(swept, self.SHIPPED) == []

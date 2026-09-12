"""The figures `EVAL.md` states, checked against a live measurement.

This repository already learnt the lesson once, for retrieval: `tools/metrics.py` exists
because the eval's own docstring claimed "recall@3 94%" for a configuration that never
measured it, and a hand-written number nobody re-derives goes stale silently. Six passes of
edits later, `EVAL.md` said "77 answerable questions" over a set of 78, a ratchet comment
said "2 of 77", and `CLAUDE.md`'s test total had rotted three times.

So the headline figures are pinned here. Deliberately only the ones that move when the
*datasets or the gate* move — set sizes and the gate's three rates. A test count changes on
every commit that adds a test, so gating one would fail on every legitimate addition and
teach people to edit the number rather than read the failure; that total is no longer
written down anywhere.

A failure here means a document and the code disagree. Fix the document — or, if the code
moved on purpose, fix both and say so in the commit.
"""

from __future__ import annotations

import os
import re

import pytest

import evals
from evals import gate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL_MD = os.path.join(ROOT, "EVAL.md")


@pytest.fixture(scope="module")
def prose() -> str:
    with open(EVAL_MD, encoding="utf-8") as handle:
        return handle.read()


@pytest.fixture(scope="module")
def measured(real_index, real_corpus):
    negatives = gate.audit(evals.negatives(), gate.haystack(real_corpus))
    return gate.measure(
        real_index, negatives, evals.questions(), evals.identifiers()
    )


class TestTheSetSizes:
    """`EVAL.md` states these in the sentence reporting the gate's result."""

    def test_the_negative_count_is_current(self, prose, measured):
        stated = re.search(r"Result on (\d+) labelled negatives", prose)
        assert stated, "EVAL.md no longer states the negative count"
        assert int(stated.group(1)) == measured["n_negatives"], (
            f"EVAL.md says {stated.group(1)} negatives; the set has "
            f"{measured['n_negatives']}"
        )

    def test_the_answerable_count_is_current(self, prose, measured):
        stated = re.search(r"and (\d+) answerable questions", prose)
        assert stated, "EVAL.md no longer states the answerable count"
        live = measured["n_positives"] + measured["n_identifiers"]
        assert int(stated.group(1)) == live, (
            f"EVAL.md says {stated.group(1)} answerable questions; the set has {live}"
        )

    def test_the_injection_count_is_current(self, prose):
        stated = re.search(r"injections\.toml` holds (\d+):", prose)
        assert stated, "EVAL.md no longer states the injection count"
        live = len(evals.injections())
        assert int(stated.group(1)) == live, (
            f"EVAL.md says {stated.group(1)} injections; the set has {live}"
        )

    def test_the_conversation_count_is_current(self, prose):
        """The count in the multi-turn section, which went stale once already.

        The set was doubled from five and the sentence saying "five" stayed, which is the
        exact rot this file exists to stop.
        """
        stated = re.search(r"conversations\.toml` holds (\d+) cases", prose)
        assert stated, "EVAL.md no longer states the conversation count"
        live = len(evals.conversations())
        assert int(stated.group(1)) == live, (
            f"EVAL.md says {stated.group(1)} conversations; the set has {live}"
        )


class TestTheSelfDisclosureSetSizes:
    """Both halves of `meta.toml`, because the second one is the point.

    The probe count and the counterpart count are stated in one sentence of `EVAL.md` and
    nowhere else — the prose around it says "same probes" rather than repeating the
    number, which is the same discipline this file exists to enforce.
    """

    def test_the_probe_count_is_current(self, prose):
        stated = re.search(r"holds (\d+) probes in four classes", prose)
        assert stated, "EVAL.md no longer states the probe count"
        live = len([case for case in evals.meta() if case.probe])
        assert int(stated.group(1)) == live, (
            f"EVAL.md says {stated.group(1)} probes; the set has {live}"
        )

    def test_the_answerable_counterpart_count_is_current(self, prose):
        stated = re.search(r"honest — (\d+) ordinary questions", prose)
        assert stated, "EVAL.md no longer states the counterpart count"
        live = len(evals.meta(evals.ANSWERABLE))
        assert int(stated.group(1)) == live, (
            f"EVAL.md says {stated.group(1)} ordinary questions; the set has {live}"
        )

    def test_the_four_classes_are_four(self, prose):
        """The word in the same sentence, which no digit check would catch."""
        assert "in four classes" in prose
        kinds = {case.kind for case in evals.meta() if case.probe}
        assert len(kinds) == 4, kinds


class TestTheHeadlineRates:
    """The three numbers the card leads with, to one decimal place."""

    def rate(self, prose: str, pattern: str) -> float:
        found = re.search(pattern, prose)
        assert found, f"EVAL.md no longer states {pattern!r}"
        return float(found.group(1))

    def test_caveat_recall(self, prose, measured):
        stated = self.rate(prose, r"caveat recall 36\.8% →\s*\n?([\d.]+)%")
        assert stated == pytest.approx(measured["caveat_recall"] * 100, abs=0.05), (
            f"EVAL.md says {stated}% caveat recall; measured "
            f"{measured['caveat_recall']:.1%}"
        )

    def test_over_refusal(self, prose, measured):
        stated = self.rate(prose, r"over-refusal unchanged at ([\d.]+)%")
        assert stated == pytest.approx(measured["over_refusal"] * 100, abs=0.05), (
            f"EVAL.md says {stated}% over-refusal; measured {measured['over_refusal']:.1%}"
        )

    def test_recall_at_five(self, prose, measured):
        stated = self.rate(prose, r"recall@5 unchanged at ([\d.]+)%")
        assert stated == pytest.approx(measured["recall@5"] * 100, abs=0.05), (
            f"EVAL.md says {stated}% recall@5; measured {measured['recall@5']:.1%}"
        )


class TestTheRatchetsQuoteWhatTheyMeasure:
    """A ratchet's comment says what it measured. That comment is a number too.

    `MAXIMUM_OVER_REFUSAL = 0.04  # measured 0.026 (2 of 78)` — the denominator drifted to
    77 when a case was added, which is exactly how the retrieval eval's docstring came to
    claim a figure that had never been true of the code beside it.
    """

    def test_the_denominators_in_the_comments_are_current(self, measured):
        path = os.path.join(ROOT, "tests", "test_gate_eval.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        negatives = re.search(r"measured [\d.]+ \((\d+) of (\d+)\)", source)
        assert negatives, "the caveat-recall ratchet no longer quotes its measurement"
        assert int(negatives.group(2)) == measured["n_negatives"]

        answerable = re.search(r"measured 0\.0\d+ \((\d+) of (\d+)\)", source)
        assert answerable, "the over-refusal ratchet no longer quotes its measurement"
        live = measured["n_positives"] + measured["n_identifiers"]
        assert int(answerable.group(2)) == live, (
            f"the ratchet comment says {answerable.group(2)} answerable; the set has {live}"
        )

    def test_the_ratchets_still_sit_below_what_is_measured(self, measured):
        from tests import test_gate_eval as gate_eval  # noqa: PLC0415

        assert measured["caveat_recall"] >= gate_eval.MINIMUM_CAVEAT_RECALL
        assert measured["over_refusal"] <= gate_eval.MAXIMUM_OVER_REFUSAL
        assert measured["recall@5"] >= gate_eval.MINIMUM_RECALL_AT_5


class TestTheStatusArgumentClipFitsARealLabel:
    """`config.STATUS_ARGUMENT_CHARS` has to clear the longest section title.

    The progress block's read step shows a section's own title rather than the corpus
    path it was given. This corpus's headings are frequently whole questions, so a label
    runs long — and the clip was 96, which put an ellipsis two words from the end of a
    real one. That was the same complaint the CSS ellipsis had already produced once
    ("why can't it show the complete cot?"), reappearing in Python after being fixed in
    the stylesheet.

    Pinned here rather than in the harness because `tools/render_check.py` builds its
    worst case FROM this constant, so it cannot tell you whether the constant is big
    enough — only that the layout survives whatever it is. This is the half that moves
    when the documents change.
    """

    def test_the_clip_clears_every_label_the_corpus_can_produce(self):
        from sage import config, profile, runtime  # noqa: PLC0415

        corpus = runtime.build(profile.active()).corpus
        longest = max(corpus.chunks, key=lambda chunk: len(chunk.label))
        assert len(longest.label) <= config.STATUS_ARGUMENT_CHARS, (
            f"the longest section label is {len(longest.label)} characters "
            f"({longest.label[:60]}…) and the clip is "
            f"{config.STATUS_ARGUMENT_CHARS}, so a read step would show it ellipsed"
        )


class TestTheRenderCountIsNotHandMaintained:
    """The size of the layout run, held against the run itself.

    This is the number that went stale in two documents at once: `CLAUDE.md` said 684
    and `EVAL.md` said 660, and nothing in the repository could say which was right —
    the figure lived only in the shape of a loop inside `main()`. It is 684, and a
    scenario or a viewport added to the harness moves it, which is exactly the kind of
    edit that forgets a document.

    `tools/scorecard.py` is on the list because it was the THIRD copy, and running the
    card is what found it: two cells and a usage line said 660 while both documents had
    been corrected to 684. It now imports `RENDER_COUNT` for the cells, so the two that
    matter cannot drift again; the usage line is prose and this holds it.

    So `render_check` states it (`RENDER_COUNT`, built from `SCENARIOS`, `SCHEMES`,
    `WIDTHS` and `states_for`) and this holds both documents to it. Importing the module
    costs nothing and needs no browser: Chromium is only launched by `calibrate()` and
    `render()`.
    """

    @pytest.fixture(scope="class")
    def harness(self):
        import sys  # noqa: PLC0415

        tools = os.path.join(ROOT, "tools")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        import render_check  # noqa: PLC0415

        return render_check

    def test_the_count_is_the_loop_it_describes(self, harness):
        frames = sum(len(harness.states_for(name)) for name in harness.SCENARIOS)
        by_hand = frames * len(harness.SCHEMES) * len(harness.WIDTHS)
        assert by_hand == harness.RENDER_COUNT

    @pytest.mark.parametrize("document", ["CLAUDE.md", "EVAL.md", "tools/scorecard.py"])
    def test_every_place_that_states_it_says_what_the_harness_does(
        self, harness, document
    ):
        with open(os.path.join(ROOT, document), encoding="utf-8") as handle:
            text = handle.read()
        # Three phrasings, and deliberately not a loose "N renders": CLAUDE.md also
        # says "at 294 and 360 renders" about two bugs the harness caught at those
        # sizes, which is history rather than a claim about how big the run is.
        stated = {
            int(n)
            for pattern in (r"for (\d{3,4}) renders",
                            r"(\d{3,4})-render",
                            r"(\d{3,4}) renders = ")
            for n in re.findall(pattern, text)
        }
        assert stated, f"{document} no longer states a render count at all"
        assert stated == {harness.RENDER_COUNT}, (
            f"{document} says {sorted(stated)} renders and the harness performs "
            f"{harness.RENDER_COUNT}"
        )

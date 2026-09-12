"""A question waiting behind an answer must not be thrown away by a chat switch.

The queue lives on the parent window — `static/app.js`, `__sageQueue` — because
telling Python about it any earlier would be a widget interaction, and a widget
interaction during a run aborts the run the question is queued behind. That is the
right design and it has one consequence nothing else in this app has: the queue is
the only place a reader's question exists outside session state, so if app.js drops
it, no Python path can put it back and nothing in the transcript records that it was
ever typed.

`resetComposerOnClear` dropped it. The token it watches (`#composer-reset`) moves
whenever `state._leave_conversation` runs, which today is New chat, opening another
chat, and deleting the open one — the trash that cleared a conversation in place went
with `#79`, so every remaining case is another conversation opening. Measured in the
running app against `tools/mock_provider.py` at 1440 and at 500: ask a question, queue
a second one mid-answer, click another chat in the panel, and 200ms later the `Queued`
row is gone, `__sageQueue` is empty, the composer is empty, neither conversation holds
the question, and the provider's request log never saw it. No notice, no bubble, no
text anywhere on the page — the reader's question simply ceased to exist.

Not sending it was right: asked in the conversation now open it would be answered with
the wrong history, into the wrong transcript, which is the "app answering something
nobody asked" the drop was written for. So the fix hands it back to the composer,
unsent, where `flushQueue` already hands back a question the limiter refused — "a
question the reader can see and send themselves, rather than one that vanished".

A string check on `static/app.js`, and no browser: the behaviour itself is about time
and lives in the app, where it was measured. What this holds is the contract that
survives a refactor — the reset path must route the queue through a hand-back rather
than assigning an empty list over it — because the failure mode is silent in every
other witness this repo has. `render_check.py` never renders `#composer-reset`, so the
layout harness returns from that function on its first line and cannot see this at all,
and the palette check reads a different file. Same arrangement as
`test_think_pill_is_measured.py`.
"""

from __future__ import annotations

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JS = os.path.join(ROOT, "static", "app.js")

#: The one place a queued question is allowed to be emptied without being sent.
HAND_BACK = "handQueueBack"


@pytest.fixture(scope="module")
def script() -> str:
    with open(APP_JS, encoding="utf-8") as handle:
        return handle.read()


def body(script: str, name: str) -> str:
    """The source of one top-level `function name(...) { … }`, braces matched.

    Counting braces rather than slicing to the next `function`, so a nested closure —
    which this file is full of — does not end the body early.
    """
    start = script.index(f"function {name}(")
    opened = script.index("{", start)
    depth = 0
    for index in range(opened, len(script)):
        if script[index] == "{":
            depth += 1
        elif script[index] == "}":
            depth -= 1
            if depth == 0:
                return script[start : index + 1]
    raise AssertionError(f"{name} has unbalanced braces")


class TestTheQueueIsHandedBackRatherThanDropped:
    def test_the_hand_back_exists(self, script):
        assert f"function {HAND_BACK}(" in script, (
            f"`{HAND_BACK}` is gone. It is what keeps a queued question alive when the "
            "reader opens another conversation; without it the question is lost with "
            "nothing on screen to say so"
        )

    def test_nothing_empties_the_queue_outside_the_hand_back(self, script):
        """`__sageQueue = []` may appear in exactly two functions, and neither loses a
        question.

        `queue()` creates the list when there is none, which cannot discard anything —
        it is guarded on the list being absent. `handQueueBack` is the only place the
        whole queue goes, and it has just read it into `giveBack`. `flushQueue` takes
        questions off the front with `shift()`, so it never assigns over the list at
        all. An assignment anywhere else is a question thrown away.
        """
        allowed = [body(script, HAND_BACK), body(script, "queue")]
        spans = [(script.index(text), script.index(text) + len(text)) for text in allowed]
        emptied = [
            match.start() for match in re.finditer(r"__sageQueue\s*=\s*\[\]", script)
        ]
        stray = [
            position
            for position in emptied
            if not any(start <= position < end for start, end in spans)
        ]
        assert not stray, (
            "something empties `__sageQueue` outside `handQueueBack` and `queue`: the "
            "reader's queued question is being discarded rather than handed back to "
            f"the composer ({len(stray)} of {len(emptied)} assignments)"
        )

    def test_the_hand_back_reads_the_queue_before_emptying_it(self, script):
        hand_back = body(script, HAND_BACK)
        read = hand_back.index("view.__sageQueue ||")
        emptied = hand_back.index("__sageQueue = []")
        assert read < emptied, (
            "`handQueueBack` empties the queue before reading it, so there is nothing "
            "left to give back"
        )

    def test_the_hand_back_writes_the_text_into_the_composer(self, script):
        hand_back = body(script, HAND_BACK)
        assert "setFieldValue(" in hand_back, (
            "`handQueueBack` does not write anything into the box. The queued question "
            "has to end up somewhere the reader can see it — `setFieldValue(box, …)` "
            "is how every other path in this file puts text back in the composer"
        )
        assert "autosizeComposer()" in hand_back, (
            "text written into the composer without `autosizeComposer()` leaves a "
            "one-line box holding several lines of question"
        )

    def test_the_hand_back_gives_back_the_WHOLE_queue(self, script):
        """Two queued questions are two things the reader typed.

        Nothing above would notice `giveBack = held[0]`: the queue is still read before
        it is emptied, `setFieldValue` is still called, no stray assignment appears and
        nothing is submitted — and every question after the first would be gone. Held
        here because it is the one part of the hand-back that a plausible simplification
        breaks silently.

        Confirmed in the running app at 1440 and at 500 (two questions queued behind one
        answer, the first of them four lines, then ＋ New chat): both came back in the
        box, oldest first, separated by a blank line, one occurrence each, and the
        provider's request log saw neither.
        """
        hand_back = body(script, HAND_BACK)
        assert "held[0]" not in hand_back, (
            "`handQueueBack` gives back only the first queued question; the rest are "
            "discarded with nothing on screen to say so"
        )
        assert ".concat(held)" in hand_back and "join('\\n\\n')" in hand_back, (
            "`handQueueBack` no longer joins the whole queue. It has to hand back every "
            "question that was waiting — separated by a blank line, oldest first, the "
            "same shape `giveBackToComposer` uses"
        )

    def test_the_reset_path_goes_through_the_hand_back(self, script):
        reset = body(script, "resetComposerOnClear")
        assert f"{HAND_BACK}(" in reset, (
            "`resetComposerOnClear` no longer routes the queue through "
            f"`{HAND_BACK}`. That function runs on every conversation switch, and the "
            "queue it leaves behind is the reader's own typing"
        )

    def test_the_box_is_emptied_BEFORE_the_hand_back_is_called(self, script):
        """Order, not presence — and getting it wrong loses the question again.

        `handQueueBack` empties the queue and then refuses to write into a box that
        already holds something, which is `restoreDraft`'s rule: newer typing wins. So
        on the one path that reaches it with text in the box — the reader had started
        the next question — the clear has to have run first, or the hand-back discards
        the queue and writes nothing. Swapping these two lines is a one-line change that
        every other test in this file passes.

        Measured in the running app at 1440 and at 500: a question queued mid-answer and
        a half-typed draft in the box, then ＋ New chat, and the queued question is in
        the composer exactly once.
        """
        reset = body(script, "resetComposerOnClear")
        cleared = reset.index("setFieldValue(box, '')")
        handed = reset.index(f"{HAND_BACK}(")
        assert cleared < handed, (
            "`resetComposerOnClear` calls the hand-back before it empties the box, so "
            "the hand-back sees a box with text in it, returns without writing, and the "
            "queue it has just emptied is gone"
        )

    def test_the_question_in_flight_is_not_handed_back_as_well(self, script):
        """`__sageSending` is cleared, never restored: Python may already have it.

        A question that reached `handToComposer` may have been accepted a frame ago, in
        which case it is in a transcript and `state.abandon_turn` has marked the turn
        for `resume_pending`. Putting it in the box too would be one question asked
        twice.
        """
        hand_back = body(script, HAND_BACK)
        assert "__sageSending = null" in hand_back
        assert "giveBack" in hand_back
        assert "__sageSending)" not in hand_back.replace("view.__sageSending = null", "")


class TestTheHeldDraftSurvivesAQuestionComingBack:
    """The other way a queued question was lost: a refusal, with one queued behind it.

    `flushQueue` holds whatever was in the box when it took it (`__sageDraftHold`) and
    puts it back on the receipt. Both recovery paths — the limiter's refusal after
    `SEND_PATIENCE_MS`, and the click that never landed after `SEND_GIVE_UP` — used to
    null that hold and put only the question back, which is a loss whenever the hold is
    itself an earlier queued question that an earlier refusal had restored. Measured
    with `SAGE_RATE_BURST=1` and two questions queued behind one answer: at +6s the
    second question was in the box, at +12s only the third was, and the second never
    reached the provider's request log.
    """

    def test_the_giver_exists_and_joins_rather_than_overwrites(self, script):
        assert "function giveBackToComposer(" in script, (
            "`giveBackToComposer` is gone: the two recovery paths in `flushQueue` are "
            "putting a question back without the draft it displaced"
        )
        giver = body(script, "giveBackToComposer")
        assert "setFieldValue(" in giver
        assert "'\\n\\n'" in giver, (
            "`giveBackToComposer` does not join the held draft with the question, so "
            "one of the two is being dropped"
        )

    def test_the_flush_never_drops_the_hold_itself(self, script):
        """Only `restoreDraft` and the two givers may clear it — by consuming it."""
        flush = body(script, "flushQueue")
        assert "__sageDraftHold = null" not in flush, (
            "`flushQueue` clears `__sageDraftHold` directly. Both of its recovery "
            "paths must go through `giveBackToComposer`, which puts the draft back in "
            "the box instead of throwing it away"
        )
        assert flush.count("giveBackToComposer(") == 2, (
            "both recovery paths — the patience expiry and the give-up — hand the "
            "question back, so both must call `giveBackToComposer`"
        )


class TestTheQueueIsNotSentIntoAnotherConversation:
    def test_the_hand_back_does_not_click_send(self, script):
        """It hands the text over; it does not submit it.

        Sending here would ask the question in whichever conversation the reader just
        opened, with that conversation's history — the failure the original drop was
        written to prevent, and the reason the fix is a hand-back rather than a flush.
        """
        hand_back = body(script, HAND_BACK)
        for forbidden in ("sendButton", ".click()", "handToComposer"):
            assert forbidden not in hand_back, (
                f"`handQueueBack` contains `{forbidden}`: a queued question must not "
                "be submitted into the conversation that has just been opened"
            )

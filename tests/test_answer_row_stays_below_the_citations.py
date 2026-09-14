"""The row of icons under an answer must end up BELOW the Sources strip, every time.

Where it goes was a decision: under the citations, because the claim -> inline marker
-> numbered reference chain is what this app is for and controls in the middle of it
break the one thing the reader came for. See CLAUDE.md.

`app.js:addAnswerActions` appends the row to the answer's keyed container, and the
Sources and Related strips are siblings of the chat message inside that same
container — committed by Streamlit on its own schedule, not this script's. So
`appendChild` alone puts the row after whatever happens to be in the container at the
instant the row is built, and the `sageActs` marker then makes that permanent: a strip
committed after the injection leaves the icons stranded ABOVE the citations for the
life of that message, with nothing to correct it.

Reported on the deployment, and reported as unstable — "sometimes when I rerun the
answer, it's in the right order" — which is the signature of a race rather than a
layout rule. On the Streamlit measured here (1.54) the order was stable across three
turns sampled every 40ms right through the commit, so the race is not reproducible
locally; `requirements.txt` allows `streamlit>=1.42,<2` and the deployment builds a
newer one. Reproduced instead by construction, in the running app: move the row above
the strip by hand and the pre-fix script leaves it there through every further `sync`
pass, including an explicit `__sageSync()`.

The fix is that position is CHECKED on every pass rather than set once. Verified the
same way: after the fix the hand-made strand is repaired before the next read, because
moving a node is itself a childList mutation and the observer is already watching for
those. That also bounds the loop — the pass it schedules finds the row already last
and does nothing.

A string check on `static/app.js`, no browser, for the reason
`test_queued_question_is_not_lost.py` gives: the behaviour is about time and lives in
the app, where it was measured. What this holds is the contract that survives a
refactor, because the failure mode is silent — the icons still work, still hit-test,
and are simply in the wrong place.
"""

from __future__ import annotations

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JS = os.path.join(ROOT, "static", "app.js")


@pytest.fixture(scope="module")
def script() -> str:
    with open(APP_JS, encoding="utf-8") as handle:
        return handle.read()


@pytest.fixture(scope="module")
def injector(script) -> str:
    """The body of `addAnswerActions`, which is where all of this has to be true."""
    start = script.index("function addAnswerActions()")
    end = script.index("\n    }\n", script.index("ACTIONS.forEach", start))
    return script[start:end]


class TestTheRowIsPutLastAndKeptThere:
    def test_the_position_is_re_asserted_and_not_only_appended(self, injector):
        """The whole fix: a comparison against the container's last child.

        Without it the row's place is decided by whatever `appendChild` found at
        injection time and never revisited.
        """
        assert re.search(r"lastElementChild\s*!==\s*row", injector), (
            "nothing in `addAnswerActions` compares the row against its container's "
            "last child, so the row's position is whatever the DOM happened to look "
            "like when it was built — which is a race with Streamlit committing the "
            "Sources strip, and it is permanent once lost"
        )

    def test_the_move_is_not_inside_the_build_once_branch(self, injector):
        """It has to run on EVERY pass, not only when the row is created.

        The build is guarded by the `sageActs` marker so the row is not rebuilt
        thirty times a second (a node replaced under a reader's focus is a node they
        cannot focus). A position check inside that guard would run exactly once, at
        the moment it cannot yet know where the strip will land.
        """
        build = injector.index("dataset.sageActs = 'true'")
        move = injector.index("lastElementChild")
        marker_block_end = injector.index("host.appendChild(fresh)")
        assert not build < move < marker_block_end, (
            "the position check sits inside the build-once branch, so it can only "
            "fire on the pass that creates the row"
        )

    def test_the_row_is_parented_to_the_keyed_container(self, injector):
        """Not to `.stChatMessage`. app.css hangs the answer's gutter on the
        container and the strips are siblings of the message inside it, so a row
        appended to the message would be indented from the citations above it."""
        assert 'closest(\'[class*="st-key-answer-"]\')' in injector

    def test_nothing_writes_a_class_to_a_node_already_on_the_page(self, injector):
        """The mutation observer takes `attributeFilter: ['class']`, and `sync` must
        not feed itself. The row's class is set on a node the script has just made
        and not yet inserted; moving a node is a childList mutation, which is
        already watched and which converges because the next pass finds it in place.
        """
        for match in re.finditer(r"\.className\s*=", injector):
            line_start = injector.rfind("\n", 0, match.start()) + 1
            line = injector[line_start:injector.index("\n", match.start())]
            assert "fresh" in line, (
                f"`{line.strip()}` writes a class to a node that may already be in "
                f"the document, which is the shape that makes `sync` re-enter itself"
            )

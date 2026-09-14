"""The Think pill has to come back OFF, and in a conversation as well as an empty one.

Reported as "when the think toggle is on, it works great in a conversation, but I can't
untoggle it in a conversation, yet I can do so in an empty chat" — the third time this
control has been described as impossible to switch off, and the third different cause.
The first was `.stChatInput button:not(#paperclip-btn)` painting it `--brand` in every
state — `757ded4`, held since by `tests/test_palette.py`. The second was a
childList-only mutation observer never running the pass that would have unlit it.

This one is about WHERE app.js reads the state from, and the shape of the fault is worth
keeping, because it is what makes a bug look like it has a side. `addThinkButton` asked
`!!doc.querySelector('.st-key-think-on')` — "is there a node ANYWHERE on the page
wearing this class". A question asked that way can only ever be answered wrong in one
direction: a stray node pins the pill lit and nothing puts it out, while turning it ON
goes on working, because `on` is the reading a stray node agrees with. So the control
arms and cannot be disarmed. And it needs a conversation to have somewhere for a stray
node to be, which is exactly the screen it was reported on — Streamlit reuses a
container's DOM node across reruns and swaps its class rather than rebuilding it, so
which node is wearing which key is not this script's to assume. That hazard already has
a name at the top of `static/app.js`: it is what `INJECTED`/`NOT_INJECTED` exist for.

The same run found the pill's wire was the one lookup in that file NOT going through
`widgetButton`, so a relabelled container arriving with a button app.js had appended
still inside it would hand the click to a copy button or a re-ask instead of the
toggle. `1be6d8b` put four injected buttons in every answer's keyed container, which
raises the odds on that without being where either fault was written: both lines are
identical in `28ecc17` and both date from `ca8e3f9`.

**Which half of this a test without a browser can hold.** Python's half was never the
fault and is checked here anyway, because it is the thing the JS reads: the flag flips
both ways and the container key follows it on the same run. The JS half is held as an
invariant on the source, which is the only browserless way to state it — the same
arrangement `tests/test_palette.py` uses to hold a selector in `app.css`.

**What only the running app can check**, and where it was checked instead: that
Streamlit really nests the hook inside the keyed container (measured on 1.54 — the chain
is `st-key-think-toggle` → `st-key-think-off` → `st-key-composer-strip`, and both shapes
`tools/render_check.py:strip` models nest it the same way), and that a click round-trips
at all. Both were driven against the real app under `tools/mock_provider.py`: with one
extra `st-key-think-on` div appended elsewhere on the page, the click reached Python and
the real container duly became `st-key-think-off` while the pill stayed `data-on="true"`
through every further click; with one injected button left in the hook's container, the
click landed on that button and the pill never moved. Both are silenced by the fix and
neither is visible from here.

**And what was NOT observed, which is worth saying so nobody over-reads the above.**
Streamlit 1.54 was not caught leaving a stray keyed node behind on this machine: ~180
clicks across the landing screen, one/two/three-turn conversations, a long answer, a
scrolled page, a narrow window, dark mode, the sidebar open, an attachment on and off,
mid-stream, after a re-ask, after ＋ New chat and after a chat switch all flipped the
pill correctly, with exactly one `st-key-think-on`/`-off` node on the page every time.
So the stray node above is the mechanism demonstrated by construction, not a shape
reproduced from the wild — the requirements allow `streamlit>=1.42,<2` and node reuse
is the thing this file already says has changed between versions. What is certain is
the direction of the fault: a document-wide existence query cannot fail in the OFF
direction only by accident, and that is the direction that was reported.
"""

from __future__ import annotations

import os
import re

import pytest
from test_app_smoke import run_app

import stub_streamlit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ASKED = "how do I submit a batch job"


@pytest.fixture(autouse=True)
def _clean_modules():
    yield
    stub_streamlit.forget_importers()


def conversation():
    """A landed turn, so the pill is read on the screen the bug was reported on."""
    return [
        {"role": "user", "text": ASKED, "attachments": []},
        {"role": "assistant", "text": "Write a script and hand it to `sbatch`.",
         "sources": [], "rating": None},
    ]


def container_keys(stub):
    return [key for name, key in stub.events if name == "container"]


def think_state(stub):
    """`data-on` off the marker app.js labels the pill from, or None if undrawn."""
    for html in stub.markdown_html:
        found = re.search(r'id="think-state"[^>]*data-on="([01])"', html)
        if found:
            return found.group(1)
    return None


class TestTheFlagGoesBothWays:
    """Python's half: one click, either direction, on either screen."""

    @pytest.mark.parametrize("answered", [False, True],
                             ids=["empty-chat", "conversation"])
    @pytest.mark.parametrize("was_on", [False, True], ids=["turning-on", "turning-off"])
    def test_a_click_flips_it(self, monkeypatch, answered, was_on):
        stub, _ = run_app(
            monkeypatch,
            openrouter=True,
            buttons={"think-toggle": True},
            session={
                "messages": conversation() if answered else [],
                "thinking": was_on,
            },
        )
        assert stub.session_state["thinking"] is (not was_on), (
            "the pill is a `st.button` that flips a flag, and it has to flip in both "
            "directions on every screen — turning it off is the direction a reader "
            "needs in a conversation, and it is the one that was reported broken"
        )

    @pytest.mark.parametrize("on", [False, True], ids=["off", "on"])
    def test_the_container_key_says_which_state_it_is_in(self, monkeypatch, on):
        """The key IS the state as far as `app.js` is concerned, so it has to be on the
        page in the same run that changed it — which is what `st.rerun()` in
        `render_think_toggle` buys, and why the marker agrees with it."""
        stub, _ = run_app(
            monkeypatch,
            openrouter=True,
            session={"messages": conversation(), "thinking": on},
        )
        keys = container_keys(stub)
        wanted = "think-on" if on else "think-off"
        unwanted = "think-off" if on else "think-on"
        assert wanted in keys, f"no st.container(key={wanted!r}) was drawn"
        assert unwanted not in keys, (
            f"both {wanted!r} and {unwanted!r} were drawn in one run; app.js reads the "
            "state off that class and cannot be asked to choose between two of them"
        )
        assert think_state(stub) == ("1" if on else "0"), (
            "#think-state disagrees with the container key it is drawn beside"
        )


class TestAStaleCopyOfAKeyedContainerIsNotTheLiveOne:
    """Streamlit does not always remove the previous copy, and the first is the dead one.

    This is the root cause of both Think-pill bugs the owner reported, and of why
    neither could be reproduced locally. Measured with the app driven against
    `tools/mock_provider.py`:

    * on Streamlit **1.54** — what this repo's tests and all 720 renders are measured
      on — there is exactly one `st-key-think-toggle` container and one `#think-state`
      marker, at every point of every flow tried;
    * on Streamlit **1.63** — what `requirements.txt` (`streamlit>=1.42,<2`) resolves
      for the deployment — one re-ask from the answer's action row leaves TWO of each,
      and a second re-ask leaves FOUR. It doubles. Nothing else duplicates: the stop
      hook, the uploader, the chat input, the pencils and the action row's own three
      hooks were all measured at one copy on both versions.

    Python renders into the LAST copy; `querySelector` returns the first. So the pill
    read its state from a container Python had stopped writing to and painted from a
    marker that still said `0` — measured on 1.63 as `hookInsideWhich ["OFF", "ON"]`
    and `markerValues ["0", "1"]` with the pill showing `data-on` absent — and the
    click went through a widget that was no longer wired. That is "I can't untoggle it"
    and "after I regenerate, the toggle stops working", from one cause.

    Last, and not "the one that is not stale", because staleness cannot be seen from
    the DOM: the copies carry the same key, hold the same markup, and are all clipped
    to a pixel by app.css. The order is the only thing that distinguishes them, and on
    a version that leaves one copy the last IS the first, so this costs nothing there.
    """

    @pytest.fixture(scope="class")
    def source(self):
        with open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8") as handle:
            return handle.read()

    def test_widget_hosts_are_resolved_to_the_last_match(self, source):
        assert "function widgetHost(" in source, (
            "`widgetHost` is gone. Every lookup of a Streamlit widget by key has to "
            "resolve the LAST matching container, because a stale earlier copy is "
            "what the first match returns"
        )
        body = source[source.index("function widgetHost("):]
        body = body[: body.index(chr(10) + "    }")]
        assert "querySelectorAll" in body and "length - 1" in body, (
            "`widgetHost` no longer takes the last match, so it is back to returning "
            "whichever copy comes first in the document"
        )

    def test_the_widget_button_lookup_goes_through_it(self, source):
        body = source[source.index("function widgetButton("):]
        body = body[: body.index(chr(10) + "    }")]
        assert "widgetHost(" in body, (
            "`widgetButton` resolves its own host again, so the stop square, the "
            "paperclip, the pencils and the action row's re-asks would each click "
            "whichever copy is first rather than the live one"
        )
        assert "doc.querySelector(selector)" not in body

    def test_the_pill_does_not_read_its_marker_by_id(self, source):
        """`getElementById` returns the first match and cannot be told otherwise.

        Duplicate ids are not legal HTML and are not this app's doing — Streamlit left
        the old copy in the document — so the marker has to be found by a lookup that
        can take the last one.
        """
        start = source.index("function addThinkButton()")
        body = source[start : source.index(chr(10) + "    function ", start + 1)]
        assert "getElementById('think-state')" not in body
        assert "querySelectorAll('#think-state')" in body, (
            "the pill reads its marker in a way that cannot skip a stale copy"
        )


class TestTheScriptReadsTheStateOffItsOwnControl:
    """The JS invariant, on the source, because a browser is not in this suite."""

    @pytest.fixture(scope="class")
    def think_button(self):
        """The body of `addThinkButton`, which is the function that paints the pill."""
        with open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8") as handle:
            source = handle.read()
        start = source.index("function addThinkButton()")
        end = source.index("\n    function ", start + 1)
        return source[start:end]

    def test_the_state_comes_from_the_container_the_hook_is_in(self, think_button):
        """Not from whether the class exists somewhere on the page.

        `var on = !!doc.querySelector('.st-key-think-on')` is the bug: one stray node
        anywhere in the document — a container Streamlit relabelled and this script
        cannot account for — answers that question `true` for ever, and the pill can be
        armed but never disarmed. Anchoring on the hook makes the reading belong to the
        control the click goes to, whatever else on the page is wearing the same class.
        """
        assert ".st-key-think-on, .st-key-think-off" in think_button, (
            "addThinkButton no longer reads the state off the keyed container that "
            "wraps this run's hook. Anchor it on the hook "
            "(`hookHost.closest('.st-key-think-on, .st-key-think-off')`) — a bare "
            "document-wide `querySelector('.st-key-think-on')` cannot tell the "
            "toggle's own container from a stale one, and it fails in exactly one "
            "direction: the pill arms and will not disarm."
        )
        assignment = think_button[think_button.index("var on ="):]
        assignment = assignment[: assignment.index(";")]
        assert "keyed" in assignment, (
            "`on` is assigned from something other than the hook's own keyed "
            f"container: {' '.join(assignment.split())!r}. The document-wide read is "
            "the fallback for a Streamlit that does not nest the two, not the answer."
        )

    def test_the_wire_is_found_with_the_injected_guard(self, think_button):
        """`widgetButton`, which is `button:not([data-sage-injected])`.

        A container Streamlit relabels can arrive wearing this widget's key with a
        button app.js appended still inside it — the row under an answer puts four of
        them in a keyed container — and `click()` on one of those copies an answer or
        re-asks a question instead of toggling. Nothing reports it: the pill is still
        there, still painted, still hit-tests as itself, and does nothing. Every other
        wire in that file already goes through this helper.
        """
        assert "widgetButton(" in think_button, (
            "the pill's click no longer looks its hook up with `widgetButton`, so it "
            "can find a button this script injected instead of Streamlit's"
        )
        assert '"] button\')' not in think_button, (
            "a descendant-button selector is back in addThinkButton. That is the one "
            "lookup shape that cannot exclude an injected button — use "
            "`widgetButton(THINK_HOOK)`."
        )

    def test_the_hook_selector_is_named_once(self, think_button):
        """Two things need the same node — the click and the state — and a second copy
        of the selector string is how they drift apart."""
        assert think_button.count('[class*="st-key-think-toggle"]') == 0, (
            "the hook selector is spelled out inside addThinkButton again; "
            "`THINK_HOOK` is the one name for it"
        )

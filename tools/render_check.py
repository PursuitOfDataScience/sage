#!/usr/bin/env python3
"""Audit static/app.css in a real browser, across every screen, theme and width.

Streamlit often cannot be installed where this repo is worked on, and every UI bug
that has actually shipped here was pure CSS. This renders the stylesheet against a
replica of Streamlit's DOM in headless Chromium and asserts that nothing is
clipped, hidden behind the fixed input bar, overflowing horizontally, wrapping
onto an unwanted extra line, painted on top of a control, too close to the message
above it, adrift above the input bar, or failing contrast.

It has already caught what reading the CSS did not:
  * the newest answer sitting 131px underneath the fixed chat input;
  * the hero subtitle and all six starter cards wrapping to two lines;
  * a maroon focus ring at 1.73:1 on the dark background;
  * the controls under the input painted over by Streamlit's own pinned bar;
  * 19–25px between a question and its answer, and up to 566px of nothing
    between the last message and the input box;
  * the slack above a short conversation growing by 42px a frame, because a media
    query was quietly overriding the padding it was being applied to;
  * that slack being applied while an answer was still generating, which put the
    question halfway down the window with the reply arriving into the bottom of it —
    which needed a model added here before it could be caught;
  * 46px of nothing between the last line typed and the bottom of the input box,
    which is the send button taking a row of its own once the text passes one line.
    The replica had no send button at all, so the box was always exactly as tall as
    its text and the bug was not expressible here;
  * three separate bugs in the attachment chips, the first time a chip was rendered
    here at all: the newest answer 5px behind one row of them and 38px behind two,
    because every spacing measurement in app.js went to the input bar's top edge and
    the chips are pinned above it; the chips floating 58px above the box on the first
    frame, from a `--bar-band` fallback tuned like a reservation when it is a
    position; and the chip's own text at 4.39:1 in light mode, which is under AA and
    had never been measured because the chip was the only thing using that colour as
    text. One screen, three bugs, none of them visible from reading the CSS.

The dead space at the end of a conversation outlived three rounds of fixes because
of a line in this file: the bar was modelled `position: fixed`, the stylesheet
reserved a bar's worth of room at the end of the page on the strength of it, and
that reservation *was* the dead space. Streamlit also ships it `sticky`, in the
flow, where it needs no room reserved at all. Five of the screens here are
rendered the first way and three the second, and app.js asks the browser which one
it is looking at rather than trusting either.

It also, for a while, cheerfully passed a top bar that was completely unusable,
because the replica modelled Streamlit's header as a small right-aligned box
when it is really a full-width strip that takes every click underneath it. Two
checks came out of that and are the ones worth keeping honest:

  * every control is hit-tested with `elementFromPoint`, so "in the DOM with a
    sensible rectangle" is no longer mistaken for "a user can click it";
  * whatever the harness cannot see, it must not silently model away — a wrong
    model is worse than no model, because it reads as a pass.

The second of those caught this file itself. `--window-size` is the *outer* window,
so every height came back 87px short of the number asked for, and Chromium will not
open a headless window narrower than 500px however small a number it is given: the
414px phone in the width list was rendered at 500px for as long as the list existed,
and every failure it reported named a size it was not looking at. Both numbers are
measured at startup by `calibrate()` now, the window is asked for the chrome on top
of the viewport wanted, and any render whose viewport is not the one requested is
reported as a failure instead of being quietly measured.

Five states per screen — the first frame with no app.js at all, at rest, scrolled to
the end, mid-generation, and just finished — except the two landing screens, which
have no turn to be in the middle of and render the first two, and the mid-answer
screen, which *is* the generating state and renders only that.

The first of those states is the layout the stylesheet's own fallbacks produce — a
frame every user sees, and where CI once found an answer 2px under the input. In the
rest the real app.js runs, because the room the page leaves for the bar and the slack
above a short conversation are both measurements it publishes; the last two states
additionally exercise the per-turn scroll pin and the settle that closes what it
leaves behind.

Usage:
    python tools/render_check.py            # audit; exits non-zero on failure
    python tools/render_check.py -v         # also print every measurement

Both colour schemes are exercised by rewriting the `prefers-color-scheme` block,
because headless Chromium cannot be told which scheme to emulate from the CLI.
Requires a Chromium binary; set SAGE_CHROME to override the path.
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys

import tomllib

CHROME = os.environ.get(
    "SAGE_CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
)
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from sage import config as config_module  # noqa: E402
from sage import profile as profile_module  # noqa: E402
from sage import tools as tools_module  # noqa: E402

# Streamlit's own header (`[data-testid="stHeader"]`) is a FULL-WIDTH fixed strip
# across the top of every app at a z-index far above anything a stylesheet sets.
# It is usually transparent, so it hides nothing — but it is on top, so it takes
# the clicks for everything underneath it. Anything interactive placed in this
# band is unreachable, however good it looks.
#
# This used to be modelled as a 220px right-aligned box, on the reasoning that
# Community Cloud's visible controls are right-aligned. That was wrong, and it
# is why the top bar passed every render while being unusable in the real app.
HOST_BAR = 60
# The part that also paints: the Community Cloud control cluster, right-aligned.
HOST_BAR_W = 220
# Streamlit's header sits at this z-index. Its pinned bottom container is not
# documented as being in the same band, but it is Streamlit chrome and it is
# fixed over the page, so it is modelled as if it were: the strip of controls
# app.py pins inside that band has to outrank whatever is really there, and a
# harness that assumed the friendlier number would pass a dead picker again.
HOST_Z = 999990


def _read(*parts: str) -> str:
    with open(os.path.join(REPO, *parts), encoding="utf-8") as handle:
        return handle.read()


CSS = _read("static", "app.css")
JS = _read("static", "app.js")

# The strings the landing screen actually draws, read from the profile that supplies
# them. They used to be scraped out of `app.py` with two regexes, which stopped
# finding anything the day they moved — and a harness that cannot find the text it is
# supposed to measure has to say so rather than measure a placeholder, so this now
# reads the same object the app does.
#
# There was a `_disclaimer()` beside these that read the caveat line out of app.py so
# the two could not drift apart. The caveat line is gone from the app, so it is gone
# from here — not left pointing at nothing, which is how a check comes to pass on a
# placeholder. The lesson is the same one: read the real string, or do not claim to be
# measuring it.

# The typeface, read out of `.streamlit/config.toml` rather than written down here.
#
# A font is not a detail this harness can afford to guess at: it decides the width of
# every string on the page, and most of the bounds below are about a string fitting
# somewhere. This file named `"Source Sans Pro"` on `body` for as long as it existed —
# and nothing on this cluster or in CI has Source Sans Pro installed, so what it
# actually measured all that time was DejaVu Sans, which is about 12% wider than the
# face the app really ships. Every bound was tuned against a font the app never had.
#
# So the faces come from the same `[[theme.fontFaces]]` table Streamlit builds the
# app's own @font-face rules from, pointed at the woff2 files in `static/fonts/` as
# absolute `file://` urls — the deployed urls are relative to the app root, which is
# not where this harness writes its pages. That makes the geometry here the geometry
# the reader gets, on any machine, with no system font installed at all.
#
# Every failure is loud. A missing table, a missing file, a face that does not load:
# each one would leave Chromium quietly measuring whatever sans it can find, which
# reads as a pass. `font-display: block` because a swap halfway through a render would
# measure two fonts in one page.
def _theme_table() -> dict:
    with open(os.path.join(REPO, ".streamlit", "config.toml"), "rb") as handle:
        return tomllib.load(handle).get("theme", {})


def _font_faces(theme: dict) -> str:
    faces = theme.get("fontFaces") or []
    if not faces:
        raise SystemExit(
            "render_check: .streamlit/config.toml declares no [[theme.fontFaces]], so "
            "this harness has no way to render the app's typeface and would measure "
            "the system fallback instead. Add the table or stop claiming to measure "
            "the app."
        )
    rules = []
    for face in faces:
        path = os.path.join(REPO, face["url"].replace("app/static/", "static/", 1))
        if not os.path.exists(path):
            raise SystemExit(
                f"render_check: {face['url']} is declared in [[theme.fontFaces]] and "
                f"is not in this repo ({path}). On the deployment that is a 404 and a "
                "page in the fallback face; here it would be a silently wrong "
                "measurement."
            )
        rules.append(
            f'@font-face {{ font-family: "{face["family"]}";'
            f' src: url("file://{path}") format("woff2");'
            f' font-weight: {face.get("weight", "400")};'
            f' font-style: {face.get("style", "normal")};'
            " font-display: block; }"
        )
    return "\n".join(rules)


THEME = _theme_table()
FONT_FACES = _font_faces(THEME)
# The stacks as the app states them. Read, not copied: a font named in one place and
# measured from another is the DejaVu mistake with a new spelling.
FONT_STACK = THEME.get("font") or "sans-serif"
CODE_STACK = THEME.get("codeFont") or "monospace"
# What `snapshot()` reports back so a render cannot pass on the wrong face. The family
# is taken off the front of each stack, which is where the app's own name is.
FONT_PROBES = {
    "sans": FONT_STACK.split(",")[0].strip(),
    "mono": CODE_STACK.split(",")[0].strip(),
}

PROFILE = profile_module.active()
SUBTITLE = PROFILE.copy.welcome_subtitle or "(missing)"
CARDS = [f"{card.icon} {card.label}" for card in PROFILE.examples]
# Read from app.js so the two can never drift apart.
TOP_GAP = int(re.search(r"var TOP_GAP = (\d+)", JS).group(1))


def theme_css(scheme: str) -> str:
    """Force one colour scheme, since the CLI cannot emulate prefers-color-scheme."""
    marker = "@media (prefers-color-scheme: dark) {"
    if scheme == "light":
        # Drop every dark block; light is the base.
        out, index = [], 0
        while True:
            start = CSS.find(marker, index)
            if start == -1:
                out.append(CSS[index:])
                break
            out.append(CSS[index:start])
            depth, pos = 0, start
            while pos < len(CSS):
                if CSS[pos] == "{":
                    depth += 1
                elif CSS[pos] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                pos += 1
            index = pos + 1
        return "".join(out)
    # Dark: make the block unconditional.
    return CSS.replace(marker, "@media all {")


BACKGROUNDS = {"dark": "#0e1117", "light": "#ffffff"}
FOREGROUNDS = {"dark": "#e5e7eb", "light": "#31333f"}

# What the Think pill shows. Both come from `profile.Copy`, so the label this replica
# renders is the label a default deployment renders — and unlike the model picker this
# replaces, there is no "longest name" to size for: the word is the same in both states
# and the pill has no width rule at all.
#
# Imported rather than copied. The pill's one hard bound is that it fits beside the send
# button in the band at 500px, and a literal here would go on passing on the day the
# profile's word got longer — which is the whole failure mode this file exists to avoid.
THINK_LABEL = profile_module.Copy().think_label
THINK_HINT = html.escape(profile_module.Copy().think_hint, quote=True)
# The brain app.js injects, inlined exactly as it does: a 14px stroke SVG with a 5px
# right margin, inside the label. Part of what the pill has to fit.
BRAIN = ('<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" '
         'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
         '<path d="M12 5a3 3 0 0 0-3 3 3 3 0 0 0-1 5.8V16a3 3 0 0 0 4 2.8V5Z"></path>'
         '<path d="M12 5a3 3 0 0 1 3 3 3 3 0 0 1 1 5.8V16a3 3 0 0 1-4 2.8V5Z"></path>'
         "</svg>")

# What the composer asks for, keyed on whether this is the landing screen. app.py
# switches on an answer existing; every screen here that is not `landing` has one.
PLACEHOLDERS = {True: "Ask any question about the RCC…",
                False: "Ask a follow-up question…"}

# The worst the status line gets, read from the profile that supplies it rather than
# written out here. It used to be `"Reading "` plus the longest document title in the
# corpus, 49 characters of it — a fair worst case back when the line named what it was
# reading, and pure fiction since it stopped: the app cannot produce that string any
# more, so measuring it measured nothing that ships. The phrases are fixed now, so the
# longest of them IS the worst case, exactly.
#
# It is the worst case for the FIXED half of the block: the line a turn opens on and
# waits between rounds on. A tool's line is named and measured differently — see the
# three constants below and `step_block`.
STATUS_LABEL = max(PROFILE.copy.status_phrases, key=len)

# A step names its tool the way a reader would and prints the argument that says which
# one. Both read off the tools that declare them rather than written out here, for the
# same reason STATUS_LABEL is: a screen rendering a string the app cannot produce
# measures nothing that ships.
STEP_NAMES = (tools_module.SearchDocs.label, tools_module.ReadDoc.label)
# A real read, anchor and all — the profile's own example of one.
# A section TITLE, which is what a read step shows — never the corpus path. The row
# resolves the id it is given to `Chunk.label` before painting it, because a path is
# this repository's name for a file rather than the documentation's and it was reported
# on sight: "docs/allocations.md shouldn't be disclosed in this way". Modelled as a
# title here so the width this measures is the width the app draws; the old value was
# `PROFILE.identity.path_example`, which is shorter than a real label and would have
# under-measured the row.
STEP_PATH = "Allocations and Service Units FAQ — Service Units (SUs)"
# And the widest line the block can hold, which is where `turn.shown` clips. Past that
# a value's own length stops mattering and short of it every length is narrower, so
# this is the exact worst case rather than a guess at one. `x` in a monospace face is
# an ordinary-width character, so the width it produces is honest.
STEP_WIDEST = "sbatch " + "x" * (config_module.STATUS_ARGUMENT_CHARS - 7)


def base_css(scheme: str) -> str:
    return f"""
{FONT_FACES}
* {{ box-sizing: border-box; }}
/* The face and the stack Streamlit itself puts on the page from `[theme] font`, which
   is why they are here and not left to app.css: the app is painted by both files and
   the harness has to model the half it does not own. */
body {{ margin: 0; background: {BACKGROUNDS[scheme]}; color: {FOREGROUNDS[scheme]};
       font-family: {FONT_STACK}; }}
.stMarkdownColoredText {{ color: {COLORED_TEXT[scheme]}; }}
[data-testid="stAppViewContainer"] {{ min-height: 100vh; }}
[data-testid="stMain"] {{ overflow: auto; height: 100vh; }}
/* The other place Streamlit's scrollbar can be: on the document, with stMain just
   a block that grows. It matters because it decides which element answers "does
   this page scroll?" — ask stMain in this shape and it says no however long the
   conversation is, which is how a screenful of slack ended up above one that
   scrolled. See `page(doc_scroll=…)`. */
.doc-scroll [data-testid="stMain"] {{ overflow: visible; height: auto; }}
.block-container {{ padding: 6rem 1rem 10rem; margin: 0 auto; }}
/* Streamlit's own wrapper between `.stMarkdown` and whatever `st.markdown` was given,
   and the one declaration on it that moves anything: a negative bottom margin, which
   collapses with the last child's and pulls the next block up by 16px.
   `st-emotion-cache-8vxb2y {{ margin-bottom: -1rem }}` on 1.54, measured live.
   Missing here, this replica was 16px more generous than the app on every gap set from
   inside a markdown block — the question-to-answer gap, the Sources strip, the notice
   and the error card — so it read 44px where the app drew 28px and passed a bound the
   app was failing. */
[data-testid="stMarkdownContainer"] {{ margin-bottom: -1rem; }}
.stMarkdown h1 {{ font-size: 2.75rem; font-weight: 600; line-height: 1.2;
                 padding: 1.25rem 0 1rem; margin: 0; }}
.stMarkdown h2 {{ font-size: 1.75rem; line-height: 1.3; margin: 0 0 .5rem; }}
/* Streamlit sizes markdown paragraphs itself, at a specificity of (0,1,1) — one class
   and one type. A bare one-class rule loses to it, which is how the caveat line that
   used to sit under the input rendered at Streamlit's size and wrapped onto a second
   line while every render here passed: the replica had no paragraph size at all, so
   the app's rule won by default. Kept because `.welcome-subtitle` is still in that
   fight. */
.stMarkdown p {{ margin: 0 0 1rem; font-size: 1rem; line-height: 1.6; }}
.stMarkdown pre {{ background: {'#262730' if scheme == 'dark' else '#f0f2f6'};
                  padding: 1rem; border-radius: 8px; overflow-x: auto; margin: 0 0 1rem; }}
/* Streamlit's `[theme] codeFont`, which it applies to `code` and `pre` itself — so a
   code block is in the mono face here even where app.css says nothing. */
.stMarkdown code, .stMarkdown pre {{ font-family: {CODE_STACK}; }}
.element-container {{ width: 100%; }}
[data-testid="stVerticalBlock"] {{ display: flex; flex-direction: column; }}
[data-testid="stHorizontalBlock"] {{ display: flex; flex-direction: row; }}
[data-testid="stColumn"] {{ flex: 1; min-width: 0; }}
.stButton button {{ width: 100%; padding: .4rem .75rem; border-radius: 8px;
   background: {'#262730' if scheme == 'dark' else '#fff'};
   color: inherit; border: 1px solid {'#3a3b46' if scheme == 'dark' else '#d5d6d8'};
   font: inherit; cursor: pointer; }}
.stButton button p {{ margin: 0; }}
/* Streamlit renders a button's label as markdown, and paints that paragraph with the
   theme font itself — so a `font-family` set on the BUTTON is handed to a child that
   has already been told otherwise. Modelled because a rule naming only the button
   passed every render here while the open model picker rendered all four names in the
   sans face in the running app: the harness could not fail on it, which reads as a
   pass. See the `p` selectors in app.css's TYPE block. */
.stButton button p {{ font-family: {FONT_STACK}; }}
/* The pinned input bar, modelled BOTH ways — see `page(sticky=…)`. `fixed` paints
   it over the conversation, so the page must leave a bar's worth of room at the end
   or the newest answer hides underneath; `sticky` puts it in the flow at the end of
   the scrolling area, where it takes its own space and reserving that room again is
   dead space. Streamlit has shipped both, this harness asserted the first for a
   year, and app.js now asks the browser which one it is looking at. */
[data-testid="stBottomBlockContainer"] {{
   background: {BACKGROUNDS[scheme]}; padding: 1rem; z-index: {HOST_Z}; }}
.bar-fixed [data-testid="stBottomBlockContainer"] {{ position: fixed; bottom: 0;
   left: 0; right: 0; }}
.bar-sticky [data-testid="stBottom"] {{ position: sticky; bottom: 0;
   z-index: {HOST_Z}; }}
/* Sticky alone would leave the input floating mid-page whenever the conversation
   is short — `bottom: 0` only offsets an element that would otherwise scroll out
   of view. So the in-flow version has to come with a column that fills the height
   and a block that grows into it, which is what puts the bar at the bottom of a
   short page and, incidentally, what makes any padding this stylesheet reserves
   for the bar pure dead space above it. */
.bar-sticky [data-testid="stMain"] {{ display: flex; flex-direction: column; }}
.bar-sticky .block-container {{ flex: 1 0 auto; }}
/* Streamlit's own padding on the composer box, which `app.css` styles the border and
   the left inset of but never resets the top and bottom of. 12px each, and both of
   them matter: the buttons are pinned to the floor of this box while the field's one
   line of text is centred in it, so the 24px it adds is 12px of daylight between the
   two. Without it the replica put clip, caret and send on one line while the running
   app hung both buttons 15px under the sentence — the harness could not have failed
   on the bug, which reads as a pass. Horizontal padding stays in `app.css`: that side
   IS ours (50px to clear the clip, 56px to clear the send button). */
.stChatInput > div {{ background: {'#262730' if scheme == 'dark' else '#f0f2f6'};
   padding-top: 12px; padding-bottom: 12px; }}
.stChatInput textarea {{ width: 100%; background: transparent; border: 0;
                        color: inherit; font: inherit; resize: none; }}
/* Streamlit's send button: its own size, in the flow, and a flex item of the box
   alongside the textarea. Modelled at its real size because the height of the box is
   what it decides — an unstyled button is small enough to hide the row it takes. */
.stChatInput button {{ width: 36px; height: 36px; flex: 0 0 auto; border-radius: 8px;
   background: {'#3a3b46' if scheme == 'dark' else '#e6e6e9'}; color: inherit;
   border: 0; font: inherit; cursor: pointer; }}
.stChatInput button p {{ margin: 0; }}
/* The other way Streamlit stacks the inside of that box: the button in a row of its
   own *under* the textarea rather than beside it. Which one it is decides whether a
   box with a paragraph in it has a band of nothing under the last line — 46px of it
   in this shape, 2px in the row shape — and it is not visible from this repo, so both
   are rendered. See `page(column_input=…)`. */
.input-column .stChatInput > div {{ flex-direction: column !important;
   align-items: stretch !important; }}
.input-column .chat-actions {{ display: flex; justify-content: flex-end;
   align-items: center; padding: 4px 8px; }}
.stChatMessage {{ display: flex; }}
/* The overlay portal Streamlit renders popovers into, at the end of <body>. Modelled
   with BOTH of the things Streamlit gives it, because the app's own rules only matter
   in contrast to them:
     - it is positioned (floating-ui anchors the panel to its trigger), so it takes no
       space in the flow. Left static it added a slab to the end of the page and the
       slack above the conversation was measured against it — 476px of dead space that
       had nothing to do with the panel;
     - the body has a light background and dark text of Streamlit's own. That is the
       white slab a dark-mode reader saw, and a stylesheet that fails to override it
       has to LOSE here, or this screen proves nothing. */
#stFloatingOverlayPortal {{ position: fixed; right: 1rem; bottom: 8rem; z-index: {HOST_Z + 5}; }}
/* The pill is a plain `st.button`, so Streamlit's own button styling reaches it and
   the base rule above is enough. Nothing is modelled for a popover any more: the
   model picker is gone and `st.popover` is used nowhere in the app, so a trigger, a
   chevron and a portalled panel were three shapes this replica carried for markup
   that no longer renders. `--picker-chars` went with them — the pill's label is one
   word in both states, so nothing has to publish a width for it. */
/* Streamlit's header: full width, transparent, and above everything. */
[data-testid="stHeader"] {{ position: fixed; top: 0; left: 0; right: 0;
   height: {HOST_BAR}px; background: transparent; z-index: {HOST_Z}; }}
/* Streamlit's own row inside it, and the sidebar arrow at the position it really
   occupies. app.js measures the arrow to place the theme toggle clear of it. */
[data-testid="stToolbar"] {{ position: relative; height: {HOST_BAR}px; }}
.toolbar-row {{ position: absolute; top: 16px; left: 16px; height: 28px;
                display: flex; align-items: center; }}
/* Flush with `#host-bar` and exactly as wide, because on the deployment they are one
   cluster: the toggle has to clear the band the host paints, not just the word inside
   it. Modelled 32px narrower at first, and the bound duly reported the toggle 8px
   inside the host's own controls at every width. */
.toolbar-actions {{ position: absolute; top: 16px; right: 0; height: 28px;
                    width: {HOST_BAR_W}px; display: flex; align-items: center;
                    justify-content: flex-end; padding-right: 16px;
                    box-sizing: border-box; }}
[data-testid="stToolbarActionButton"] {{ height: 28px; border: 0;
                    background: transparent; color: {FOREGROUNDS[scheme]}; }}
/* Streamlit's running indicator, in the place and at the size it really renders: in the
   header's right-hand group, immediately left of the host's Share button, and only while
   a script is running. It is modelled so the app's rule hiding it has something to hide
   — the reader photographed this drawn on top of the theme toggle, and with nothing here
   the hit test on that toggle had nothing to fail on. */
.status-widget {{ position: absolute; top: 16px; height: 28px;
                  right: {HOST_BAR_W}px; width: 92px;
                  background: {BACKGROUNDS[scheme]}; color: {FOREGROUNDS[scheme]}; }}
[data-testid="stExpandSidebarButton"] {{ width: 28px; height: 28px; border: 0;
                background: transparent; color: {FOREGROUNDS[scheme]}; }}
/* The host's own control cluster, which additionally paints. */
#host-bar {{ position: fixed; top: 0; right: 0; width: {HOST_BAR_W}px;
            height: {HOST_BAR}px; background: {BACKGROUNDS[scheme]}; z-index: 999991; }}
"""


def _cards_html() -> str:
    rows = ""
    for a, b in ((0, 1), (2, 3), (4, 5)):
        rows += f"""<div data-testid="stHorizontalBlock">
  <div data-testid="stColumn"><div class="st-key-example-card-{a} element-container">
    <div class="stButton"><button><p>{CARDS[a]}</p></button></div></div></div>
  <div data-testid="stColumn"><div class="st-key-example-card-{b} element-container">
    <div class="stButton"><button><p>{CARDS[b]}</p></button></div></div></div>
</div>"""
    return rows


def chips(wrapped: bool = True) -> str:
    """Attachment chips, rendered where app.py renders them: above the controls.

    Modelled at all because they were not, and the consequence was a row of `fixed`
    elements nothing in this file had ever measured. Two of them, one with a long
    name, because the row wraps and a single short chip proves nothing about that.
    Both container shapes, for the reason `strip` renders both.
    """
    buttons = "".join(
        f'<div class="element-container"><div class="stButton">'
        f"<button><p>{label}</p></button></div></div>"
        for label in (
            "📝 slurm-12345.out · 8,412 characters  ✕",
            "🖼️ pasted-image.png · 184 KB image  ✕",
        )
    )
    if wrapped:
        return ('<div class="st-key-attachments element-container">'
                f'<div data-testid="stVerticalBlock">{buttons}</div></div>')
    return ('<div class="st-key-attachments" data-testid="stVerticalBlock">'
            f"{buttons}</div>")


def strip(clear: bool = True, wrapped: bool = True, pressed: bool = False) -> str:
    """The model picker, in the bottom-right corner of the input box.

    Rendered last in the block, where app.py renders it, and pinned into the box by
    app.css from a position app.js measures off the send button.

    `clear` is dead and kept only so the scenario table below need not be rewritten:
    the 🗑️ that used to share this row is gone, because every chat in the panel has a
    ✕ and New chat sits above them. Nothing renders for it either way.

    `wrapped` picks which of the two shapes `st.container(key=…)` produces: the
    `st-key-…` class on a wrapper *around* the vertical block, or on the vertical
    block itself. Which one Streamlit emits is an implementation detail that has
    changed between versions, and modelling only the wrapped shape is how a
    stylesheet that stacked the three controls in a column in the real app passed
    170 renders here in a row. Both shapes are rendered now, so a rule that only
    reaches one of them fails the audit.
    """
    trash = ""
    # One control. There was a 🗑️ to its left and a caveat line left of that, then the
    # model picker on its own, and now the Think pill — and with the first of those went
    # the whole idea of a row under the input, which is where the vertical space this
    # corner bought back came from.
    # The Think pill, in both states. `pressed` is what app.js sets and what app.css
    # paints the "on" fill off, so rendering only one of them would leave the filled
    # pill — a white label on maroon, the one contrast pair here that can fail — never
    # measured. The brain is inlined exactly as app.js injects it, inside the label,
    # because a 14px SVG with a right margin is part of what the pill has to fit.
    controls = f"""
    {trash}
    <div class="st-key-think-{'on' if pressed else 'off'}" data-testid="stVerticalBlock">
      <div class="element-container"><div class="stButton">
        <button aria-pressed="{'true' if pressed else 'false'}" title="{THINK_HINT}"><p>{BRAIN}{THINK_LABEL}</p></button>
      </div></div>
    </div>"""
    if wrapped:
        return f"""<div class="st-key-composer-strip" data-testid="stVerticalBlockBorderWrapper">
 <div data-testid="stVerticalBlock">{controls}</div></div>"""
    return f"""<div class="st-key-composer-strip" data-testid="stVerticalBlock">
 {controls}</div>"""


# Real citation labels, not short ones. A chip's text is `"{doc_title} — {heading}"`,
# and RCC headings are frequently whole questions, so 60–90 characters is the ordinary
# case rather than the long tail. Six of them, because `SEARCH_RESULTS` is 6 and
# `ToolRunner.sources` dedupes across every tool round, so a six-source answer is
# routine — and because the ragged-wrap bug this markup replaced needed five real-length
# labels before it appeared at all. Two short chips, which is what these fixtures used
# to hold, cannot wrap at any width this file renders: the check could not have failed.
REAL_SOURCES = [
    ("Storage System Layout — How do I increase my storage quota?", "docs"),
    ("Batch jobs — Why does my job fail with “exceeded memory limit, being killed”?",
     "docs"),
    ("Allocations and Service Units FAQ — How do I check how many service units I have "
     "remaining on my allocation?", "docs"),
    ("Partitions — Partition QoS and per-user limits", "docs"),
    ("Overview of RCC’s HPC Systems — Midway3", "docs"),
    ("Skyway FAQs — Which cloud provider should I use?", "web"),
]
REAL_RELATED = [
    "Running jobs on RCC clusters — Service units, allocations, and accounts",
    "Large-Memory Jobs",
    "Checking job status in the terminal",
]


def source_list(sources=None) -> str:
    items = "".join(
        f'<div class="source-item"><a class="source-link" href="#">{label}</a>'
        f'<span class="source-kind">{kind}</span></div>'
        for label, kind in (REAL_SOURCES if sources is None else sources)
    )
    return (f'<div class="sources"><span class="sources-label">Sources</span>'
            f'<div class="source-list">{items}</div></div>')


def related_list(related=None) -> str:
    items = "".join(
        f'<div class="related-item"><a class="related-link" href="#">{label}</a></div>'
        for label in (REAL_RELATED if related is None else related)
    )
    return (f'<div class="sources related"><span class="sources-label">Related</span>'
            f'<div class="related-list">{items}</div></div>')


def references(sources=None, related=None) -> str:
    """Both strips, in the wrapper `st.markdown` puts around them.

    One call renders both in `app.py`, so one wrapper holds the pair — and it is
    `[data-testid="stMarkdownContainer"]`, which carries `margin-bottom: -1rem`. As
    bare siblings of the answer, which is how they were rendered here, the gap above
    Sources was a plain margin between two divs; in the app it is that margin against
    a negative one on the block above. The two agreed by luck at 0.55rem and would
    have stopped agreeing the moment the value moved, which is the whole reason this
    wrapper is modelled anywhere.
    """
    return ('<div class="element-container"><div class="stMarkdown">'
            '<div data-testid="stMarkdownContainer">'
            f"{source_list(sources)}"
            f"{related_list(related) if related is not False else ''}"
            "</div></div></div>")


REFERENCES = references()


# The inline citation marker `links.mark_sources` puts at the end of a cited sentence,
# as Streamlit renders `:small[:gray[[1](url)]]`: a size span, a colour span, and an
# anchor inside them. Modelled because the replica is the only place the marker's own
# rule can be seen at every width — it sits in the flow of a paragraph, so if it ever
# grew a line box of its own it would push an answer around.
MARKER = (
    '<span style="font-size: 0.875rem;">'
    '<span class="stMarkdownColoredText">'
    '<a href="https://docs.rcc.uchicago.edu/slurm/sbatch/#gpu-jobs" '
    'target="_blank" rel="noopener noreferrer">1</a></span></span>'
)

# What Streamlit's `:gray[]` resolves to, per theme. Measured in the running app:
# `rgba(49, 51, 63, 0.6)` on white, `rgba(250, 250, 250, 0.6)` on its dark surface.
# Per theme and not hardcoded to one, because the app's rule is `color: inherit` and
# a marker modelled with the light grey on the dark page is a contrast reading of a
# thing that never renders — a pass this check has not earned.
COLORED_TEXT = {"light": "rgba(49, 51, 63, 0.6)", "dark": "rgba(250, 250, 250, 0.6)"}


def answer_block(index: int, question: bool = True) -> str:
    """One turn. `question=False` drops the bubble, for the screen where the reader
    has reopened it and an editor is standing in its place."""
    asked = """
<div class="element-container"><div class="stMarkdown"><div data-testid="stMarkdownContainer">
  <div class="user-message"><div class="user-bubble">How do I request a GPU for a
  batch job on Midway3, and what partition should I use?</div></div>
</div></div></div>
""" if question else ""
    # The progress block, folded, on a FINISHED answer. It used to die with the turn
    # that drew it; a stored message carries its steps now and
    # `transcript.render_steps` draws it again, above the text, where the live one
    # already was — so nothing moves when the turn ends. Rendered here because that
    # makes it part of every answer's geometry: it is inside the chat message, so the
    # answer's own top edge, the copy button's corner and the gap to the question above
    # are all measured with it present.
    return asked + f"""
<div class="st-key-answer-{index} element-container"><div class="stChatMessage">
 <div></div>
 <div class="stMarkdown"><div data-testid="stMarkdownContainer">
  {folded_block(2)}
  <h2>Requesting a GPU</h2>
  <p>Add <code>--gres=gpu:1</code> to your script and submit to the
  <code>gpu</code> partition.{MARKER}</p>
  <pre><code>#!/bin/bash
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --time=04:00:00
#SBATCH --mem=32G
module load cuda/11.8
python train.py --epochs 100 --batch-size 64 --output /scratch/midway3/$USER/run</code></pre>
 </div></div></div>
 {REFERENCES}
</div>"""


CHAT_MARKER = ('<div class="element-container"><div class="stMarkdown">'
               '<div data-testid="stMarkdownContainer">'
               '<div class="chat-container"></div></div></div></div>')


def editor_block() -> str:
    """A question reopened for editing, standing where its bubble stood.

    Modelled because the first version of it was not, and shipped as a full-bleed box
    at the left margin under a column of right-aligned questions — reported as the
    layout being "somewhat problematic". Nothing here could see it: the editor is a
    state the replica had no markup for, so every render was of the screen where it
    does not exist.

    `st.form` inside `st.container(key=...)`, which is what app.py builds, because the
    form is what carries Streamlit's own width behaviour and the container is what
    app.css hangs the rule on.
    """
    return (
        '<div data-testid="stVerticalBlock" '
        'class="stVerticalBlock st-key-edit-box-0">'
        '<div data-testid="stForm" class="stForm">'
        '<div class="element-container st-key-edit-text-1">'
        '<div class="stTextArea" data-testid="stTextArea">'
        '<div data-baseweb="textarea"><textarea rows="3">'
        "How do I request a GPU for a batch job on Midway3, and what partition "
        "should I use?</textarea></div></div></div>"
        '<div data-testid="stHorizontalBlock" class="stHorizontalBlock">'
        '<div data-testid="stColumn" class="stColumn" style="flex: 6"></div>'
        '<div data-testid="stColumn" class="stColumn" style="flex: 2">'
        '<div class="element-container st-key-FormSubmitter-edit-form-1-Send">'
        '<div class="stButton"><button kind="primaryFormSubmit"><p>Send</p>'
        "</button></div></div></div>"
        '<div data-testid="stColumn" class="stColumn" style="flex: 2">'
        '<div class="element-container st-key-FormSubmitter-edit-form-1-Cancel">'
        '<div class="stButton"><button kind="secondaryFormSubmit"><p>Cancel</p>'
        "</button></div></div></div>"
        "</div></div></div>"
    )

# An answer made of things that do not fit: a partition table with twelve columns,
# a generated anchor nobody would shorten, and a scratch path four levels deep.
#
# Modelled because none of it was, and the stylesheet had nothing to say about a
# table at all. Markdown tables size to their content, `html`/`body` here carry
# `overflow-x: hidden`, and the two together mean a wide table does not scroll and
# does not spill — it is simply cut off at the window edge with no way to reach the
# rest. Measured in the running app at a 500px viewport: a 946px table, 490px of it
# past the edge, on a page whose document could not be scrolled sideways by a pixel.
# Six of the RCC guide's own pages carry tables this wide.
WIDE_ANSWER = """
<div class="element-container"><div class="stMarkdown"><div data-testid="stMarkdownContainer">
  <div class="user-message"><div class="user-bubble">Which partition should I submit
  to?</div></div>
</div></div></div>
<div class="st-key-answer-0 element-container"><div class="stChatMessage">
 <div></div>
 <div class="stMarkdown"><div data-testid="stMarkdownContainer">
  <p>Every partition on Midway3, with the limits that decide which one you want:</p>
  <table>
   <thead><tr><th>Partition</th><th>Nodes</th><th>CPUs/node</th><th>Memory/node</th>
    <th>GPUs</th><th>Max walltime</th><th>QoS</th><th>Account</th><th>Notes</th>
    <th>Cost/SU</th><th>Shared</th><th>Preemptible</th></tr></thead>
   <tbody>
    <tr><td>caslake</td><td>168</td><td>48</td><td>192 GB</td><td>none</td>
     <td>36:00:00</td><td>normal</td><td>pi-yourpi</td><td>general purpose compute</td>
     <td>1.0</td><td>yes</td><td>no</td></tr>
    <tr><td>gpu</td><td>12</td><td>48</td><td>192 GB</td><td>4x V100</td>
     <td>36:00:00</td><td>gpu</td><td>pi-yourpi</td><td>CUDA workloads only</td>
     <td>2.5</td><td>yes</td><td>no</td></tr>
   </tbody>
  </table>
  <p>Full details in the
  <a href="#">https://docs.rcc.uchicago.edu/slurm/sbatch/#a-generated-anchor-nobody-would-shorten-for-you</a>
  section, and write your output to
  <code>/project2/someverylongprojectname/subdirectory/another/deeply/nested/run.tar.gz</code>.</p>
 </div></div></div>
 {sources}
</div>""".format(
    sources=references([("Partitions — Which partition should I use?", "docs")],
                       related=False)
)

# One question and a two-line reply: the shape that used to leave 121–566px of
# nothing between the answer and the input box, because the page was shorter than
# the window and there was no scroll left for app.js to close the gap with. The
# failover notice is on it because that is when a reader is looking at the bottom.
SHORT_ANSWER = f"""
<div class="element-container"><div class="stMarkdown"><div data-testid="stMarkdownContainer">
  <div class="user-message"><div class="user-bubble">How do I submit a batch job with
  sbatch?</div></div>
</div></div></div>
<div class="st-key-answer-0 element-container"><div class="stChatMessage">
 <div></div>
 <div class="stMarkdown"><div data-testid="stMarkdownContainer"><p>Submit it with <code>sbatch ./my_job.sbatch</code>, and the
 scheduler prints the job id it assigned.</p></div></div></div>
 {references([("Batch jobs — Submitting a job", "docs")],
             ["Checking job status in the terminal"])}
</div>
<div class="element-container"><div class="stMarkdown"><div data-testid="stMarkdownContainer">
  <div class="notice">The first model was unavailable (out of credit), so another
  answered. This turn took longer than usual.</div></div></div></div>"""

def landing(wrapped: bool = True) -> str:
    """The hero and the starter cards.

    The cards' container is rendered in the two shapes `st.container(key=…)` really
    produces — the key on a wrapper around the vertical block, or on the block itself.
    It used to be modelled as `.element-container`, which Streamlit never emits and
    which carries `width: 100%` in this replica: exactly the declaration the grid was
    missing. So the grid measured 780px here and collapsed to 585px in the app, with
    every card label wrapping to two lines, and no render could see it.
    """
    grid = _cards_html()
    if wrapped:
        cards = ('<div class="st-key-examples">'
                 f'<div data-testid="stVerticalBlock">{grid}</div></div>')
    else:
        cards = ('<div class="st-key-examples" data-testid="stVerticalBlock">'
                 f"{grid}</div>")
    return f"""
<div class="element-container"><div class="stMarkdown"><div data-testid="stMarkdownContainer">
  <div class="welcome">
    <h1 class="welcome-title">What can I help you with?</h1>
    <p class="welcome-subtitle">{SUBTITLE}</p>
  </div></div></div></div>
{cards}"""

def _check_balanced(scenarios: dict) -> None:
    """Every fixture must close every div it opens.

    One missing `</div>` in the mid-answer screen re-parented everything after it:
    Streamlit's bottom container was parsed *inside* the block that holds the
    conversation instead of beside it, so the in-flow bar landed mid-window with
    553px of empty page below it. Nothing failed — the checks that would have
    noticed only run in states that screen does not render — so the screen added to
    catch a bug was structurally unable to see it. A replica that is not the shape
    it claims to be is the one failure mode this harness cannot afford.
    """
    for name, body in scenarios.items():
        opened = len(re.findall(r"<div\b", body))
        closed = len(re.findall(r"</div\s*>", body))
        if opened != closed:
            raise SystemExit(
                f"render_check: the {name!r} fixture opens {opened} divs and closes "
                f"{closed}. Every render of it measures a DOM the app never has."
            )


# Which screens render the bar in the flow rather than fixed over the page. Split
# across the scenarios rather than doubling every render: both ways of pinning it
# are then audited at every width, in both themes, in every state. Whichever
# Streamlit is doing, one of these screens is looking at it.
STICKY_BAR = {"landing-flat", "answer", "long-chat", "attached-flat"}

# Which screens put the scrollbar on the document rather than on stMain. Kept to
# one screen for the same reason as above: it costs a screen, not a doubling, and
# every state and width still passes through the shape.
DOC_SCROLL = {"doc-scroll"}

# Which screens render the model picker's panel open, and in which of the two shapes
# Streamlit has portalled it into. One screen each: the panel does not change with the
# conversation, so states and widths are what matter, not the page behind it.

# What each screen has waiting in the queue app.js keeps on the parent window. Only
# one screen has anything: a queue exists only while an answer is arriving, and what is
# under test is the row it draws at the end of the page.
QUEUED = {
    "queued": (
        "and once it is running, how do I check whether it is still going?",
        "second one, queued behind the first",
    ),
}

# Which screens render the input with something in it rather than on its placeholder.
TYPED_INPUT = {"composing", "composing-column"}
# …and which of those stack the send button under the textarea rather than beside it.
COLUMN_INPUT = {"composing-column"}

# What was actually pasted in when the dead space got reported: a dictionary entry,
# several lines of it, in two scripts. Long enough to grow the box past one line at
# every width, which is the condition the bug needs.
TYPED = (
    "spurt — a sudden short burst of liquid, speed or activity — My son had a "
    "growth spurt over the summer. 喷出；一阵突发的活动或速度 — and a second line so "
    "the box is unambiguously taller than one row at every width this renders."
)

def step_row(name: str, argument: str, seconds: str) -> str:
    """One finished step, as `sage.ui.turn._done_html` writes it."""
    return (
        '<div class="status-step">'
        '<span class="status-mark" aria-hidden="true">✓</span>'
        f'<span class="status-name">{name}</span>'
        f'<span class="status-arg">{argument}</span>'
        f'<span class="status-time">{seconds}</span>'
        "</div>"
    )


def live_row(name: str = "", argument: str = "") -> str:
    """The step that is running — or, with no name, the row a turn opens on.

    That second form is what this file rendered before there were steps, down to the
    byte, because that frame of a turn did not change. The live step differs from it in
    two ways and both are deliberate: the argument is a sibling of `.status-text`
    rather than inside it (the text is a gradient clipped to its own glyphs, so a child
    of it is invisible), and the live line carries no `role`, because the block around
    it is the one live region.
    """
    role = ' role="status" aria-live="polite"' if not name else ""
    return (
        f'<div class="status-row"{role}>'
        '<span class="status-dot" aria-hidden="true"></span>'
        f'<span class="status-text">{name or STATUS_LABEL}</span>'
        + (f'<span class="status-arg">{argument}</span>' if argument else "")
        + '<span class="status-dots" aria-hidden="true"><span></span><span></span>'
        "<span></span></span></div>"
    )


def step_block(*, live: str, steps: int = 6) -> str:
    """The block mid-turn: every step that has finished, and the live line under them.

    Six, because that is the tallest the block gets on a real turn — the default
    `config.MAX_TOOL_ROUNDS` is 4 and a single round may call more than one tool — and
    the whole question about a block that grows a line at a time is whether the page
    still has room for the line after it.
    """
    rows = [
        step_row(STEP_NAMES[index % 2],
                 STEP_WIDEST if index == 0 else STEP_PATH,
                 f"{index / 3 + 0.4:.1f}s")
        for index in range(steps)
    ]
    return (
        '<div class="status-block" role="status" aria-live="polite">'
        + "".join(rows) + live + "</div>"
    )


def folded_block(steps: int = 3) -> str:
    """The line the block becomes when the answer starts, opened again.

    Rendered OPEN, and that is the point of rendering it at all: closed, the browser
    skips its contents, every step inside is a box with no layout behind it, and a
    check on those boxes passes without having looked at anything. Open is also the
    state a reader has to be able to use — it is what the summary line is for.
    """
    rows = [
        step_row(STEP_NAMES[index % 2], STEP_PATH, f"{index / 2 + 0.3:.1f}s")
        for index in range(steps)
    ]
    return (
        '<details class="status-done" open>'
        f'<summary class="status-summary">{steps} steps · 12.4s</summary>'
        '<div class="status-block">' + "".join(rows) + "</div>"
        "</details>"
    )


def in_flight(body: str) -> str:
    """A question, and whatever the assistant has put under it so far.

    What is actually on screen while an answer is being generated. The other screens
    render a *finished* answer with the processing marker set, which is a much taller
    page — so the slack app.js puts above a short conversation stayed small there and
    the check below had nothing to catch. On this screen it is the whole page, which is
    how the question ended up halfway down the window with the answer arriving
    underneath it.
    """
    return f"""
<div class="element-container"><div class="stMarkdown"><div data-testid="stMarkdownContainer">
  <div class="user-message"><div class="user-bubble">How do I connect to Midway via
  SSH?</div></div>
</div></div></div>
<div class="element-container"><div class="stChatMessage">
 <div></div>
 <div class="stMarkdown"><div data-testid="stMarkdownContainer">
  {body}
 </div></div></div></div>"""


# The answer, while it is still arriving. Its own chat message under the block rather
# than inside it, which is the shape the app draws: the block is written into a slot
# taken before the answer's container exists, so they are siblings, and the gap
# between them is the one the reader watches the first words appear in.
STREAMING_ANSWER = """
<div class="st-key-live-answer-1 element-container"><div class="stChatMessage">
 <div></div>
 <div class="stMarkdown"><div data-testid="stMarkdownContainer">
  <p>You reach Midway over SSH from a terminal, and which host you use depends on
  the cluster your account is on.</p>
 </div></div></div></div>"""

IN_FLIGHT = in_flight(live_row())
# The same screen once the turn has done something: six finished steps, each naming a
# tool and what it was given, and the live line under them. This is the one that grows
# — 22px a step, measured — so it is where "does the newest thing on the page still
# clear the composer" is asked of a block rather than of an answer.
IN_FLIGHT_STEPS = in_flight(step_block(live=live_row(STEP_NAMES[1], STEP_PATH)))
# And once the answer has started: the block is one summary line, with the steps behind
# a disclosure the reader can open — during the turn, because it is the browser's own
# control and a Streamlit one would be a rerun, and a rerun mid-turn aborts the answer.
IN_FLIGHT_FOLDED = in_flight(folded_block()) + STREAMING_ANSWER

# The strip's container shape alternates across the screens, so both shapes are
# audited at every width, in both themes, in every state.
SCENARIOS = {
    "landing": landing(wrapped=True) + strip(clear=False, wrapped=True),
    "landing-flat": landing(wrapped=False) + strip(clear=False, wrapped=False),
    "answer": CHAT_MARKER + answer_block(0) + strip(wrapped=False),
    # The same conversation with its question reopened for editing. The one screen
    # where a question is not a bubble, and the one the replica could not draw when
    # the editor first shipped at the wrong side of the page.
    "editing": CHAT_MARKER + editor_block() + answer_block(0, question=False)
    + strip(wrapped=False),
    "short-answer": CHAT_MARKER + SHORT_ANSWER + strip(),
    "long-chat": CHAT_MARKER
    + "".join(answer_block(i) for i in range(6))
    + strip(wrapped=False),
    # The same long conversation with the scrollbar on the document instead of on
    # stMain (see DOC_SCROLL). Only one thing differs, and it is the thing that
    # decides whether app.js thinks this page has room to spare.
    "doc-scroll": CHAT_MARKER
    + "".join(answer_block(i) for i in range(6))
    + strip(wrapped=False),
    # A conversation with a half-written question still in the box. The only screen
    # where the input is not one line tall, and so the only one that can see what the
    # send button does to the height of the box it sits in.
    "composing": CHAT_MARKER + SHORT_ANSWER + strip(),
    # The same half-written question with the send button stacked under the text. This
    # is the shape the dead space appears in; the one above is the shape it does not.
    "composing-column": CHAT_MARKER + SHORT_ANSWER + strip(),
    # A conversation with files attached but not yet sent. The chips are `fixed` above
    # the input, and the page has to reserve room for them or they land on the newest
    # answer — which nothing here could have caught, because nothing here had a chip.
    "attached": CHAT_MARKER + SHORT_ANSWER + chips() + strip(),
    "attached-flat": CHAT_MARKER + SHORT_ANSWER + chips(wrapped=False) + strip(),
    # The picker, open. The page behind it is an ordinary answer; what is under test
    # is the panel, which lives outside every container this stylesheet reaches.
    # The pill switched on. Its own screen rather than another state on an
    # existing one, because what it is for is the filled variant: white on
    # `--brand`, which is the one contrast pair in this band that can fail,
    # and a 10px-wider box than the outlined version once the fill lands.
    "think-on": CHAT_MARKER + SHORT_ANSWER + strip(pressed=True),
    "in-flight": CHAT_MARKER + IN_FLIGHT + strip(wrapped=False),
    # The same turn, once it has done something. Three finished turns behind it for the
    # reason the `queued` screen has them: the bound that matters here — the newest
    # thing on the page is under the composer — can only fire on a page long enough to
    # scroll, and a question with six status lines under it does not fill a window.
    "in-flight-steps": CHAT_MARKER
    + "".join(answer_block(i) for i in range(3))
    + IN_FLIGHT_STEPS + strip(wrapped=False),
    # And once the answer has started arriving: one summary line where the block was,
    # opened again, with the answer underneath it.
    "in-flight-folded": CHAT_MARKER
    + "".join(answer_block(i) for i in range(3))
    + IN_FLIGHT_FOLDED + strip(wrapped=False),
    # The same mid-turn screen with the reader's next question waiting behind it. Its
    # body is the in-flight one: what is added is not markup but the state app.js
    # holds a queue in, so the row measured here is the row `renderQueue` builds. It
    # stands at the very end of the page, which is the one place a new element can
    # hide under the composer — the failure this harness exists for, and the reason
    # `.queued-note` is on the list of things `newest` can be.
    #
    # Two of them, because a second queued question adds a row and the pair is what
    # says whether the block grows the way the page reserves for.
    # Three finished turns behind it on purpose, not the bare in-flight screen: the
    # bound that matters here — `newest` is under the composer — can only fire on a
    # page long enough to scroll, and a question and a status row do not fill a
    # window. On a short page the row sits mid-screen and every check passes without
    # ever looking at the thing the screen was added for.
    "queued": CHAT_MARKER
    + "".join(answer_block(i) for i in range(3))
    + IN_FLIGHT + strip(wrapped=False),
    # An answer whose content is wider than the column it is drawn in.
    "wide-answer": CHAT_MARKER + WIDE_ANSWER + strip(),
    "error": CHAT_MARKER
    + """
<div class="element-container"><div class="stMarkdown"><div data-testid="stMarkdownContainer">
  <div class="user-message"><div class="user-bubble">How do I run PyTorch on GPUs?</div></div>
</div></div></div>
<div class="element-container"><div class="stMarkdown"><div data-testid="stMarkdownContainer">
  <div class="error-card" role="alert">
    <div class="error-title">Could not complete that request</div>
    <div class="error-body">This model is out of credit or its quota is used up.
      Switch to another model and try again.</div>
  </div></div></div></div>
<div class="st-key-error-actions element-container">
 <div data-testid="stHorizontalBlock">
  <div data-testid="stColumn"><div class="st-key-retry element-container">
    <div class="stButton"><button><p>↻ Try again</p></button></div></div></div>
  <div data-testid="stColumn"><div class="st-key-switch-model element-container">
    <div class="stButton"><button><p>→ Use deepseek-v4-flash-free</p></button></div></div></div>
 </div></div>"""
    + strip(),
}

# Elements every scenario should keep clear of the chrome, and their line budgets.
_check_balanced(SCENARIOS)

LINE_LIMITS = {
    ".welcome-subtitle": 1,
    # Two lines is fine for an error action; three means the label no longer fits
    # its column and should be shortened rather than allowed to sprawl.
    ".st-key-retry button p": 1, ".st-key-switch-model button p": 2,
    # NB: the loop below gates these on width >= 641, because at phone widths nearly
    # everything wraps and a limit there would be noise. Anything that must hold at a
    # phone width belongs in NARROW_LINE_LIMITS instead, where the gate does not
    # apply — a budget listed only here is silently unenforced below 641px.
    **{f".st-key-example-card-{i} button p": 1 for i in range(6)},
}

# Line budgets that apply BELOW 641px too, where the general gate does not. Empty
# since the caveat line — the one element that had to hold at a phone width — was
# removed from under the input.
NARROW_LINE_LIMITS: dict[str, int] = {
    # The status line, at a phone width too — this is the one place the general gate
    # would be wrong to let go. It is a progress cue over an empty answer, so a second
    # row is the page growing under a reader who is waiting and has nothing else to
    # look at. The phrases it can hold are fixed, and `Copy.status_phrases` is the set.
    ".status-text": 1,
    # And every step under it, which is where the same requirement got harder: the
    # argument on a step is a query or a path the MODEL chose, at up to
    # `config.STATUS_ARGUMENT_CHARS`, and six of them can be on the page at once. A
    # step that wraps costs a line each, at the moment a reader is waiting and watching
    # — so the width is held by an ellipsis (`.status-arg` in app.css) and this is the
    # check that the ellipsis is doing it. Both ends of the column: the first row
    # carries the widest argument the app can produce and the last is the one nearest
    # the composer.
    ".status-step": 1,
    "last:.status-step": 1,
    ".status-arg": 1,
    "last:.status-arg": 1,
    # The line the whole block folds into. Two words and a number; a second line here
    # means something has gone wrong with the disclosure marker.
    ".status-summary": 1,
}

MEASURE = """
<script>
function parts(c) {
  var m = (c || '').match(/[\\d.]+/g);
  if (!m || m.length < 3) return null;
  return [+m[0], +m[1], +m[2], m.length > 3 ? +m[3] : 1];
}
function over(fg, bg) {           // composite a translucent layer onto an opaque one
  var a = fg[3];
  return [fg[0] * a + bg[0] * (1 - a), fg[1] * a + bg[1] * (1 - a),
          fg[2] * a + bg[2] * (1 - a), 1];
}
function ratio(fgRaw, bgRaw) {
  var b = parts(bgRaw) || [255, 255, 255, 1];
  var f = parts(fgRaw) || [0, 0, 0, 1];
  if (f[3] < 1) f = over(f, b);   // translucent text must be composited first
  function lum(v3) {
    var m = v3.slice(0, 3).map(function (v) {
      v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2];
  }
  var x = lum(f), y = lum(b);
  return Math.round(((Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)) * 100) / 100;
}
// Effective background: composite every translucent layer up the tree. A flat
// backgroundColor read misses gradients entirely, which made the maroon user
// bubble measure as white-on-white (1:1).
function solidBg(el) {
  var stack = [];
  for (var n = el; n; n = n.parentElement) {
    var cs = getComputedStyle(n);
    var img = cs.backgroundImage || '';
    if (img.indexOf('gradient') !== -1) {
      var g = img.match(/rgba?\\([^)]*\\)/);
      if (g) { stack.push(parts(g[0])); break; }
    }
    var c = parts(cs.backgroundColor);
    if (c && c[3] > 0) { stack.push(c); if (c[3] === 1) break; }
  }
  var base = parts(getComputedStyle(document.body).backgroundColor) || [255,255,255,1];
  if (!stack.length || stack[stack.length - 1][3] < 1) stack.push(base);
  var out = stack.pop();
  while (stack.length) out = over(stack.pop(), out);
  return 'rgb(' + Math.round(out[0]) + ',' + Math.round(out[1]) + ',' + Math.round(out[2]) + ')';
}
function box(sel) {
  var el;
  if (sel.indexOf('last:') === 0) {
    var all = document.querySelectorAll(sel.slice(5));
    el = all.length ? all[all.length - 1] : null;
  } else {
    el = document.querySelector(sel);
  }
  if (!el) return null;
  var r = el.getBoundingClientRect(), cs = getComputedStyle(el);
  var lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.2;
  return {
    top: Math.round(r.top), bottom: Math.round(r.bottom),
    left: Math.round(r.left), right: Math.round(r.right),
    lines: Math.max(1, Math.round(r.height / lh)),
    fontPx: Math.round(parseFloat(cs.fontSize) * 10) / 10,
    // The face this element is actually set in — the first family of the stack,
    // which is the one the browser will use now that it is loaded. Recorded because
    // nothing else here can see a typeface: a page in the wrong font passes every
    // bound in this file, and the one that shipped (every model name in the open
    // picker in the sans face) was found by looking at the running app.
    family: (cs.fontFamily || '').split(',')[0].replace(/["']/g, '').trim(),
    overflowX: el.scrollWidth - el.clientWidth,
    contrast: ratio(cs.color, solidBg(el)),
    hit: hitTest(el, r)
  };
}
// Is this element the thing a user's click would actually land on? Geometry
// alone cannot tell you: the top bar had a perfectly good rectangle for 100
// renders while sitting underneath Streamlit's full-width header, which is
// transparent (so it looked fine) and on top (so it took every click).
// '' means yes; anything else names what is in the way.
function hitTest(el, r) {
  if (r.width < 1 || r.height < 1) return 'zero-sized';
  var x = r.left + r.width / 2, y = r.top + r.height / 2;
  if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return 'offscreen';
  var top = document.elementFromPoint(x, y);
  if (!top) return 'nothing painted there';
  if (el.contains(top) || top.contains(el)) return '';
  return (top.getAttribute('data-testid') || top.id ||
          top.className || top.tagName || 'something').toString().slice(0, 60);
}
// Whichever element actually scrolls, not whichever one usually does. This
// replica gave `[data-testid="stMain"]` `overflow: auto` from the day it was
// written, and every measurement below took that for granted; the app has a
// shape where the document scrolls and stMain reports no overflow at all, and
// asking the element that is not the scrollport whether the page scrolls is
// what put a screenful of slack above a conversation that already scrolled.
// Falls back to stMain so a page with nowhere to scroll still measures.
function scrollport() {
  var el = document.querySelector('[data-testid="stMain"]');
  var candidates = [el, document.scrollingElement, document.documentElement];
  for (var i = 0; i < candidates.length; i++) {
    var c = candidates[i];
    if (c && c.scrollHeight > c.clientHeight + 1) return c;
  }
  return el;
}
var main = scrollport();
if (window.__scrollBottom && main) main.scrollTop = main.scrollHeight;
// Leave the view where app.js's per-turn pin would have left it, so the settle
// that runs once the answer lands has something to actually close.
if (window.__pinLast && main) {
  var asked = document.querySelectorAll('.user-message');
  var lastAsked = asked[asked.length - 1];
  if (lastAsked) main.scrollTop = Math.max(0, Math.min(
    lastAsked.getBoundingClientRect().top + main.scrollTop - TOPGAP,
    main.scrollHeight - main.clientHeight));
}
function snapshot() {
  // The two custom properties app.js publishes. Reported so a failed gap check
  // says whether the reservation was measured or still on the CSS fallback —
  // "2px under the input bar" with no numbers took a while to place.
  var root = getComputedStyle(document.documentElement);
  // Re-resolved rather than reused from the pin above: app.js has run by now, and
  // the slack it added can be what made something start scrolling.
  var port = scrollport();
  // The popover panel's own background. Reported as a colour rather than folded into
  // the contrast numbers because the failure was not unreadable text — it was a white
  // slab on a dark page, which contrasts beautifully and looks awful.
  // Where the text cursor sits relative to the paperclip. Two paddings stack to
  // produce it — the box insets the textarea past the clip, then the textarea insets
  // its own text — so neither rectangle on its own says how far apart they look.
  var clipEl = document.getElementById('paperclip-btn');
  var areaEl = document.querySelector('.stChatInput textarea');
  var cursorGap = (clipEl && areaEl) ? Math.round(
      areaEl.getBoundingClientRect().left
      + parseFloat(getComputedStyle(areaEl).paddingLeft)
      - clipEl.getBoundingClientRect().right) : null;
  // The other half of "same row": how far the clip sits below the line of text it is
  // beside. Measured against the first line's middle rather than the textarea's,
  // because the textarea grows downwards and its own middle walks away from the text
  // the clip is level with. Positive means the clip hangs low.
  var sendEl = document.querySelector(SEND_SELECTOR);
  function riseOf(el) {
    if (!el || !areaEl) return null;
    var area = areaEl.getBoundingClientRect();
    var style = getComputedStyle(areaEl);
    var firstLine = area.top + parseFloat(style.paddingTop)
                    + parseFloat(style.lineHeight) / 2;
    var box = el.getBoundingClientRect();
    return Math.round(box.top + box.height / 2 - firstLine);
  }
  var clipDrop = riseOf(clipEl);
  var sendDrop = riseOf(sendEl);
  // Empty room inside the model picker's trigger, past the name and the chevron. The
  // button is a fixed width so that picking a model cannot resize it, and the whole
  // question about that width is whether it is the name's width or an arbitrary one.
  // The status line's shimmer, at both ends of its sweep. `box()` below reports the
  // contrast of `cs.color`, and for this one element that is a lie: the fill is
  // transparent and what a reader sees is the gradient clipped to the glyphs, so the
  // colour the check would read is the fallback nobody is looking at. Every stop is
  // pulled out of the gradient instead and measured against what is behind the text —
  // the worst of them is the moment the highlight is over the word.
  // Where the answer stops and its references start, and where Sources stops and
  // Related starts. Two gaps rather than one because they are a hierarchy: the strips
  // are one block, set apart from the prose, and Related is the second half of that
  // block rather than a third section of the page. Measured off the last thing the
  // answer actually drew — a paragraph on one screen, a code block or a table on
  // another — because the margins that produce the gap are collapsing against
  // whatever that is, not against a container.
  var refs = document.querySelector('.sources:not(.related)');
  var refsRel = refs && refs.parentElement
      ? refs.parentElement.querySelector('.sources.related') : null;
  // The last thing the answer drew BEFORE this strip, not the last on the page: a
  // conversation has several answers, and pairing the first Sources with the final
  // paragraph of the last reply measured most of the page as a gap.
  var prose = [].slice.call(document.querySelectorAll(
      '.stChatMessage p, .stChatMessage pre, .stChatMessage table, .stChatMessage h2'))
      .filter(function (el) {
        return refs && (el.compareDocumentPosition(refs)
                        & Node.DOCUMENT_POSITION_FOLLOWING);
      });
  var lastProse = prose.length ? prose[prose.length - 1] : null;
  var answerToRefs = (refs && lastProse) ? Math.round(
      refs.getBoundingClientRect().top - lastProse.getBoundingClientRect().bottom)
      : null;
  var refsToRelated = (refs && refsRel) ? Math.round(
      refsRel.getBoundingClientRect().top - refs.getBoundingClientRect().bottom)
      : null;
  // How far the last strip hangs out of the bottom of the answer holding it. Should be
  // nothing: a child outside its parent's box is content the page cannot account for,
  // and the last time this was 16px it made a window-sized page report itself as
  // scrollable, which is the one question `fill()` asks before deciding a short
  // conversation has no slack to take.
  var refsOwner = refs ? refs.closest('[class*="st-key-answer-"]') : null;
  var lastStrip = refsRel || refs;
  var refsOverhang = (refsOwner && lastStrip) ? Math.round(
      lastStrip.getBoundingClientRect().bottom
      - refsOwner.getBoundingClientRect().bottom) : null;
  var statusEl = document.querySelector('.status-text');
  var statusStops = null;
  if (statusEl) {
    var image = getComputedStyle(statusEl).backgroundImage || '';
    var behind = solidBg(statusEl.parentElement || document.body);
    var found = image.match(/rgba?\\([^)]*\\)/g) || [];
    statusStops = found.map(function (stop) { return ratio(stop, behind); });
  }
  // EVERY row of a list, not just the first. `box()` below resolves one element per
  // selector, which is why no check here could express "do the wrapped rows line up"
  // — the ragged Sources strip was measured in a scratch probe and shipped for months
  // with a green harness. The marker comes back too, so "are these two lists visually
  // different?" is answerable without asserting on a colour this file also chose.
  function rows(selector) {
    return [].slice.call(document.querySelectorAll(selector)).map(function (el) {
      var b = el.getBoundingClientRect();
      var marker = getComputedStyle(el, '::before').content || '';
      return {left: Math.round(b.left), top: Math.round(b.top),
              right: Math.round(b.right), marker: marker};
    });
  }
  var out = {viewport: {w: innerWidth, h: innerHeight}, hostBar: HOSTBAR,
           lists: {'.source-item': rows('.source-item'),
                   '.related-item': rows('.related-item')},
           cursorGap: cursorGap,
           clipDrop: clipDrop, sendDrop: sendDrop,
           statusStops: statusStops,
           answerToRefs: answerToRefs, refsToRelated: refsToRelated,
           refsOverhang: refsOverhang,
           scrolled: port ? Math.round(port.scrollTop) : 0,
           // Whether there is anywhere to scroll to. A conversation shorter than
           // the window sits at the bottom of the space reserved for it, so if
           // that reservation is wrong it lands under the input with no scroll
           // available to reveal it.
           canScroll: !!port && port.scrollHeight - port.clientHeight > 1,
           // Whether it would scroll with the slack taken back out. app.js only
           // adds slack to a page too short to fill the window, so asking
           // "does it scroll?" of the padded page answers a question the padding
           // itself decides: enough slack makes any page scrollable, and the
           // check that reads it then fires on every page it succeeded on.
           canScrollUnfilled: !!port
             && port.scrollHeight - port.clientHeight
                - (parseFloat(root.getPropertyValue('--fill')) || 0) > 1,
           // How much scroll is left below this position. Reported as the
           // distance rather than as "is it at the end", because what the bound
           // below it needs is not whether the page can move but whether it can
           // move FAR ENOUGH: mid-turn app.js stops the view one `--tail-gap`
           // above the composer, and the document reserves the bar's height plus
           // that gap below the last message — so the view settles short of the
           // end rather than on it, by an amount that moves with every line the
           // page grows. Measured at 0, 18, 23 and 30px inside one six-step turn.
           scrollRoom: !port ? 0
             : Math.max(0, Math.round(port.scrollHeight - port.clientHeight
                                      - port.scrollTop)),
           docOverflowX: Math.max(0, document.documentElement.scrollWidth - innerWidth),
           reserved: {bar: root.getPropertyValue('--bar-h').trim(),
                      // The bar alone, which is what the chips are anchored to. Named
                      // separately because a failure where the two disagree is a
                      // different bug from either of them being wrong.
                      band: root.getPropertyValue('--bar-band').trim(),
                      pickRight: root.getPropertyValue('--pick-right').trim(),
                      fill: root.getPropertyValue('--fill').trim()},
           // Did the app's own faces actually arrive? Every width, wrap and overlap
           // bound below is a measurement of a string, and a string measured in
           // whatever sans the machine happens to have is a number about a page
           // nobody sees. The failure is silent by nature — the text renders, in the
           // wrong face — so it is reported per render rather than assumed.
           fonts: (function () {
             var probes = FONTPROBES, got = {status: document.fonts.status};
             Object.keys(probes).forEach(function (k) {
               got[k] = document.fonts.check('400 16px "' + probes[k] + '"');
             });
             return got;
           })(),
           els: {}};
  SELECTORS.forEach(function (s) { out.els[s] = box(s); });
  document.title = JSON.stringify(out);
}
// Give app.js's requestAnimationFrame + interval work time to settle.
setTimeout(snapshot, 700);
</script>
"""

# The Think pill. Named because three checks below treat it specially: collapsed
# width, whether it is inside the strip pinned for it, and reachability. It kept the
# name `PICKER` from the model picker that stood in this corner before it, for the
# same reason `.st-key-composer-strip` and `--pick-right` kept theirs — the selector
# table, the checks and the fixture would all have to move to say nothing new.
PICKER = '.st-key-composer-strip button'
# The strip the controls sit in, and the input it must never cover.
STRIP = ".st-key-composer-strip"
INPUT = ".stChatInput textarea"
# The bordered box around the textarea, and the button that sends. Both measured so
# the space between the end of the text and the bottom of the box can be: in the flow
# the button takes a row of its own once the text passes one line, and that row is a
# band of nothing under what was typed.
INPUT_BOX = ".stChatInput > div"
SEND = '.stChatInput button:not(#paperclip-btn):not(#stop-btn)'
# The square app.js puts in the send button's corner while an answer generates, and
# the pencil it puts in the gutter beside each question. Both are injected rather
# than rendered by Streamlit, both are the only way to reach a thing the app can now
# do, and neither is visible to anything else in this file — so both are measured:
# a control that lands in the wrong place is a feature that shipped broken.
STOP = "#stop-btn"
EDIT = ".user-edit-btn"
# The copy button beside a question, in the same gutter as the pencil. Unlike the
# pencil it stays available mid-answer — copying costs no turn — so it is the one of
# the pair that must fit alongside the other without either reaching the bubble.
QCOPY = ".user-copy-btn"
# The box a reopened question is edited in, and the row of buttons under it. Measured
# because the first version was a full-bleed box at the left margin under a column of
# right-aligned questions, and nothing here could see it: the replica had no markup
# for the one screen where a question is not a bubble.
EDITOR = '[class*="st-key-edit-box-"]'
# The attachment chips. `fixed` above the input, so they are part of the composer's
# footprint: whatever the page reserves at its end has to cover them too.
CHIPS = ".st-key-attachments"
THEME_TOGGLE = "#theme-toggle"
# The block holding whatever the reader sent while an answer was still arriving. Named
# because it is measured as the end of the conversation as well as measured in itself.
QUEUED_NOTE = ".queued-note"
# What app.js parks in a finished answer's top-right corner, and the prose it is
# parked on top of. Absolutely positioned inside the message, so the corner it sits
# in is a corner the text also uses unless the message reserves it — measured in the
# running app, the button covered the last 30px of every answer's first line.
ANSWER_COPY = '[class*="st-key-answer-"] .rcc-copy-btn'
# A paragraph, not the container: a block fills the content box, so its right edge
# is where a line of the answer is allowed to end.
ANSWER_TEXT = '[class*="st-key-answer-"] .stChatMessage p'
ANSWER_TABLE = '[class*="st-key-answer-"] table'
# The inline citation marker. Measured like any other text, because it is: 14px, in
# the flow of a paragraph, and dim by design — which is the combination that goes
# under AA without anyone noticing. Streamlit's own `:gray[]` renders it at 3.69:1 on
# white, so `app.css` overrides the anchor with `--text-muted` and this is what holds
# that override to the same bar as everything else a reader has to read.
ANSWER_MARKER = '[class*="st-key-answer-"] .stMarkdownColoredText a'

SELECTORS = [
    ".welcome-title", ".welcome-subtitle", ".user-bubble", "last:.user-bubble",
    ".error-card", ".notice", ".st-key-error-actions",
    ".error-title", ".error-body", ".sources-label",
    ".source-link", ".related-link", ".source-item", "last:.source-item",
    ".source-kind",
    ".st-key-answer-5", ".st-key-answer-0", ".stChatMessage pre",
    ".stChatMessage code", '[data-testid="stBottomBlockContainer"]',
    ANSWER_COPY, ANSWER_TEXT, ANSWER_TABLE, ANSWER_MARKER,
    STRIP, INPUT, INPUT_BOX, SEND, STOP, EDIT, "last:" + EDIT, QCOPY, EDITOR,
    CHIPS, ".st-key-attachments button", "#paperclip-btn",
    # A question waiting its turn: the block, the bubble, its label and the ✕ that
    # takes it back. All four, because the row is built by app.js rather than by a
    # stylesheet rule anybody reads, and a piece of it going missing would show up
    # here as a selector nothing rendered.
    QUEUED_NOTE, ".queued-bubble", ".queued-label", ".queued-drop",
    ".status-text",
    # A step on the progress block, and the machine data on it. Both ends of the
    # column, because the block grows downwards and the last line is the one with the
    # composer under it. `.status-arg` is measured for its own sake: it is the only
    # element on the block allowed to be narrower than its content, and the check that
    # it ellipses rather than wraps is the line budget below.
    ".status-step", "last:.status-step", ".status-arg", "last:.status-arg",
    ".status-summary",
    # The theme toggle, which lives in the one band of this page that has already
    # killed a control: Streamlit's header takes every click aimed at anything
    # underneath it, and the fix is a z-index that outranks the chrome. Measured AND
    # hit-tested, because "on screen" and "clickable" came apart there once before.
    THEME_TOGGLE, '[data-testid="stExpandSidebarButton"]', "#host-bar",
    ".st-key-composer-strip button",
    # The rightmost control in the strip, so the row is measured end to end: with
    # a model name in it, it is the widest thing under the input.
    "last:.st-key-composer-strip button",
    PICKER,
    # The error card's actions. The switch one carries a whole model name, so it
    # is the widest button in the app and the first thing to overflow at 360px.
    ".st-key-retry button p", ".st-key-switch-model button p",
] + [f".st-key-example-card-{i} button p" for i in range(6)]

# Controls a user has to be able to click. For these, occupying a sensible
# rectangle is not enough — something else must not be on top of them. The input
# is on the list because the strip of controls is pinned in a band the bar above
# it reserves: if the two measurements ever disagree, the strip lands on the
# textarea, and "the box will not take a click" is the worst bug in the app.
INTERACTIVE = {
    PICKER, ".st-key-composer-strip button", "last:.st-key-composer-strip button", INPUT,
    SEND, STOP, THEME_TOGGLE,
    # The ✕ on a queued question. It is the only way to take one back, so a queue with
    # it painted over or under the composer is a queue that sends the question the
    # reader decided against.
    ".queued-drop",
    ".st-key-retry button p", ".st-key-switch-model button p",
    *(f".st-key-example-card-{i} button p" for i in range(6)),
}

# The picker ellipses a long model id on purpose, and it is now both the first
# button in the row on the landing screen (no Clear to precede it) and the last one
# everywhere, since the row is right-aligned and it belongs in the corner. So all
# three selectors that can reach it are exempt from the overflow check; the emoji
# button they also reach has nothing to ellipse.
ELLIPSIS_OK = {PICKER, ".st-key-composer-strip button", "last:.st-key-composer-strip button",
               # A query or a path too long for the window is ellipsed on purpose, and
               # an ellipsed line reports scrollWidth past clientWidth — that reading
               # IS the feature working. What must not overflow is the row holding it,
               # which is `.status-step`, and that is not on this list.
               ".status-arg", "last:.status-arg"}

# Text painted as a gradient clipped to the glyphs. `getComputedStyle().color` on these
# is the fallback a browser without `background-clip: text` would use, not the colour a
# reader sees, so the generic contrast check would be reading the wrong number — pass
# or fail. The status line is measured properly instead, stop by stop, further down.
CLIPPED_TEXT = {".welcome-title", ".status-text"}

# Elements whose own horizontal overflow is the fix rather than the bug. A table too
# wide for the answer column has to scroll *somewhere*; the alternative — the one the
# `wide-answer` screen was added to catch — is content clipped at the window edge that
# no gesture can reach, because app.css hides the document's horizontal overflow.
SCROLLS_OK = {ANSWER_TABLE, EDITOR}

# How far apart things should be, in px. Both ends matter: the first of these was
# reported twice as "barely any spacing between the user and AI messages", at a
# measured 19–25px; the second as "such a big empty space" between the end of an
# answer and the input box, at a measured 121–566px.
GAP_QUESTION_TO_ANSWER = (30, 60)
# Only an upper bound: a reply taller than the window runs off the bottom, and
# that is the reader's to scroll, not dead space.
MAX_TAIL_GAP = 64
# Room allowed between the last line of text in the input and the bottom of the box.
# Measured from the textarea's edge, so its own 16px of bottom padding is already
# inside that edge and does not count; what does is the box's 12px of padding and 2px
# of border under it, plus rounding — anything more is a row of furniture, which is
# what the send button was taking once the text grew past one line.
#
# Was 20, from a replica that gave the box no vertical padding at all. Every shape
# measured 12px under the truth, so this is the same margin over a healthy box (22px
# in the worst shape) and the same catch on the 46px the send button took.
# The band of controls under the text, measured from the bottom of the textarea to the
# bottom of the box. `--composer-band` is 46px and the textarea has 4px of padding below
# its last line, so the drawn figure is around 50; the window either side is for the
# rounding Streamlit's own wrappers introduce at different widths.
MIN_CONTROL_BAND = 38
MAX_CONTROL_BAND = 64
# How far out of line with each other the three controls in that band may be, measured
# on their bottom edges. They are pinned to the same offset, so anything here is a
# control that has been given a different size rather than a different position.
MAX_BAND_SPREAD = 8
MAX_INPUT_DEAD_SPACE = 32
# Room allowed between the attachment chips and the top of the input box. They are
# pinned 0.35rem above it; this is that plus the bar's own top padding and rounding.
# Rendered in the flow instead, they were most of a page away.
MAX_CHIP_GAP = 40
# How far the text cursor may sit from the paperclip beside it. The clip is inset 12px
# from the edge of the box; the cursor matching that reads as one row.
MAX_CURSOR_GAP = 16
# And how far off that row either composer button may sit vertically. Reported from
# the running app: the clip was 15px below the line of text it is beside, which is
# most of a line — it read as hanging under the sentence rather than starting it.
# Both buttons were pinned 10px off the floor of a box that centres one line of text
# 15px higher up, so the offset was measuring from the wrong edge. Half a line is the
# most that can pass for level.
MAX_BUTTON_DROP = 6
# Empty room allowed inside the model picker's trigger, past the name and the chevron.
# The button is a fixed width, so this is the difference between a width chosen for the
# name and one chosen at random: at a flat 15rem it was 104px of nothing beside a name
# that needed 136 in the app, and 59px of it here.
#
# Not zero, because the width comes out of `ch` units and a "0" is wider than the
# lowercase letters model ids are mostly made of — about 10% in a proportional face.
# In IBM Plex Mono, which is what the picker is set in now, a "0" is exactly as wide
# as every other character, so the reading should be tight; the allowance stays loose
# because it is the safe direction. The other side of the check is not, so it has no
# allowance at all: a negative reading means the name is being ellipsed, which is the
# failure that matters and the thing keeping the 0.78 in `app.css` honest.
# How much lighter the lit end of the status line's sweep has to be than the dim end,
# as a ratio of their contrasts against the page. An animation nobody can see is not an
# animation: the sweep it replaced ran 11:1 to 7.7:1, two dark maroons 1.42x apart, and
# read as a static line for as long as it shipped.
MIN_SHIMMER_SWING = 1.8
# The smallest side either injected control may have. Both are icon-only buttons with
# no label to widen them, and both are the ONLY way to reach something the app can do
# — calling off a generation, reopening a question — so a few pixels of drift in a
# padding is the difference between a feature and a control nobody can hit. Under the
# 44px WCAG target on purpose: the pencil sits in the gutter beside a bubble and
# taking 44px there would push the bubble in on a phone, which is a visible change to
# every question for the sake of a control that also has a full-size route (the
# composer) to the same outcome.
MIN_CONTROL_SIDE = 24
# How far the stop square may sit from the corner the send button occupies. They are
# the same control at two moments of a turn — the reader asked for the arrow to become
# a square — so anything a reader could see as a jump is a bug. 2px is rounding.
MAX_SWAP_DRIFT = 2
# The two gaps under an answer, both bounded at both ends. Reported as "barely any":
# at 8.8px the Sources strip was closer to the last line of the answer than two of its
# own paragraphs are to each other, so the references read as a last line of the prose.
# Too far is the other failure and the one that is easy to cause fixing this — pushed
# down the page they stop belonging to the answer above and start belonging to the
# rating row below.
ANSWER_TO_REFS = (14, 34)
# And Related against Sources, which has to stay the tighter of the two: they are one
# block, and a Related set as far from Sources as Sources is from the answer reads as a
# third section rather than as the second half of the references.
REFS_TO_RELATED = (8, 20)


# Every check above measures one frame. This one measures a *sequence*, because the
# per-turn scroll is the one behaviour in app.js whose bug lives in the transition
# rather than in any single layout: send a follow-up, and the view must move to the
# question and keep up with the answer arriving under it.
#
# It exists because modelling the pin was not enough. The state checks above
# reproduce the pin's formula (`__pinLast`) rather than running `autoScroll`, so they
# agreed with a version that pinned once, on a page that had not grown an answer yet,
# clamped against the bottom — and then held still for the rest of the turn while the
# reply streamed in 778px below the composer. Re-implementing a function is not
# testing it; this drives the real one.
#
# It also started too kind. `p.scrollTop = p.scrollHeight` put the reader at the END of
# the conversation before submitting, which is the one starting position where the bug
# does not show: the question is appended into the room the page reserves for the bar,
# so it lands just above the composer whether or not anything scrolls. The report was
# always about the other case — "if i enter the prompt when the scrollbar isn't at the
# bottom, the page stays where it is" — so `startFrac` places the reader part-way up as
# well, and `grab` has them take the page over mid-answer, which must not be undone.
FOLLOW_DRIVER = r"""
<style>PORTCSS</style>
<script>
var OPTS = FOLLOWOPTS;
var out = {steps: []};

// The scrollport as the READER experiences it: walk out from the conversation and take
// the innermost box that both overflows and is a scroll container.
//
// Deliberately not app.js's own `scroller()`. This used to be a copy of it — the same
// three-item list, the same `scrollHeight > clientHeight` test — and a harness that
// reuses the code under test cannot see that code pick the wrong element. It picked
// stAppViewContainer's overflow and wrote scroll positions into stMain for three
// rounds of this bug while every check here agreed with it.
function port() {
  var chain = [];
  var node = document.querySelector('.chat-container') || document.body;
  for (; node; node = node.parentElement) chain.push(node);
  chain.push(document.scrollingElement, document.documentElement);
  for (var i = 0; i < chain.length; i++) {
    var el = chain[i];
    if (!el || el.scrollHeight <= el.clientHeight + 1) continue;
    var over = getComputedStyle(el).overflowY;
    if (over === 'auto' || over === 'scroll' || over === 'overlay'
        || el === document.scrollingElement) return el;
  }
  return document.documentElement;
}
function portName(el) {
  return el ? (el.getAttribute('data-testid') || el.tagName) : 'none';
}
// The reader's own scrolling, and the harness's own placement of it. Instant on
// purpose: under a virtual clock a smooth scroll never advances, so a driver that let
// `scroll-behavior` apply to itself would measure a page nobody had scrolled.
function move(el, top) {
  if (el.scrollTo) { el.scrollTo({top: top, behavior: 'instant'}); }
  else { el.scrollTop = top; }
}
function tick(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

var held = false;

// The two numbers the reader cares about: how far the newest content runs past the
// composer, and whether their question has reached the top of the window (past which
// a long reply is theirs to scroll).
function look(label) {
  var p = port();
  var asked = document.querySelectorAll('.user-message');
  var last = asked[asked.length - 1];
  var tail = document.querySelector('#streamed') || last;
  var bar = document.querySelector('[data-testid="stBottomBlockContainer"]');
  var barTop = bar ? bar.getBoundingClientRect().top : innerHeight;
  out.steps.push({
    at: label,
    held: held,
    scrollTop: Math.round(p.scrollTop),
    maxScroll: Math.round(p.scrollHeight - p.clientHeight),
    questionTop: last ? Math.round(last.getBoundingClientRect().top) : null,
    hiddenBelow: tail ? Math.round(tail.getBoundingClientRect().bottom - barTop) : null
  });
}

function para(n) {
  var p = document.createElement('p');
  p.textContent = 'Streamed sentence number ' + n + ', long enough to take a line or '
    + 'two of the answer as it arrives from the model in real time. ';
  return p;
}

function marker() {
  if (document.getElementById('processing-signal')) return;
  var signal = document.createElement('div');
  signal.id = 'processing-signal';
  signal.hidden = true;
  document.body.appendChild(signal);
}

(async function () {
  await tick(400);                       // app.js boots and settles the page
  var p = port();
  // Where the reader is when they press Enter. 1 is the end of the last answer; less
  // than that is part-way up, which is the case that was never rendered here.
  move(p, Math.round(OPTS.startFrac * (p.scrollHeight - p.clientHeight)));
  out.shape = portName(p);
  await tick(300);
  look('before submit');

  // The rerun that starts a turn. app.py renders `#processing-signal` and then the
  // question, as two separate deltas, so there is a real window in which app.js sees a
  // generation in flight with the PREVIOUS question still the newest one in the DOM.
  // Rendered as that window, because a pass landing in it must not leave the page
  // pinned to the old question. Nothing here touches the scroll — that is what is
  // being measured.
  marker();
  await tick(150);
  look('marker only');

  var block = document.querySelector('[data-testid="stVerticalBlock"]');
  var q = document.createElement('div');
  q.className = 'element-container';
  q.innerHTML = '<div class="stMarkdown"><div data-testid="stMarkdownContainer">'
    + '<div class="user-message">'
    + '<div class="user-bubble">what else can you do?</div></div></div></div>';
  block.appendChild(q);
  var streamed = document.createElement('div');
  streamed.id = 'streamed';
  streamed.className = 'st-key-answer-9 element-container';
  streamed.innerHTML = '<div class="stChatMessage"><div></div>'
    + '<div class="stMarkdown">'
    + '<div data-testid="stMarkdownContainer" id="sink"></div></div></div>';
  block.appendChild(streamed);
  await tick(600);
  look('question appended');

  var sink = document.getElementById('sink');
  for (var n = 1; n <= 12; n++) {
    sink.appendChild(para(n));
    await tick(180);
    if (n === 3 || n === 6 || n === 12) look('streaming ' + n);
    // The reader scrolls up to re-read something while the answer is still arriving.
    // From here on the page is theirs: every later step asserts it stayed where they
    // put it, not that the view kept following.
    if (OPTS.grab && n === 6) {
      var g = port();
      move(g, Math.max(0, g.scrollTop - 300));
      await tick(120);
      out.grabbedAt = Math.round(g.scrollTop);
      held = true;
      look('reader scrolled up');
    }
  }
  await tick(500);
  look('answer complete');
  document.title = JSON.stringify(out);
})();
</script>
"""


# Dragging a file onto the composer, which is behaviour over a sequence rather than a
# layout — so, like the follow-up scroll above, it is driven rather than measured.
#
# It is here because it was reported as "no reaction at all, and the feature isn't
# available", and every check in this file agreed with the app: Streamlit's uploader has
# a dropzone of its own, app.css clips that widget to one pixel, and this replica did
# not render the widget at all. Nothing anywhere could see that the only place on the
# page that would accept a file was invisible and a pixel wide.
#
# Two things are asserted that are easy to get wrong in opposite directions. The drop
# must be CANCELLED — the browser's default action for a file dropped on a document is
# to navigate to it, so a miss below the composer replaced the conversation with a
# picture of the file — and a drag carrying *text* must NOT be, or dragging a selected
# sentence into the box stops inserting it.
DROP_DRIVER = r"""
<script>
var out = {steps: [], changes: 0};

function tick(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

function uploader() {
  return document.querySelector('[data-testid="stFileUploader"] input[type=file]');
}

// Streamlit learns about a programmatic file list from the `change` event app.js
// dispatches, so counting them is how this tells "the file arrived" from "the file
// arrived twice" — which is what a drop handler registered twice per rebuild does.
var input = uploader();
if (input) input.addEventListener('change', function () { out.changes += 1; });

function transfer(files, text) {
  var dt = new DataTransfer();
  files.forEach(function (name) {
    dt.items.add(new File(['sbatch job.sh\n'], name, {type: 'text/plain'}));
  });
  if (text) dt.items.add(text, 'text/plain');
  return dt;
}

// Dispatched rather than performed: headless Chrome cannot start an OS drag, so the
// events are made by hand. `types` is what app.js reads to decide a drag carries files,
// and a real DataTransfer populates it from what was added — so this models the one
// property the code under test depends on rather than asserting it.
function fire(kind, selector, dt) {
  var at = document.querySelector(selector);
  var event = new DragEvent(kind, {bubbles: true, cancelable: true, dataTransfer: dt});
  at.dispatchEvent(event);
  return event.defaultPrevented;
}

function look(label, prevented) {
  var box = document.querySelector('.stChatInput > div');
  var style = box ? getComputedStyle(box) : null;
  var files = uploader();
  out.steps.push({
    at: label,
    lit: document.body.dataset.sageDropping === 'true',
    borderStyle: style ? style.borderStyle : null,
    borderColor: style ? style.borderColor : null,
    files: files ? [].slice.call(files.files).map(function (f) { return f.name; }) : null,
    changes: out.changes,
    prevented: prevented === undefined ? null : prevented
  });
}

(async function () {
  await tick(400);                       // app.js boots
  look('idle');

  // Streamlit re-runs the component on every rerun, so the page ends up with a second
  // copy of app.js and the first copy's listeners still attached to a document that
  // outlived it. A drop then lands on both, and the second handler seeds its transfer
  // from a list the first has already added to — one file, attached twice.
  if (REBUILD) {
    var again = document.createElement('script');
    again.textContent = document.querySelector('#sage-js').textContent;
    document.body.appendChild(again);
    await tick(300);
  }

  var carried = transfer(['notes.txt', 'run.sh']);
  fire('dragenter', '.stChatInput textarea', carried);
  var overPrevented = fire('dragover', '.stChatInput textarea', carried);
  await tick(60);
  look('file held over the composer', overPrevented);

  // Out of the window without letting go. `dragleave` with nothing on the other side of
  // it is the only one of the many a moving drag fires that means the drag has left.
  fire('dragleave', '.stChatInput textarea', carried);
  await tick(60);
  look('dragged back out');

  fire('dragenter', '.stChatInput textarea', carried);
  fire('dragover', '.stChatInput textarea', carried);
  var dropPrevented = fire('drop', '.stChatInput textarea', carried);
  await tick(200);
  look('dropped on the composer', dropPrevented);

  // Anywhere else on the page, which is where a drop aimed at a 56px-tall box at the
  // bottom of a window actually lands. It has to attach, and above all it must not be
  // left to the browser to navigate to.
  var missed = transfer(['missed.log']);
  fire('dragenter', '[data-testid="stMainBlockContainer"]', missed);
  fire('dragover', '[data-testid="stMainBlockContainer"]', missed);
  var awayPrevented = fire('drop', '[data-testid="stMainBlockContainer"]', missed);
  await tick(200);
  look('dropped past the composer', awayPrevented);

  // A drag carrying a selected sentence. Cancelling this one would break dragging text
  // into the box, which is a thing the browser does for nothing and nobody asked to lose.
  var words = transfer([], 'some selected words');
  var textPrevented = fire('dragover', '.stChatInput textarea', words);
  await tick(60);
  look('text dragged over the composer', textPrevented);

  // A drag that ends without a `dragleave` — cancelled with Escape, or let go over
  // another window. Nothing reports it, so the composer has to time out of the lit
  // state on its own or stay lit for the rest of the session.
  fire('dragenter', '.stChatInput textarea', transfer(['abandoned.txt']));
  fire('dragover', '.stChatInput textarea', transfer(['abandoned.txt']));
  await tick(60);
  look('drag abandoned');
  await tick(1200);
  look('after the stale timer');

  document.title = JSON.stringify(out);
})();
</script>
"""


SELECT_DRIVER = """
<script>
(async function () {
  var out = [];
  function tick(ms) { return new Promise(r => setTimeout(r, ms)); }

  // Resolve once the document has gone `still` milliseconds without a mutation, or
  // after `cap` whatever happens — a page that never stops moving is a finding for
  // another check, not a reason for this one to hang.
  function quiet(still, cap) {
    return new Promise(function (done) {
      var last = Date.now();
      var observer = new MutationObserver(function () { last = Date.now(); });
      observer.observe(document.documentElement, {
        childList: true, subtree: true, attributes: true, characterData: true,
      });
      var started = Date.now();
      (function poll() {
        if (Date.now() - last >= still || Date.now() - started >= cap) {
          observer.disconnect();
          done();
          return;
        }
        setTimeout(poll, 25);
      })();
    });
  }

  // Let the page finish arriving before driving it. Two conditions, both waited on
  // rather than slept through.
  //
  // This sequence flaked, at 2 failures in 21 whole-suite runs — reporting "selecting
  // a passage of an answer offered no way to ask about it" with nothing wrong with
  // the app. Measured at the same rate on a commit from before the surrounding
  // refactor, so it is the harness and it is not new; it had simply never landed on
  // a run anyone was watching.
  //
  // What a failing run actually recorded: the bubble element exists from the moment
  // of the selection onward and stays `hidden` for the rest of the sequence. So
  // `placeAskBubble` ran and found no selection to place it against — the synthetic
  // selection was made into a page still initialising, and did not survive to the
  // 10ms timer that reads it. The `rebuilt` half never flaked, which is the tell: it
  // already waited 120ms after injecting its second copy.
  //
  // 1. The listeners are attached. `addSelectionAsk` installs `__sageAskOff` last, so
  //    its presence is the signal that the mouseup handler is live.
  // 2. The DOM has stopped moving. app.js rewrites the answers it is given — a copy
  //    button, an edit hook — and a selection made underneath that work is a
  //    selection the page can still collapse.
  //
  // Waiting for quiet rather than retrying the selection, on purpose: a retry would
  // also paper over an app that really does clobber a reader's selection, which is a
  // bug this check should keep being able to see. A reader cannot select text in the
  // first frame either.
  for (var w = 0; w < 200 && !window.__sageAskOff; w++) await tick(25);
  await quiet(120, 2000);

  var rehooked = null;
  if (REBUILD) {
    // `__sageAskOff` is the newest copy's own teardown function. Every copy of the
    // script must install its own — that is what proves it re-registered rather than
    // trusting a flag left on the window by a copy that no longer exists.
    var before = window.__sageAskOff;
    var again = document.createElement('script');
    again.textContent = document.getElementById('sage-js').textContent;
    document.body.appendChild(again);
    await tick(120);
    rehooked = {had: !!before, changed: window.__sageAskOff !== before};
  }
  function bubble() { return document.getElementById('ask-selection'); }
  function report(at) {
    var b = bubble();
    var box = document.querySelector('[data-testid="stBottomBlockContainer"]');
    var area = document.querySelector('.stChatInput textarea');
    out.push({
      at: at,
      present: !!b,
      shown: !!(b && !b.hidden),
      rect: b && !b.hidden ? {
        top: Math.round(b.getBoundingClientRect().top),
        left: Math.round(b.getBoundingClientRect().left),
        right: Math.round(b.getBoundingClientRect().right),
        bottom: Math.round(b.getBoundingClientRect().bottom),
        w: Math.round(b.getBoundingClientRect().width),
        h: Math.round(b.getBoundingClientRect().height),
      } : null,
      composer: area ? area.value : null,
      barTop: box ? Math.round(box.getBoundingClientRect().top) : null,
      viewport: {w: innerWidth, h: innerHeight},
    });
  }
  function pick(selector, chars) {
    var el = document.querySelector(selector);
    if (!el) return false;
    var range = document.createRange();
    if (chars) {
      var node = el.firstChild;
      while (node && node.nodeType !== 3) node = node.firstChild;
      if (!node) return false;
      range.setStart(node, 0);
      range.setEnd(node, Math.min(chars, node.textContent.length));
    } else {
      range.selectNodeContents(el);
    }
    var sel = getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
    return true;
  }
  // Polled, not slept. `placeAskBubble` runs on a 10ms timer and the machine this
  // renders on is shared — a fixed 120ms wait reported "selecting a passage offered
  // no way to ask about it" once in four sequences under load, which is a check that
  // fails for a reason that has nothing to do with the app.
  async function settle(want) {
    for (var i = 0; i < 40; i++) {
      var b = document.getElementById('ask-selection');
      if (!!(b && !b.hidden) === want) return;
      await tick(25);
    }
  }

  // Selecting, and selecting again if nothing came of it.
  //
  // Retrying the stimulus, not weakening the assertion: `settle` still has to see
  // the button, and a page that never shows one still fails. What this absorbs is
  // the harness racing the page — the driver picks text at machine speed on a shared
  // runner, and a selection made while app.js is still rewriting the answer around
  // it does not survive to the 10ms timer that reads it. A reader cannot select text
  // in the first frames, so this is not a case the app has to handle.
  //
  // It went red on CI twice. The waits above (listeners installed, DOM gone quiet)
  // fixed it on this machine — 0 in 60 — and did not on the runner, which is slower
  // and busier; a wait long enough for the worst runner is a wait this check pays on
  // every render. Repeating the pick costs nothing when the first one works.
  async function selectAndSettle(selector, chars) {
    for (var attempt = 0; attempt < 4; attempt++) {
      if (!pick(selector, chars)) return false;
      await settle(true);
      var bubble = document.getElementById('ask-selection');
      if (bubble && !bubble.hidden) return true;
      await quiet(80, 500);
    }
    return false;
  }

  if (rehooked) out.push({at: 'rehooked', rehooked: rehooked});
  report('idle');

  // A passage of an answer: the case the control exists for.
  await selectAndSettle('[class*="st-key-answer-"] .stChatMessage p');
  report('answer selected');

  // Clicking it drafts into the composer and stands down.
  var b = bubble();
  if (b && !b.hidden) b.click();
  await settle(false);
  report('after clicking it');

  // A question is the reader's own words; there is nothing to ask about them.
  getSelection().removeAllRanges();
  await tick(60);
  pick('.user-bubble');
  await settle(false);
  report('question selected');

  // A stray click's worth of text is not a passage.
  getSelection().removeAllRanges();
  await tick(60);
  pick('[class*="st-key-answer-"] .stChatMessage p', 4);
  await settle(false);
  report('four characters selected');

  // And it does not ride the page: it is fixed, so it hides rather than drift.
  getSelection().removeAllRanges();
  await tick(60);
  await selectAndSettle('[class*="st-key-answer-"] .stChatMessage p');
  document.dispatchEvent(new Event('scroll', {bubbles: true}));
  await settle(false);
  report('after a scroll');

  document.title = JSON.stringify(out);
})();
</script>
"""


def check_selection(width, height) -> tuple[list[str], int]:
    """Select a passage of an answer and see whether it can be asked about.

    Rendered twice, for the reason `check_drop` is: Streamlit re-runs
    `components.html`'s script on every rerun of the app.

    What the second render can and cannot show, stated because getting this wrong once
    already produced a check that passed on the bug it was written for. This replica
    runs app.js inline, so both copies share one realm and the first copy's listeners
    are still alive when the second arrives — whereas Streamlit rebuilds the *iframe*,
    which destroys them. So `rebuilt` cannot reproduce the symptom (a bubble that
    never appears again after the first rerun), and asserting on the symptom here
    passed with the bug reinstated.

    It asserts on the cause instead, which does survive the difference: every copy of
    the script must install its OWN `__sageAskOff`. A copy that skips registration
    because a flag on the parent window says someone already did it leaves the
    previous copy's teardown in place — and in the app, that previous copy is dead.
    """
    problems: list[str] = []
    body = CHAT_MARKER + "".join(answer_block(i) for i in range(2))
    checked = 0
    for label, rebuild in (("fresh", "false"), ("rebuilt", "true")):
        name = f"select-{label}-{width}"
        html = page(body, "light", scroll=False,
                    driver=SELECT_DRIVER.replace("REBUILD", rebuild))
        data = render(name, html, width, height, budget=20000)
        if data is None or not isinstance(data, list):
            problems.append(f"{name}: the selection sequence reported nothing")
            continue
        checked += 1
        steps = {step["at"]: step for step in data}

        rehooked = steps.get("rehooked", {}).get("rehooked")
        if rebuild == "true":
            if not rehooked:
                problems.append(f"{name}: the rebuild reported nothing")
            elif not rehooked.get("had"):
                problems.append(
                    f"{name}: the first copy of app.js installed no teardown, so "
                    "nothing here can tell a re-registration from a skipped one"
                )
            elif not rehooked.get("changed"):
                problems.append(
                    f"{name}: a second copy of app.js did not re-register the "
                    "selection handlers — it left the previous copy's teardown in "
                    "place, and in the app that copy is dead with its iframe, so the "
                    "ask button would never appear again"
                )

        if steps.get("idle", {}).get("shown"):
            problems.append(f"{name}: the ask button is up with nothing selected")

        picked = steps.get("answer selected", {})
        if not picked.get("shown"):
            problems.append(
                f"{name}: selecting a passage of an answer offered no way to ask "
                "about it"
            )
        else:
            rect, view = picked["rect"], picked["viewport"]
            if rect["left"] < 0 or rect["right"] > view["w"]:
                problems.append(
                    f"{name}: the ask button runs off the side of the window "
                    f"({rect['left']}..{rect['right']} of {view['w']})"
                )
            if rect["bottom"] > view["h"]:
                problems.append(
                    f"{name}: the ask button is {rect['bottom'] - view['h']}px below "
                    "the bottom of the window"
                )
            if min(rect["w"], rect["h"]) < MIN_CONTROL_SIDE:
                problems.append(
                    f"{name}: the ask button is {rect['w']}x{rect['h']}, too small "
                    f"to hit (want {MIN_CONTROL_SIDE} on the short side)"
                )
            # The composer is `fixed` over the page. A control that appears under it
            # is a control that cannot be clicked at all.
            if picked["barTop"] is not None and rect["top"] > picked["barTop"]:
                problems.append(
                    f"{name}: the ask button is behind the composer "
                    f"(button at {rect['top']}, bar starts at {picked['barTop']})"
                )

        used = steps.get("after clicking it", {})
        drafted = used.get("composer") or ""
        if "About this part of your answer" not in drafted:
            problems.append(
                f"{name}: clicking it drafted nothing into the composer "
                f"(composer holds {drafted[:60]!r})"
            )
        if used.get("shown"):
            problems.append(f"{name}: the ask button stayed up after it was used")

        if steps.get("question selected", {}).get("shown"):
            problems.append(
                f"{name}: selecting the reader's own question offers to ask about it"
            )
        if steps.get("four characters selected", {}).get("shown"):
            problems.append(f"{name}: a four-character selection counts as a passage")
        if steps.get("after a scroll", {}).get("shown"):
            problems.append(
                f"{name}: the ask button survived a scroll — it is positioned in "
                "viewport coordinates, so it would be left pointing at nothing"
            )
    return problems, checked


def check_drop(width, height) -> tuple[list[str], int]:
    """Drag files onto the composer and watch what the page does about it.

    Rendered twice: once on a page whose app.js ran the way this replica loads it, and
    once with a second copy of the script appended, which is what Streamlit does to
    `components.html` on every rerun. The second is the one that catches a handler
    registered twice — one dropped file, attached twice, or two change events for it.
    """
    problems: list[str] = []
    body = CHAT_MARKER + "".join(answer_block(i) for i in range(2))
    checked = 0
    for label, rebuild in (("fresh", "false"), ("rebuilt", "true")):
        name = f"drop-{label}-{width}"
        html = page(body, "dark", scroll=False,
                    driver=DROP_DRIVER.replace("REBUILD", rebuild))
        data = render(name, html, width, height, budget=20000)
        if data is None or not data.get("steps"):
            problems.append(f"{name}: the drag sequence reported nothing")
            continue
        checked += 1
        steps = {step["at"]: step for step in data["steps"]}

        idle = steps.get("idle", {})
        if idle.get("files") is None:
            problems.append(
                f"{name}: no file input on the page at all, so nothing here can say "
                "whether a dropped file reaches Streamlit"
            )
            continue

        over = steps.get("file held over the composer", {})
        if not over.get("lit"):
            problems.append(
                f"{name}: a file held over the composer changed nothing about it — a box "
                "that answers a drag with nothing reads as one that does not take files"
            )
        if over.get("borderStyle") == idle.get("borderStyle") and (
                over.get("borderColor") == idle.get("borderColor")):
            problems.append(
                f"{name}: the composer is drawn identically "
                f"({idle.get('borderStyle')} {idle.get('borderColor')}) whether or not a "
                "file is being held over it"
            )
        if not over.get("prevented"):
            problems.append(
                f"{name}: the dragover was not cancelled, so the browser will never "
                "deliver a drop to this page however accurately it is aimed"
            )

        out = steps.get("dragged back out", {})
        if out.get("lit"):
            problems.append(
                f"{name}: the composer stayed lit after the drag left the window"
            )

        dropped = steps.get("dropped on the composer", {})
        if dropped.get("files") != ["notes.txt", "run.sh"]:
            problems.append(
                f"{name}: two files dropped on the composer reached Streamlit's uploader "
                f"as {dropped.get('files')!r}"
            )
        if dropped.get("changes") != 1:
            problems.append(
                f"{name}: one drop dispatched {dropped.get('changes')} change events — "
                "Streamlit reads the file list on that event, so anything but one means "
                "the file was offered twice or not at all"
            )
        if not dropped.get("prevented"):
            problems.append(
                f"{name}: the drop was left to the browser, which navigates to the "
                "dropped file — the conversation is gone and the file never arrives"
            )
        if dropped.get("lit"):
            problems.append(f"{name}: the composer stayed lit after the drop")

        away = steps.get("dropped past the composer", {})
        if away.get("files") != ["notes.txt", "run.sh", "missed.log"]:
            problems.append(
                f"{name}: a file dropped away from the composer reached the uploader as "
                f"{away.get('files')!r} — a drop that misses a 56px box must still land"
            )
        if not away.get("prevented"):
            problems.append(
                f"{name}: a drop past the composer was left to the browser, which "
                "replaces the conversation with the file that was dropped"
            )

        text = steps.get("text dragged over the composer", {})
        if text.get("prevented"):
            problems.append(
                f"{name}: a drag carrying text was cancelled, which stops a selected "
                "sentence being dragged into the box"
            )
        if text.get("lit"):
            problems.append(
                f"{name}: the composer offered to attach a drag that carried no file"
            )

        abandoned = steps.get("drag abandoned", {})
        stale = steps.get("after the stale timer", {})
        if abandoned.get("lit") and stale.get("lit"):
            problems.append(
                f"{name}: a drag abandoned without a dragleave left the composer lit "
                "with nothing able to clear it"
            )
    return problems, checked


def page(body: str, scheme: str, scroll: bool, generating: bool = False,
         pin: bool = False, script: bool = True, sticky: bool = False,
         doc_scroll: bool = False, typed: bool = False, landing: bool = False,
         column_input: bool = False, portal: str = "", queued=(),
         driver: str = "") -> str:
    """The replica, with or without app.js, and with the bar pinned either way.

    `script=False` is the app's first frame: the stylesheet's own fallback for how
    much room the bar takes, before app.js has measured the real thing. It is a
    state a user sees, and it is the one CI caught an answer 2px underneath the
    input in — the two fallbacks disagreed with each other by 26px and every
    render that ran app.js papered over it.

    `sticky` is the other thing Streamlit does with its bottom container: put it in
    the flow at the end of the scrolling area rather than fixed over the page. This
    replica asserted `fixed` from the day it was written, the stylesheet reserved a
    bar's worth of room at the end of every conversation on the strength of it, and
    that reservation was the dead space three rounds of fixes could not find.
    Nothing here is allowed to model only one of them again.

    `doc_scroll` moves the scrollbar off stMain and onto the document. Nothing
    about the stylesheet changes; what changes is which element can answer "does
    this conversation scroll?", and a wrong answer there is how a page that
    scrolled got a screenful of slack padded on top of it.

    `typed` fills the input with a paragraph instead of leaving it on its placeholder.
    An empty box is one line tall and hides everything about how a full one behaves.

    `portal` is markup appended at the very end of `<body>`, where Streamlit renders
    overlays. Anything in there is outside every container this app styles, which is
    the whole reason it needs modelling separately.

    `window.__sageWatched` is set for any body with a conversation in it, because in
    the app there is no other kind: a conversation only ever appears by growing in
    front of the reader, and `fill()` reads that flag to leave it where it is rather
    than padding it down to the composer. Without this the replica would render the
    one state the app never reaches — a short conversation nobody watched arrive — and
    every check here would pass on a layout the reader never sees.

    `queued` is what the reader has typed and sent while this answer was still
    arriving. Seeded as the state app.js keeps it in, NOT written into a fixture as
    markup: the row is injected by `renderQueue`, and a hand-copy of its markup here
    would be a replica of a replica — it would keep passing after the real function
    stopped producing that shape. Seeding the state means the harness measures what
    app.js actually draws. (It would also delete a static fixture on sight: with an
    empty queue, `renderQueue` removes the row it finds.)

    `column_input` stacks the send button under the textarea instead of beside it. In
    the row shape a full box has 2px under its last line; in the column shape it has
    46px, and 46px under what you just typed is what got reported as "an empty space
    between the bottom of the text and the bottom of the input text box". Both are
    rendered because which one Streamlit builds is not visible from this repo — and a
    fix tested only in the shape that cannot show the bug is not a tested fix.
    """
    # The send button is modelled because it is what decides the height of the box.
    # Left in the flow it is a sibling of the textarea, and once the text runs past one
    # line it lands on a row of its own underneath — a band of nothing between the last
    # line typed and the bottom of the box. The replica had no button at all, so the
    # box was always exactly as tall as its text and the bug could not appear here.
    #
    # `rows` stands in for Streamlit's auto-grow: a textarea does not grow to fit its
    # own value, so `typed` is what a box with a paragraph in it actually looks like.
    send = ('<button data-testid="stChatInputSubmitButton" aria-label="Send">'
            "<p>↑</p></button>")
    bar = ('<div data-testid="stBottom">'
           '<div data-testid="stBottomBlockContainer">'
           '<div class="stChatInput" data-testid="stChatInput"><div>'
           # The paperclip app.js injects. Without the test id above, `addPaperclip`
           # never fired here, so neither the button nor the `:not(#paperclip-btn)`
           # exclusion that keeps it out of the send button's corner was ever rendered.
           '<button id="paperclip-btn" type="button">📎</button>'
           # Two placeholders, as app.py has them: the landing screen names the
           # subject because nothing else on that page does, and every screen with an
           # answer on it asks for a follow-up instead.
           + ('<textarea rows="6">' + TYPED + "</textarea>" if typed else
              f'<textarea rows="1" placeholder="{PLACEHOLDERS[landing]}">'
              '</textarea>')
           + (f'<div class="chat-actions">{send}</div>' if column_input else send)
           + "</div></div></div></div>")
    # Streamlit's file uploader, where app.py renders it: in the main block rather than
    # in the bar, and clipped to a single pixel by app.css because uploads are driven
    # from the paperclip. Absent from this replica for as long as it existed, and its
    # absence is why nothing here could see that a file dragged onto the composer had
    # nowhere on the page to land. `st-key-uploader-0` is the container key app.py gives
    # it, and the dropzone inside is Streamlit's own — the one whose 1px is the reason
    # app.js has to take the drop itself.
    uploader = ('<div data-testid="stElementContainer" '
                'class="element-container st-key-uploader-0">'
                '<div data-testid="stFileUploader" class="stFileUploader">'
                '<section data-testid="stFileUploaderDropzone" role="presentation">'
                '<input type="file" multiple>'
                "</section></div></div>")
    # The clipped widgets whose clicks app.js's injected controls carry back to Python.
    # Without them the injectors find nothing to wire to and quietly do not run — the
    # square and the pencils would be absent from every render here and present in the
    # app, which is the shape of a harness that cannot see the thing it is checking.
    #
    # One edit hook per question, because that is app.py's contract and app.js checks
    # it: it pairs the Nth `.user-message` with the Nth hook and injects nothing at all
    # if the two counts disagree. Counted off the body rather than written into each
    # scenario so a new scenario with a question in it cannot forget one.
    #
    # One FEWER than the questions while generating, and disabled, because that is
    # what the app does: the question being answered is drawn from the turn block
    # without a hook, and the settled ones above it have theirs disabled for the
    # length of the turn. Both halves are load-bearing — app.js refuses to pair the
    # two lists if they disagree by more than that one, and it hides a pencil whose
    # hook is disabled — so a replica that modelled neither would render pencils this
    # app does not draw.
    questions = body.count('class="user-message"')
    hooks = "".join(
        f'<div data-testid="stElementContainer" '
        f'class="stElementContainer element-container st-key-edit-open-{index}">'
        f'<button{" disabled" if generating else ""}>Edit this question</button></div>'
        for index in range(max(0, questions - 1) if generating else questions)
    )
    if generating:
        hooks += ('<div data-testid="stElementContainer" '
                  'class="stElementContainer element-container st-key-stop-generation">'
                  "<button>Stop generating</button></div>")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{base_css(scheme)}</style><style>{theme_css(scheme)}</style></head>
<body class="{'bar-sticky' if sticky else 'bar-fixed'}{' doc-scroll' if doc_scroll else ''}{' input-column' if column_input else ''}">
<div data-testid="stHeader">
  <!-- Streamlit's own sidebar arrow, at the geometry it really has (18,16,28x28), and
       the host's toolbar actions on the right. The second one is why this markup
       exists: `Share` is a HOST item — Community Cloud sends it over the
       host-communication channel and Streamlit renders it into `stToolbarActions` — so
       it is absent from any local run, and app.js reserves room for the theme toggle by
       measuring it. Modelled at the width `#host-bar` paints, because on the deployment
       they are the same cluster, and the toggle has to clear the whole of it rather
       than just the word. Without this the toggle would only ever render at its
       no-controls fallback of 16px, in the corner, and the bound that keeps it off the
       host's own buttons would have nothing to fail on. -->
  <div data-testid="stToolbar">
    <div class="toolbar-row">
      <button data-testid="stExpandSidebarButton">&raquo;</button>
    </div>
    <div data-testid="stToolbarActions" class="toolbar-actions">
      <button data-testid="stToolbarActionButton">Share</button>
    </div>
    {'<div class="status-widget" data-testid="stStatusWidget">Stop</div>' if generating else ''}
  </div>
</div><div id="host-bar"></div>
<div data-testid="stAppViewContainer">
  <div data-testid="stMain" class="main">
    <div data-testid="stMainBlockContainer" class="block-container">
      <div data-testid="stVerticalBlock">{body}{hooks}{uploader}</div></div>
    {bar if sticky else ''}</div>
  {'' if sticky else bar}</div>
{'<div id="processing-signal" hidden></div>' if generating else ''}
{portal}
<script>window.__scrollBottom = {str(scroll).lower()}; window.__pinLast = {str(pin).lower()};
window.__sageWatched = {str('chat-container' in body).lower()};
window.__sageQueue = {json.dumps(list(queued))};</script>
{'<script id="sage-js">' + JS + '</script>' if script else ''}
{driver or MEASURE.replace("HOSTBAR", str(HOST_BAR)).replace("TOPGAP", str(TOP_GAP)).replace("SELECTORS", json.dumps(SELECTORS)).replace("SEND_SELECTOR", json.dumps(SEND)).replace("FONTPROBES", json.dumps(FONT_PROBES))}
</body></html>"""


_PROBE = ('<!doctype html><html><body><script>document.title='
          'JSON.stringify({w:innerWidth,h:innerHeight})</script></body></html>')
# The phone this wants to render. Chromium will not open a headless window this
# narrow — 500px is as far as it goes — so what `calibrate()` returns for it is the
# narrowest real width available, and that is what goes in the width list.
PHONE_W, PHONE_H = 414, 896


def calibrate():
    """What viewport does `--window-size` actually produce?

    Not the one it asks for. `--window-size` is the *outer* window, so every height
    comes back short by the browser's own chrome, and Chromium will not open a window
    narrower than a floor of its own however small a number it is given. This harness
    asked for 414x896 for a year and rendered 500x809: the phone width it claimed to
    cover did not exist, and every failure it reported named a size it was not looking
    at. Measured here rather than hardcoded, because both numbers belong to whichever
    Chromium is installed.
    """
    path = os.path.join(HERE, "_calibrate.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_PROBE)
    def probe(w, h):
        out = subprocess.run(
            [CHROME, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
             f"--window-size={w},{h}", "--virtual-time-budget=300", "--dump-dom",
             f"file://{path}"], capture_output=True, text=True, timeout=120).stdout
        start, end = out.find("<title>"), out.find("</title>")
        if start == -1:
            raise SystemExit("render_check: could not calibrate the viewport — "
                             f"{CHROME} produced no measurement")
        return json.loads(out[start + 7 : end])
    big = probe(1200, 1000)
    # The narrowest the phone entry can be is found by asking for a phone and seeing
    # what comes back — not by asking for 1x1, which read as the tidier way to find
    # the floor and returned a width of 0 on CI's Chromium: a window that degenerate
    # is one it declines to report rather than one it clamps, and every render then
    # failed at "asked for a 0px viewport". Where a Chromium does honour PHONE_W, this
    # gains the real phone width instead of settling for the floor.
    chrome_w, chrome_h = 1200 - big["w"], 1000 - big["h"]
    # Asked for twice on purpose. The first probe says what a phone request lands on;
    # the second asks for *that*, the way `render()` will, and takes what comes back.
    # Where the window has no borders the two agree and the second is a no-op, but
    # `render()` adds `chrome_w` to whatever it is given, so on a platform where that
    # is not zero the naive floor would be a width `render()` can never hit — and the
    # assertion downstream would turn that into 300 failures rather than one.
    phone = probe(PHONE_W + chrome_w, PHONE_H + chrome_h)
    narrow = probe(phone["w"] + chrome_w, PHONE_H + chrome_h)["w"]
    os.remove(path)
    if not 1 <= narrow <= 640:
        raise SystemExit(
            f"render_check: asked for a {PHONE_W}px-wide window and got {narrow}px. "
            "The narrow screen has to land under the 640px mobile breakpoint or the "
            "mobile rules go unrendered — fix this rather than auditing four desktop "
            "widths and calling one of them a phone."
        )
    return {"chrome_h": chrome_h, "chrome_w": chrome_w,
            "min_w": narrow, "min_h": phone["h"]}


VIEWPORT = None   # filled in by main(); {'chrome_h', 'chrome_w', 'min_w', 'min_h'}


def render(name, html, width, height, shot=False, budget=1500):
    path = os.path.join(HERE, f"{name}.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    # `width`/`height` are the CSS viewport wanted, so the window has to be asked for
    # the chrome on top of it. Whether that landed is checked per render in main().
    pad_w = VIEWPORT["chrome_w"] if VIEWPORT else 0
    pad_h = VIEWPORT["chrome_h"] if VIEWPORT else 0
    cmd = [CHROME, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
           f"--window-size={width + pad_w},{height + pad_h}",
           f"--virtual-time-budget={budget}"]
    if shot:
        cmd.append(f"--screenshot={os.path.join(HERE, name + '.png')}")
    cmd += ["--dump-dom", f"file://{path}"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
    start, end = out.find("<title>"), out.find("</title>")
    if start == -1:
        return None
    import html as _html

    # The payload rides back in <title>, so every entity has to come back out —
    # `&gt;` in particular, or any selector containing ">" gets a mangled key.
    return json.loads(_html.unescape(out[start + 7 : end]))


# The question's top edge is allowed to be a hair under TOP_GAP without that counting
# as "not pinned yet": the pin lands within a pixel or two and rounding is reported to
# whole pixels on both sides.
FOLLOW_SLACK = 8

# Which box the app's vertical overflow settles on — and this replica *defines* that,
# which is how it managed to bless a scroll that never happened.
#
# `base_css` gives stMain `overflow: auto; height: 100vh`, and `doc_scroll` moves the
# overflow to the document. Those were the only two shapes ever rendered, and app.js
# named both of them outright. But Streamlit has put the app's scrollbar on
# `.appview-container` and on `section.main` as well as on `[data-testid="stMain"]`
# across the versions requirements.txt allows — and app.css's own
# `overflow-x: hidden` on html, body, stAppViewContainer and stMain makes all four
# scroll containers here, because CSS computes a `visible` axis to `auto` beside a
# non-visible one. On the shape where the overflow lands on stAppViewContainer, app.js
# matched nothing at all and its scroll function returned on its first line: no pin, no
# settle, no landing reset, on every turn at every window size.
#
# So two more shapes, as a stylesheet override rather than a `page()` flag, because
# they are shapes `page()`'s own base CSS defines away — and defining a shape away is
# how a check comes to pass on a page the app never has.
_CONTAINER_CSS = (
    '[data-testid="stMain"] { overflow: visible !important; height: auto !important; }'
    '[data-testid="stAppViewContainer"] { height: 100vh !important;'
    " min-height: 0 !important; overflow: auto !important; }"
)
# The same, except stMain keeps a height it cannot scroll. `overflow: visible` reports
# scrollHeight past clientHeight and then ignores every assignment to scrollTop, so a
# scroller chosen by "does this overflow?" picks stMain, writes into it all turn, and
# the page never moves. The two halves fail identically and for different reasons, so
# both are rendered.
_DEAF_CSS = (
    '[data-testid="stMain"] { overflow: visible !important; height: 100% !important; }'
    '[data-testid="stAppViewContainer"] { height: 100vh !important;'
    " min-height: 0 !important; overflow: auto !important; }"
)
# Not a scrollport shape: a stylesheet turning every scroll into an animation. One
# `scroll-behavior: smooth` in Streamlit's own CSS — which this repo cannot see — makes
# `el.scrollTop = x` a request rather than a move, so the position read back on the
# next line is the old one. app.js has to ask for an instant scroll explicitly.
_SMOOTH_CSS = 'html, body, [data-testid="stMain"] { scroll-behavior: smooth !important; }'

# name, the scrollport the reader really has, extra CSS, doc_scroll, sticky bar.
# The bar is pinned both ways across the list rather than doubling every render, the
# same trade `STICKY_BAR` makes for the screens above.
FOLLOW_SHAPES = [
    ("stMain", "stMain", "", False, False),
    ("document", "HTML", "", True, True),
    ("container", "stAppViewContainer", _CONTAINER_CSS, False, True),
    ("container-deaf-main", "stAppViewContainer", _DEAF_CSS, False, False),
    ("smooth", "stMain", _SMOOTH_CSS, False, False),
]


def check_follow(widths) -> tuple[list[str], int]:
    """Send a follow-up on a scrolled page and watch where the view goes.

    The invariant, at every step of the turn: either the newest content is above the
    composer, or the question has reached the top of the window. Those are the two
    honest resting places. Anything else is the reader looking at a still page while
    their answer arrives somewhere below it, which is the bug this reproduces.

    Three starting positions, because the bug was reported three times and the first
    version of this check only rendered the one that hides it:

      * `end` — the reader at the bottom of the last answer. The forgiving case: the
        page reserves a bar's worth of room past its last message, so a question
        appended into it lands above the composer even if nothing scrolls at all.
      * `up` — the reader part-way up, which is what was actually reported. Nothing
        arrives on screen unless the view moves.
      * `grab` — the reader at the end, who then scrolls up mid-answer. Here the
        assertion inverts: the page must stay where they put it. The guard meant to do
        that shipped as unreachable code (it tested `reader && !offscreen` on a path
        that only runs when `offscreen`), so it was never exercised by anything.
    """
    problems: list[str] = []
    body = CHAT_MARKER + "".join(answer_block(i) for i in range(3))
    checked = 0
    for shape, expect, css, doc_scroll, sticky in FOLLOW_SHAPES:
        # A narrow window as well as a wide one: the shorter the viewport, the longer
        # the page stays too short to put the question at the top, which is the whole
        # failure.
        for label, start, grab in (("end", 1.0, False), ("up", 0.4, False),
                                   ("grab", 1.0, True)):
            for width, height in widths:
                name = f"follow-{shape}-{label}-{width}"
                opts = json.dumps({"startFrac": start, "grab": grab})
                html = page(body, "dark", scroll=False, doc_scroll=doc_scroll,
                            sticky=sticky,
                            driver=(FOLLOW_DRIVER.replace("PORTCSS", css)
                                    .replace("FOLLOWOPTS", opts)))
                data = render(name, html, width, height, budget=20000)
                if data is None or not data.get("steps"):
                    problems.append(f"{name}: the follow-up sequence reported nothing")
                    continue
                checked += 1
                if data.get("shape") != expect:
                    problems.append(
                        f"{name}: meant to put the scrollbar on {expect} and the page "
                        f"put it on {data['shape']} — this render measured a shape it "
                        f"does not claim to be"
                    )
                    continue
                grabbed = data.get("grabbedAt")
                for step in data["steps"]:
                    # The reader put the page there themselves, and the marker-only
                    # window is a half-built page with no new question in it yet. What
                    # both have to be judged on is where the steps AFTER them end up.
                    if step["at"] in ("before submit", "marker only"):
                        continue
                    if step["held"]:
                        if grabbed is None:
                            continue
                        if abs(step["scrollTop"] - grabbed) > FOLLOW_SLACK:
                            problems.append(
                                f"{name}/{step['at']}: the reader scrolled to "
                                f"{grabbed} and the view was dragged to "
                                f"{step['scrollTop']} — a reader who scrolls away "
                                f"mid-answer must keep the page"
                            )
                        continue
                    # The newest text has to be on screen, full stop. This used to
                    # accept "the question is pinned at the top of the window" as an
                    # alternative resting place, and that is what shipped as the page
                    # freezing: the view arrived on send and then every token after the
                    # first screenful streamed in below the fold with nothing moving.
                    # The only turn where the reader may be left behind is one where the
                    # reader chose it, which the hand-off branch above handles.
                    if step["hiddenBelow"] > FOLLOW_SLACK:
                        problems.append(
                            f"{name}/{step['at']}: the newest content runs "
                            f"{step['hiddenBelow']}px past the composer (question "
                            f"{step['questionTop']}px down, scrollTop "
                            f"{step['scrollTop']} of {step['maxScroll']}), so the view "
                            f"stopped following the answer as it streamed"
                        )
    return problems, checked


# Every selector this run measured something for. A check keyed on a selector that
# matches nothing passes silently, and this file is full of `if not found: continue` —
# `audit_citations` skips its whole body when `.source-item` is absent, which is exactly
# what would happen the day a class is renamed in `sage/ui/transcript.py` and the fixture
# here is not. `_check_balanced` guards the fixtures' shape; this guards their content.
SEEN_SELECTORS: set[str] = set()

# The list selectors the measurement collects every row of, named here because
# `audit_citations` reads them and the coverage check has to know they exist.
LIST_SELECTORS = (".source-item", ".related-item")

# Which face each of these has to be in. Two faces carry a distinction the app makes
# on purpose — language in the sans, machine data in the mono — and it is the one
# thing on the page that no measurement notices: a model name in the wrong font is the
# right size, in the right place, at the right contrast, and wrong. The values are
# read out of `[theme]` rather than written here, so renaming the typeface in one
# place moves this check with it.
#
# The prose entries are not padding. `html, body` in app.css is the only thing putting
# the sans on most of this page, and `!important` in the mono block above is a blunt
# instrument: a selector typo there that caught `.source-link` or an answer's
# paragraphs would set a documentation title or a whole answer in Plex Mono, which is
# a change to every screen in the app and fails nothing else in this file.
FACES = {
    ".stChatMessage pre": "mono",
    ".stChatMessage code": "mono",
    # The query a turn searched for and the section it read. Both ends of the column,
    # because the block is built a line at a time and one line set in the body face
    # would be the only thing on the page where a path is not code.
    ".status-arg": "mono",
    "last:.status-arg": "mono",
    ".source-kind": "mono",
    # The pill, and it is SANS. The model picker here was mono because its label
    # was a served model id — machine data, like a path in an answer. This label
    # is one English word from the profile, so it takes the interface face, and
    # this line is what holds app.css to having taken it off the mono list.
    PICKER: "sans",
    ".welcome-title": "sans",
    ".welcome-subtitle": "sans",
    ".user-bubble": "sans",
    ANSWER_TEXT: "sans",
    ".sources-label": "sans",
    ".source-link": "sans",
    ".related-link": "sans",
    INPUT: "sans",
}


def audit(data, scenario, scheme, width, state: str) -> list[str]:
    problems, els = [], data["els"]
    SEEN_SELECTORS.update(selector for selector, box in els.items() if box)
    # The state belongs in the label. Six identical-looking failures that named only
    # screen, theme and width could not be placed to a state at all, and the state is
    # what says whether app.js had run, whether an answer was in flight, and whether
    # the view had been scrolled — i.e. most of what a failure means.
    where = f"{scenario}/{scheme}/{width}px/{state}"
    generating = state == "generating"
    # "unmeasured" is the first frame, so it is at the top of the page like "rest":
    # the host-toolbar collision check below is meaningful in both.
    #
    # Unless app.js has moved it. "rest" stopped being a synonym for "at the top of
    # the page" when a finished turn started following its own tail down, so that the
    # Sources strip and the rating row clear the composer. On the shortest viewport
    # (966x626) that lands the page at its maximum scroll, which puts the top of the
    # answer 25px behind the host overlay — with no less-scrolled position that also
    # shows the tail. Reading the measured position rather than inferring it from the
    # state name is what the collision check's own comment already asks for: once the
    # page is scrolled, content passing under a fixed overlay is inherent. A page that
    # has NOT scrolled is still judged, which is the case the check was written for.
    scrolled = state not in ("rest", "unmeasured") or data["scrolled"] > 0

    for selector, face in FACES.items():
        measured = els.get(selector)
        if not measured:
            continue
        if measured["family"] != FONT_PROBES[face]:
            problems.append(
                f"{where}: {selector} is set in {measured['family']!r}, and the "
                f"{face} face is {FONT_PROBES[face]!r}"
            )

    if data["docOverflowX"] > 0:
        problems.append(f"{where}: page scrolls sideways by {data['docOverflowX']}px")

    # The theme toggle is in the top-right corner, which is also where the host paints
    # its own controls — Share and the ⋮ menu, at a z-index this app deliberately
    # outranks. Outranking them means a toggle placed carelessly does not disappear
    # under them; it covers them, which is worse, because it is invisible here and
    # visible only to a reader of the deployment. So the reservation app.js measures is
    # bounded on geometry: beside them, never on top.
    toggle, host = els.get(THEME_TOGGLE), els.get("#host-bar")
    if toggle and host and toggle["right"] > host["left"] and toggle["bottom"] > host["top"]:
        problems.append(
            f"{where}: {THEME_TOGGLE} overlaps the host's own controls by "
            f"{round(toggle['right'] - host['left'])}px — it would be painted over "
            f"Share on the deployment"
        )

    bar = els.get('[data-testid="stBottomBlockContainer"]')
    # The top of everything pinned at the bottom, not just of the bar. The attachment
    # chips sit above the bar and are `fixed` too, so a gap measured to the bar's top
    # would read as healthy while a chip sat on the newest answer. Every check below
    # that used to say "the input bar" now means "the composer", which is what a reader
    # sees: one block of furniture at the bottom of the page.
    chip_row = els.get(CHIPS)
    if bar and chip_row and chip_row["top"] < bar["top"]:
        bar = dict(bar, top=chip_row["top"])
    for sel, b in els.items():
        if not b:
            continue
        # Only meaningful at rest: once the page is scrolled, content passing
        # beneath a fixed host overlay is inherent, not an app defect. What must
        # never happen is content being unreachable — covered by the input-bar
        # check below, which only runs in the scrolled state.
        # `#host-bar` is exempt: it is not content of this app but the model OF the
        # overlay this check is about, so it collides with itself by construction. It
        # is measured only so the theme toggle can be held clear of it above.
        if (sel != "#host-bar"
                and not scrolled and b["top"] < data["hostBar"] and b["bottom"] > 0
                and b["right"] > width - HOST_BAR_W):
            problems.append(
                f"{where}: {sel} collides with the host toolbar "
                f"({data['hostBar'] - b['top']}px under it)"
            )
        # The picker ellipsing a long model id is intended, and <pre> scrolls.
        # (Both selectors that reach the picker trigger are exempt; the trash
        # button, matched by `last:`, is not — it has nothing to ellipse.)
        if (b["overflowX"] > 1 and "pre" not in sel
                and sel not in ELLIPSIS_OK and sel not in SCROLLS_OK):
            problems.append(f"{where}: {sel} overflows horizontally by {b['overflowX']}px")
        limit = (LINE_LIMITS.get(sel) if width >= 641
                 else NARROW_LINE_LIMITS.get(sel))
        if limit and b["lines"] > limit:
            problems.append(f"{where}: {sel} wraps to {b['lines']} lines (want {limit})")
        # Small text needs 4.5:1; >=18.66px counts as large text at 3:1.
        if b["contrast"] and "chip" not in sel:
            need = 3.0 if b["fontPx"] >= 18.66 else 4.5
            if b["contrast"] < need and sel not in CLIPPED_TEXT:
                problems.append(
                    f"{where}: {sel} contrast {b['contrast']}:1 (needs {need}:1)"
                )

    # Every stop of the status line's sweep, not the colour it claims. The highlight
    # end is the lowest-contrast text the app ever paints, and it is on screen for
    # exactly as long as the reader is waiting with nothing else to look at. Small text
    # at 14-15px, so the ordinary 4.5:1 applies to all of it — a shimmer that dips
    # under it for the third of a second the band is over a word is still a shimmer
    # that dips under it.
    stops = data.get("statusStops")
    if stops:
        worst = min(stops)
        if worst < 4.5:
            problems.append(
                f"{where}: the status line's shimmer reaches {worst}:1 at the lit end "
                f"of its sweep (needs 4.5:1 — every stop of it is text a reader is "
                f"watching)"
            )
        # …and the other failure, which is not a contrast one: two stops a reader
        # cannot tell apart. That was the old sweep — 11:1 to 7.7:1, a 1.42x swing
        # between two dark maroons, which on screen is a line that does not move.
        # 1.8 is where that sits on the wrong side and the pair replacing it (2.4x on
        # white, 2.6x on the dark page) sits comfortably on the right one.
        if max(stops) / worst < MIN_SHIMMER_SWING:
            problems.append(
                f"{where}: the status line's sweep runs {worst}:1 to {max(stops)}:1, "
                f"which is not a visible change in lightness — it reads as a line "
                f"that is not animating at all"
            )

    # The references, and how far they sit from the answer and from each other.
    for what, gap, (low, high) in (
        ("the Sources strip", data.get("answerToRefs"), ANSWER_TO_REFS),
        ("Related", data.get("refsToRelated"), REFS_TO_RELATED),
    ):
        if gap is None:
            continue
        if gap < low:
            problems.append(
                f"{where}: {gap}px between {what} and what is above it "
                f"(want {low}-{high} — any less and it reads as part of it)"
            )
        elif gap > high:
            problems.append(
                f"{where}: {gap}px between {what} and what is above it "
                f"(want {low}-{high} — any more and it stops belonging to it)"
            )
    # The references have to be inside the answer that owns them. They are its last
    # child, and Streamlit's markdown wrapper carries `margin-bottom: -1rem`, which puts
    # a last child's box past its parent's bottom edge rather than merely tightening
    # what follows. 16px of that made a page exactly the height of the window report
    # `scrollHeight > clientHeight`, which is the single question `fill()` asks before
    # deciding a short conversation has no slack — so it published none, and a
    # one-answer page sat at the top with a screenful of nothing under it.
    overhang = data.get("refsOverhang")
    if overhang is not None and overhang > 0:
        problems.append(
            f"{where}: the references hang {overhang}px out of the bottom of the "
            f"answer holding them — content outside its own container is content the "
            f"page cannot measure, and `fill()` reads that measurement"
        )

    # …and the hierarchy between the two, which is the point of having both. Checked as
    # an ordering rather than as two numbers, so tuning either bound cannot quietly
    # invert it.
    outer, inner = data.get("answerToRefs"), data.get("refsToRelated")
    if outer is not None and inner is not None and inner >= outer:
        problems.append(
            f"{where}: Related is {inner}px under Sources while Sources is {outer}px "
            f"under the answer — the two strips are one block, so the gap inside it "
            f"has to be the smaller one"
        )

    # A zero-width control in this corner is the exact bug that shipped twice with the
    # model picker: present in the DOM, invisible on screen. The floor is lower than it
    # was — 40px against 80 — because the thing being measured changed size. The picker
    # showed a served model id and could not be narrower than one; the Think pill shows
    # one short word beside a 14px icon and measures 72px at every width in the running
    # app. A floor above that would fail on a correct control, and a floor at zero
    # would not catch the bug it exists for, so it sits between the two: wide enough
    # that a collapsed pill is caught, narrow enough that a deployment whose word is
    # shorter than "Think" still passes.
    picker = els.get(PICKER)
    if picker and picker["right"] - picker["left"] < 40:
        problems.append(
            f"{where}: the Think pill is only "
            f"{picker['right'] - picker['left']}px wide (collapsed)"
        )

    # No slack bound any more, and its absence is deliberate. `MAX_PICKER_SLACK` held
    # the picker's width to the longest model id it could show rather than to a round
    # number, and the pair of bounds under it caught a name being ellipsed. The pill
    # has no width rule at all — it is sized by one word that does not change between
    # its two states — so there is no declared width for a measurement to disagree
    # with, and a slack check would only be re-measuring the browser's own text
    # layout. What is still worth holding is that it fits in the box beside the send
    # button, which the containment and overlap bounds below do.

    # The picker belongs INSIDE the input box, in its bottom-right corner beside the
    # send button. This bound used to say the opposite — that the controls must sit
    # under the input and never on it — because they were a row below it that the bar
    # padded a band for. That row is gone, and with it a little over 4rem of window
    # given to one control, so the requirement is inverted: the picker is in the box.
    #
    # Checked as containment rather than as "it overlaps somewhere", because app.js
    # places it from a measurement off the send button and a stale or absent
    # measurement would leave it hanging off an edge. Its clickability is checked
    # separately (`picker`, below) and matters more here than it did on the page: the
    # textarea is now behind it.
    box = els.get(INPUT_BOX)
    if picker and box:
        out = []
        if picker["top"] < box["top"] - 1:
            out.append(f"{round(box['top'] - picker['top'])}px above its top")
        if picker["bottom"] > box["bottom"] + 1:
            out.append(f"{round(picker['bottom'] - box['bottom'])}px below its bottom")
        if picker["right"] > box["right"] + 1:
            out.append(f"{round(picker['right'] - box['right'])}px past its right edge")
        if picker["left"] < box["left"] - 1:
            out.append(f"{round(box['left'] - picker['left'])}px past its left edge")
        if out:
            problems.append(
                f"{where}: the model picker is outside the input box — "
                + ", ".join(out)
            )
    # And it must share the band with the other two controls rather than sit on either.
    # It is at the band's left end now, past the paperclip, with the send button at the
    # far end — the arrangement ChatGPT and Claude both use, and the one that stopped
    # the picker and the arrow fighting for the same corner.
    send_btn, clip = els.get(SEND), els.get("#paperclip-btn")
    if picker and send_btn and picker["right"] > send_btn["left"] + 1:
        problems.append(
            f"{where}: the model picker overlaps the send button by "
            f"{round(picker['right'] - send_btn['left'])}px"
        )
    if picker and clip and picker["left"] < clip["right"] - 1:
        problems.append(
            f"{where}: the model picker overlaps the paperclip by "
            f"{round(clip['right'] - picker['left'])}px"
        )

    # The chips belong to the composer, immediately above the box. They used to render
    # in the flow, which put them under the starter cards in the middle of the page —
    # "at a random spot in the middle of the ui" — so both halves of that are checked:
    # above the input, and not adrift from it.
    box = els.get(INPUT_BOX)
    if chip_row and box:
        if chip_row["bottom"] > box["top"] + 1:
            problems.append(
                f"{where}: the attachment chips overlap the input box by "
                f"{chip_row['bottom'] - box['top']}px"
            )
        elif box["top"] - chip_row["bottom"] > MAX_CHIP_GAP:
            problems.append(
                f"{where}: the attachment chips are {box['top'] - chip_row['bottom']}px "
                f"above the input box (want at most {MAX_CHIP_GAP} — they are part of "
                f"the composer, not of the page)"
            )

    # The composer is two rows: the text, and a band of controls under it. It used to be
    # one — the text between the paperclip and the send button — and three bounds here
    # held that: the cursor within 16px of the clip, and each button level with the line
    # of text beside it. All three are gone, because the thing they described is gone.
    # The model picker floated into that single row is what took them out: on the
    # deployment it covered the reader's own question.
    #
    # What replaces them is the contract of a band. The three controls are level with
    # EACH OTHER rather than with the text, they are all inside the box, and none of
    # them is over the text — which is the property the old arrangement could not have
    # and the reason for the change.
    clip_el, send_el = els.get("#paperclip-btn"), els.get(SEND)
    row = [(name, box_) for name, box_ in
           (("paperclip", clip_el), ("model picker", picker), ("send button", send_el))
           if box_ and box_["bottom"] - box_["top"] > 0]
    if len(row) > 1:
        floors = [box_["bottom"] for _, box_ in row]
        spread = round(max(floors) - min(floors))
        if spread > MAX_BAND_SPREAD:
            names = ", ".join(name for name, _ in row)
            problems.append(
                f"{where}: the controls in the composer's band are {spread}px out of "
                f"line with each other ({names}; want within {MAX_BAND_SPREAD} — they "
                f"are one row)"
            )

    # Under the text is the band of controls, and it is bounded at both ends: too small
    # and a control is on the text, too large and the box has a strip of nothing in it.
    # This used to be "at most 32px of dead space", which was right when the controls
    # shared the text's row and everything below it was padding.
    box, area = els.get(INPUT_BOX), els.get(INPUT)
    if box and area:
        under = round(box["bottom"] - area["bottom"])
        if not MIN_CONTROL_BAND <= under <= MAX_CONTROL_BAND:
            problems.append(
                f"{where}: {under}px between the end of the text and the bottom of the "
                f"input box (want {MIN_CONTROL_BAND}-{MAX_CONTROL_BAND} — that space "
                f"is the band the paperclip, the picker and the send button sit in)"
            )
    # Nothing in the band may be over the text. This is what the whole two-row layout
    # is for: the reader's screenshot showed a question running underneath the model
    # picker, and the send button had the same exposure at every width.
    for name, ctl in (("send button", send_el), ("model picker", picker),
                      ("paperclip", clip_el)):
        if ctl and area and ctl["top"] < area["bottom"] - 1 and area["lines"] > 0:
            problems.append(
                f"{where}: the {name} is over the text by "
                f"{round(area['bottom'] - ctl['top'])}px — a long question would run "
                f"underneath it"
            )

    # The stop square, checked from both sides.
    #
    # While an answer streams it has to BE there. app.js injects it, and an injector
    # that silently matches nothing is a button the reader reaches for and does not
    # find — the same failure mode the copy-button check below exists for. And it has
    # to be in the corner the arrow was in a moment ago, because that swap is the
    # whole design: a square that lands anywhere else is a second control rather than
    # the send button changing state.
    #
    # When nothing is generating it has to be GONE. Left on the page it sits directly
    # on top of the arrow at the same absolute corner, and the composer cannot send.
    stop = els.get(STOP)
    # A square that is present and invisible is a square the reader cannot press, so
    # it counts as missing rather than as a badly-placed one. Without this the "no
    # stop button" branch below was unreachable — anything that hid the square left a
    # zero rectangle behind, which reported as 1010px of corner drift instead of as
    # the control being gone.
    if stop and stop["right"] - stop["left"] <= 0:
        stop = None
    if generating:
        if not stop:
            problems.append(
                f"{where}: no stop button while an answer generates — app.js found "
                "nothing to inject into or nothing to wire to, so the reader has no "
                "way to call the turn off"
            )
        else:
            if send_el:
                drift = max(abs(stop["right"] - send_el["right"]),
                            abs(stop["bottom"] - send_el["bottom"]))
                if drift > MAX_SWAP_DRIFT:
                    problems.append(
                        f"{where}: the stop square is {drift}px off the send button's "
                        f"corner (square right/bottom {stop['right']},{stop['bottom']};"
                        f" arrow {send_el['right']},{send_el['bottom']}) — the arrow is "
                        "supposed to become the square, not be joined by it"
                    )
            side = min(stop["right"] - stop["left"], stop["bottom"] - stop["top"])
            if side < MIN_CONTROL_SIDE:
                problems.append(
                    f"{where}: the stop square's smallest side is {side}px "
                    f"(want at least {MIN_CONTROL_SIDE})"
                )
            # Over the text, not merely to the left of it. The square is in the band
            # under the text now, in the send button's place, so "its left edge is
            # inside the text's width" is true by design and says nothing.
            if area and stop["top"] < area["bottom"] - 1 and area["lines"] > 0:
                problems.append(
                    f"{where}: the stop square overlaps the text by "
                    f"{round(area['bottom'] - stop['top'])}px"
                )
    elif stop and stop["right"] - stop["left"] > 0:
        problems.append(
            f"{where}: the stop square is still on the page with nothing generating — "
            "it is in the send button's corner, so the composer cannot send"
        )

    # The box a reopened question is edited in.
    #
    # It replaces a bubble, so it has to stand where the bubble stood. A question in
    # this app is always on the right — the bubble is a flex item pushed to the end of
    # its row and capped at 78% of the width — and the editor's first version ignored
    # all of that and filled the column from the left margin. Nothing was broken;
    # it just read as a different page. So this checks the two things that make it
    # read as the same one: it starts past the middle, and it ends where a bubble ends.
    # ONE property, deliberately: which side of the page it is on.
    #
    # How WIDE it is cannot honestly be judged here. A Streamlit form sizes itself
    # from rules this repo cannot see, and the replica gets it wrong by more than
    # half — 223px against the 515px the same box measures in the running app — so a
    # bound on its width or on where its right edge falls would be a bound on the
    # replica. The side is not like that: `margin-left: auto` is app.css's own, it is
    # the whole of the fix, and it lands the same way whatever the box's width. The
    # rest of this screen is checked by driving the real app.
    editor = els.get(EDITOR)
    if editor and editor["left"] < data["viewport"]["w"] / 2:
        problems.append(
            f"{where}: the question editor starts at {editor['left']}px, left of the "
            f"middle of a {data['viewport']['w']}px window — questions in this app are "
            "right-aligned, so editing one throws it across the page and back"
        )

    # The pencil that reopens a question. Its whole claim is that it costs the
    # transcript nothing: it goes in the gutter to the left of a bubble that stops at
    # 78% of the width, so it must be clear of the bubble and on the page at every
    # width. Overlapping the bubble would put it on top of the question text at the
    # one width where the question is long enough to reach its own maximum.
    pencil, bubble = els.get(EDIT), els.get(".user-bubble")

    # The copy button is the pencil's neighbour and outlives it: it stays through a
    # turn, because putting a question on the clipboard costs nothing and reruns
    # nothing. So it is checked in every state, and it is the one that decides whether
    # the pair still fits in the gutter.
    qcopy = els.get(QCOPY)
    if bubble and state != "unmeasured":
        if not qcopy or qcopy["right"] - qcopy["left"] <= 0:
            problems.append(
                f"{where}: no copy button beside a question — app.js injected "
                "nothing, so a sent question cannot be copied"
            )
        else:
            if qcopy["right"] > bubble["left"] + 1:
                problems.append(
                    f"{where}: the question's copy button overlaps its bubble by "
                    f"{qcopy['right'] - bubble['left']}px"
                )
            if qcopy["left"] < 0:
                problems.append(
                    f"{where}: the question's copy button is {-qcopy['left']}px off "
                    "the left edge of the page"
                )
            side = min(qcopy["right"] - qcopy["left"], qcopy["bottom"] - qcopy["top"])
            if side < MIN_CONTROL_SIDE:
                problems.append(
                    f"{where}: the question's copy button's smallest side is {side}px "
                    f"(want at least {MIN_CONTROL_SIDE})"
                )
            if pencil and pencil["right"] - pencil["left"] > 0 and (
                qcopy["right"] > pencil["left"] + 1
            ):
                problems.append(
                    f"{where}: the question's copy button and pencil overlap each "
                    f"other by {qcopy['right'] - pencil['left']}px"
                )

    if generating:
        # Disabled for the length of a turn, and app.css hides a disabled one, so a
        # rectangle here means the reader is being offered a control that cannot work.
        if pencil and pencil["right"] - pencil["left"] > 0:
            problems.append(
                f"{where}: a question still offers an edit pencil while an answer "
                "generates — clicking it would abandon the answer on screen"
            )
    elif bubble and state != "unmeasured":
        if not pencil or pencil["right"] - pencil["left"] <= 0:
            problems.append(
                f"{where}: no edit control on a question — app.js paired nothing, so "
                "a sent question cannot be corrected"
            )
        else:
            if pencil["right"] > bubble["left"] + 1:
                problems.append(
                    f"{where}: the edit pencil overlaps the question bubble by "
                    f"{pencil['right'] - bubble['left']}px"
                )
            if pencil["left"] < 0:
                problems.append(
                    f"{where}: the edit pencil is {-pencil['left']}px off the left "
                    "edge of the page"
                )
            side = min(pencil["right"] - pencil["left"],
                       pencil["bottom"] - pencil["top"])
            if side < MIN_CONTROL_SIDE:
                problems.append(
                    f"{where}: the edit pencil's smallest side is {side}px "
                    f"(want at least {MIN_CONTROL_SIDE})"
                )

    if generating:
        # The question may leave the top of the window — but only because the answer
        # needed the room.
        #
        # This used to require it on screen unconditionally, written against a version
        # that pinned to the DOCUMENT's bottom: the document reserves a bar's height
        # plus a gap below the last message, so that scroll pushed the question off the
        # top *and* left a third of the window empty above the composer. Following the
        # tail instead cannot do that — it stops at one gap above the composer — and
        # requiring the question on screen forbade following a reply longer than the
        # window at all. That shipped, and it read as the page freezing: the view
        # arrived on send, then every token after the first screenful streamed in below
        # the fold with nothing moving.
        #
        # So the two are told apart by what is at the BOTTOM. A question above the fold
        # with the newest text against the composer is a reader watching an answer
        # arrive; a question above the fold with a screenful of nothing under the text
        # is the old bug, and that is what this now catches.
        asked = els.get("last:.user-bubble")
        finished = max(
            (b for sel, b in els.items()
             if b and sel in (".st-key-answer-5", ".st-key-answer-0", ".stChatMessage")),
            key=lambda b: b["bottom"], default=None,
        )
        composer = els.get('[data-testid="stBottomBlockContainer"]')
        if asked and asked["top"] < data["hostBar"]:
            slack = (composer["top"] - finished["bottom"]
                     if composer and finished else None)
            if slack is None or slack > MAX_TAIL_GAP:
                problems.append(
                    f"{where}: the question is {data['hostBar'] - asked['top']}px above "
                    f"the fold while its answer generates, and the text under it stops "
                    f"{slack}px short of the composer — so the view scrolled past the "
                    f"answer rather than following it"
                )
        # And not below it either. Sending a follow-up from halfway up a long
        # conversation left the reader where they were, with the question and the answer
        # arriving off the bottom of the screen — "i have to scroll down myself". The
        # scroll that fixes it is app.js's per-turn pin, so this is the check that the
        # pin actually ran.
        if asked and asked["top"] > data["viewport"]["h"]:
            problems.append(
                f"{where}: the question is {asked['top'] - data['viewport']['h']}px "
                "below the fold while its answer generates (the per-turn scroll did "
                "not run)"
            )
        # And not the other way either. The slack that sits a *finished* short
        # conversation above the composer was also being applied to a question with
        # a "Reading…" row under it, which put the question halfway down the window
        # with the answer arriving into the bottom of it and the top half empty.
        # Reported as "way below the top of the page, which looks very off".
        # 0.35 rather than 0.4 of the window. At 0.4 this cleared the failure it
        # exists to catch by two pixels at 966×626 — a guard that passes by 2px is
        # one font metric away from not passing at all. With the slack suppressed
        # mid-turn the question sits ~100px down at every width, so the tighter
        # ceiling costs nothing and buys ~30px of margin at the narrowest window.
        ceiling = round(data["viewport"]["h"] * 0.35)
        # …and only where the layout could do anything about it, which is what the
        # scroll left below the view says. The question can only be raised by moving
        # the page, so a window with less scroll remaining than the lift needed is
        # being asked for something the geometry forbids.
        #
        # This used to read `not atEnd` — the view being within 2px of the document's
        # end — and that is the same test only while the app scrolls to the end, which
        # it does not. Mid-turn `autoScroll` follows the TAIL and stops one
        # `--tail-gap` above the composer; the document reserves the bar's height plus
        # that gap below the last message, so the view settles some tens of pixels
        # short of the end and the exact number moves with every line the answer or
        # the progress block adds. Measured in the running app at 768x900, three turns
        # above and a six-step turn in flight: the question sat 474-572px down while
        # the scroll left below it went 0 → 23 → 30 → 18 → 23 → 0 as the block grew.
        # `atEnd` was therefore true on some frames of that turn and false on others,
        # with nothing about the layout differing between them, and the screens that
        # passed it passed by coincidence — `in-flight-steps` and `in-flight-folded`
        # by 1px, until a typeface change moved a rounding by 13.
        #
        # The bound itself is unchanged, and so is what it was written for: a question
        # stranded mid-window with the top half of the page EMPTY, which is the `--fill`
        # slack arriving mid-turn. That shape has the whole slack below the view to
        # scroll through — 463px against a 148px lift when it was reported — so it
        # still fires, and the `--fill` check further down catches it a second time.
        #
        # What the app does instead of lifting the question is written down in
        # `static/app.js`: "Keep the newest text on screen while the answer arrives.
        # NOT bring the question to the top of the viewport" — asked for again on
        # 2026-08-28 and declined there, because putting a question at the top needs a
        # viewport of content beneath it and at send time there is none.
        lift = asked["top"] - ceiling if asked else 0
        if lift > 0 and data.get("scrollRoom", 0) > lift:
            problems.append(
                f"{where}: the question is {asked['top']}px down the window while "
                f"its answer generates (want no lower than {ceiling}, and there is "
                f"{data['scrollRoom']}px of scroll below the view to lift it with)"
            )

    # The progress block, while a turn is working. Its lines are held to one line each
    # by the budgets above and its last line has to clear the composer, which `newest`
    # below is what says. Two things are left, and the first is the one that keeps the
    # rest honest.
    step = els.get(".status-step")
    if scenario.startswith("in-flight-") and not step:
        problems.append(
            f"{where}: this screen models the progress block and no step rendered — "
            f"every check on the block passes here without having looked at anything"
        )
    if step:
        # One column, flush left. The block is a list of lines and a summary above
        # them; the `<details>` marker is drawn INSIDE the summary's box for exactly
        # this reason, because outside it the marker hangs into the message's own left
        # margin and the line it belongs to starts somewhere the others do not.
        for sel in ("last:.status-step", ".status-summary"):
            other = els.get(sel)
            if other and abs(other["left"] - step["left"]) > 1:
                problems.append(
                    f"{where}: {sel} starts {round(other['left'] - step['left'])}px "
                    f"off the left edge of the step column — the block is one list, "
                    f"and a line of it that does not line up reads as a broken indent"
                )

    # An OPEN popover is meant to cover the page: that is what an overlay is, and
    # clicking the thing underneath is how a reader dismisses it. So on the screens
    # that render one, the composer being covered is the feature, and what has to stay
    # reachable is the panel's own buttons — which are in INTERACTIVE and are checked.
    # Nothing is exempt any more. This held the controls the open model-picker panel
    # was allowed to cover; the picker is gone, `st.popover` is used nowhere in the
    # app, and a control this file cannot reach is now a control that is broken.
    covered_by_overlay: set[str] = set()
    # And the send button is deliberately unreachable while an answer generates: the
    # stop square is in its corner, which is the swap the reader asked for. The check
    # above reads that as "something is on top of the send button", which it is — so
    # this is the one state where that is the feature. The square itself is in
    # INTERACTIVE and is hit-tested in its place, so the corner is still checked; what
    # is exempt is only the button underneath it.
    if generating:
        covered_by_overlay = covered_by_overlay | {SEND}
    for sel in INTERACTIVE - covered_by_overlay:
        b = els.get(sel)
        # 'offscreen' is covered by the geometry checks above and is expected for
        # in-flow content once the page is scrolled. What this is here to catch is
        # a control that is on screen with something painted over it.
        if b and b["hit"] and b["hit"] != "offscreen":
            problems.append(f"{where}: {sel} is not clickable — {b['hit']} is on top")

    # The picker is the one control with no second home on the landing screen, so
    # it has to be reachable in every scenario and every scroll state.
    if picker and picker["hit"]:
        problems.append(f"{where}: the model picker is unreachable ({picker['hit']})")

    # Inside an answer: the two things that were drawn on top of it or off the end of
    # it, neither of which any check here could see until the elements were named.
    copy, prose = els.get(ANSWER_COPY), els.get(ANSWER_TEXT)
    if prose and state != "unmeasured" and not copy:
        # Without the button there is nothing to overlap, so the check below would
        # pass on a screen it cannot judge. app.js matches finished answers by their
        # keyed container; if that stops matching, this says so rather than going
        # quiet.
        problems.append(
            f"{where}: no copy button on a finished answer — app.js matched nothing, "
            f"so the overlap check cannot fail here"
        )
    if copy and prose and prose["right"] > copy["left"] + 1:
        problems.append(
            f"{where}: the copy button is painted over the answer's first line "
            f"({prose['right'] - copy['left']}px of overlap) — an absolutely "
            f"positioned corner is only free if the text stops before it"
        )

    # A table wider than the answer column. `html`/`body` hide the document's
    # horizontal overflow, so anything past the window edge is not merely ugly, it is
    # unreachable: at a phone width the partition table lost half its columns with no
    # gesture that could bring them back.
    table = els.get(ANSWER_TABLE)
    if table and prose and table["right"] > prose["right"] + 1:
        problems.append(
            f"{where}: the table runs {table['right'] - prose['right']}px past the "
            f"answer column (the page clips its own horizontal overflow, so that part "
            f"cannot be scrolled to)"
        )

    asked, answered = els.get(".user-bubble"), els.get(".st-key-answer-0")
    if asked and answered:
        gap = answered["top"] - asked["bottom"]
        low, high = GAP_QUESTION_TO_ANSWER
        if not low <= gap <= high:
            problems.append(
                f"{where}: {gap}px between the question and its answer "
                f"(want {low}–{high})"
            )

    # The bottom of the conversation, whatever ended it — a trailing failover
    # notice is part of it, and measuring only the answer above one is how the
    # space under it stayed dead while this harness reported a pass.
    newest = max(
        (b for sel, b in els.items()
         if b and sel in (".st-key-answer-5", ".st-key-answer-0", ".error-card",
                          ".st-key-error-actions", ".notice",
                          # A queued question is the last thing on the page when
                          # there is one, so it is what must clear the composer.
                          QUEUED_NOTE,
                          # And so is the progress block, for as long as the turn is
                          # working: it grows a line per tool call, and on the screens
                          # where nothing has been answered yet it is the only thing
                          # the page has to leave room for. Measured at its last step
                          # rather than at the block, because a block whose own box is
                          # clear of the composer can still have its sixth line behind
                          # it if anything inside it overhangs.
                          "last:.status-step")),
        key=lambda b: b["bottom"], default=None,
    )
    reserved = data.get("reserved", {})
    # app.js publishes these in px. Still holding the stylesheet's rem fallback in
    # a state that loads app.js means it never ran, and every measured thing below
    # is then auditing a layout the app only has for one frame. Said out loud,
    # because as a gap number it reads like a spacing bug and is not one: it was a
    # `requestAnimationFrame` that never fired in a browser producing no frames.
    if state != "unmeasured" and reserved.get("bar", "").endswith("rem"):
        problems.append(
            f"{where}: app.js never measured the input bar (--bar-h is still "
            f"{reserved.get('bar')})"
        )

    # Slack above the conversation is for a page shorter than the window. On a page
    # that scrolls it is a gap at the TOP instead — reported as "the top and bottom
    # both have the problem" — and it got there because `fill()` asked stMain whether
    # the page scrolls rather than asking which element does.
    # Measured with the slack subtracted, not as the page stands: a short page that
    # took slack often scrolls *because* of it, and reading the padded page would
    # fire this on every page the slack was right for.
    fill = reserved.get("fill", "0px")
    if (state in ("rest", "settled") and data.get("canScrollUnfilled")
            and fill not in ("", "0px")):
        problems.append(
            f"{where}: {fill} of slack above a conversation that scrolls "
            f"without it (only a page shorter than the window has slack to take)"
        )
    # And none at all on a conversation the reader watched arrive, which is all of
    # them. This is the check for the thing that was actually reported: the padding
    # arriving at the end of a short turn moved the question 463px down the window,
    # and the same padding moved it again whenever the editor opened or closed. Any
    # non-zero value here is that jump coming back.
    if (state != "unmeasured" and "chat-container" in SCENARIOS.get(scenario, "")
            and fill not in ("", "0px")):
        problems.append(
            f"{where}: {fill} of slack was applied to a conversation the reader "
            f"watched arrive — that is the page moving under them at the moment the "
            f"turn ends"
        )

    if newest and bar:
        gap = bar["top"] - newest["bottom"]
        # What the page reserved, versus what the bar actually takes. When these
        # disagree the gap checks below are measuring a stale reservation, which
        # is a different bug from a stylesheet that reserved the wrong amount.
        room = (f"reserved --bar-h {reserved.get('bar', '?')}, bar is really "
                f"{data['viewport']['h'] - bar['top']}px")
        # Scrolled to the very end, nothing may hide under the fixed input — and
        # on a page with nowhere to scroll, nothing may hide under it at all,
        # because the conversation is pinned to the bottom of what was reserved
        # and there is no scroll left to bring it back out.
        if gap < 0 and (state == "scrolled"
                        or (state in ("rest", "unmeasured")
                            and not data.get("canScroll", True))):
            problems.append(
                f"{where}: newest content is {-gap}px under the input bar ({room})"
            )
        # At rest and just-finished are the views a reader is actually left looking
        # at, so they are the ones that must not be a third of a screen of nothing.
        # A negative gap means the reply runs off the bottom, which is theirs to
        # scroll; this is only ever about empty space.
        #
        # Not the first frame: closing this space is app.js's job (it is measured
        # slack, put above the conversation), and that frame's job is only to not
        # hide anything, which the check above covers.
        #
        # Only where there is somewhere to scroll. A conversation shorter than the
        # window now keeps the position it had while it was being answered — the
        # padding that used to slide it down to the composer was a 463px jump at the
        # moment the reader was reading, and "it has to stay at where it is" settled
        # which of the two costs more. So the empty space on a short conversation
        # falls below it, deliberately, and this bound no longer applies there. On a
        # page that DOES scroll the same gap still means the scroll stopped short,
        # which is the failure this was written for and which it still catches.
        if (state in ("rest", "settled") and gap > MAX_TAIL_GAP
                and data.get("canScroll", True)):
            problems.append(
                f"{where}: {gap}px of dead space between the last message and the "
                f"input bar (want at most {MAX_TAIL_GAP}; {room})"
            )

    problems.extend(audit_citations(data, where))
    return problems


def audit_citations(data, where: str) -> list[str]:
    """The Sources and Related lists: aligned rows, and two visibly different lists.

    Both used to be rows of identical chips in a wrapping flexbox with the label as the
    first item, which indents line one and drops every later line back to the container
    edge — 66px of sawtooth with six real citations at 820px. No check could see it,
    because the measurement read only the first chip in the document.
    """
    problems: list[str] = []
    lists = data.get("lists") or {}
    SEEN_SELECTORS.update(
        selector for selector, rows in lists.items() if rows
    )

    for selector in (".source-item", ".related-item"):
        found = lists.get(selector) or []
        if not found:
            continue
        lefts = {row["left"] for row in found}
        if len(lefts) > 1:
            problems.append(
                f"{where}: {selector} rows start at {sorted(lefts)} — a citation list "
                f"whose rows do not share a left edge reads as broken, not as a list"
            )
        # One row per line. Two rows sharing a `top` means they sat side by side, which
        # is the chip layout coming back and the reader losing the numbering's meaning.
        tops = [row["top"] for row in found]
        if len(set(tops)) != len(tops):
            problems.append(
                f"{where}: {selector} put more than one entry on a line (tops {tops})"
            )

    sources, related = lists.get(".source-item") or [], lists.get(".related-item") or []
    if sources and related:
        # Different in a way a reader can see, taken from the marker the cascade
        # resolved rather than from a colour this file also chose. Chromium reports
        # `content` unresolved — `counter(source) "."`, not `"1."` — so both spellings
        # count as numbered; asserting only on a digit passed on the chip layout, whose
        # marker is `none`, and failed on the list that actually numbers its rows.
        marker = sources[0]["marker"]
        numbered = "counter" in marker or any(ch.isdigit() for ch in marker)
        if not numbered:
            problems.append(
                f"{where}: the Sources list is not numbered (marker {marker!r}) — the "
                f"numbering is what distinguishes a citation from a suggestion"
            )
        if related[0]["marker"] == marker:
            problems.append(
                f"{where}: Sources and Related share the marker {marker!r}, so nothing "
                f"but the label tells them apart"
            )

    # And the marker has to occupy real space, or a numbered list renders as an
    # unnumbered one however the stylesheet is written.
    link = data["els"].get(".source-link")
    row = (sources or [None])[0]
    if link and row:
        indent = link["left"] - row["left"]
        if indent < 10:
            problems.append(
                f"{where}: the citation number column reserves only {indent}px, so the "
                f"numbers are not visible beside the titles"
            )
    return problems


def main() -> int:
    global VIEWPORT
    verbose = "-v" in sys.argv
    VIEWPORT = calibrate()
    # The narrowest entry is Chromium's own floor rather than a phone's width, because
    # a headless window will not go below it and a number it silently ignores is worse
    # than an honest one: this list said 414px for a year and rendered 500px. 500 is
    # still under the 640px mobile breakpoint, so the mobile rules are exercised — what
    # is not covered is a real 414px screen, and saying so is the point.
    # 660 is here because it is the tightest width for the starter cards: two
    # columns, just above the 640px breakpoint that would stack them, so the
    # longest label has the least room it ever gets. Without it the one-line rule
    # was unenforced across the whole 641-760 band.
    widths = [(1440, 1080), (1263, 900), (966, 626), (768, 900), (660, 900),
              (VIEWPORT["min_w"], PHONE_H)]
    failures: list[str] = []
    checked = 0

    for scenario, body in SCENARIOS.items():
        for scheme in ("dark", "light"):
            for width, height in widths:
                # the first frame before app.js has measured the bar, at rest,
                # scrolled to the bottom, mid-generation (app.js pinning the
                # question), and just-finished (app.js closing the dead space the
                # pin left behind).
                if scenario.startswith("landing"):
                    states = ["unmeasured", "rest"]   # no turn to be in the middle of
                elif scenario == "think-on":
                    # The pill is the same whatever the conversation behind it is
                    # doing, so scrolling and generating would re-measure one control.
                    states = ["unmeasured", "rest"]
                elif scenario.startswith("composing"):
                    # What these two are for is the inside of the input box, and that
                    # is the same whether the page is scrolled or an answer is in
                    # flight. Three more states each would be 60 renders and a minute
                    # of CI to re-measure an identical box.
                    states = ["unmeasured", "rest"]
                elif scenario == "in-flight":
                    states = ["generating"]           # it *is* the mid-turn screen
                elif scenario.startswith("in-flight-"):
                    # Mid-turn, which is when the progress block exists, and scrolled
                    # to the end, which is the state its clearance bound fires in:
                    # `newest` counts the block's last step, so this is what would
                    # catch a sixth line hiding under the composer. Both are real
                    # frames — the block is on the page for the whole tool loop and
                    # for as long as the answer takes to arrive after it.
                    states = ["generating", "scrolled"]
                elif scenario == "queued":
                    # Mid-turn, which is when a queue exists, and scrolled to the end,
                    # which is the state the clearance bound below actually fires in:
                    # `newest` counts the queued row, so this is what would catch it
                    # hiding under the composer. Both are real frames — the row also
                    # exists for the moment between the turn ending and the queue
                    # draining, and nothing has scrolled it away by then.
                    states = ["generating", "scrolled"]
                elif scenario == "wide-answer":
                    # What this screen is for is the width of what is inside an
                    # answer, and that does not change with the scroll position or
                    # with a turn being in flight. Two states, for the same reason
                    # the picker renders two.
                    states = ["unmeasured", "rest"]
                else:
                    states = ["unmeasured", "rest", "scrolled", "generating",
                              "settled"]
                for state in states:
                    suffix = "" if state == "rest" else f"-{state}"
                    name = f"{scenario}-{scheme}-{width}{suffix}"
                    html = page(body, scheme, scroll=state == "scrolled",
                                generating=state == "generating",
                                pin=state == "settled",
                                script=state != "unmeasured",
                                sticky=scenario in STICKY_BAR,
                                doc_scroll=scenario in DOC_SCROLL,
                                typed=scenario in TYPED_INPUT,
                                landing=scenario.startswith("landing"),
                                column_input=scenario in COLUMN_INPUT,
                                queued=QUEUED.get(scenario, ()),
                                portal="")
                    data = render(name, html, width, height,
                                  shot=(scheme == "dark" and width == 1263
                                        and state == "rest"))
                    if data is None:
                        failures.append(f"{name}: render failed")
                        continue
                    checked += 1
                    # Every measurement below is only about the viewport it was taken
                    # in, so a viewport that is not the one asked for invalidates the
                    # render rather than failing a check inside it.
                    got = (data["viewport"]["w"], data["viewport"]["h"])
                    if got != (width, height):
                        failures.append(
                            f"{name}: asked for a {width}x{height} viewport and got "
                            f"{got[0]}x{got[1]} — nothing measured here is about the "
                            f"size it claims"
                        )
                        continue
                    # Same reasoning one step further in: the right viewport in the
                    # wrong typeface measures a page nobody is looking at either, and
                    # unlike the viewport it does not announce itself.
                    #
                    # Asked only of the faces this page actually sets something in.
                    # `document.fonts.check` is false for a face that is declared and
                    # has never been asked for, which is the correct answer and not a
                    # fault: a screen with no code, no badge and no model name on it
                    # has no reason to have fetched the mono. Every screen here has
                    # both today — the picker is on all of them — so this is about the
                    # next screen somebody adds, not about a failure being hidden.
                    families = {box["family"] for box in data["els"].values() if box}
                    missing = [face for face, family in FONT_PROBES.items()
                               if family in families
                               and not data.get("fonts", {}).get(face)]
                    if missing:
                        failures.append(
                            f"{name}: {', '.join(missing)} did not load "
                            f"({FONT_PROBES}), so every width below was measured in "
                            "the fallback face"
                        )
                        continue
                    failures.extend(audit(data, scenario, scheme, width, state))
                    if verbose:
                        print(f"\n--- {name} (usable {data['viewport']['h']}px, "
                              f"scrollTop {data['scrolled']}) ---")
                        for sel, b in data["els"].items():
                            if b:
                                print(f"  {sel:42} top={b['top']:>5} "
                                      f"lines={b['lines']} contrast={b['contrast']}")

    # Two window sizes rather than all six: this stage costs about a second a render
    # and what it varies is the scrollport, not the breakpoint. A tall window and the
    # narrowest one Chromium will open cover both ends of "is the page long enough to
    # put the question at the top yet".
    follow_problems, follow_checked = check_follow(
        [(1263, 900), (VIEWPORT["min_w"], PHONE_H)]
    )
    failures.extend(follow_problems)

    # One width, because what this drives is behaviour rather than a breakpoint: the
    # composer takes a dropped file the same way at every size.
    drop_problems, drop_checked = check_drop(1263, 900)
    failures.extend(drop_problems)

    # Two widths for this one, because where the button lands IS about the window:
    # it is clamped to the viewport and pushed off the composer, and both of those
    # only bite when there is not much room.
    select_checked = 0
    for size in ((1263, 900), (VIEWPORT["min_w"], PHONE_H)):
        select_problems, ran = check_selection(*size)
        failures.extend(select_problems)
        select_checked += ran

    # Which selectors nothing ever matched. Not a style rule: every check keyed on one of
    # these ran its "absent, so nothing to say" branch in all 660 renders, so the number
    # this harness prints is over fewer rules than it appears to be. The Sources strip
    # shipped ragged for months behind a green run for the neighbouring reason — the
    # measurement read only the first chip — and the lesson is the same one.
    unmeasured = [
        selector for selector in list(SELECTORS) + list(LIST_SELECTORS)
        if selector not in SEEN_SELECTORS
    ]
    if unmeasured:
        failures.append(
            f"{len(unmeasured)} selector(s) matched nothing in any of the {checked} "
            "renders, so every check keyed on them passed without looking — this is a "
            "whole-run property, so it fires for a truncated screen list too: "
            + ", ".join(unmeasured)
        )

    print(f"\nChecked {checked} renders across {len(SCENARIOS)} screens, "
          f"2 themes, {len(widths)} widths, plus {follow_checked} follow-up scroll "
          f"sequences, {drop_checked} file-drag sequences and {select_checked} "
          f"text-selection sequences.")
    if failures:
        print(f"\n{len(failures)} problem(s):")
        for problem in dict.fromkeys(failures):
            print(f"  ✗ {problem}")
        return 1
    print("No layout or contrast problems found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The progress block's markup: one line per thing a turn did.

Not in `sage/ui/`, and not for layering's own sake. `ui.turn` builds this block while a
turn is in flight from live `Step` objects; `ui.transcript` builds the same block again
from the dicts a stored answer carries, so a reader who looked away can still open it.
`ui.turn` already imports `ui.transcript`, so the second caller could not import the
first — and two copies of one control's markup is two designs one bug away from
disagreeing with each other.

Streamlit is not imported here. This returns strings.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from . import config


def shown(value) -> str:
    """One tool argument, as a line of the block can hold it.

    Coerced rather than trusted. `llm._parse` guarantees a dict and nothing whatever
    about what is in it, and a model that types its query as a number — `{"query":
    123}` — must not be able to end a turn with an AttributeError dressed up as
    "something went wrong reaching the assistant", which is the failure the previous
    version of this row avoided by printing nothing at all.

    Whitespace is collapsed because a newline in a value is a newline in the middle of
    a row that is one line tall, and `None` becomes empty rather than the word "None".

    The clip is `config.STATUS_ARGUMENT_CHARS` and is about the size of the DOM rather
    than the width of the line — app.css ellipses what is still too wide. It lives in
    `config` because `tools/render_check.py` renders the worst case this produces and
    cannot import this module: its CI job has no Streamlit in it.
    """
    text = " ".join(str("" if value is None else value).split())
    if len(text) <= config.STATUS_ARGUMENT_CHARS:
        return text
    return text[: config.STATUS_ARGUMENT_CHARS - 1] + "…"


def elapsed(seconds: float) -> str:
    """How long something took, in the shortest form that is still honest."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}m{rest:02d}s"


@dataclass
class Step:
    """One thing the turn did, as the block reports it.

    `started` is where its clock started, which is where the previous step's stopped —
    see `Status._mark`. `seconds` is None while it is running and the measurement once
    it has stopped, which is also how the block knows which line is the live one.
    """

    name: str
    detail: str = ""
    started: float = 0.0
    seconds: float | None = None


#: The animated ellipsis, INSIDE `.status-live` and after the message's last element.
#:
#: It was a third child of `.status-row`, beside the dot and the message — which is
#: what put it at the far right of the page whenever the message wrapped. A flex item
#: that has wrapped is as wide as the column it wrapped in, however short its last
#: line, so an ellipsis placed after that item's BOX is placed after the column and not
#: after the words: measured at 611px past the last glyph on a 90-character section
#: title at 1440, and drifting less the closer the last line came to filling its line
#: (63px at 160 characters). That sawtooth is why it looked intermittent — "it still
#: drifts sometimes" — and why the bound written for the first version of this bug could
#: not see it: that one measured the wrapper's right edge, which is 8px from the
#: ellipsis at every length.
#:
#: In the message's own inline flow the ellipsis is at the end of the text rather than
#: at the end of a box, so it rides with the last word and wraps when the words wrap.
#: `tools/render_check.py` holds it there against the last GLYPH, per row, across a
#: sweep of message lengths — and holds it to being on the same LINE as that glyph,
#: which is the second half of the story and is `_argument_html`'s to tell.
ELLIPSIS = (
    '<span class="status-dots" aria-hidden="true"><span></span><span></span>'
    "<span></span></span>"
)


def status_html(text: str) -> str:
    """The line a turn opens with, and the one it waits on between rounds.

    What this app has always drawn there, in the order it has always drawn it — the one
    thing that moved is the nesting of the animated ellipsis, which is now inside
    `.status-live` with the words (see `ELLIPSIS`). It is the first thing a reader sees
    on every turn, and the block below only ever adds to it.
    """
    return (
        '<div class="status-row" role="status" aria-live="polite">'
        '<span class="status-dot" aria-hidden="true"></span>'
        '<span class="status-live">'
        f'<span class="status-text">{html.escape(text)}</span>'
        f"{ELLIPSIS}</span></div>"
    )


def live_html(step: Step) -> str:
    """The sweeping row, naming the step that is actually running.

    Same one-line shape as `status_html` and the same gradient, with the tool's
    reader-facing name where the fixed phrase was and its argument beside it. No ✓ and
    no time: neither is true yet.

    This is the third position this row has held, and the two before it were both
    reported. It drew a step per call and KEPT them, which by the third round was six
    rows of history stacked over an empty answer — "it's everything showing, which looks
    bad", "it should be like what we had before with the cool status message with
    gradients". So it became one line carrying a fixed phrase from the profile, and that
    was too little: "it stills shows searching the relevant doc and things like that
    rather than very specific cot shown in the status message". One line, specific, is
    what both complaints leave — the accumulation was the fault, not the detail.

    The argument is its own element rather than part of the text beside it, for the
    reason `_argument_html` records: the live text is a gradient clipped to its glyphs,
    so a child of it inherits `-webkit-text-fill-color: transparent` with no background
    of its own and is invisible.

    A section title is long enough to WRAP this row, which is the one shape the row's
    geometry had never been measured in: the ellipsis belongs after the last word (see
    `ELLIPSIS`) and the leading dot belongs beside the first line (`.status-row` in
    app.css), and both of those were wrong until they were looked at.
    """
    # Name and argument inside ONE `.status-live` wrapper, which is what carries the
    # gradient. A `background-clip: text` sweep on the name alone lit the name, left the
    # argument in the flat muted colour beside it and lit the animated ellipsis after
    # that: "it illuminates search and the middle part is dark and then '...' gets
    # gradient. it looks weird." One background across one element clips to every glyph
    # inside it, so the band crosses the whole message once, smoothly.
    #
    # The ellipsis goes inside the argument, glued to its last word — `_argument_html`
    # says why. With no argument there is no last word to glue it to and it follows the
    # name, which cannot be orphaned: the name is one short word at the start of a line.
    return (
        '<div class="status-row" role="status" aria-live="polite">'
        '<span class="status-dot" aria-hidden="true"></span>'
        '<span class="status-live">'
        f'<span class="status-text">{html.escape(step.name)}</span>'
        f"{_argument_html(step.detail, ELLIPSIS) or ELLIPSIS}</span></div>"
    )


def _argument_html(detail: str, trailing: str = "") -> str:
    """The machine's half of a line: a path, a query. Monospace, and nothing else.

    Its own element rather than part of the text beside it, because the live line's
    text is painted as a gradient clipped to the glyphs — a child of it inherits
    `-webkit-text-fill-color: transparent` with no background of its own to show
    through, which is a value the reader cannot see at all.

    `trailing` — the animated ellipsis, on the live row only — is put inside a
    `white-space: nowrap` span with the value's LAST WORD, so that when there is no room
    for it the word comes down to the next line with it. Being in the text flow is what
    keeps the ellipsis beside the words at all (see `ELLIPSIS`); being in the flow as an
    atomic inline is what let it wrap *alone*, to the left margin a line below the last
    word, which reads as more disconnected than the gap it replaced rather than less.
    Chrome allows that break whatever character precedes the ellipsis — WORD JOINER,
    NBSP and ZERO WIDTH JOINER were each measured and none prevents it — and it is the
    containing inline that suppresses it: 0 orphans across 141 column widths, against 34
    without.

    Only when the last word is short (`config.STATUS_TAIL_CHARS`). A query the model
    chose can be one unbroken token of `config.STATUS_ARGUMENT_CHARS`, and `nowrap`
    around that would defeat the `overflow-wrap: anywhere` that lets it break mid-token
    and keeps it inside the column — 127px of overflow, measured. Nothing is lost by
    falling back: a last word that long fills its own line, so there is no room left for
    the ellipsis to be orphaned from.
    """
    if not detail:
        return ""
    head, space, tail = detail.rpartition(" ")
    if trailing and len(tail) <= config.STATUS_TAIL_CHARS:
        return (
            f'<span class="status-arg">{html.escape(head)}{space}'
            f'<span class="status-tail">{html.escape(tail)}{trailing}</span></span>'
        )
    return f'<span class="status-arg">{html.escape(detail)}</span>{trailing}'




def _done_html(step: Step) -> str:
    """A step that has finished: what it was, on what, and how long it took."""
    return (
        '<div class="status-step">'
        '<span class="status-mark" aria-hidden="true">✓</span>'
        f'<span class="status-name">{html.escape(step.name)}</span>'
        f"{_argument_html(step.detail)}"
        f'<span class="status-time">{elapsed(step.seconds or 0.0)}</span>'
        "</div>"
    )


def steps_html(steps: list[Step]) -> str:
    """The finished steps, as rows. Only ever drawn inside the folded block.

    It used to take a `live` step and append a row for it, and `_live_html` drew that
    row — both went when the live block went back to being the sweeping phrase. The
    only caller is `summary_html`, which has no live step by definition: it is built
    once the answer has started. A parameter whose one caller always passes `None` is
    a shape the next reader has to rule out by hand.
    """
    rows = [_done_html(step) for step in steps if step.seconds is not None]
    return (
        '<div class="status-block" role="status" aria-live="polite">'
        + "".join(rows)
        + "</div>"
    )


def summary_html(steps: list[Step], seconds: float) -> str:
    """The one line the block becomes once the answer starts arriving.

    A `<details>`, which is the whole reason the steps can still be opened during a
    turn: it is the browser's own disclosure, so expanding it never reaches the server.
    A Streamlit control here would be a widget, a widget click is a rerun, and a rerun
    during a turn aborts the answer the summary is about.
    """
    count = len(steps)
    label = "1 step" if count == 1 else f"{count} steps"
    return (
        '<details class="status-done">'
        f'<summary class="status-summary">{label} · {elapsed(seconds)}</summary>'
        + steps_html(steps)
        + "</details>"
    )

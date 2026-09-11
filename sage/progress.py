"""The progress block's markup: one line per thing a turn did.

Not in `sage/ui/`, and not because of layering for its own sake. `ui.turn` builds this
block while a turn is in flight from live `Step` objects; `ui.transcript` builds the
same block again from the dicts a stored answer carries, so a reader who looked away
can still open it. `ui.turn` already imports `ui.transcript`, so the second caller
could not import the first — and two copies of one control's markup is two designs
one bug away from disagreeing with each other.

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


def status_html(text: str) -> str:
    """The line a turn opens with, and the one it waits on between rounds.

    Byte for byte what this app has always drawn there, and deliberately so: it is the
    first thing a reader sees on every turn, and the block below only ever adds to it.
    """
    return (
        '<div class="status-row" role="status" aria-live="polite">'
        '<span class="status-dot" aria-hidden="true"></span>'
        f'<span class="status-text">{html.escape(text)}</span>'
        '<span class="status-dots" aria-hidden="true"><span></span><span></span>'
        "<span></span></span></div>"
    )


def _argument_html(detail: str) -> str:
    """The machine's half of a line: a path, a query. Monospace, and nothing else.

    Its own element rather than part of the text beside it, because the live line's
    text is painted as a gradient clipped to the glyphs — a child of it inherits
    `-webkit-text-fill-color: transparent` with no background of its own to show
    through, which is a value the reader cannot see at all.
    """
    return f'<span class="status-arg">{html.escape(detail)}</span>' if detail else ""


def _live_html(step: Step) -> str:
    """The step that is running now: the same row, minus the live region.

    No `role` on it, because the block around it is the one live region — two nested
    ones is the same line announced twice.

    No elapsed time on it either. A number already wrong by the time it is painted
    would have to be driven by a timer to be worth reading, and every frame of that
    timer is a repaint of the block during the one part of a turn a reader is watching.
    The dots are what say this line is the live one; its time arrives with the line
    after it.
    """
    return (
        '<div class="status-row">'
        '<span class="status-dot" aria-hidden="true"></span>'
        f'<span class="status-text">{html.escape(step.name)}</span>'
        f"{_argument_html(step.detail)}"
        '<span class="status-dots" aria-hidden="true"><span></span><span></span>'
        "<span></span></span></div>"
    )


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


def steps_html(steps: list[Step], *, live: Step | None) -> str:
    rows = [_done_html(step) for step in steps if step.seconds is not None]
    if live is not None:
        rows.append(_live_html(live))
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
        + steps_html(steps, live=None)
        + "</details>"
    )

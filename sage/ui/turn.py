"""One turn: the progress block, the tool loop, the answer, and every way it can end."""

from __future__ import annotations

import logging
import time

import streamlit as st

from .. import (
    config,
    feedback,
    history,
    links,
    llm,
    normalize,
    prompts,
    redact,
)
from ..progress import (
    Step,
    shown,
    status_html,
    steps_html,
    summary_html,
)
from ..tools import gather_context
from .access import get_provider
from .state import get_limiter
from .transcript import citations, render_user
from .view import View

logger = logging.getLogger(__name__)

# Why a model refused, in words a user can act on. One entry per failover kind — the
# notice reads "{model} is unavailable ({reason})", so a kind with no entry here puts
# its own internal name in front of the reader: "nemotron-3-ultra is unavailable
# (empty)". `tests/test_app_smoke.py` holds the two lists together.
REASONS = {
    "quota": "out of credit",
    "auth": "its key was rejected",
    "allowance": "its free allowance is used up",
    "empty": "it returned no answer",
    "rate_limit": "it is refusing requests for now",
    "unavailable": "it is not responding",
    "network": "it could not be reached",
    "unknown": "it failed",
}

# Failures worth trying a different model for, rather than showing a card about. Each
# one means "this model cannot answer and another might"; `View.alternative` decides
# which other, because a spent key and a spent free allowance point in opposite
# directions.
#
# Written as the complement of what cannot be helped by switching, not as a list of
# what can. It was the other way round — three kinds of eleven — and the eight left
# out included the one a reader actually hit: `empty`, a model that answered nothing
# at all, which ended the turn with a card advising a different model while the
# machinery for choosing one sat unused. Reported from the running app on
# `opencode:nemotron-3-ultra-free`. A short deny-list fails safe when a new kind is
# added to `llm._MESSAGES`; a short allow-list fails into that dead end again.
#
# `context` is the exception and the reason it is one: the conversation is too long
# for the *request*, so every model in the lineup gets the same oversized message and
# refuses it the same way. Walking them is a certain failure per model, and the remedy
# is the reader's — clear the chat — which is what the card says.
FAILOVER_KINDS = llm.KINDS - {"context"}

# Streamlit signals "stop this script and start again" by raising. Matched by class
# name rather than imported, because the module those classes live in has moved
# between versions (`scriptrunner.script_runner` → `scriptrunner_utils.exceptions`)
# and because the test stub raises its own equivalents — a name test covers all
# three, an import covers whichever one happened to be installed when it was written.
CONTROL_FLOW_NAMES = frozenset(
    {"RerunException", "StopException", "Rerun", "Stop", "RerunError"}
)

# What the progress block says, and where each part of it comes from.
#
# Two fixed phrases live in the profile (`Copy.status_thinking`, `Copy.status_working`),
# because a deployment over something other than documentation would word them
# differently. Everything else on the block belongs to the turn: one line per tool
# call, named by `View.public_names` — the same reader-facing word `sage.redact` swaps
# into an answer that mentions the tool — with the one argument that tool declared
# worth showing (`View.public_arguments`) beside it, and how long it took after that.
#
# This REVERSES the rule the row shipped with, which was that nothing from inside the
# machine could reach it: not the query, not the path, not the section's own title, on
# the reasoning that a filename is not something a reader can place and that a model's
# query is its wording rather than theirs. The owner asked for the opposite — "the user
# needs to see the detailed status updates and which sections to read etc, this is more
# precise" — so the specifics are on the block now, and the Sources strip under the
# finished answer is no longer the only place they appear. The old reasoning is written
# down here rather than deleted, because it was deliberate and it was about a real
# complaint; what it got wrong was deciding for the reader how much they wanted to see.
#
# What that rule was right about is kept. The argument is whatever the model typed, so
# nothing is trusted about it: `shown` coerces, collapses and clips it, and the row
# ellipses whatever is still too wide (`.status-arg` in app.css) rather than wrapping.
# And the block is progress rather than a log — it collapses to one summary line the
# moment the answer starts arriving, and the steps go back behind a disclosure the
# reader opens if they want them.


def is_control_flow(exc: BaseException) -> bool:
    return type(exc).__name__ in CONTROL_FLOW_NAMES








def call_step(view: View, call: dict) -> tuple[str, str]:
    """What one tool call is called on the block, and the argument worth showing.

    The name is the tool's reader-facing one, so the block and the answer call the same
    thing by the same word — `sage.redact` swaps that word into an answer that names
    the tool, and a row saying `search_docs` while the answer says `search` would be
    two names for one thing. A tool that declares no name falls back to the profile's
    fixed phrase rather than printing the identifier the provider API needs, which is
    nobody's word for anything.

    Which argument to show is the tool's own declaration (`tools.Tool.argument`) rather
    than a branch here on `SEARCH_DOCS` / `READ_DOC`: a deployment that registers a
    third tool gets a line for it by declaring one, and this function never learns its
    name.
    """
    name = call.get("name") or ""
    arguments = call.get("input")
    key = view.public_arguments.get(name, "")
    value = arguments.get(key) if key and isinstance(arguments, dict) else None
    if name in view.section_arguments:
        # A section id is this repository's name for a file, not the documentation's.
        # `docs/allocations.md#how-do-i-check-...` reached the page and was reported
        # immediately — "docs/allocations.md shouldn't be disclosed in this way" — and
        # it is the only place in the app where one did: the Sources strip resolves
        # every id to `Chunk.label` first, and `links.fix_links` does it to the paths a
        # model writes into an answer.
        #
        # So it is resolved to the section's own title, which is the same fact in the
        # reader's terms. An id that does not resolve shows nothing rather than falling
        # back to the string: a model that invented a path has told the reader nothing,
        # and printing the invention is the disclosure this is here to prevent.
        wanted = str(value or "")
        found = view.corpus.chunk(wanted)
        if found is not None:
            value = found.label
        else:
            # A read with no anchor is a whole page, which is a legitimate call and has
            # no chunk id — `Corpus.chunk` keys on `{source}/{path}#{anchor}`. The page
            # still has a title, so it still has a reader-facing name. Without this the
            # row said `read` and nothing at all for every page-level read.
            page = view.corpus.document(wanted.split("#", 1)[0])
            value = page.title if page is not None else ""
    return view.public_names.get(name) or view.copy.status_working, shown(value)














class Status:
    """The progress block: one line per thing the turn did, written in place.

    Each change used to rebuild the row: `slot.empty()` threw the chat bubble away and
    the next line was drawn into a fresh one. Streamlit reconciles that as a removal
    and an insertion, and for exactly one frame the browser laid the page out with the
    new row 32px lower — the row's own height — before it settled back. Measured at
    16ms per hop, on every transition:

        t=4496  top=682  'Searching the documentation'
        t=4510  top=650  'Searching the documentation'          (+14ms)
        t=4994  top=682  'Reading the relevant sections'
        t=5010  gone                                            (+16ms)

    A reader sees that as the line twitching downward each time it changes, which
    reads as instability in the page rather than as progress.

    So the bubble is created once and only what is inside it is replaced. A change is
    then one markdown element rewritten in a node that never leaves the layout — which
    is also why the whole block is a single element rather than one per step: another
    step is a longer string in the same node, not a Streamlit element appended to a
    container, so nothing above it can move and no widget key can collide.

    Reopened lazily because the block is genuinely taken down — by a failure, and by
    the end of a turn — and `st.empty()` cannot be written into again once its parent
    has gone. The steps outlive that: a block taken down and reopened is the same list
    of steps, because they are what the turn did rather than what is on the screen.
    """

    def __init__(self, slot) -> None:
        self._slot = slot
        self._line = None
        self._steps: list[Step] = []
        #: The fixed phrase to show when nothing is running — "Thinking". Cleared by
        #: the tool call that replaces it.
        self._phrase = ""
        self._collapsed = False
        #: The clock the summary line reports. Wall time since the block appeared,
        #: not the sum of the steps: the wait for the first word of the answer belongs
        #: to no step, and it is part of what the reader sat through.
        self._opened = time.monotonic()
        #: Where the next step's clock starts: when the last one stopped.
        #:
        #: A step is therefore the WAIT for that call and not the call itself, and that
        #: is the number worth printing. A search of an in-memory index takes 10-40ms,
        #: so a step timed from the moment `runner.run` is entered reads `0.0s` on
        #: every line of every turn — a column of zeroes, while the two seconds the
        #: reader actually waited sit in the round trip that produced the call and are
        #: attributed to nothing. Timed from the end of the previous step, the lines
        #: add up to the turn.
        self._mark = self._opened

    # --- what happened --------------------------------------------------

    def show(self, text: str) -> None:
        """Wait on a fixed phrase, with whatever has already been done above it."""
        self._stop()
        self._phrase = text
        self._collapsed = False
        self._paint()

    def begin(self, name: str, detail: str) -> None:
        """A tool call, starting now. Its own line, as it happens."""
        self._stop()
        self._phrase = ""
        self._steps.append(Step(name, detail, self._mark))
        self._collapsed = False
        self._paint()

    def collapse(self) -> None:
        """Text has arrived: down to one quiet line the reader can open again.

        A turn that called nothing has nothing to summarise, so it clears instead —
        which is what every turn used to do at this point.
        """
        self._stop()
        self._phrase = ""
        if not self._steps:
            self.clear()
            return
        self._collapsed = True
        self._paint()

    def record(self) -> list[dict]:
        """What this turn did, as plain data for the stored message to carry.

        The block itself dies with the turn — it is painted into an `st.empty()` that
        belongs to the run — so a reader who looked away lost the account of which
        sections were read. This is the same arrangement `sources` already has: the
        turn produces it, the message keeps it, `transcript.render_assistant` draws it
        again. Only finished steps: a step still running when the turn ended is a step
        whose duration is unknown, and a line with no time on it in a settled answer
        reads as a measurement that failed rather than one that was never taken.

        Dicts and not `Step`, because this goes into `session_state` and out to
        `feedback` — a dataclass would be one refactor away from a stored message that
        cannot be read back by the version that reads it next.
        """
        return [
            {"name": step.name, "detail": step.detail, "seconds": step.seconds}
            for step in self._steps
            if step.seconds is not None
        ]

    def clear(self) -> None:
        self._slot.empty()
        self._line = None

    # --- and what that looks like ---------------------------------------

    def _stop(self) -> None:
        """Stop the clock on the running step, if there is one."""
        live = self._live
        if live is not None:
            now = time.monotonic()
            live.seconds = now - live.started
            self._mark = now

    @property
    def _live(self) -> Step | None:
        """The step still running: the last one, while it has no measurement."""
        if self._steps and self._steps[-1].seconds is None:
            return self._steps[-1]
        return None

    def _html(self) -> str:
        if self._collapsed:
            return summary_html(self._steps, time.monotonic() - self._opened)
        if not self._steps:
            return status_html(self._phrase)
        live = self._live or (Step(self._phrase) if self._phrase else None)
        return steps_html(self._steps, live=live)

    def _paint(self) -> None:
        if self._line is None:
            with self._slot.container(), st.chat_message("assistant"):
                self._line = st.empty()
        self._line.markdown(self._html(), unsafe_allow_html=True)


def collapsing(stream, status: Status):
    """Yield deltas, collapsing the block as soon as text arrives.

    Collapsing rather than clearing, which is what this did when the block was one
    line: the steps are what the turn did, and taking them off the page at the moment
    the answer starts is taking them away exactly when the reader has something to
    check them against. What goes is the room they took, not the record.

    A stream carrying no text at all leaves the block as it stands, for the round after
    it to add to — or for the end of the turn to take down. It used to clear here too,
    and with steps on the page that would be a removal and an insertion for every round
    a model narrates nothing, which is the reflow this whole class is shaped to avoid.
    """
    collapsed = False
    for delta in stream:
        if not collapsed:
            status.collapse()
            collapsed = True
        yield delta


def recording(stream):
    """Yield deltas, and keep a copy somewhere a stopped turn can still reach.

    `st.write_stream` accumulates the answer in a local, and a stop throws the run
    holding that local away — so without this the text on screen at the moment of the
    click is gone by the time anything can save it. Session state is what survives an
    interrupted run, which is why the copy goes there and not into a variable.

    One `append` per delta rather than a growing string: an answer arrives in a few
    thousand fragments, and `+=` on a string re-copies the whole answer for each one.
    """
    for delta in stream:
        st.session_state.partial.append(delta)
        yield delta


def paced(stream, interval_ms: int = -1):
    """Yield deltas, joining the ones that arrive inside the same repaint interval.

    `st.write_stream` draws the answer once per delta, and every draw is the *whole*
    answer: the element is replaced with the accumulated text, so the browser reparses
    all of it and re-highlights every code block in it again. That is affordable for
    the tenth delta and not for the thousandth, and a long answer arrives in a few
    thousand of them — the work grows with the square of the answer while the reader
    sees the same words appear either way.

    Which is what a slower laptop feels: a 7.6 KB answer, streamed a word at a time
    against a 4x-throttled CPU, spent 2.6 of its 5.3 seconds with the main thread
    blocked, ran at 14 fps, froze for 1.4s in one go, and moved 1.9 MB over a socket
    to deliver 7.6 KB. The page was not slow because the answer was long. It was slow
    because it was redrawn 1237 times.

    So the deltas are the same and the repaints are fewer. Three rules, and the first
    two are why nothing else in this file had to change:

    * The first delta is always painted at once. `collapsing` folds the status block
      when text arrives, so holding that text back would leave a collapsed summary
      with nothing under it, and time-to-first-word is the one moment of a turn a
      reader is actually watching.
    * A delta that arrives more than an interval after the last repaint is painted at
      once too. A stream slower than the repaint rate is therefore untouched — no
      added latency, and a turn whose deltas are far apart behaves exactly as before.
    * Anything else waits for the delta that crosses the interval, or for the end of
      the stream, whichever comes first. Nothing is dropped, nothing is reordered, and
      joining is `"".join` over what has not been drawn yet, so the finished text is
      identical to the byte.

    The one thing a reader could notice is a burst that lands just before the model
    goes quiet: those words wait for the next delta rather than for the clock, because
    a generator only runs when it is pulled. That is at most one interval's worth of
    text, and it is held during a pause the stream itself introduced.

    Outside `recording`, deliberately: what a stopped turn keeps is what *arrived*, not
    what was painted, so no text a reader was sent is lost to a repaint that had not
    happened yet. The gap between the two is not new and not this generator's doing —
    stopping this answer mid-flow kept 335 and 965 characters more than the screen was
    showing before the change, and 190 and 222 after it, because a browser redrawing
    the whole answer per delta was already further behind the stream than one interval.
    """
    if interval_ms < 0:
        interval_ms = config.STREAM_REPAINT_MS
    if interval_ms <= 0:
        yield from stream
        return
    interval = interval_ms / 1000.0
    held: list[str] = []
    painted: float | None = None
    for delta in stream:
        if not delta:
            continue
        held.append(delta)
        now = time.monotonic()
        if painted is not None and now - painted < interval:
            continue
        painted = now
        yield "".join(held)
        held.clear()
    if held:
        yield "".join(held)


def attempts_allowed(view: View) -> int:
    """How many models this turn may ask, counting the one it started on.

    The lineup is the natural ceiling and `config.MAX_MODEL_ATTEMPTS` only narrows it.
    Nothing else is needed to make the walk terminate: `tried` is what
    `View.alternative` skips, so a turn can never ask the same model twice and "every
    model, once" is finite by construction.

    The fixed three this replaces was a third of the lineup on the deployment it was
    written for, and it was written for one case — several free models spent at the
    same time. Stopping there means stopping while the models that would have answered
    are still on the list, which is the whole complaint.
    """
    limit = config.MAX_MODEL_ATTEMPTS
    ceiling = len(view.models) or 1
    return min(limit, ceiling) if limit > 0 else ceiling


def detail(view: View, exc: BaseException | None) -> str:
    """A one-line, non-secret description of a failure for the details panel."""
    if exc is None:
        return ""
    text = f"{type(exc).__name__}: {exc}"
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    if status:
        text = f"{text}  (HTTP {status})"
    return f"{text}\nmodel={view.model.key}"[:800]


def run(view: View) -> None:
    """Answer the question at the end of the transcript.

    Ends in a rerun on every path that is not already one, because the answer is
    committed to session state and the page has to be redrawn from it — with links
    resolved, the Sources strip under the bubble, and the rating buttons live.
    """
    model = view.model
    runtime = view.runtime

    # Marker element app.js polls to know a generation is in flight.
    st.markdown('<div id="processing-signal" hidden></div>', unsafe_allow_html=True)

    render_user(st.session_state.messages[-1])
    status = Status(st.empty())
    status.show(view.copy.status_thinking)

    answer = st.empty()
    runner = runtime.toolset.runner()
    started = time.monotonic()
    rounds = 0
    final_text = ""
    question = st.session_state.messages[-1].get("text", "")
    # Set only when Streamlit aborts this run from underneath us. The `finally` below
    # must then leave `processing` alone and not issue a rerun of its own: the abort
    # already is one, and clearing the flag on a turn that never finished left the
    # question on screen with no answer, no error and nothing to click.
    interrupted = False

    def record_failure(kind: str) -> None:
        """A turn that produced no answer. Ratings cannot see these — there is nothing
        under the question to rate — so without this the log would describe only the
        turns that went well."""
        feedback.record_turn(
            question=question, outcome="failed", model=model.key, error_kind=kind,
            rounds=rounds, searches=len(runner.queries), sections=len(runner.sources),
            caveats=runner.caveats, seconds=time.monotonic() - started,
        )

    def fail(message: str, why: str) -> None:
        """Surface a failure — and drop any notice, which can only contradict it.

        A leftover "retrying with X…" sitting above "could not complete that
        request" is how the UI ended up arguing with itself.
        """
        st.session_state.error = message
        st.session_state.error_detail = why
        st.session_state.notice = ""
        st.session_state.switched_from = None

    def grounded(messages: list[dict]) -> list[dict]:
        """Retrieve up front, for models that cannot call tools."""
        context, chunks = gather_context(
            runtime.retriever, question, identity=runtime.identity
        )
        for chunk in chunks:
            runner.sources.append(chunk)
        if not context:
            return messages
        return [
            messages[0],
            {
                "role": "system",
                "content": prompts.grounded_instruction(context, runtime.identity),
            },
            *messages[1:],
        ]

    # What the deployment budget is actually counting. A turn is one message to the
    # reader and anywhere from one to MAX_TOOL_ROUNDS + 1 requests to the provider,
    # so this — not the message count — is what the shared key is charged for.
    # Cumulative across every round of this turn — see TOOL_RESULT_CHAR_BUDGET.
    tool_chars = 0

    def start(msgs, schemas):
        # Charged as each request is made, not tallied and committed at the end. A
        # turn that fails halfway, or that the reader abandons by touching the page,
        # still cost the provider the calls it made — and a counter that only commits
        # on success drifts loose exactly when things are going wrong and requests
        # are being retried.
        get_limiter().record_calls(1, time.monotonic())
        # `thinking` read here rather than captured once at the top of the turn, so a
        # failover that lands on a provider which does not take the field carries the
        # flag the NEXT request should have and not the one the first request had.
        # `composer.render_think_toggle` clears it on the run after such a hop, but
        # the hop happens inside this turn, before that run exists — and the adapter
        # is the second guard: it sends the field only where the profile declared it.
        return llm.start(
            provider, model.id, msgs, schemas,
            thinking=bool(st.session_state.thinking),
        )

    try:
        provider = get_provider(model.provider)
        messages = history.build(
            st.session_state.messages,
            runtime.system_prompt,
            vision=config.sees_images(model.id),
        )
        use_tools = model.supports_tools

        if use_tools:
            try:
                turn = start(messages, runtime.tool_schemas)
            except llm.AssistantError as exc:
                if not llm.rejects_tools(exc.original or exc):
                    raise
                # The model does not do tool calls; retrieve up front instead.
                logger.info("%s rejected tools; using single-pass retrieval", model.id)
                use_tools = False
        if not use_tools:
            messages = grounded(messages)
            turn = start(messages, None)

        for round_number in range(config.MAX_TOOL_ROUNDS + 1):
            rounds = round_number + 1
            # Per round, not per turn. `answer.empty()` below wipes the display
            # between rounds, so a stop must keep what is on the screen now — not
            # this round's text appended to a previous round's, which the reader has
            # not been able to see since the tool call that replaced it.
            st.session_state.partial = []
            # `key="live-answer"` so the stylesheet can reserve the copy button's
            # gutter while the answer is still arriving. Without it the streaming
            # answer had the full content width and the stored one — which app.css
            # pads by 2.25rem on `[class*="st-key-answer-"]` — was 36px narrower, so
            # every line re-wrapped and every code block shrank at the instant the
            # turn ended. Measured 660px → 624px at a 1440 viewport.
            #
            # NOT `answer-…`: three places in app.js use `[class*="st-key-answer-"]`
            # as the test for "this is a finished answer" — the copy button, the
            # quote-a-passage control, and the tail measurement. A live container
            # under that name would put a copy button on a half-written answer and
            # offer to quote a sentence still being typed. The name is different and
            # only app.css's gutter rule matches both.
            #
            # Numbered by round, because a widget key has to be unique within a run
            # and this block runs once per tool round. A flat `live-answer` raised
            # `StreamlitDuplicateElementKey` on the second round and took the whole
            # turn out with it — every question that searched before answering died
            # on the error card, which is most of them. Plain answers have one round
            # and never saw it.
            with (
                answer.container(),
                st.container(key=f"live-answer-{round_number}"),
                st.chat_message("assistant"),
            ):
                streamed = st.write_stream(
                    paced(recording(collapsing(turn.deltas(), status)))
                )
            # write_stream returns a list when chunks are not all strings.
            if isinstance(streamed, list):
                streamed = "".join(str(part) for part in streamed)
            # THIS round's text, not the best text seen so far.
            #
            # It used to keep the last non-empty round, and that turned a model's
            # throat-clearing into an answer. Several of them narrate the tool call
            # they are about to make — "Let me search for more specific Midway3
            # hardware details." — and then, if the round after the search comes back
            # with nothing, that sentence was the only text the turn had. It shipped
            # as the reply, with a Sources strip of four documents under it, looking
            # for all the world like a finished answer that had been cut off. Reported
            # from the running app, with the screenshot.
            #
            # A round that ends in a tool call is the model saying what it is about to
            # do; the answer is whatever the round that stops calling tools produces.
            # If that is nothing, the turn produced no answer, and the empty check
            # below turns it into the error card that offers Try again and another
            # model — which is the truth, and is recoverable, in a way that a
            # confident non-answer is not.
            final_text = streamed or ""

            if not turn.tool_calls or not use_tools:
                break
            if round_number == config.MAX_TOOL_ROUNDS:
                # A backstop now, not the ordinary way out. The request that produced
                # this round was sent with no tools at all (see the bottom of the loop),
                # so reaching here means the model wrote a tool call anyway, against an
                # empty tool list — which happens, and is the one case left where the
                # turn genuinely has no prose to show. Kept rather than deleted for
                # exactly that reason; `tests/test_app_smoke.py` holds it.
                logger.warning("Tool-round limit reached without a final answer")
                final_text = final_text or (
                    "I wasn't able to finish looking that up. Please try rephrasing "
                    "your question."
                )
                break

            answer.empty()
            messages.append(turn.as_message())
            for call in turn.tool_calls:
                # Before the call, not after it: the line is what is happening, and a
                # read of a long section is a second or two in which the only thing on
                # the page that could say so is this one. `status.begin` stops the
                # clock on the line above it, so the times are per call rather than
                # per round — a round of parallel calls runs them in this order and
                # reports each one's own.
                status.begin(*call_step(view, call))
                result = runner.run(call["name"], call["input"])
                # The budget is cumulative across rounds, which is the whole point:
                # each result is individually legal at MAX_DOC_CHARS and it is the
                # sum that overruns what was trimmed for before the loop started.
                # Clipped rather than dropped, and told so, because a model handed a
                # truncated section can still answer from it or ask for a narrower
                # one — whereas a silent empty result reads as "no such page".
                room = config.TOOL_RESULT_CHAR_BUDGET - tool_chars
                if len(result) > room:
                    result = (
                        result[: max(0, room)]
                        + "\n\n[Truncated: this turn has reached its reading limit. "
                        "Answer from what you have, or say which section you still "
                        "need.]"
                    )
                tool_chars += len(result)
                messages.append(llm.tool_result_message(call, result))

            # Every call is done and the next request has not gone out yet, so nothing
            # is running: the block waits on the phrase it opened with, under the steps
            # it has. Without this the last step would sit there with its clock stopped
            # and no live line anywhere, which reads as a turn that has stalled — and
            # this wait is most of what the reader is waiting for, because the model
            # thinking about what it just read is the slow part of a round.
            status.show(view.copy.status_thinking)

            # The last request of the turn goes out with the tools withdrawn.
            #
            # The ceiling was never told to the model, and a model that answers every
            # round with another tool call therefore never reached the round that writes
            # prose: it spent the fifth request the way it spent the first, and the loop
            # fell out of the bottom and printed "I wasn't able to finish looking that
            # up" over the top of everything the turn had read. Reported from the running
            # app — a question about a negative service-unit balance, asked three ways,
            # answered none of them, while the section that answers it in one clause was
            # sitting in `messages` having been read twice.
            #
            # Withdrawing the tools is the fix rather than a bigger ceiling because the
            # ceiling is not what binds: given ten rounds both models on the lineup filled
            # ten, rephrasing the same query five times. Rule 3 of the system prompt — "if
            # the first search misses, rephrase the keywords and search again" — has no
            # stopping condition in it, and a fact recorded in a single clause reads as a
            # miss for as long as you keep searching for a page about it. So the app
            # supplies the stopping condition: with nothing left to call, the only move a
            # model has is the answer. `grounded()` above takes the tools away the same
            # way and for the same reason, and its docstring records what happens when you
            # do it without saying so — eight answers in fourteen wrote the call out as
            # text — which is why the instruction goes with it.
            if round_number + 1 == config.MAX_TOOL_ROUNDS:
                messages.append({
                    "role": "system",
                    "content": prompts.last_round_instruction(runtime.identity),
                })
                turn = start(messages, None)
            else:
                turn = start(messages, runtime.tool_schemas)

        status.clear()

        # An answer that is not there. The turn succeeded — no exception, maybe even a
        # search and a read — and the stream carried nothing but whitespace, which the
        # renderer then had nothing to draw: the transcript skips an assistant message
        # with no text, so what the reader was left with was their own question, no
        # reply, no error card and no button. Raised rather than papered over with a
        # sentence, because the useful thing here is the retry and the model switch the
        # error card already offers.
        if not final_text.strip():
            logger.warning("%s returned an empty answer", model.key)
            raise llm.AssistantError("empty")

        # A model reasoning out loud instead of answering. One turn in 554 recorded ones
        # did this: 34,645 characters of it, quoting the instructions back line by line,
        # cut off mid-sentence by the token ceiling, with a Sources strip of six real
        # sections under it. The same outcome as the preamble case above — the model said
        # what it was going to do and never did it — so it takes the same route: the error
        # card, which offers Try again and another model, rather than a wall of monologue
        # dressed as an answer. `normalize` owns the pattern; `evals.checks` counts it.
        if normalize.opens_with_deliberation(final_text):
            logger.warning(
                "%s answered with its own reasoning (%d chars); treating as no answer",
                model.key, len(final_text),
            )
            raise llm.AssistantError("empty")

        # A tool call the model typed instead of making. The same shape of failure one
        # line up, and it arrives by the same door the round limit used to: the last
        # request of a turn goes out with no tools, and a model that wanted to call one
        # anyway has nowhere to put it but the stream. Caught here rather than left to
        # `redact`, which swaps a tool's *name* out of a sentence and would turn a
        # screenful of angle brackets into a slightly more readable screenful of angle
        # brackets. Before the redaction for that reason.
        if normalize.is_written_out_tool_call(final_text):
            logger.warning(
                "%s wrote a tool call out as its answer (%d chars); treating as no answer",
                model.key, len(final_text),
            )
            raise llm.AssistantError("empty")

        # The names of the tools, out of the prose and replaced by what a reader would
        # call them — see `sage/redact.py`. Before the citation strip, so the strip's own
        # diff stays about the strip: `evals/harness.py` records the text at that seam,
        # and a word swapped here would otherwise read as the stripper eating a sentence.
        final_text, redacted = redact.apply(final_text, runtime.toolset.public_names)
        if redacted:
            # Worth a line in the log even though the reader is unaffected: it is the
            # model declining an instruction, and a deployment tuning its prompt wants
            # to know how often that happens.
            logger.info(
                "%s named the machinery; removed %s from the answer",
                model.key, ", ".join(sorted(set(redacted))),
            )

        sources = citations(runner.sources)

        # Re-render once with links resolved, so a raw `docs/...md` target never flashes.
        answer.empty()
        st.session_state.messages.append(
            {
                "role": "assistant",
                # Stored stripped, not merely rendered stripped: this text is also what
                # goes back upstream next turn, and a footer in the history is a worked
                # example teaching the model to write another one. Handed the strip's
                # own contents, so an unlabelled list of links can be checked against
                # what the reader is already being shown rather than guessed at.
                #
                # Three passes, innermost first, because the duplication has three
                # shapes: an index identifier printed as prose, a parenthetical of
                # section titles inside a sentence, and a footer under the answer. The
                # bare-reference pass goes first so the two title-matching passes judge
                # the prose that is actually left — and because it is the only one whose
                # input is a string the reader must never see at all.
                "text": links.strip_source_footer(
                    links.strip_inline_citations(
                        links.strip_bare_references(final_text, view.corpus), sources
                    ),
                    view.corpus,
                    sources,
                ),
                "sources": sources,
                # What the turn actually did, so the block survives the turn that drew
                # it — asked for directly. The Sources strip says what was CITED; this
                # says what was searched for, in the words the model chose, and what
                # was read without being cited. On a wrong answer that is the
                # difference between "this is wrong" and "it searched for the wrong
                # thing", which is the one question the strip cannot answer.
                "steps": status.record(),
                "rating": None,
                "model": model.key,
                # What `redact.apply` took out, kept with the turn rather than only
                # logged. `tools/agent_bench.py` scores the model on what it *tried* to
                # say, and a fix that blinded the instrument measuring it would be the
                # worst outcome available. Nothing in `sage/ui/` reads this.
                "redacted": sorted(set(redacted)),
            }
        )
        st.session_state.tried = []
        # Only now is a failover a fact worth reporting: the replacement model
        # has produced this answer. Any older notice belongs to an older turn.
        switched = st.session_state.switched_from
        st.session_state.switched_from = None
        # No model names, and no instruction. This used to read "<name> was
        # unavailable (<reason>), so <name> answered instead. Pick a different one
        # from the model button under the input box" — and every clause of that is now
        # wrong for a reader. There is no model button: the picker is gone, so the
        # instruction sends them looking for a control that does not exist. And the
        # names were only ever actionable BECAUSE of that control; without it they are
        # operator information on a reader's screen, which is what was reported
        # ("we don't have a model picker, why do we need this?").
        #
        # What survives is the one thing a reader can use: an explanation for why this
        # answer took longer than the last one. The names are not lost — `model.key`
        # goes to `feedback.record_turn` below and the error card's technical-details
        # panel prints the real id, which is where an operator looks.
        st.session_state.notice = (
            f"The first model was unavailable ({REASONS.get(switched[1], switched[1])})"
            ", so another answered. This turn took longer than usual."
            if switched
            else ""
        )
        feedback.record_turn(
            question=question, outcome="answered", model=model.key, rounds=rounds,
            searches=len(runner.queries), sections=len(runner.sources),
            caveats=runner.caveats, sources=len(sources),
            redacted=len(set(redacted)),
            seconds=time.monotonic() - started,
        )
        if runner.queries and not sources:
            feedback.record_miss(runner.queries, st.session_state.messages[-2]["text"])
        # A path the corpus does not have is a model inventing a citation. The renderer
        # no longer dresses it up as a working link, which means the only trace it
        # leaves is this line — and a deployment tuning its prompt wants to see it.
        invented = links.unresolved(final_text, view.corpus)
        if invented:
            logger.warning("%s cited %d path(s) that do not exist: %s",
                           model.key, len(invented), ", ".join(invented[:5]))

    except llm.AssistantError as exc:
        status.clear()
        answer.empty()
        tried = list(st.session_state.tried)
        alternative = view.alternative(exc.kind, skip=tried)
        # One ledger and one rule for every kind: each model in the lineup may be
        # asked once, and `View.alternative` picks which is next. The *direction* still
        # depends on the failure — a refusal about the model prefers the next model
        # behind the same key, a refusal about the key prefers the other provider —
        # but the budget does not, because `tried` makes a repeat impossible and a
        # finite lineup walked without repeats cannot ping-pong.
        #
        # Which is why the `failed_over` boolean that used to guard the key-level case
        # is gone rather than kept alongside this. It capped a refusal about the key at
        # a single hop, and on the deployment it was written for — where the second
        # key was *also* out of credit — that one hop landed on the second dead end and
        # stopped, with every model that would have answered still on the list.
        may_switch = len(tried) + 1 < attempts_allowed(view)
        if exc.kind in FAILOVER_KINDS and alternative is not None and may_switch:
            # Out of credit on one provider is exactly what the second one is for.
            logger.info("%s unusable (%s); failing over to %s",
                        model.key, exc.kind, alternative.key)
            st.session_state.tried = [*tried, model.key]
            st.session_state.failover_to = alternative.key
            st.session_state.switched_from = (model.label, exc.kind)
            # Present tense: the retry has not happened yet. The past-tense
            # version is written only once an answer actually arrives.
            # Same reasoning as the settled notice below: the fact, not the names.
            # A reader watching a turn take eight seconds is owed an account of why,
            # and can do nothing with which model it was.
            st.session_state.notice = (
                f"That model is unavailable ({REASONS.get(exc.kind, exc.kind)}). "
                "Retrying…"
            )
        else:
            # An "unknown" kind means classify() had nothing to go on, so log the
            # full traceback — otherwise the only signal is a generic message.
            logger.error(
                "Turn failed (%s): %r",
                exc.kind,
                exc.original,
                exc_info=exc.original if exc.kind == "unknown" else None,
            )
            record_failure(exc.kind)
            fail(exc.user_message, detail(view, exc.original or exc))
    except Exception as exc:  # last-resort guard so the UI never dies
        if is_control_flow(exc):
            # Streamlit's own control flow, not a failure. Re-raised so the rerun or
            # stop it represents actually happens. Still checked here because the
            # hierarchy has moved before and an older build may put these under
            # Exception; on 1.54 the handler below is the one that fires.
            interrupted = True
            raise
        status.clear()
        answer.empty()
        logger.exception("Unexpected failure")
        classified = llm.classify(exc)
        record_failure(classified.kind)
        fail(classified.user_message, detail(view, exc))
    except BaseException:
        # Streamlit's control flow does NOT derive from Exception. On 1.54
        # `RerunException.__mro__` is (RerunException, ScriptControlException,
        # BaseException) — so a real rerun, raised at the next `st.*` call inside
        # `st.write_stream` when the reader touches the page mid-answer, sailed past
        # the handler above with `interrupted` still False. The `finally` then cleared
        # `processing` and fired a second `st.rerun()` over the one already in flight,
        # which is exactly the "no answer, no error card, nothing to click" dead end
        # its own comment describes.
        #
        # Below `except Exception`, not above it: an earlier clause wins, so putting
        # BaseException first would make the real-failure handler unreachable.
        #
        # Set for every BaseException, not only the control-flow ones. A
        # KeyboardInterrupt or a SystemExit is also a run that is ending, and calling
        # `st.rerun()` underneath one replaces it with a rerun just the same.
        interrupted = True
        raise
    finally:
        switch_to = st.session_state.pop("failover_to", None)
        if switch_to:
            # `processing` stays True: the same question runs again, on the new
            # model, as soon as the rerun re-enters this block.
            st.session_state.model = switch_to
            st.session_state.error = None
            st.session_state.error_detail = ""
        elif not interrupted:
            st.session_state.processing = False
            # The answer is committed (or the failure is), so the running copy is
            # spent. Left here it would be the text a later stop keeps.
            st.session_state.partial = []
        # Not while interrupted: the abort in flight IS a rerun, and calling another
        # one here replaced it — which left the question on screen with no answer, no
        # error card and nothing to click, because `processing` had been cleared by a
        # turn that never finished.
        if not interrupted:
            st.rerun()

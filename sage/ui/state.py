"""Session state, the limiter, and the three moments a turn begins or ends.

Everything Streamlit remembers between runs is declared in one place here, with the
reason each key exists next to it, and every path that starts a turn goes through
`start_new_turn` — which is what makes `may_start_turn` a gate rather than a
suggestion.
"""

from __future__ import annotations

import copy
import logging
import time

import streamlit as st

from .. import config, limits, redact
from .access import whoami

logger = logging.getLogger(__name__)

SESSION_DEFAULTS: tuple[tuple[str, object], ...] = (
    ("messages", []),
    ("processing", False),
    # The Think toggle in the corner of the input box. Off by default, and that is the
    # safe default rather than a shy one: reasoning tokens are billed as output tokens,
    # so on-by-default spends a free allowance on every turn whether the question
    # needed the thinking or not. Cleared by `composer.render_think_toggle` whenever
    # the model answering cannot take the parameter, which an automatic failover can
    # bring about without anyone touching the control.
    ("thinking", False),
    # A list, not one file. Holding one meant the guard in `uploads` dropped anything
    # offered while a file was already attached, and a second attachment looked from
    # the outside like a control that does nothing.
    ("attachments", []),
    # How many times the user has dismissed each uploaded file with a chip's ✕. The
    # uploader widget still reports them on every rerun — nothing here can reach into
    # it and remove one — so without this they come straight back on the next run. A
    # count rather than a flag, so a file that is deliberately re-picked can return
    # while one merely still being reported cannot.
    ("dropped_uploads", {}),
    # Why a file was refused, keyed the same way, so the reason survives a rerun.
    ("upload_refusals", {}),
    ("uploader_key", 0),
    # Bumped by the Clear button. Rendered into the page for app.js, which is the only
    # side that can reach the text inside Streamlit's chat input.
    ("clear_token", 0),
    # Set by the stop button's callback, which runs before the script does. Read
    # once, at the top, because by the time the transcript is drawn it is too late:
    # the block that draws it hides the last question while `processing` is set.
    ("stop_requested", False),
    # The answer as it arrives, one delta per entry. It lives here rather than in a
    # local because a stop is an interrupted script run — the run holding the local
    # is the one being thrown away — and session state is the only thing that
    # survives it. This is what a stopped turn keeps instead of discarding.
    ("partial", []),
    # Index of the user message being edited in place, or None.
    ("editing", None),
    # Bumped every time the editor opens, and spliced into its widget keys so no key
    # is ever reused. See `transcript.render_user_editor`.
    ("edit_session", 0),
    ("error", None),
    ("error_detail", ""),
    ("model", ""),
    ("notice", ""),
    # Models this turn has already asked and been refused by. A failure another
    # model might not have — which is nearly all of them; see `turn.FAILOVER_KINDS`
    # — is walked past to the next one, and this is the ledger that both stops the
    # walk landing back where it started and ends it once the lineup is spent. It
    # replaced a separate boolean for key-level failures, which capped those at one
    # hop however many models were left.
    ("tried", []),
    # (label, kind) of a model an automatic failover moved off. Held until the
    # replacement has actually answered, so the notice can never claim a switch
    # worked while an error card below it says it did not.
    ("switched_from", None),
    # Every conversation this session holds, and which of them is open.
    #
    # One list of messages is LIVE at a time — `messages`, at the top of this tuple —
    # and the records here are where the others wait. That is not duplication for its
    # own sake: `messages` is rebound, not just mutated (`start_new_turn` truncates it
    # for an edited question, opening another chat replaces it with that chat's), so a
    # record holding the same list object would come unstuck from it the first time
    # either of those ran, silently, with the sidebar then listing a conversation that
    # no longer matches the one on screen. Switching stashes the live list into the
    # open record and loads the target's, which leaves every existing path free to go
    # on rebinding `messages` exactly as it did before.
    #
    # A record is {"id": int, "messages": list}. There is no stored title: the title is
    # derived from the first question every time it is drawn, so a chat cannot end up
    # labelled with a question the reader has since edited away.
    ("chats", []),
    ("chat_id", 0),
    # Ids are handed out and never reused, so a button key can never name two
    # different chats across one session.
    ("next_chat_id", 1),
)

#: How much of the first question becomes the chat's name in the sidebar. Long enough
#: to tell two questions about the same thing apart, short enough to fit the panel on
#: one line: Streamlit's sidebar is 300px wide and a row's label has 240 of them, which
#: is about this many characters at the size the list is set in. The stylesheet
#: ellipses anything that still overruns, so this is where it looks deliberate rather
#: than where it stops being possible.
TITLE_CHARS = 34


def initialise() -> None:
    """Give this session its own copy of every default.

    A copy, and the word is load-bearing. `SESSION_DEFAULTS` is built once, when this
    module is imported — once per *process*, not once per session — so the `[]` beside
    `messages` is a single list object. Handing it to `setdefault` gave every session
    in the process the same list: one reader's question appended to it appeared in
    another reader's transcript, and the app opened on somebody else's conversation
    instead of the landing screen. On a public deployment that is other people's
    questions, their attachments, and whatever they pasted into them.

    This is a regression the refactor introduced and nothing caught. The list used to
    be written inside `app.py`'s module body, which Streamlit re-executes on every
    script run, so a fresh `[]` was built for each session by accident rather than on
    purpose. Moving the declaration into a module that is imported once removed the
    accident and left nothing in its place.

    `deepcopy` rather than a table of factories: it cannot be got wrong later. A new
    mutable default added to that tuple is safe the day it is written, with no one
    having to notice that it needs to be.
    """
    for key, default in SESSION_DEFAULTS:
        if key not in st.session_state:
            st.session_state[key] = copy.deepcopy(default)
    # The open chat always exists. The sidebar draws one row per record, so a session
    # with none of them would show an empty list above a New chat button while a
    # conversation was on screen — and `_stash` would have nowhere to put it.
    if not st.session_state.chats:
        st.session_state.chats = [{"id": 0, "messages": []}]
        st.session_state.chat_id = 0
        st.session_state.next_chat_id = 1


# --- the chats in this session --------------------------------------------


def chat_title(messages: list[dict], fallback: str) -> str:
    """What to call a conversation in the sidebar: its first question, shortened.

    Derived rather than stored, so an edited or cleared first question renames the
    chat instead of leaving a label nothing on screen says any more. `fallback` is the
    profile's word for a chat with nothing in it yet — the copy belongs to the
    deployment, so it is passed in rather than written here.
    """
    for message in messages:
        if message.get("role") != "user":
            continue
        text = " ".join(str(message.get("text", "")).split())
        if not text:
            continue
        if len(text) <= TITLE_CHARS:
            return text
        # Cut at a word boundary where there is one within reach, so the label does
        # not end mid-word for the sake of four characters.
        clipped = text[:TITLE_CHARS].rstrip()
        space = clipped.rfind(" ")
        if space >= TITLE_CHARS - 12:
            clipped = clipped[:space]
        return clipped + "…"
    return fallback


def active_messages(chat_id: int) -> list[dict]:
    """The messages to draw for one chat — live for the open one, stored otherwise.

    The open chat's messages are read from `messages` rather than from its record,
    because the record is only written on a switch: a turn that has just landed is in
    `messages` and nowhere else, and a sidebar reading records would name the open
    chat after the question before last.
    """
    if chat_id == st.session_state.chat_id:
        return st.session_state.messages
    for record in st.session_state.chats:
        if record["id"] == chat_id:
            return record["messages"]
    return []


def _stash() -> None:
    """Put the live conversation away — or drop it, if nothing was ever asked in it.

    A conversation with no messages is not a conversation, and keeping it is what made
    `New chat` look broken. It used to refuse to do anything on an empty chat, so that
    pressing it ten times could not leave ten identical `Nothing asked yet` rows — and
    what that read as was a dead button: "when clicking +new chat button, it doesn't
    work until a new prompt is entered in that session".

    Pruning here rather than refusing there gets both: the button always opens a new
    conversation, and the list never fills with blanks, because the blank you are
    leaving goes as you leave it. (A reader pressing it twice on an empty chat sees no
    change, and there is none to see — both states are an empty conversation.)
    """
    for index, record in enumerate(st.session_state.chats):
        if record["id"] != st.session_state.chat_id:
            continue
        if st.session_state.messages:
            record["messages"] = st.session_state.messages
        else:
            st.session_state.chats.pop(index)
        return


def _leave_conversation() -> None:
    """Reset everything that belongs to the conversation being left.

    Shared by clearing, switching and starting a new chat, because all three are the
    same event as far as the rest of session state is concerned: whatever a turn left
    behind — a half-answer, an error card, a failover ledger, files picked for a
    question that is no longer on screen — belongs to a conversation that is no longer
    the one being looked at.
    """
    st.session_state.processing = False
    st.session_state.partial = []
    st.session_state.stop_requested = False
    st.session_state.editing = None
    st.session_state.edit_session += 1
    st.session_state.attachments = []
    st.session_state.dropped_uploads = {}
    st.session_state.upload_refusals = {}
    st.session_state.error = None
    st.session_state.error_detail = ""
    st.session_state.notice = ""
    st.session_state.tried = []
    st.session_state.switched_from = None
    # And the MODEL, which is the one thing this function used to leave behind.
    #
    # A failover is per-turn in its reasoning and was permanent in its effect: it sets
    # `session_state.model`, nothing here put it back, and while the model picker
    # existed that did not matter because a reader could move themselves. With the
    # picker gone there was no way back at all. Reported from the running app as three
    # symptoms of this one omission — an error card naming a Zen model on a deployment
    # whose default is the OpenRouter router ("isn't our default openrouter free? why
    # is this showing up?"), the Think pill missing from a brand-new chat because the
    # provider it had been walked to does not take the parameter, and a notice about
    # model churn the reader could do nothing about.
    #
    # Per conversation, not per turn: inside one conversation a failover has to stick,
    # or the next question walks back into the model that just refused. Leaving a
    # conversation is where the ledger is already being torn up, so it is where the
    # default comes back. `app.current_model` validates it against what the providers
    # actually served, so a default that is no longer available falls through exactly
    # as it did before.
    st.session_state.model = config.DEFAULT_MODEL
    # A failover in flight belongs to the turn being left. Left set, it fires on the
    # next run and `turn.run`'s `finally` sets `processing` again — a question from
    # the conversation that was just closed, answered into the one that replaced it.
    st.session_state.pop("failover_to", None)
    st.session_state.uploader_key += 1
    # Nothing here can empty the composer — the text in it is client-side state
    # Streamlit only reads on submit — so leaving a conversation left the last
    # question sitting in the box over whatever replaced it, as if it were still
    # about to be sent. app.js empties it when this counter moves.
    st.session_state.clear_token += 1


def delete_chat(chat_id: int) -> None:
    """Remove a conversation, and open a neighbour if it was the one being read.

    One click, not two. This asked for a confirmation once — the row armed and a second
    click on the ✕ went through — and a control that does nothing the first time it is
    pressed reads as a broken one: "the chat doesn't go away but you need to click it
    again. which is buggy". So it goes on the first click, and what that costs is
    honest: a conversation is in this session's memory and nowhere else, so a mis-click
    loses it.

    A session always has an open chat — `initialise` guarantees one and the sidebar
    draws a row per record — so deleting the last one does not leave the app with
    nothing selected: an empty chat takes its place, which is the same state the app
    opens in.

    `_leave_conversation` only runs when the open chat actually changed. Deleting one
    the reader is not in must not throw away the answer they are looking at, the error
    card under it, or the file they have just attached.
    """
    remaining = [
        record for record in st.session_state.chats if record["id"] != chat_id
    ]
    if len(remaining) == len(st.session_state.chats):
        return   # already gone; the rerun this returns into redraws without it
    st.session_state.chats = remaining

    if chat_id == st.session_state.chat_id:
        if remaining:
            # The newest survivor, which is the row that was directly above the one
            # just removed — where the reader is already looking.
            target = remaining[-1]
        else:
            target = {"id": st.session_state.next_chat_id, "messages": []}
            st.session_state.next_chat_id += 1
            st.session_state.chats = [target]
        st.session_state.chat_id = target["id"]
        st.session_state.messages = target["messages"]
        _leave_conversation()
    st.rerun()


def abandon_turn(model_key: str, names: dict[str, str] | None = None) -> None:
    """End the turn because the reader is leaving this conversation, not watching it.

    A part-answer is kept, exactly as a stop keeps one — it is text the reader may want,
    in the conversation it belongs to.

    An answer that had produced NOTHING yet is different, and this is the difference
    `finish_stopped_turn` cannot make. That function appends an empty assistant message
    on purpose, so a reader who pressed Stop sees that something happened rather than
    being left with a question and no reply. A reader who has walked off to another chat
    is not looking at that screen, and what they find when they come back to it is a
    question with the bare word `Stopped` under it and no answer — reported with a
    screenshot of exactly that, and "this is certainly a bug".

    So a turn that arrived empty is dropped whole, the question with it, and the
    conversation is left as it was before it was asked. Nothing half-done, and — because
    `_stash` drops a conversation with no messages — no empty chat left in the panel
    either, which is where that screenshot's spare `Nothing asked yet` row came from.
    """
    if not st.session_state.processing:
        return
    if "".join(st.session_state.partial).strip():
        finish_stopped_turn(model_key, names)
        return

    st.session_state.partial = []
    st.session_state.processing = False
    st.session_state.stop_requested = False
    # The same reason `_leave_conversation` pops it: a pending failover would re-ask
    # this question on the next run, in whatever conversation is open by then.
    st.session_state.pop("failover_to", None)
    st.session_state.switched_from = None
    st.session_state.error = None
    st.session_state.error_detail = ""
    st.session_state.notice = ""
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        st.session_state.messages.pop()
    logger.info("Turn abandoned before it produced anything; the question goes with it")


def new_chat() -> None:
    """Put the open conversation away and start an empty one. Always.

    It used to return without doing anything when the open conversation was empty, to
    keep the panel from filling with identical blank rows. `_stash` drops the blank
    instead, so this no longer has to refuse — and refusing is what a reader read as a
    broken button.
    """
    _stash()
    chat_id = st.session_state.next_chat_id
    st.session_state.next_chat_id += 1
    st.session_state.chats.append({"id": chat_id, "messages": []})
    st.session_state.chat_id = chat_id
    st.session_state.messages = []
    _leave_conversation()
    st.rerun()


def open_chat(chat_id: int) -> None:
    """Switch to another conversation in this session."""
    if chat_id == st.session_state.chat_id:
        return
    target = next(
        (record for record in st.session_state.chats if record["id"] == chat_id), None
    )
    if target is None:
        # A stale button key — the chat is gone. Doing nothing is right: the rerun
        # this returns into redraws the sidebar without it.
        return
    _stash()
    st.session_state.chat_id = chat_id
    st.session_state.messages = target["messages"]
    _leave_conversation()
    st.rerun()


@st.cache_resource(show_spinner=False)
def get_limiter() -> limits.Limiter:
    """One limiter for the whole process.

    `cache_resource` is shared across every session in the process, which is what
    makes the deployment budget a real total rather than a per-tab one. It is also
    the ceiling on this design: the counters live in memory, so they reset when the
    app restarts — which on a platform that hibernates idle apps is roughly daily.
    A deployment that needs the budget to survive a restart needs external storage.
    """
    return limits.Limiter(
        burst=config.RATE_BURST,
        refill_seconds=config.RATE_REFILL_SECONDS,
        daily_turns=config.DAILY_TURNS,
        daily_window=config.DAILY_WINDOW_SECONDS,
        call_budget=config.CALL_BUDGET,
        budget_window=config.BUDGET_WINDOW_SECONDS,
    )


def may_start_turn() -> bool:
    """Ask the limiter whether a turn may run, and say why if not.

    One gate, and every path that spends provider calls goes through it. "Try again"
    did not: it set `processing` directly, so a deployment whose call budget was
    spent refused new questions while the button under the error card kept making
    requests, one per click, for as long as anyone cared to click it.

    The refusal goes to `notice`, the same neutral strip a failover uses, so it reads
    as information rather than as an error with a Try-again button that would itself
    be refused.
    """
    verdict = get_limiter().check(whoami(), time.monotonic())
    if verdict.allowed:
        return True
    logger.info("Turn refused for %s: %s", whoami(), verdict.message)
    st.session_state.notice = verdict.message
    return False


def start_new_turn(
    question: str, attachments=None, replacing: int | None = None
) -> None:
    # The one place every turn begins — the composer, the starter cards and an edited
    # question all come through here — so it is the one place a turn can be refused.
    # Checked before any state is touched: a refused question must leave the transcript
    # exactly as it was, or the reader is left looking at their own question with no
    # answer under it and nothing to click, which is the shape of a broken app rather
    # than a busy one.
    #
    # `replacing` is an index into `messages`: everything from there on is dropped and
    # this question takes its place. That is what re-sending an edited question means —
    # the answer below it, and every turn after it, was a reply to wording that no
    # longer exists. Truncating happens AFTER the gate for the same reason the append
    # does: a refused edit must leave the conversation intact, not delete the tail of
    # it and then decline to replace it.
    if not may_start_turn():
        st.rerun()
        return

    if replacing is not None:
        st.session_state.messages = st.session_state.messages[:replacing]

    st.session_state.messages.append(
        {"role": "user", "text": question, "attachments": list(attachments or [])}
    )
    st.session_state.processing = True
    st.session_state.editing = None
    # Belongs to a turn that is over. An abandoned half-answer left here would be
    # committed by the next stop as if it were this turn's.
    st.session_state.partial = []
    st.session_state.stop_requested = False
    st.session_state.error = None
    # Both of these belong to the turn that just ended, and a new question is where
    # they stop being true.
    #
    # `tried` is the walk's ledger. Cleared only on a *successful* answer, it survived
    # a failover that then failed for some other reason and stayed set for the rest of
    # the session — so every later refusal showed an error card instead of failing
    # over, until the reader picked a model by hand.
    #
    # `notice` is the "X was unavailable, Y answered instead" line. It renders under
    # the transcript, which puts a notice about the previous turn directly above the
    # new question while the new one generates, reading as if it belonged to it.
    st.session_state.tried = []
    st.session_state.notice = ""
    st.session_state.attachments = []
    # Both, together: the widget is reset so its files stop being reported, and the
    # dismissal list is emptied because the keys in it refer to a widget that no
    # longer exists. Leaving stale keys behind would silently refuse a file with the
    # same name later in the conversation.
    st.session_state.dropped_uploads = {}
    st.session_state.upload_refusals = {}
    st.session_state.uploader_key += 1
    st.rerun()


# --- stopping a turn -------------------------------------------------------
#
# A generation could not be called off. The reader who spotted a typo in the question
# a second after sending it had three options, and all of them were worse than
# waiting: touch the page and the rerun restarts the whole turn from the first
# provider call, clear the conversation and lose it, or sit through an answer to a
# question they no longer wanted asked.
#
# The mechanism is Streamlit's own, used deliberately instead of fought. Any widget
# interaction during a run aborts that run — `st.write_stream` raises at its next
# write — and until now the abort was something the app only defended against
# (`interrupted`, and the `disabled=` on the rating buttons). A stop is that same
# abort, asked for on purpose, with one flag set to say so.
#
# The order the pieces run in is what makes it work:
#
#   1. `request_stop` is an `on_click` callback, so it runs BEFORE the script does
#      on the run that follows the click. A button whose value were merely read where
#      it is rendered would be read at the bottom of the page, long after the
#      transcript above it had been drawn for a turn that is no longer running.
#   2. `finish_stopped_turn` runs at the top, before anything is drawn.
#   3. The turn block at the end sees `processing` cleared and does not start again.


def request_stop() -> None:
    st.session_state.stop_requested = True


def finish_stopped_turn(model_key: str, names: dict[str, str] | None = None) -> None:
    """Keep what arrived before the reader pressed stop, and end the turn there.

    The half-written answer is kept rather than thrown away. It is what was on the
    screen at the moment of the click — often it is the answer, and the reader
    stopped it because they had already read enough — and deleting it would make the
    button destructive in a way nothing about a square suggests.

    A stop with nothing to keep still appends a message, empty. The transcript skips
    an assistant message with no text, so without one the reader is left looking at
    their own question with no reply, no error and nothing to click: the exact dead
    end this app has fixed twice before. `stopped` is what `render_assistant` reads
    to say so, and `history.build` drops an empty assistant turn on its own, so
    nothing empty is ever sent upstream.

    Sources are not kept. They live on the ToolRunner in the run that was abandoned,
    and reconstructing them would mean mirroring every read into session state for a
    Sources strip under an answer that stops mid-sentence. The citations inside the
    text itself survive, because `links.fix_links` resolves those at render time.
    """
    st.session_state.stop_requested = False
    # Not `if processing`: the click races the turn. A stop that lands after the
    # answer has already been committed must not append a second, empty message
    # under it.
    if not st.session_state.processing:
        st.session_state.partial = []
        return

    text = "".join(st.session_state.partial).strip()
    # The same swap `turn.run` makes on a finished answer. A stop lands mid-sentence and
    # this text is stored and rendered exactly as it arrived, so without it the one path
    # that skips `redact.apply` is the one where the reader is still reading.
    text, removed = redact.apply(text, names or {})
    if removed:
        logger.info(
            "removed internal name(s) from a stopped answer: %s",
            ", ".join(sorted(set(removed))),
        )
    st.session_state.partial = []
    st.session_state.processing = False
    # A failover in flight is off too. Without this the pending switch fires on the
    # next run, `processing` is set again by the turn's `finally`, and the turn the
    # reader just stopped starts over on a different model.
    st.session_state.pop("failover_to", None)
    st.session_state.switched_from = None
    st.session_state.notice = ""
    st.session_state.error = None
    st.session_state.error_detail = ""
    st.session_state.messages.append(
        {
            "role": "assistant",
            "text": text,
            "sources": [],
            "rating": None,
            "model": model_key,
            "redacted": sorted(set(removed)),
            "stopped": True,
        }
    )
    logger.info("Turn stopped by the reader after %d characters", len(text))

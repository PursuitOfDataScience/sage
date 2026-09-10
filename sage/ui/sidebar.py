"""The panel of conversations: what this session is holding, and what to do with one.

Collapsed on first load, because that is where `app.py` has always left the sidebar and
opening it by default would move the whole page sideways for a reader who did not ask
for a panel. Streamlit draws the arrows that open and close it; `static/app.js` gives
them the labels Streamlit leaves off.

Two controls per conversation, in one row of screen: its name, and the ✕ that removes
it. Laid out by CSS rather than `st.columns` — see the composer strip for why a column
here is a control that can end up in the DOM and invisible on screen.

Why the rows are buttons and not a `st.radio` of titles: a radio holds its own value
under its widget key, and this app has been bitten by that once already — the model
picker was a selectbox, an automatic failover set `session_state.model`, and on the next
run the selectbox handed back its *previous* value and switched straight back to the
provider that had just refused. A chat list has the same shape, because the open chat
can change without anyone touching this widget (`new_chat` opens one, and deleting the
open one opens its neighbour). Buttons hold no state, so a programmatic switch survives.
See `composer.render_model_picker`, which reached the same answer from the same bug.
"""

from __future__ import annotations

import html

import streamlit as st

from .state import (
    active_messages,
    arm_delete,
    chat_title,
    delete_chat,
    new_chat,
    open_chat,
)
from .view import View


def render(view: View) -> None:
    """Draw the panel: a way out of this conversation, then the ones there are.

    Every control here is inert while an answer is streaming, and that is the whole
    reason this is safe to add. A click on any Streamlit widget aborts the run that is
    streaming — that is the mechanism the stop button is built on — so a live chat
    switch would end the turn halfway, throw the half-written answer away, and leave
    the reader in a different conversation wondering where their answer went. `disabled`
    is the only thing that stops a click reaching the server, so it is what is used
    here rather than a check once the click has arrived. The queued-prompt path in
    `static/app.js` is what a reader who wants to get on with something else uses
    instead, and it does not touch the server at all.

    The open row is NOT disabled, though it was. Streamlit renders a disabled button
    greyed and with a not-allowed cursor, which put the panel's one emphasised row
    behind a forbidden sign — and clicking the conversation you are already in costs a
    rerun and changes nothing, so there was never anything to protect. Which row is
    open is said by the stylesheet instead, off the row's container key.
    """
    copy = view.copy
    chats = list(st.session_state.chats)
    busy = bool(st.session_state.processing)
    armed = st.session_state.pending_delete

    with st.sidebar, st.container(key="chat-list"):
        # Rendered only when there is a conversation to leave. On an empty one it had
        # nothing to do, and a panel opening on a disabled `New chat` button directly
        # above a row that also read "New chat" was the same two words for two
        # different things — reported as "two awkward new chats".
        #
        # One `if`, and the short circuit is the point: with no messages `st.button` is
        # never called, so the widget is not drawn at all rather than drawn inert.
        #
        # No `help=` on it either. The label already says what the button does, so a
        # tooltip is a black box following the cursor around — the same reason the
        # starter cards do without one. It is also not free: Streamlit renders a `help`
        # tooltip by wrapping the control, and the wrapper carries a second,
        # zero-sized copy of the button — two elements answering to
        # `.st-key-chat-list button`, one of them invisible and unclickable, for a
        # sentence nobody needed.
        if st.session_state.messages and st.button(
            f"＋  {copy.new_chat}",
            key="new-chat",
            use_container_width=True,
            disabled=busy,
        ):
            new_chat()

        # What the list is, said once. It replaced an ALL-CAPS "CHATS" over a list of
        # chats — a label that decorated rather than informed — with the one fact about
        # this list a reader cannot see anywhere else: it lasts as long as the tab does.
        st.markdown(
            f'<div class="chats-heading">{html.escape(copy.chats_heading)}</div>',
            unsafe_allow_html=True,
        )

        # Newest first: the list grows downward as a session goes on, and the chat a
        # reader is most likely to want back is the one they just left.
        for record in reversed(chats):
            _row(record["id"], copy, busy=busy, armed=armed == record["id"])


def _row(chat_id: int, copy, *, busy: bool, armed: bool) -> None:
    """One conversation: its name and the ✕ — or, once armed, the confirmation.

    Two widget keys per row, and they are the same two whichever state the row is in
    (`chat-name-…` and `chat-act-…`). That is deliberate: the stylesheet sizes the row
    off those keys, so arming a delete must not change which slot is which, or the row
    would move under the cursor reaching for it. Buttons hold no state, so re-using a
    key for a different label across states is free.

    The row's own container key carries the state — `chat-row-open-…`,
    `chat-row-past-…`, `chat-row-arm-…` — because that is the only thing a stylesheet
    can read. It cannot read `disabled` instead: every row is disabled while an answer
    arrives, so a rule keyed on that emphasised the whole list at once.
    """
    open_now = chat_id == st.session_state.chat_id
    state = "arm" if armed else ("open" if open_now else "past")

    with st.container(key=f"chat-row-{state}-{chat_id}"):
        if armed:
            # Active voice, and it says what the click does. A ✓ would be one glyph
            # asking the reader to guess which of two irreversible readings it has.
            if st.button(
                copy.delete_chat,
                key=f"chat-name-{chat_id}",
                use_container_width=True,
                disabled=busy,
            ):
                delete_chat(chat_id)
            if st.button("✕", key=f"chat-act-{chat_id}", disabled=busy):
                arm_delete(None)
            return

        if st.button(
            chat_title(active_messages(chat_id), copy.untitled_chat),
            key=f"chat-name-{chat_id}",
            use_container_width=True,
            disabled=busy,
        ):
            open_chat(chat_id)
        # Two clicks, because this cannot be undone: the conversation is only in this
        # session's memory and nothing anywhere else has a copy of it.
        #
        # No `help=` on either ✕, and it is the same two reasons as the New chat button
        # above plus a third. Streamlit's tooltip is a black panel that opens beside the
        # cursor — on a 240px row it covered the row above, which is the one thing a
        # reader needs to see while deciding whether to delete this one. `static/app.js`
        # gives both buttons a `title` and an `aria-label` instead: a native tooltip is
        # small, and unlike `help=` it also gives the control an accessible name, which
        # a lone ✕ badly needs.
        if st.button("✕", key=f"chat-act-{chat_id}", disabled=busy):
            arm_delete(chat_id)

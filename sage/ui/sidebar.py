"""The panel of conversations: one row per chat in this session, and a way to start one.

Collapsed on first load, because that is where `app.py` has always left the sidebar and
opening it by default would move the whole page sideways for a reader who did not ask
for a panel. Streamlit draws its own control to open it.

Why the rows are buttons and not a `st.radio` of titles: a radio holds its own value
under its widget key, and this app has been bitten by that once already — the model
picker was a selectbox, an automatic failover set `session_state.model`, and on the
next run the selectbox handed back its *previous* value and switched straight back to
the provider that had just refused. A chat list has the same shape, because the open
chat can change without anyone touching this widget (`new_chat` opens one). Buttons
hold no state, so a programmatic switch survives. See `composer.render_model_picker`,
which reached the same answer from the same bug.
"""

from __future__ import annotations

import html

import streamlit as st

from .state import active_messages, chat_title, new_chat, open_chat
from .view import View


def render(view: View) -> None:
    """Draw the list. Newest chat first, the open one marked, nothing else.

    Every control here is inert while an answer is streaming, and that is the whole
    reason this is safe to add. A click on any Streamlit widget aborts the run that is
    streaming — that is the mechanism the stop button is built on — so a live chat
    switch would end the turn halfway, throw the half-written answer away, and leave
    the reader in a different conversation wondering where their answer went. `disabled`
    is the only thing that stops a click reaching the server, so it is what is used
    here rather than a check once the click has arrived. The queued-prompt path in
    `static/app.js` is what a reader who wants to get on with something else uses
    instead, and it does not touch the server at all.
    """
    copy = view.copy
    chats = list(st.session_state.chats)
    busy = bool(st.session_state.processing)
    # An empty conversation IS what New chat offers, so on one there is nothing for the
    # button to do — and a button that does nothing when pressed is the shape this app
    # has fixed three times already. `state.new_chat` refuses the same case anyway;
    # this is what says so before the press rather than after it.
    empty = not st.session_state.messages

    with st.sidebar, st.container(key="chat-list"):
        st.markdown(
            f'<div class="chats-heading">{html.escape(copy.chats_heading)}</div>',
            unsafe_allow_html=True,
        )
        # No `help=`: the label already says what the button does, so a tooltip is a
        # black box following the cursor around — the same reason the starter cards do
        # without one. It is also not free here. Streamlit renders a `help` tooltip by
        # wrapping the control, and the wrapper carries a second, zero-sized copy of
        # the button: two elements answering to `.st-key-chat-list button`, one of them
        # invisible and unclickable, for a sentence nobody needed.
        if st.button(
            f"＋  {copy.new_chat}",
            key="new-chat",
            use_container_width=True,
            disabled=busy or empty,
        ):
            new_chat()

        # Newest first: the list grows downward as a session goes on, and the chat a
        # reader is most likely to want back is the one they just left.
        for record in reversed(chats):
            chat_id = record["id"]
            open_now = chat_id == st.session_state.chat_id
            # The same two marks the model picker uses, for the same job — which row
            # is the current one — so a reader learns the convention once.
            mark = "●" if open_now else "○"
            title = chat_title(active_messages(chat_id), copy.new_chat)
            if st.button(
                f"{mark}  {title}",
                # Two key shapes, and the difference is what the stylesheet reads to
                # emphasise the open row. It cannot read `disabled` instead: the open
                # row is disabled, but so is every other row while an answer is
                # arriving, so a rule keyed on that emphasised the whole list and it
                # stopped saying where the reader was. The open row's key is never used
                # for a click — it is the one row that is always inert — so spending it
                # on saying *which* row this is costs nothing.
                key=f"chat-current-{chat_id}" if open_now else f"open-chat-{chat_id}",
                use_container_width=True,
                # The open chat is not a place to go. Left clickable it read as a
                # control that does nothing, which is the shape this app has fixed
                # three times elsewhere.
                disabled=busy or open_now,
            ):
                open_chat(chat_id)

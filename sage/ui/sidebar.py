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
    abandon_turn,
    active_messages,
    chat_title,
    delete_chat,
    new_chat,
    open_chat,
)
from .view import View


def leave(view: View) -> None:
    """Keep the half-written answer, then let the caller walk away from it.

    Everything in this panel works while an answer is streaming, and this is what makes
    that safe. A click on any Streamlit widget aborts the run that is streaming — that
    is the mechanism the stop button is built on — so there is no version of this where
    the turn survives the click. The choice is only between refusing the click and
    ending the turn well, and refusing it was wrong: "you can't create a new chat when
    the current session is generating the answer, which is problematic", and the same
    for switching.

    So a click ends the turn. `abandon_turn` keeps whatever text had arrived, marked
    `stopped`, in the conversation being left — and drops the whole turn, question
    included, when nothing had arrived at all. That second case is what a reader found
    when they started a new chat a moment after asking: the old conversation held their
    question with the bare word `Stopped` under it and no answer. It ignores a call with
    no turn running, so this is a no-op the rest of the time.

    Called BEFORE the switch, because it appends to `messages` — the live list — and
    the switch is what stashes that list into the record it belongs to.
    """
    abandon_turn(view.model.key, view.public_names)


def render(view: View) -> None:
    """Draw the panel: a way out of this conversation, then the ones there are.

    Nothing here is `disabled`. Two states used to be: every row and the New chat button
    while an answer was arriving, and the open row always. Both were reported as bugs —
    a greyed row behind a not-allowed cursor ("grey and a weird forbidden sign"), and a
    panel that could not be used at all for the length of a turn. Which row is open is
    said by the stylesheet instead, off the row's container key, and a turn in flight is
    handled by `leave` rather than by refusing the click.
    """
    copy = view.copy
    chats = list(st.session_state.chats)

    with st.sidebar, st.container(key="chat-list"):
        # Always drawn. It was drawn only when the open conversation had messages, on
        # the reasoning that an empty one has nothing to leave — and the effect was that
        # pressing it made it disappear, because the chat it opens is empty by
        # definition. Reported as "after adding two new chats, that adding new chat
        # button is gone. also buggy", and it was.
        #
        # Pressing it on an empty conversation does nothing at all (`state.new_chat`
        # returns on that case, so ten presses cannot leave ten identical rows). That is
        # a quieter failure than a control that vanishes as you use it, and the two
        # labels no longer collide: the button says New chat and an unasked conversation
        # says something else entirely.
        #
        # No `help=`: the label already says what the button does, so a tooltip is a
        # black box following the cursor around — the same reason the starter cards do
        # without one. It is also not free, because Streamlit renders a `help` tooltip by
        # wrapping the control and the wrapper carries a second, zero-sized copy of the
        # button.
        if st.button(
            f"＋  {copy.new_chat}",
            key="new-chat",
            use_container_width=True,
        ):
            leave(view)
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
            _row(view, record["id"], copy)


def _row(view: View, chat_id: int, copy) -> None:
    """One conversation: its name, and the ✕ that removes it.

    The ✕ removes it on the first click. It used to arm the row and want a second click
    to confirm, on the reasoning that a conversation exists in this session's memory and
    nowhere else — and what that read as was a broken button: "when clicking x to delete
    a chat, the chat doesn't go away but you need to click it again. which is buggy". A
    control that does nothing the first time you press it is worse than one that does
    what it says, so it does what it says.

    Two widget keys per row, `chat-name-…` and `chat-act-…`. The stylesheet sizes the
    row off those keys — the name flexes, the ✕ does not — so they are what the row's
    layout depends on rather than anything about the buttons themselves.

    The row's own container key carries which conversation is open (`chat-row-open-…`
    against `chat-row-past-…`), because that is the only thing a stylesheet can read —
    and because nothing in this panel is `disabled` any more, there is nothing else it
    could have keyed on.
    """
    open_now = chat_id == st.session_state.chat_id

    with st.container(key=f"chat-row-{'open' if open_now else 'past'}-{chat_id}"):
        if st.button(
            chat_title(active_messages(chat_id), copy.untitled_chat),
            key=f"chat-name-{chat_id}",
            use_container_width=True,
        ):
            leave(view)
            open_chat(chat_id)
        # No `help=` on the ✕ either, and one reason more than the button above:
        # Streamlit's tooltip is a black panel that opens beside the cursor, and on a
        # 240px row it covered the row above. `static/app.js` gives it a `title` and an
        # `aria-label` instead — a native tooltip is small, and unlike `help=` it also
        # gives the control an accessible name, which a lone ✕ badly needs.
        if st.button("✕", key=f"chat-act-{chat_id}"):
            # The turn ends here too, and it has to: the click has already aborted the
            # run that was streaming, so the only question is whether what arrived is
            # kept. It is — in the conversation it belongs to, which may well not be
            # the one being deleted.
            leave(view)
            delete_chat(chat_id)

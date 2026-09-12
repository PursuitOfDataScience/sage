"""The bottom of the page: what is attached, the box, and the two controls beside it.

There is deliberately no caveat line under the input. It went from a popover, to
three paragraphs under the starter cards, to one 11px line beside the model name, and
each version was still a permanent fixture at the bottom of every screen for something
read once and then ignored. Neither half of it is lost: every answer carries a Sources
strip to the documentation it came from, so "this can be wrong, here is what it read"
is attached to the thing that might be wrong; and the system prompt hands out the
contact address in the answer to a question the documentation cannot settle, which is
when it is wanted.
"""

from __future__ import annotations

import html

import streamlit as st

from .. import config
from .state import request_stop, start_new_turn
from .view import View


def render_attachments(view: View) -> None:
    """The chips for what is attached, pinned directly above the input box.

    They used to render wherever the script happened to reach them — in the middle of
    the page, under the starter cards, a long way from the box they belong to. They
    are part of the composer, so they are pinned to it: app.js measures this row and
    the page reserves room for it, exactly as it does for the controls underneath.
    """
    if not st.session_state.attachments:
        return
    with st.container(key="attachments"):
        for index, item in enumerate(st.session_state.attachments):
            if st.button(
                # Filename and the ✕, and a truncation warning if there is one. The
                # character and page counts that used to sit here were four chips of
                # arithmetic on a four-file turn, none of it telling the reader
                # anything they did not already know about a file they chose.
                f"{item.icon} {item.filename}"
                + (f" · {item.summary}" if item.summary else "")
                + "  ✕",
                key=f"drop-attachment-{index}",
                help="Remove this attachment",
            ):
                dropped = st.session_state.attachments.pop(index)
                if dropped.key:
                    st.session_state.dropped_uploads[dropped.key] = (
                        st.session_state.dropped_uploads.get(dropped.key, 0) + 1
                    )
                st.rerun()
        if any(item.kind == "image" for item in st.session_state.attachments) and not (
            config.sees_images(view.model.id)
        ):
            # Said next to the picture, once, rather than discovered when the answer
            # ignores it.
            #
            # It used to end "— pick a Pixtral or Claude model to have this one looked
            # at", with the names built from `SAGE_VISION_MODELS` so the sentence could
            # not drift from the list that decides it. That instruction died with the
            # model picker: there is nothing left for a reader to pick. What is left is
            # the fact, and the fact is worth keeping — the alternative is a reader
            # who attaches a screenshot and learns it was never read from an answer
            # that talks about something else.
            #
            # On this deployment it is now a rare line rather than the common one: the
            # default provider is on `SAGE_VISION_MODELS`, so this renders only after
            # an automatic failover has moved the turn to a model that cannot see.
            st.caption(
                f"{view.model.label} cannot read images — this one is attached, "
                "and will not be looked at."
            )


def ask(view: View) -> str | None:
    """The input box, and the token app.js watches to know when to empty it."""
    # No `max_chars`. That argument is the only thing that puts Streamlit's "15/8000"
    # counter inside the box, and a running character count is noise in a box you type
    # a question into — it reads as a form field with a quota. The limit itself is
    # still enforced, in `submit` below, where it costs nothing to look at.
    #
    # Enforced there rather than hidden with CSS on purpose: the counter's own test id
    # is Streamlit's, unversioned, and not visible from this repo, so a rule naming it
    # would be a guess that fails silently the day it changes. Not asking for the
    # counter cannot fail that way.
    #
    # Two prompts, because the box is asking for two different things. On the landing
    # screen it is the only instruction on the page about what this app is for, so it
    # names the subject. Once an answer is on screen the subject is established and the
    # useful thing to say is that the conversation carries: the box takes a follow-up,
    # it is not a fresh search that has forgotten what was just asked.
    #
    # Keyed on an answer existing rather than on there being any messages at all. A
    # question that is still generating, or one that failed and left its retry button,
    # has nothing to follow up on yet — "ask a follow-up" over an empty answer reads as
    # if one arrived.
    answered = any(item["role"] == "assistant" for item in st.session_state.messages)
    prompt = st.chat_input(
        view.copy.followup_placeholder if answered else view.copy.placeholder
    )

    # A marker element rather than a callback, for the same reason `#processing-signal`
    # is one: this file cannot touch the textarea, and a value in the DOM is something
    # app.js can compare against what it last acted on, so a clear empties the box
    # exactly once.
    st.markdown(
        f'<div id="composer-reset" data-token="{st.session_state.clear_token}" '
        "hidden></div>",
        unsafe_allow_html=True,
    )
    return prompt


def submit(prompt: str) -> None:
    """Send what was typed, or say why it is too long and hand it back."""
    asked = prompt.strip()
    if len(asked) > config.MAX_PROMPT_CHARS:
        # The cap the counter used to advertise. Said once, at the moment it matters,
        # instead of counted out on screen for every question that was never near it.
        over = len(asked) - config.MAX_PROMPT_CHARS
        # Keyed for the same reason the upload refusals are: this is the end of the
        # page, and app.js has to know it is there or it reserves room to the last
        # message and leaves the explanation under the composer.
        with st.container(key="prompt-notes"):
            st.warning(
                f"⚠️ That question is {over:,} characters over the "
                f"{config.MAX_PROMPT_CHARS:,}-character limit. Shorten it, or attach "
                "the long part as a file."
            )
            # And handed back, because `st.chat_input` empties its box on submit:
            # without this, "shorten it" asks the reader to shorten something the app
            # has just destroyed. The counter that used to enforce this made
            # overrunning impossible in the first place, so losing the text is a
            # regression this pays off.
            with st.expander("Your question, to copy back out", expanded=True):
                st.code(asked, language=None)
    else:
        start_new_turn(asked, st.session_state.attachments)


def render_think_toggle(view: View) -> None:
    """Ask the model to work through the question before answering.

    A `st.button` that flips a session flag, and NOT `st.toggle`, for the reason that
    cost this app the model picker twice over: a stateful widget stores its value under
    its own widget key, and this one can be changed from Python. An automatic failover
    can move the session to a provider that does not take the field, at which point the
    flag is cleared — and a widget that had been switched on would hand its previous
    value straight back on the next run and switch it on again. The model picker was a
    selectbox and did exactly that with the provider that had just refused; the chat
    list is buttons for the same reason. A button holds no state, so Python's word is
    final.

    Not drawn at all unless the model answering now takes the parameter — see
    `View.can_think`. A pill that is present and does nothing is the failure this app
    has a standing rule about.

    One word in both states, from the profile. The pill is the leftmost member of a
    right-anchored cluster, so a label that grew from "Think" to "Thinking" on click
    would move the control out from under the cursor that had just pressed it. The
    state is said by the fill, and by `aria-pressed` for a reader who cannot see it.
    """
    if not view.can_think:
        # And the flag goes with it, so a failover onto a provider without reasoning
        # cannot leave a turn quietly asking for a field that provider will reject.
        st.session_state.thinking = False
        return
    on = bool(st.session_state.thinking)
    # The state is carried by the CONTAINER KEY, not by an attribute app.js writes.
    # It was `aria-pressed`, set from a marker element on every sync pass, and the
    # paint was a frame behind for good: `sync()` runs off a mutation observer, so the
    # pass that set the attribute saw the state before the click and the pass that
    # would have corrected it never came — measured in the running app, the marker
    # read `data-on="1"` while the button it belonged to still said
    # `aria-pressed="false"` five seconds later. A container key cannot be a frame
    # behind, because Streamlit puts it on the node in the same run that changed it.
    # `sidebar._row` reached the same answer for which conversation is open, and its
    # comment is the general form: the container key is the only thing a stylesheet
    # can read. app.js still sets `aria-pressed` for the accessibility tree, where
    # being a frame late costs nothing a reader can see.
    with st.container(key="think-on" if on else "think-off"):
        if st.button(view.copy.think_label, key="think-toggle"):
            st.session_state.thinking = not on
            st.rerun()
    # What app.js needs to style and label it: the state, and the words for the
    # `title`/`aria-label` it sets. A marker element rather than `help=`, because
    # Streamlit's tooltip is a black panel beside the cursor AND it wraps the control
    # in a second, zero-sized copy of the button — which the composer's geometry
    # bounds would then be measuring. The ✕ on a chat row is labelled the same way.
    st.markdown(
        f'<div id="think-state" data-on="{"1" if on else "0"}" '
        f'data-label="{html.escape(view.copy.think_label, quote=True)}" '
        f'data-hint="{html.escape(view.copy.think_hint, quote=True)}" hidden></div>',
        unsafe_allow_html=True,
    )


def render_controls(view: View) -> None:
    """The Think toggle, parked inside the input box at its bottom right.

    Two controls have stood here and gone. A 🗑️ that emptied the conversation, removed
    because the chat panel has a ✕ on every row and a New chat button above them. And
    the model picker, which named what would answer and let a reader change it — the
    documented way round a spent quota. It is gone by decision: "we shouldn't have a
    model picker but rather use the model picker position for the think toggle... we
    don't need users to pick a model or anything like that."

    What that costs is worth writing down rather than discovering. A reader can no
    longer move off a model that is slow or answering badly; the only remaining manual
    switch is the error card's "Use <model>", which appears when a turn has already
    failed. Automatic failover is untouched — `View.alternative` and the whole lineup
    still walk on a refusal — so the recovery path that matters most is the one that
    never needed a control. And nothing on the page now names the model answering.
    Where a deployment's default is a router that serves a different model per request,
    that label was already telling the reader less than it appeared to — which is why
    a profile gives such a row a nickname instead of a model name.

    `st.container(key="composer-strip")` keeps its name. It was historical when one
    control replaced two, and it is historical again; renaming it would touch a dozen
    stylesheet rules, the layout harness's fixture and its selector table, to say what
    this comment says for free.

    No `st.columns`: a column has no intrinsic width, which is how the picker came to
    be invisible twice.

    Nothing measures where this sits any more, and that is the point. It used to be a
    `position: fixed` container at `--pick-right`/`--pick-bottom`, which app.js
    published by measuring Streamlit's own send button every pass — and a fixed element
    chasing a measurement of the box can only follow it: "it can jump out of the box
    when scrolling up and down", while the send arrow never did because the arrow is
    really inside the box. What Streamlit renders here is now the clipped hook; the
    visible pill is `#think-btn`, injected by app.js INTO
    `[data-testid="stChatInput"]` and positioned from the box's own edges.
    """
    with st.container(key="composer-strip"):
        render_think_toggle(view)


def render_stop_hook() -> None:
    """The Streamlit button app.js clicks, and the only thing that can end a turn.

    Clipped to a pixel, exactly like the file uploader above it, for the same reason:
    the control the reader actually presses is drawn in the composer by app.js, where
    the send button was a moment ago, and this is the widget that carries the click
    back to Python. A `st.button` is the only thing that can — nothing app.js injects
    has a channel to this script.

    Rendered before the turn block and nowhere else. That block ends in `st.rerun()`,
    so a widget declared after it does not exist on the one run where it is needed.

    Rendered on EVERY run, though, not only while a turn is in flight. It used to be
    conditional, which tied a widget's lifetime to a turn's: Streamlit forgets a
    widget the moment a run does not re-create it, and this one is created on the runs
    where an answer is streaming and destroyed on the run that stops it. Nothing was
    ever proved to go wrong there — a stop trigger was traced across three
    stop-then-ask cycles and never fired twice — but the window costs nothing to
    close, and what it would look like if it ever opened is a turn nobody stopped
    ending as `Stopped`. `finish_stopped_turn` ignores a request with no turn running,
    so an always-present button is inert exactly when it should be, and app.js only
    draws the square while `#processing-signal` is on the page.
    """
    st.button("Stop generating", key="stop-generation", on_click=request_stop)

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
            # ignores it. The picker is right there.
            st.caption(
                f"{view.model.label} cannot read images — pick a "
                f"{_vision_names()} model to have this one looked at."
            )


def _vision_names() -> str:
    """"a Pixtral or Claude" — from the configured list, not from a sentence.

    `SAGE_VISION_MODELS` is what decides whether the caption appears at all, so it is
    also what should decide which names it tells the reader to look for. Written out
    by hand, the two drifted apart the first time a deployment set the variable.
    """
    names = [mark.strip().title() for mark in config.VISION_MODELS if mark.strip()]
    if not names:
        return "vision-capable"
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} or {names[-1]}"


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


def render_model_picker(view: View) -> None:
    """Switch provider/model mid-session — the way round a spent API quota.

    Drawn in the corner of the input box, beside the send button: it names what will
    answer, next to the control that sends.


    A popover of buttons rather than a selectbox, for two reasons that both bit:

    * A selectbox stores its own value under its widget key. After an automatic
      failover set `session_state.model` and reran, the selectbox handed back its
      *previous* value on that run and switched straight back to the provider
      that had just refused. Buttons hold no state, so a programmatic switch
      survives.
    * A selectbox is a block with no intrinsic width, so in a row that sizes its
      children to their content it resolved to zero and the control was invisible.
      A button is sized by its label, exactly like the ℹ️ and 🗑️ beside it.
    """
    if len(view.models) < 2:
        return
    # One `with`, not two nested: the caption that used to sit between them is gone,
    # and ruff is right that a bare nest reads as if something belonged in the gap.
    with st.popover(view.model.label), st.container(key="model-list"):
        for index, option in enumerate(view.models):
            mark = "●" if option.key == view.model.key else "○"
            if st.button(
                f"{mark}  {option.label}",
                key=f"pick-{index}",
                use_container_width=True,
            ):
                st.session_state.model = option.key
                # A deliberate choice clears the record of the automatic one,
                # so the next refusal can fail over again.
                st.session_state.tried = []
                st.session_state.switched_from = None
                st.session_state.notice = ""
                st.rerun()


def render_controls(view: View, has_messages: bool) -> None:
    """The model picker, parked inside the input box at its bottom right.

    There used to be a 🗑️ beside it that emptied the conversation. It is gone: the panel
    of chats has a ✕ on every row and a New chat button above them, so the trash was a
    third way to do a thing there were already two better ways to do — "the trash can be
    removed because of this design".

    And with the trash gone the row itself had no reason to be a row. The picker is one
    control, so it sits *in* the composer rather than under it: the bar no longer reserves
    a band below the input for a strip of controls, which is a little over 4rem of
    vertical space the page gets back and the reason the input box now sits lower.

    `st.container(key="composer-strip")` keeps its name, and the name is now historical —
    it is one control in the corner of the box, not a strip under it. Renaming the key
    would touch a dozen stylesheet rules, the layout harness's fixture and its selector
    table, all to say something the comment above says for free.

    `has_messages` is still taken, and no longer read. It said whether there was anything
    to clear, which was the trash's question.

    No `st.columns`: a column has no intrinsic width, which is how the picker came to be
    invisible twice. Where it sits is measured by app.js from Streamlit's own send
    button and published for the stylesheet, so it stays beside it at every width.
    """
    with st.container(key="composer-strip"):
        render_model_picker(view)


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

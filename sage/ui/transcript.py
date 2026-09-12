"""The conversation: questions, the way back into them, answers and their sources."""

from __future__ import annotations

import html

import streamlit as st

from .. import config, feedback, links
from .state import may_start_turn, start_new_turn
from .view import View


def escape(text: str) -> str:
    return html.escape(text, quote=False).replace("\n", "<br>")


# --- questions -------------------------------------------------------------


def render_user(message: dict, position: int | None = None) -> None:
    """One question in the transcript, and the way back into it.

    `position` is its index in `messages`, and passing None means "not editable" —
    the one caller that does is the turn block, which draws the question it is
    currently answering. A pencil on that one would offer to rewrite a question while
    the answer to it is arriving.
    """
    if position is not None and st.session_state.editing == position:
        render_user_editor(position, message)
        return

    badges = "".join(
        f'<div class="attachment-badge">{item.icon} '
        f"{html.escape(item.filename)}</div>"
        for item in (message.get("attachments") or [])
    )
    # Wrapped in a row of their own. Loose in the bubble they were inline boxes, so the
    # question ran straight on from the last filename with no space at all.
    if badges:
        badges = f'<div class="attachment-badges">{badges}</div>'
    st.markdown(
        f'<div class="user-message"><div class="user-bubble">{badges}'
        f'{escape(message.get("text", ""))}</div></div>',
        unsafe_allow_html=True,
    )
    if position is not None:
        render_edit_hook(position)


def render_edit_hook(position: int) -> None:
    """The clipped button app.js's pencil clicks, one per question.

    The same arrangement as the paperclip and the stop square: the control the reader
    presses is drawn by app.js, in the gutter beside the bubble where there is already
    empty space, and this is the widget that carries the click back to Python. Only a
    `st.button` can do that, and a `st.button` here — in the flow, under every
    question — would be a row of furniture the transcript does not have today.

    So it is taken out of the flow instead, clipped to a pixel exactly as the file
    uploader is. app.js pairs the Nth `.user-message` with the Nth of these, which
    holds because this is rendered immediately after the bubble it belongs to and
    both lists are read in document order.

    Bare, with no `st.container` around it. There was one, and the wrapper was the bug:
    Streamlit reuses a container's DOM node across reruns and relabels its class rather
    than rebuilding it, so after one open-and-cancel the node carrying
    `st-key-edit-hook-0` was the node that had been an answer — still holding the copy
    button app.js had appended to it, because that button is not React's to remove.
    app.js looked inside for `button` and got the copy button. Every pencil on the page
    then copied an answer to the clipboard instead of opening the editor, silently, for
    the rest of the session. Keyed on the widget itself, there is no wrapper to reuse.

    Disabled while an answer generates, for the reason the rating buttons are: the
    click is the rerun, so it would abandon the answer on screen. The stop button is
    the control for that, and it is the one that says so.
    """
    if st.button(
        "Edit this question",
        key=f"edit-open-{position}",
        disabled=st.session_state.processing,
    ):
        st.session_state.editing = position
        st.session_state.edit_session += 1
        st.rerun()


def render_user_editor(position: int, message: dict) -> None:
    """The question, in a box, standing where its bubble stood.

    Sending replaces this question and drops everything after it, because everything
    after it is a reply to wording that is being withdrawn. That is destructive, and
    it is the reason this is a two-step control rather than an editable bubble that
    resends on blur: the reader has to send for the tail of the conversation to go.

    The attachments come with it. They belong to the question, not to the text of it,
    and re-uploading three files to fix a typo is not an edit.

    **A form, and that is the whole point of the shape.** Streamlit prints "Press
    ⌘+Enter to apply" inside every multi-line text box it draws, and there is no
    argument that turns it off. On a bare `st.text_area` that sentence is a lie of
    omission: the key commits the value to the widget and nothing else, so the reader
    who believed it — and the reader who wrote this app did believe it, in the box
    itself — pressed it, watched nothing happen, and had to go and find the button.
    Inside `st.form` the same key submits, so the instruction the box gives is the
    instruction that works.

    The keys carry `session`, a counter bumped every time the pencil is pressed, so
    no widget key is ever reused. Streamlit drops a widget's state when a run does
    not re-create it, and these are created only while the editor is open — reusing
    `edit-send-0` across two openings is exactly the shape that makes a stale button
    value arrive as a click nobody made. A question re-sent because the reader opened
    the editor is worse than any bug this file has had, because it costs a turn and
    deletes the conversation under it.
    """
    attachments = message.get("attachments") or []
    session = st.session_state.edit_session
    # Questions asked after this one. Their answers replied to wording that is being
    # withdrawn, so sending takes them with it — which is right, and was a shock:
    # "i edited the first message in the chat history but everything got wiped off,
    # all the chat." It was one turn and the whole chat was that turn, so nothing
    # unexpected happened except that nothing had said it would. Said here, before
    # the button, and only when there is actually something to lose.
    later = sum(
        1
        for item in st.session_state.messages[position + 1 :]
        if item.get("role") == "user"
    )
    with (
        st.container(key=f"edit-box-{position}"),
        st.form(key=f"edit-form-{session}", border=False, clear_on_submit=False),
    ):
        if later:
            st.caption(
                f"⚠️ Sending replaces this question and removes the "
                f"{later} later question{'s' if later != 1 else ''} and "
                f"{'their' if later != 1 else 'its'} answers."
            )
        if attachments:
            st.caption(
                "Still attached: " + ", ".join(item.filename for item in attachments)
            )
        edited = st.text_area(
            "Edit your question",
            value=message.get("text", ""),
            key=f"edit-text-{session}",
            label_visibility="collapsed",
        )
        # Right-aligned, and the wide spacer is what does it: the buttons belong under
        # the right-hand edge of a box that stands where a right-aligned bubble stood,
        # not adrift at the left margin of a page whose questions are all on the other
        # side.
        columns = st.columns([6, 2, 2], gap="small")
        with columns[1]:
            send = st.form_submit_button(
                "Send", type="primary", use_container_width=True
            )
        with columns[2]:
            cancel = st.form_submit_button("Cancel", use_container_width=True)
        asked = (edited or "").strip()
        if send and len(asked) > config.MAX_PROMPT_CHARS:
            # The same cap the composer enforces, said here because this box does not
            # go through it. Nothing is dropped: the text stays in the box.
            over = len(asked) - config.MAX_PROMPT_CHARS
            st.warning(
                f"⚠️ That question is {over:,} characters over the "
                f"{config.MAX_PROMPT_CHARS:,}-character limit."
            )
            send = False
        elif send and not asked:
            st.warning("⚠️ A question cannot be empty.")
            send = False

    if cancel:
        st.session_state.editing = None
        st.rerun()
    if send:
        start_new_turn(asked, attachments, replacing=position)


# --- citations -------------------------------------------------------------


def citations(chunks: list) -> list[dict]:
    """The Sources strip: one entry per destination, in the order they were read.

    Deduplicated on the URL and not the chunk id, because the id is an index key and
    the URL is what the reader is given. The two come apart wherever indexing cuts
    finer than the published page can be linked: a scraped page is windowed and every
    window shares the page URL, and `search_docs` may return two windows of one page
    (MAX_PER_PAGE allows two sections of any page). "Who is the director of the RCC"
    listed four citations that were two pages. An over-long docs section splits the
    same way and its parts share one anchor.

    The first read of a destination keeps the slot: it is the one the answer was built
    from first, and its label is the page's own name rather than a later cut's.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for chunk in chunks:
        if chunk.url in seen:
            continue
        seen.add(chunk.url)
        out.append(
            {
                "id": chunk.id,
                "label": chunk.label,
                "url": chunk.url,
                "source": chunk.source,
            }
        )
    return out


def related_sections(corpus, sources: list[dict], limit: int = 3) -> list[dict]:
    """Sibling sections of the pages actually cited — discovery for free.

    No extra model call: the chunks are already indexed, so neighbouring sections
    of a cited page are known and are always real documentation.

    A lead is somewhere the reader is not already being sent, so what has to be new is
    the destination — the URL — and not the chunk id. Filtering on the id let one page
    arrive three times: asking who directs the RCC cited "Our Team" and then offered
    "Our Team (part 2)", "(part 3)" and "(part 4)", which were three of that page's
    thirteen indexing windows, three identical links, and the link already listed
    directly above them under Sources. Three windows of one page is not discovery, it
    is the citation again with a number after it.

    Showing nothing is the right answer when a page has nothing else to point at, and
    for a scraped page that is always: it has no anchors, so no window of it is ever a
    second destination. `render_sources` omits the block entirely when this is empty.
    """
    seen = {source.get("url", "") for source in sources}
    pages = {source["id"].split("#", 1)[0] for source in sources}
    out: list[dict] = []
    for chunk in corpus.chunks:
        if len(out) >= limit:
            break
        page = f"{chunk.source}/{chunk.path}"
        if page not in pages or chunk.url in seen or not chunk.heading:
            continue
        seen.add(chunk.url)
        out.append({"label": chunk.heading, "url": chunk.url})
    return out


def render_sources(sources: list[dict], related: list[dict]) -> None:
    """The citations under an answer, and the sibling sections worth a look.

    Two lists rather than two rows of identical chips. They used to share every class,
    which left the reader unable to tell what the answer was built from ("Sources")
    from what it merely suggests next ("Related") — and as wrapping chip rows they were
    ragged: a flex row whose first item is the label indents its first line only, so
    every later line dropped back to the container edge, 66px to the left of the line
    above it, measured with six real citations at the 820px content width.

    Sources are numbered, one per line, the way a paper cites: the number is what makes
    a reference list readable, and it lets an answer say "see 2" if it wants to. Related
    is a plain vertical list of leads, no numbers and no source badge, which is the
    difference in kind said in the layout instead of in a heading.
    """
    if not sources:
        return
    items = "".join(
        f'<div class="source-item">'
        f'<a class="source-link" href="{html.escape(source["url"], quote=True)}" '
        f'target="_blank" rel="noopener noreferrer">{html.escape(source["label"])}</a>'
        f'<span class="source-kind">{html.escape(source["source"])}</span></div>'
        for source in sources
    )
    strip = (
        '<div class="sources"><span class="sources-label">Sources</span>'
        f'<div class="source-list">{items}</div></div>'
    )

    if related:
        leads = "".join(
            f'<div class="related-item">'
            f'<a class="related-link" href="{html.escape(item["url"], quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">{html.escape(item["label"])}</a>'
            "</div>"
            for item in related
        )
        strip += (
            '<div class="sources related"><span class="sources-label">Related</span>'
            f'<div class="related-list">{leads}</div></div>'
        )
    st.markdown(strip, unsafe_allow_html=True)


# --- answers ---------------------------------------------------------------


def render_rating(position: int, message: dict) -> None:
    if not feedback.enabled():
        return
    if message.get("rating"):
        st.markdown(
            '<div class="rating-thanks">Thanks — noted.</div>', unsafe_allow_html=True
        )
        return

    with st.container(key=f"rate-{position}"):
        columns = st.columns([1, 1, 12], gap="small")
        for column, verdict, glyph, hint in (
            (columns[0], "up", "👍", "This answered my question"),
            (columns[1], "down", "👎", "This was wrong or unhelpful"),
        ):
            with column:
                if st.button(
                    glyph,
                    key=f"rate-{position}-{verdict}",
                    help=hint,
                    # Not while an answer is arriving. Any click reruns the script,
                    # and a rerun mid-turn abandons the half-written answer and runs
                    # the whole turn again from the first provider call — so rating an
                    # earlier answer while the next one streams silently costs a
                    # second turn and loses the one on screen. `disabled` is what
                    # stops the click reaching the server at all; an inert callback
                    # would not, because the rerun is the click, not the handler.
                    disabled=st.session_state.processing,
                ):
                    question = next(
                        (
                            item.get("text", "")
                            for item in reversed(
                                st.session_state.messages[:position]
                            )
                            if item.get("role") == "user"
                        ),
                        "",
                    )
                    feedback.record_rating(
                        verdict,
                        question,
                        message.get("text", ""),
                        message.get("sources", []),
                    )
                    message["rating"] = verdict
                    st.rerun()


def _evidence(view: View, sources: list[dict]) -> dict[str, str]:
    """The text of each section the answer was built from, keyed by its chunk id.

    What `links.mark_sources` attributes an unlinked paragraph with when the turn read
    exactly one section — the case where there is nothing to get wrong. It is read
    from the corpus rather than stored on the message because it is already there:
    the strip carries the ids, and the ids resolve.
    """
    found = {}
    for source in sources:
        chunk = view.corpus.chunk(str(source.get("id", "")))
        if chunk is not None:
            found[chunk.id] = chunk.text
    return found


def render_assistant(view: View, position: int, message: dict) -> None:
    sources = message.get("sources", [])
    with st.container(key=f"answer-{position}"):
        with st.chat_message("assistant"):
            text = message.get("text", "")
            if text:
                # Resolve the paths the model wrote, then number them against the
                # strip below, so a claim carries a marker to the section it rests on
                # and the marker and the strip agree. Both are render-time: the stored
                # answer keeps its links, because that text goes back upstream as
                # history.
                st.markdown(
                    links.mark_sources(
                        links.fix_links(text, view.corpus), sources, _evidence(view, sources)
                    )
                )
            if message.get("stopped"):
                # Said inside the bubble, under the text it belongs to. A stopped
                # answer that ends mid-sentence otherwise reads as a model that broke
                # off on its own, and the difference matters: one is worth retrying
                # and the other is the reader's own doing. It is also the only thing
                # in the bubble when the stop landed before any text, which is what
                # keeps that turn from rendering as nothing at all.
                st.markdown(
                    '<div class="stopped-note">Stopped</div>', unsafe_allow_html=True
                )
        render_sources(sources, related_sections(view.corpus, sources))
        # Not on a stopped answer. Rating half a sentence the reader cut off says
        # nothing about whether the app answered the question.
        if not message.get("stopped"):
            render_rating(position, message)


# --- the strips under the conversation --------------------------------------


def render_notice() -> None:
    """The neutral strip: a failover, or a turn the limiter would not start.

    Rendered on the landing screen too, and that is the point. It used to live inside
    the branch that draws a conversation, so a refusal with nothing on screen yet had
    nowhere to appear: clear the chat, click a starter card with the token bucket
    empty, and the click did nothing at all — no question, no answer, no reason, on a
    screen whose only controls are those cards.
    """
    if st.session_state.notice:
        # `role="status"` because this is often the only account of why a click did
        # nothing, and a reader who cannot see it has no other way to be told.
        st.markdown(
            f'<div class="notice" role="status">'
            f"{html.escape(st.session_state.notice)}</div>",
            unsafe_allow_html=True,
        )


def render_error_card(view: View) -> None:
    """What went wrong, and the two things that can be done about it."""
    st.markdown(
        '<div class="error-card" role="alert">'
        '<div class="error-title">Could not complete that request</div>'
        f'<div class="error-body">{html.escape(st.session_state.error)}</div></div>',
        unsafe_allow_html=True,
    )
    if st.session_state.error_detail:
        # Streamlit Cloud logs are awkward to reach; surfacing the real exception here
        # is what turns "something went wrong" into a fixable report. Collapsed so it
        # stays out of the way for normal users.
        with st.expander("Technical details"):
            st.code(st.session_state.error_detail, language="text")
    # "Switch to another model" is only useful if switching is one click away from
    # where the advice appears. Sending the user hunting for a control elsewhere on
    # the page is how a spent quota became a dead end.
    alternative = view.fallback
    with st.container(key="error-actions"):
        # Half-width each, flush with the error card above: narrower columns wrapped
        # the model name onto a second line, which looks broken.
        slots = st.columns(2) if alternative else st.columns([1, 2, 1])
        with slots[0] if alternative else slots[1]:  # centred when alone
            retry = st.button("↻ Try again", key="retry", use_container_width=True)
        switch = False
        if alternative:
            with slots[1]:
                switch = st.button(
                    f"→ Use {alternative.label}",
                    key="switch-model",
                    use_container_width=True,
                )
    if retry or switch:
        # Switching model happens either way, before the gate. It costs nothing and it
        # is the remedy the card itself recommends — refusing it while a bucket refills
        # would take the fix away from the reader at the moment they reached for it,
        # and leave "switch to another model and try again" printed above a button
        # that does neither.
        if switch:
            st.session_state.model = alternative.key
            st.session_state.switched_from = None
        # The turn, though, goes through the same gate as a new question: it costs the
        # same one-to-five provider calls, and skipping the check meant a spent
        # deployment budget stopped new questions while this button went on spending,
        # one turn per click. On a refusal the error card and its buttons stay exactly
        # where they are — clearing them would take away the only way back — and the
        # notice above says how long to wait.
        if may_start_turn():
            # On both paths, not just the deliberate switch: "Try again" is the reader
            # asking for another attempt, and leaving the guard set means the retry
            # cannot fail over even though this is a fresh attempt at the question.
            st.session_state.tried = []
            st.session_state.error = None
            st.session_state.error_detail = ""
            if st.session_state.messages[-1]["role"] == "user":
                st.session_state.processing = True
        st.rerun()


def render_conversation(view: View) -> None:
    """Every message so far, then the notice and error strips beneath them."""
    # Marker only: app.js keys page-scroll behaviour off its presence — without it
    # the screen is the landing screen, which always starts at the top.
    st.markdown('<div class="chat-container"></div>', unsafe_allow_html=True)

    rendered = st.session_state.messages
    if st.session_state.processing and rendered and rendered[-1]["role"] == "user":
        rendered = rendered[:-1]

    for position, message in enumerate(rendered):
        if message["role"] == "user":
            render_user(message, position)
        elif message.get("text") or message.get("stopped"):
            # `or stopped`: an assistant turn with no text is normally nothing to
            # draw, but a turn stopped before its first token is a thing that
            # happened and the reader has to see that it did.
            render_assistant(view, position, message)

    render_notice()

    if st.session_state.error and not st.session_state.processing:
        render_error_card(view)

"""Taking files off the uploader widget, once each, with a reason when one is refused.

The widget is the awkward part: it re-reports every file it holds on every rerun,
nothing here can reach in and remove one, and a refusal has to outlive the run that
produced it. What is *in* a file (whether it is text, whether it is an image, how it
is decoded) is `sage/files.py`, which knows nothing about Streamlit.
"""

from __future__ import annotations

import hashlib

import streamlit as st

from .. import config, ocr


def upload_key(item) -> tuple:
    """Identity of an uploaded file across reruns.

    Name, size and a digest of the first 4 KB, not Streamlit's `file_id`, which
    changes on every rerun for the same file in some versions and would re-process and
    re-append one attachment per interaction with the page.

    The digest is there because name and size alone collided: two different
    `config.yaml` files of the same length were one attachment, and the second was
    dropped without a word. 4 KB rather than the whole file so a 10 MB upload is not
    rehashed on every rerun.
    """
    head = item.getvalue()[:4096]
    return (item.name, item.size, hashlib.blake2b(head, digest_size=8).hexdigest())


def render() -> None:
    """Draw the (clipped) uploader, take what it offers, and explain any refusals."""
    # `accept_multiple_files`, and no `type=`.
    #
    # The type filter was a list of extensions the picker would offer, and it is gone
    # for the same reason the extension gate in `files.process` went: it refused a
    # pasted screenshot outright (the name app.js gives one is not on any list) and it
    # refused every cluster file whose extension nobody thought of. `files.process`
    # reads the bytes and says yes or no with a reason, which is the check that was
    # doing the work anyway.
    upload = st.file_uploader(
        "Attach a file",
        accept_multiple_files=True,
        key=f"uploader-{st.session_state.uploader_key}",
        label_visibility="collapsed",
    )

    keyed = [(upload_key(item), item) for item in upload or []]
    offered = {key for key, _item in keyed}

    # Dismissals are COUNTED, not just remembered, and the count is how many copies of
    # a file to skip on this run.
    #
    # A plain set of keys blacklisted the file outright, so after dismissing a chip the
    # user could pick the *same file* again and nothing whatsoever happened: no chip,
    # no warning. Worse on the landing screen, where the Clear button that resets this
    # does not render, so there was no route back at all short of reloading the page.
    #
    # Counting keeps the distinction that matters. `accept_multiple_files` accumulates,
    # so a re-picked file is reported twice: one dismissal skips the first copy and the
    # second is a fresh offer and attaches. A file dismissed and not re-picked is still
    # reported once, still skipped, and still does not come back on its own.
    dismissed = dict(st.session_state.dropped_uploads)
    # Keys the widget has stopped reporting cannot come back, so their counts are dead.
    dismissed = {key: count for key, count in dismissed.items() if key in offered}

    # Reasons files were refused, so the explanation outlives the run that produced it.
    # A bare `st.warning` is discarded whenever the run ends in a rerun (which it does
    # whenever a file is dropped while an answer is generating), and the refusal was
    # permanent, so the user was left with a file in the uploader, no chip, and no
    # reason.
    refusals = {
        key: why
        for key, why in dict(st.session_state.get("upload_refusals", {})).items()
        if key in offered
    }

    held = {item.key for item in st.session_state.attachments if item.key}
    for key, item in keyed:
        if key in held:
            continue
        if dismissed.get(key, 0) > 0:
            dismissed[key] -= 1
            continue
        # `ocr.process` is `files.process` plus one more try for a scanned PDF, when
        # `config.PDF_OCR` asks for it; off, the two are the same call.
        attachment, error = ocr.process(item.name, item.getvalue())
        if not error:
            # The per-file limit does not bound the total, and a handful of legal
            # screenshots made one illegal request. Refused here rather than by the
            # provider, which reports it as "this conversation got too long".
            attached = sum(held_item.size for held_item in st.session_state.attachments)
            if attached + item.size > config.MAX_ATTACHED_BYTES:
                limit = config.MAX_ATTACHED_BYTES // (1024 * 1024)
                error = (
                    f"{item.name} would put this turn over the {limit} MB total for "
                    "attachments. Send what is attached first, or drop something."
                )
        if error:
            # Remembered rather than clearing the whole widget: a bad file among three
            # good ones used to reset the uploader and take the other two with it.
            st.session_state.dropped_uploads[key] = (
                st.session_state.dropped_uploads.get(key, 0) + 1
            )
            refusals[key] = error
            continue
        attachment.size = item.size
        attachment.key = key
        st.session_state.attachments.append(attachment)
        held.add(key)

    st.session_state.upload_refusals = refusals
    if refusals:
        # In a container of its own, and the key is the point: these land at the end of
        # the page, below the last message, and app.js measures the end of the page to
        # decide how much room the composer needs and where to scroll. It had no idea
        # these existed, so on a conversation the reason a file was refused rendered
        # 65 of its 80 pixels *behind* the input bar: a file that did not attach, and
        # an explanation the reader could not see. `.st-key-upload-notes` is what makes
        # it part of the tail. Created only when there is something to say, so an empty
        # container is never in the way of that measurement.
        with st.container(key="upload-notes"):
            for why in refusals.values():
                st.warning(f"⚠️ {why}")

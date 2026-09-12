"""The stylesheet, the script, and the one measurement CSS cannot make.

Nothing here decides how the app looks — `static/app.css` does, and it is guarded by
`.claude/hooks/ui-guard.sh`, `tools/palette_check.py` and `tests/test_palette.py`.
This only gets it onto the page.
"""

from __future__ import annotations

import logging
import os

import streamlit as st
import streamlit.components.v1 as components

logger = logging.getLogger(__name__)

# `sage/ui/assets.py` -> the repository root -> `static/`.
STATIC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "static",
)


@st.cache_resource(show_spinner=False)
def load(name: str) -> str:
    try:
        with open(os.path.join(STATIC, name), encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        logger.error("Missing static asset %s: %s", name, exc)
        return ""


def inject() -> None:
    st.markdown(f"<style>{load('app.css')}</style>", unsafe_allow_html=True)
    components.html(f"<script>{load('app.js')}</script>", height=0)


def size_model_picker(models) -> None:
    """Tell the stylesheet how wide the picker's trigger has to be.

    The stylesheet cannot work this out: the lineup is discovered from the provider at
    runtime, so the longest name it can show is known here and nowhere else. Sized to
    the longest rather than to the selected one on purpose — a width that tracked the
    selection would resize the button every time a model was picked, which reflows the
    row it sits in the corner of.

    A second `<style>` because the stylesheet is injected before any provider has been
    asked what it serves, and moving that injection later would leave the no-key error
    screen unstyled.
    """
    if not models:
        return
    st.markdown(
        f"<style>:root {{ --picker-chars: {max(len(m.label) for m in models)}; }}"
        "</style>",
        unsafe_allow_html=True,
    )

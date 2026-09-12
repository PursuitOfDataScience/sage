#!/usr/bin/env python3
"""Sage — a documentation assistant (Streamlit entry point).

This file is the *order of the page*, and almost nothing else. What the assistant is
about comes from a profile (`profiles/*.toml`); how it reads, searches, answers and
draws comes from `sage/` and `sage/ui/`. What is left here is the sequence, which
Streamlit makes load-bearing in a way that is worth being able to read in one screen:

    page config → assets → runtime → keys → login → state → model
    → sidebar (the chats in this session)
    → body (landing screen | conversation)
    → uploader → input box → attachments → controls → stop hook
    → the turn

Every step is one call. Moving one is a UI change, which is why they are listed
rather than scattered: `st.rerun()` means nothing after it runs, `set_page_config`
must come first, and `static/app.js` finds several of these widgets by the position
they are drawn in.
"""

from __future__ import annotations

import logging

import streamlit as st

from sage import config, profile, providers, runtime
from sage.ui import (
    access,
    assets,
    composer,
    landing,
    sidebar,
    state,
    transcript,
    turn,
    uploads,
)
from sage.ui.view import View

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.WARNING),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sage.app")

PROFILE = profile.active()

st.set_page_config(
    page_title=PROFILE.identity.page_title,
    page_icon=PROFILE.identity.icon,
    layout="wide",
    initial_sidebar_state="collapsed",
)

assets.inject()


@st.cache_resource(show_spinner=f"Indexing {PROFILE.identity.topic} documentation…")
def load_runtime() -> runtime.Runtime:
    return runtime.build(PROFILE)


# Both gates before the index is built: a deployment with no key cannot answer, and a
# visitor who has not signed in must not be answered, and neither is worth seven
# seconds of indexing to find out.
READY = access.configured_providers()
if not READY:
    st.error(access.missing_key_message())
    st.stop()

access.gate(PROFILE.copy)

RUNTIME = load_runtime()
state.initialise()


def current_model(models: list[providers.Model]) -> providers.Model:
    """The selected model, falling back to the configured default then anything."""
    for candidate in (st.session_state.model, config.DEFAULT_MODEL):
        chosen = providers.parse_key(candidate)
        if chosen and any(option.key == chosen.key for option in models):
            return chosen
    if models:
        return models[0]
    # Nothing was discovered and nothing was configured: the provider is reachable
    # only in the sense that it has a key. Naming its first declared model is the
    # best guess available, and it is the profile's guess rather than this file's.
    entry = providers.entry(READY[0])
    return providers.Model(READY[0], entry.models[0] if entry and entry.models else "")


MODELS: list[providers.Model] = []
for name in READY:
    MODELS.extend(access.available_models(name))

MODEL = current_model(MODELS)
st.session_state.model = MODEL.key
VIEW = View(runtime=RUNTIME, models=tuple(MODELS), model=MODEL)

# Before anything is drawn: the stop button's callback has already run, and the
# transcript below hides the last question while `processing` is set.
if st.session_state.stop_requested:
    state.finish_stopped_turn(MODEL.key, VIEW.public_names)

has_messages = bool(st.session_state.messages)

# --- the chats in this session ----------------------------------------------
#
# Before the body, because every control in it ends in `st.rerun()`: a switch drawn
# after the conversation would redraw the conversation it is leaving first, and on the
# run that opens an empty chat that is a whole transcript rendered to be thrown away.
# Drawn on every screen, landing included, so the way back to a previous chat does not
# disappear the moment one is cleared.

sidebar.render(VIEW)

# --- body ------------------------------------------------------------------

if not has_messages:
    landing.render(VIEW)
else:
    transcript.render_conversation(VIEW)

# --- composer ---------------------------------------------------------------
#
# All of it before the turn below: that block ends in `st.rerun()`, so anything after
# it is never reached while an answer is generating — which is exactly when a user
# whose model just ran out of credit reaches for the picker.

uploads.render()
prompt = composer.ask(VIEW)
composer.render_attachments(VIEW)
composer.render_controls(VIEW)
composer.render_stop_hook()

if prompt and prompt.strip():
    composer.submit(prompt)

# --- the turn ---------------------------------------------------------------

if st.session_state.processing:
    turn.run(VIEW)

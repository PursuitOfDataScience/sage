"""Who may use this deployment, and which providers it can actually reach.

Both questions are asked before anything is drawn, and both can stop the page: no
key at all is a deployment that cannot answer, and a login gate that has not been
passed is one that must not.
"""

from __future__ import annotations

import logging
import threading
import uuid

import streamlit as st

from .. import config, providers, quota

logger = logging.getLogger(__name__)


def api_key(provider: str) -> str:
    """The provider's key, from the environment or from `st.secrets`."""
    key = providers.api_key(provider)
    if key:
        return key
    variable = providers.key_var(provider)
    if not variable:
        return ""
    try:
        return str(st.secrets.get(variable, ""))
    except Exception:  # no secrets.toml present
        return ""


def configured_providers() -> list[str]:
    """Providers that actually have a key, in the profile's preference order."""
    return [name for name in providers.names() if api_key(name)]


def missing_key_message() -> str:
    """What to say when nothing is configured, naming this profile's variables.

    Built from the provider list rather than written out, so a deployment that swaps
    Mistral for Anthropic is not told to set `MISTRAL_API_KEY`.
    """
    entries = [providers.entry(name) for name in providers.names()]
    variables = [item.key_env for item in entries if item and item.key_env]
    if not variables:
        return (
            "**No provider is configured.** Add a `[[providers]]` entry to the "
            "profile, then reload."
        )
    named = " and/or ".join(f"`{variable}`" for variable in variables)
    hints = " ".join(item.hint for item in entries if item and item.hint)
    return (
        f"**No API key is set.** Provide {named} in the environment or "
        f"`.streamlit/secrets.toml`, then reload. {hints}".rstrip()
    )


@st.cache_resource(show_spinner=False)
def get_provider(name: str):
    """Cached per provider; the key is read inside so it never becomes a cache key."""
    return providers.build(name, api_key(name))


# An hour, and the `ttl` is the whole point of this decorator call. `cache_resource`
# without one holds for the life of the process, and the lineup is discovered rather
# than configured precisely so that a model the provider starts serving appears with no
# commit, which a list fetched once at boot and never again cannot do. It used to work
# by accident: Streamlit Community Cloud hibernates an idle app, so the process died
# roughly daily and the next reader got a fresh catalogue. `keepalive.yml` then started
# pinging every four hours to stop the app sleeping, and took that restart away with it,
# so `x-preview-f-free` was served by the provider, discovered correctly by
# `openai_compat.models()`, and still absent from the picker for as long as the process
# stayed up. Costs one keyless `GET /models` an hour; Zen serves it without a key at all.
@st.cache_resource(show_spinner=False, ttl=3600)
def available_models(name: str) -> list[providers.Model]:
    try:
        provider = get_provider(name)
        found = provider.models()
        # The same hour's check of the key's own counters, for an entry that names an
        # endpoint for them. Off the page's thread: a slow status endpoint must not hold
        # up the render that happens to refresh this cache.
        watch_limits(name, provider)
        return found
    except Exception as exc:
        # Cached like any other result, so a provider that is briefly unreachable does
        # not empty the picker for the rest of the process's life, only until the ttl
        # lapses. Another reason not to leave this unbounded.
        logger.warning("Could not list models for %s: %s", name, exc)
        return []


def watch_limits(name: str, provider) -> threading.Thread | None:
    """Log a WARNING when this provider's key or free-model counter is nearly spent.

    In a daemon thread, started at most once per `available_models` refresh, so once an
    hour per provider per process. Nothing on the page waits for it and nothing it does
    can raise into a render: a provider without a `status` method, or an entry without
    a `status_path`, is not asked at all. The lines are `sage.quota`'s, and they are the
    warning an operator gets before a limit refuses a reader, rather than after.

    Returns the thread, for a test to join; the app ignores it.
    """
    entry = providers.entry(name)
    status_of = getattr(provider, "status", None)
    if not callable(status_of) or not (entry and entry.status_path):
        return None
    if config.LIMIT_WARNING_FRACTION <= 0:
        return None

    def check() -> None:
        try:
            for line in quota.warnings(name, status_of(), config.LIMIT_WARNING_FRACTION):
                logger.warning(line)
        except Exception:  # noqa: BLE001 (a warning light must never break the page)
            logger.debug("Could not check %s limits", name, exc_info=True)

    thread = threading.Thread(target=check, name=f"sage-limits-{name}", daemon=True)
    thread.start()
    return thread


def login_configured() -> bool:
    """Is there an OIDC provider for `st.login()` to send anyone to?

    Checked separately from `SAGE_REQUIRE_LOGIN`, because the two failure modes are
    not the same. A missing `[auth]` block with the flag on would lock every reader
    out of a working app (including whoever set the flag), so the flag alone is
    never enough to gate on.
    """
    try:
        return bool(st.secrets.get("auth"))
    except Exception:  # no secrets.toml at all
        return False


def gate(copy) -> None:
    """Require a signed-in, allowed account before the app renders anything."""
    if not (config.REQUIRE_LOGIN and login_configured()):
        if config.REQUIRE_LOGIN:
            # Loud, because the deployment asked to be private and is not.
            logger.error(
                "SAGE_REQUIRE_LOGIN is set but no [auth] section is configured; "
                "the app is running OPEN. Add an OIDC provider to secrets.toml."
            )
        return
    if not getattr(st.user, "is_logged_in", False):
        st.markdown(f"### {copy.login_heading}")
        st.write(copy.login_prompt)
        st.button("Sign in", on_click=st.login, type="primary")
        st.stop()
    if not config.email_allowed(getattr(st.user, "email", "") or ""):
        st.error(copy.login_denied)
        st.button("Sign out", on_click=st.logout)
        st.stop()


def whoami() -> str:
    """A stable key for the rate limiter.

    The signed-in subject when there is one, because that is the only identity a
    reader cannot shed by opening a new tab. Falling back to a per-session id keeps
    the limiter useful when the app is open (it still stops a loop and a leaning
    Enter key) while being honest that it is a courtesy, not enforcement: a new
    private window is a new session.

    Not the IP address, which `st.context` will happily hand over. Campus NAT and the
    VPN put hundreds of people behind one, so a per-IP cap either does nothing or
    locks out a whole building, and on a hosted platform the value can be the
    proxy's rather than the reader's.
    """
    if getattr(st.user, "is_logged_in", False):
        subject = getattr(st.user, "sub", "") or getattr(st.user, "email", "")
        if subject:
            return f"user:{subject}"
    if "session_id" not in st.session_state:
        st.session_state.session_id = uuid.uuid4().hex
    return f"session:{st.session_state.session_id}"

"""A Streamlit stub good enough to import and drive `app.py` in tests.

Streamlit cannot run headless in CI here, but the module-level flow in `app.py`
(session state, the welcome screen, the tool loop) is exactly the part most worth
smoke-testing. This records calls instead of rendering.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace


class Rerun(BaseException):
    """Raised in place of st.rerun(), which halts a real script run.

    Derived from BaseException, not Exception, because that is what Streamlit does:
    `RerunException` and `StopException` subclass `ScriptControlException`, which
    subclasses `BaseException` directly. Modelling them as ordinary exceptions meant
    every test of the turn loop's control-flow guard exercised the one hierarchy where
    it worked, and the guard was dead in the app for as long as it existed.
    """


class Stop(BaseException):
    """Raised in place of st.stop()."""


class SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        self.pop(name, None)


@contextmanager
def _noop_context():
    yield None


class Slot:
    """Stands in for st.empty().

    A real `st.empty()` is a DeltaGenerator: writing to it *replaces* whatever it
    holds, which is how the status row changes its words without the row being taken
    out of the page and put back. Modelled here because the alternative is a stub
    where only `empty()` exists, which quietly forces every caller into the
    destroy-and-recreate shape that was the bug.
    """

    def __init__(self, recorder):
        self._recorder = recorder

    def empty(self):
        self._recorder.events.append(("empty", None))

    def markdown(self, body, unsafe_allow_html=False, **kwargs):
        self._recorder.markdown(body, unsafe_allow_html=unsafe_allow_html, **kwargs)

    @contextmanager
    def container(self):
        yield None


class StubStreamlit(ModuleType):
    def __init__(self, chat_input=None, buttons=None, upload=None, selections=None,
                 text_areas=None):
        super().__init__("streamlit")
        self.session_state = SessionState()
        self.events: list[tuple[str, object]] = []
        self.button_labels: dict[str, str] = {}
        # `help=` renders as a hover tooltip. Recorded so tests can hold the line
        # on not putting one on a control that already carries its own label.
        self.tooltips: dict[str, str] = {}
        # Which controls were rendered inert, keyed the same way.
        self.disabled: dict[str, bool] = {}
        self.markdown_html: list[str] = []
        # Whatever `st.chat_input` was called with beyond its placeholder. Starts
        # empty rather than None so a test can assert on it without the app having
        # had to reach the call.
        self.chat_input_kwargs: dict[str, object] = {}
        # Same, for the uploader.
        self.uploader_kwargs: dict[str, object] = {}
        self.stream_chunks: list[int] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.captions: list[str] = []
        self._chat_input = chat_input
        self._buttons = buttons or {}
        self._upload = upload
        self._selections = selections or {}
        # What a keyed `st.text_area` hands back, so a test can type into the
        # in-place question editor. Unkeyed, or a key nobody scripted, returns the
        # `value=` the app passed — which is the un-edited question.
        self._text_areas = text_areas or {}
        self.text_area_values: dict[str, object] = {}
        # `on_click=` handlers, by key, so a test can prove one was wired up and
        # then run it the way Streamlit does — before the next script run.
        self.callbacks: dict[str, object] = {}
        # The form currently being built, so `form_submit_button` can name itself the
        # way Streamlit does.
        self._form: str | None = None
        self.secrets = SimpleNamespace(get=lambda _key, default="": default)
        # `st.user` exists on every Streamlit the requirements allow (>=1.42), and
        # on an app with no `[auth]` configured it is present with `is_logged_in`
        # False rather than absent. Modelling it as missing would have let the login
        # gate raise AttributeError in the app while the tests stayed green — the
        # same "model the real shape" mistake that left the control-flow guard dead.
        self.user = SimpleNamespace(is_logged_in=False, email="", sub="")

    def login(self, *_args, **_kwargs):
        self.events.append(("login", None))

    def logout(self, *_args, **_kwargs):
        self.events.append(("logout", None))

    # --- layout -----------------------------------------------------------
    def set_page_config(self, **kwargs):
        self.events.append(("set_page_config", kwargs))

    def columns(self, spec, **_kwargs):
        count = spec if isinstance(spec, int) else len(spec)
        return [_noop_context() for _ in range(count)]

    def container(self, key=None, **_kwargs):
        self.events.append(("container", key))
        return _noop_context()

    @property
    def sidebar(self):
        """`with st.sidebar:` — a region, recorded so a test can prove it was used.

        Modelled as a context manager only. The real `st.sidebar` is also a
        DeltaGenerator with every widget hanging off it, but `sage/ui/sidebar.py` uses
        the `with` form so that the widgets inside it are ordinary `st.*` calls —
        which is what lets the rest of this stub, and every assertion written against
        it, go on working unchanged.
        """
        self.events.append(("sidebar", None))
        return _noop_context()

    def chat_message(self, role, **_kwargs):
        self.events.append(("chat_message", role))
        return _noop_context()

    def popover(self, label, **_kwargs):
        self.events.append(("popover", label))
        return _noop_context()

    @contextmanager
    def form(self, key=None, **_kwargs):
        """A form, and the key its submit buttons are named after.

        Streamlit derives a submit button's widget key from the form's:
        `FormSubmitter-{form key}-{label}`. Modelled rather than invented, because a
        test that drove a key Streamlit does not use would pass against a button the
        app never renders.
        """
        self.events.append(("form", key))
        previous = self._form
        self._form = key
        try:
            yield None
        finally:
            self._form = previous

    def form_submit_button(self, label="Submit", **kwargs):
        return self.button(label, key=f"FormSubmitter-{self._form}-{label}", **kwargs)

    def expander(self, label, **_kwargs):
        return _noop_context()

    def empty(self):
        return Slot(self)

    # --- output -----------------------------------------------------------
    def markdown(self, body, unsafe_allow_html=False, **_kwargs):
        self.events.append(("markdown", body))
        if unsafe_allow_html:
            self.markdown_html.append(body)

    def write(self, *args, **_kwargs):
        self.events.append(("write", args))

    def error(self, body, **_kwargs):
        self.errors.append(str(body))

    def warning(self, body, **_kwargs):
        self.warnings.append(str(body))

    def caption(self, body, **_kwargs):
        self.events.append(("caption", body))
        self.captions.append(str(body))

    def code(self, body, **_kwargs):
        self.events.append(("code", body))

    def write_stream(self, stream):
        # Record the chunk count so tests can prove a turn actually streamed
        # rather than arriving as one block.
        parts = [str(part) for part in stream]
        self.stream_chunks.append(len(parts))
        return "".join(parts)

    # --- widgets ----------------------------------------------------------
    def button(self, label, key=None, help=None, disabled=False,  # noqa: A002
               on_click=None, **_kwargs):
        self.events.append(("button", key or label))
        self.button_labels[key or label] = label
        if help:
            self.tooltips[key or label] = help
        # Recorded because `disabled` is the only thing that stops a click reaching
        # the server: a rerun IS the click, so an inert handler still costs a turn.
        self.disabled[key or label] = bool(disabled)
        if disabled:
            return False
        clicked = bool(self._buttons.get(key, False))
        # `on_click` runs BEFORE the script on the run after the click, not here —
        # a callback that fired at the point the widget is declared would be no
        # different from reading the return value, and the stop button depends on the
        # difference. So it is recorded, and a test that wants the callback's effect
        # sets the state it would have set. What this DOES model is that a callback
        # and a truthy return never both drive the same button.
        if on_click is not None:
            self.callbacks[key or label] = on_click
            return False
        return clicked

    def text_area(self, label, value="", key=None, **_kwargs):
        self.events.append(("text_area", key or label))
        typed = self._text_areas.get(key, value)
        self.text_area_values[key or label] = typed
        return typed

    def file_uploader(self, label, key=None, **kwargs):
        self.events.append(("file_uploader", key))
        # Recorded so a test can prove the app asks for more than one file and does
        # not filter by extension — the two settings that decided whether a second
        # attachment, or a pasted screenshot, could arrive at all.
        self.uploader_kwargs = dict(kwargs)
        return self._upload

    def chat_input(self, placeholder=None, **kwargs):
        # Recorded so a test can prove the controls under the box are rendered
        # after it, rather than back in a bar at the top of the page.
        self.events.append(("chat_input", placeholder))
        # And the kwargs, because `max_chars` is the one that puts a character
        # counter inside the box — the absence of an argument is the thing under
        # test, and nothing else here can see an argument that was not passed.
        self.chat_input_kwargs = dict(kwargs)
        return self._chat_input

    def selectbox(self, label, options=None, index=0, key=None, **_kwargs):
        options = list(options or [])
        self.events.append(("selectbox", (key, tuple(options))))
        if key in self._selections:
            return self._selections[key]
        return options[index] if options else None

    # --- control flow -----------------------------------------------------
    def stop(self):
        raise Stop

    def rerun(self):
        raise Rerun

    def cache_resource(self, *dargs, **dkwargs):
        """Supports @st.cache_resource(...) — memoizes on the argument tuple."""
        def decorate(function):
            cache: dict = {}

            def wrapper(*args, **kwargs):
                key = (args, tuple(sorted(kwargs.items())))
                if key not in cache:
                    cache[key] = function(*args, **kwargs)
                return cache[key]

            wrapper.clear = cache.clear
            # Kept so a test can assert a cache is *bounded*. `cache_resource` with no
            # ttl holds for the life of the process, which for anything discovered from
            # a provider means a list that never changes again — see
            # `sage.ui.access.available_models` for the one that cost a model its place
            # in the picker.
            wrapper.ttl = dkwargs.get("ttl")
            return wrapper

        if dargs and callable(dargs[0]) and not dkwargs:
            return decorate(dargs[0])
        return decorate


# Every module that does `import streamlit`. Each one binds the stub *object* it was
# imported against, so a module left in `sys.modules` across two installs would go on
# writing to the previous run's session state — the widget keys would be recorded on a
# stub no assertion is looking at, and the app would read a `messages` list the test
# never set. `app` was the only such module until the view was split up; now it is
# `app` plus everything under `sage.ui`, and the rule is "anything that imports
# streamlit is forgotten between installs", applied by prefix so a new UI module is
# covered the day it is written rather than the day someone remembers this list.
_STREAMLIT_MODULES = ("streamlit", "app")
_STREAMLIT_PACKAGES = ("streamlit.", "sage.ui")


def forget_importers() -> None:
    """Drop the stub and everything that imported it, so the next install is clean."""
    for name in list(sys.modules):
        if name in _STREAMLIT_MODULES or name.startswith(_STREAMLIT_PACKAGES):
            sys.modules.pop(name, None)


def install(**kwargs) -> StubStreamlit:
    """Put the stub in sys.modules, and drop anything that imported the last one."""
    forget_importers()
    return install_module(**kwargs)


def install_module(**kwargs) -> StubStreamlit:
    stub = StubStreamlit(**kwargs)

    components = ModuleType("streamlit.components")
    v1 = ModuleType("streamlit.components.v1")
    v1.html = lambda *args, **kwargs: None
    components.v1 = v1
    stub.components = components

    sys.modules["streamlit"] = stub
    sys.modules["streamlit.components"] = components
    sys.modules["streamlit.components.v1"] = v1
    return stub

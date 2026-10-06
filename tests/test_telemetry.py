"""What a turn leaves behind for an operator, where it goes, and what never goes with it.

Three layers, tested in the order a record is made. The adapter asks an endpoint for
usage and tags the request only where the profile entry says the endpoint understands
it, and reads back the served model, the finish reason and the token counts. The turn
turns each model call into a `call` record and the whole question into one `turn`
record, joined by one id across every script run a failover takes. And the sinks put
every record wherever they are pointed, without ever raising, and without the switch
that turns them on putting a control on the page.

Driven the way `tests/test_app_smoke.py` drives the app: the stubbed Streamlit, a
scripted provider, the real `turn.run`. A failover is the run AFTER the one that failed,
so the tests that need one go through `evals/harness.py`, which reuses one session
across runs exactly as Streamlit does.
"""

from __future__ import annotations

import json
import logging
import pathlib
import re
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

import stub_streamlit
from evals import harness
from sage import config, feedback, llm, providers, telemetry
from sage.files import Attachment
from sage.profile import ProviderEntry, from_mapping
from sage.providers.base import CallTag, current_tag, tagged, usage_counts
from sage.providers.mistral import MistralProvider
from sage.providers.openai_compat import OpenAICompatProvider

ROOT = pathlib.Path(__file__).resolve().parent.parent


def event(text="", tool_calls=None, **said):
    return providers.Chunk(text=text, tool_calls=tool_calls or [], **said)


def call(index, identifier, name, arguments):
    return {"index": index, "id": identifier, "name": name, "arguments": arguments}


SEARCH = [event(tool_calls=[call(0, "c1", "search_docs", '{"query":"storage quota"}')])]
READ = [event(tool_calls=[call(0, "c2", "read_doc", '{"path":"docs/storage/main.md"}')])]
ANSWER = [
    event("Your /home quota is ", model="vendor/served-model:free"),
    event("30 GB.", finish_reason="stop", tokens_in=120, tokens_out=9),
]


def records(text: str) -> list[dict]:
    """Every record in a sink's output, in order."""
    found = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{") and '"v"' in line:
            found.append(json.loads(line))
    return found


def written(path) -> list[dict]:
    path = pathlib.Path(path)
    return records(path.read_text(encoding="utf-8")) if path.exists() else []


@pytest.fixture(autouse=True)
def no_sinks(monkeypatch):
    """Every test starts with both sinks off and the once-per-process warning unspent."""
    monkeypatch.setattr(config, "FEEDBACK_LOG", "")
    monkeypatch.setattr(config, "TELEMETRY", "")
    monkeypatch.setattr(telemetry, "_warned", False)


@pytest.fixture(autouse=True)
def _clean_modules():
    yield
    stub_streamlit.forget_importers()


# --- the sinks ----------------------------------------------------------------------


class TestWhereARecordGoes:
    def test_stdout_is_one_json_object_per_line_with_severity_and_message(
        self, monkeypatch, capsys
    ):
        """The shape Cloud Logging turns into a structured entry. Fields at the top
        level, so a filter on `jsonPayload.outcome` works without unwrapping."""
        monkeypatch.setattr(config, "TELEMETRY", "stdout")
        feedback.record_turn(question="q", outcome="answered", model="p:m", calls=2,
                             seconds=1.5, turn_id="t1", session="s1")
        feedback.record_call(turn_id="t1", n=1, round_number=1, provider="p",
                             model="m", ok=False, error_kind="rate_limit", status=429)
        lines = [line for line in capsys.readouterr().out.splitlines() if line]
        assert len(lines) == 2
        turn, failed = (json.loads(line) for line in lines)
        assert turn["severity"] == "INFO"
        assert turn["message"].startswith("turn answered")
        assert (turn["kind"], turn["v"], turn["calls"]) == ("turn", 1, 2)
        assert turn["deploy"] == config.DEPLOYMENT and turn["git_sha"] == config.GIT_SHA
        assert failed["severity"] == "WARNING", "a failed call is a warning"
        assert "rate_limit" in failed["message"]

    def test_a_failed_turn_is_a_warning(self, monkeypatch, capsys):
        monkeypatch.setattr(config, "TELEMETRY", "stdout")
        feedback.record_turn(question="q", outcome="failed", model="p:m",
                             error_kind="empty")
        (line,) = records(capsys.readouterr().out)
        assert line["severity"] == "WARNING"

    def test_a_call_the_reader_cut_off_is_not_a_warning(self, monkeypatch, capsys):
        """Nothing an operator could fix went wrong."""
        monkeypatch.setattr(config, "TELEMETRY", "stdout")
        feedback.record_call(turn_id="t", n=1, round_number=1, provider="p", model="m",
                             ok=None, error_kind="interrupted")
        (line,) = records(capsys.readouterr().out)
        assert line["severity"] == "INFO"

    def test_a_file_gets_the_bare_record(self, monkeypatch, tmp_path):
        path = tmp_path / "deep" / "telemetry.jsonl"
        monkeypatch.setattr(config, "TELEMETRY", str(path))
        assert feedback.record_turn(question="q", outcome="answered", model="p:m")
        (row,) = written(path)
        assert row["kind"] == "turn"
        assert "severity" not in row and "message" not in row

    def test_every_record_goes_to_every_sink(self, monkeypatch, tmp_path, capsys):
        log = tmp_path / "feedback.jsonl"
        monkeypatch.setattr(config, "FEEDBACK_LOG", str(log))
        monkeypatch.setattr(config, "TELEMETRY", "stdout")
        feedback.record_turn(question="q", outcome="answered", model="p:m")
        feedback.record_call(turn_id="t", n=1, round_number=1, provider="p", model="m")
        feedback.record_miss(["quota"], "q", turn_id="t")
        feedback.record_rating("up", "q", "an answer", [], turn_id="t")
        kinds = ["turn", "call", "miss", "rating"]
        assert [row["kind"] for row in records(capsys.readouterr().out)] == kinds
        assert [row["kind"] for row in written(log)] == kinds

    def test_two_files_both_get_it_and_one_file_named_twice_gets_it_once(
        self, monkeypatch, tmp_path
    ):
        first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
        monkeypatch.setattr(config, "FEEDBACK_LOG", str(first))
        monkeypatch.setattr(config, "TELEMETRY", str(second))
        feedback.record_turn(question="q", outcome="answered", model="p:m")
        assert len(written(first)) == len(written(second)) == 1

        monkeypatch.setattr(config, "TELEMETRY", str(first))
        feedback.record_turn(question="q", outcome="answered", model="p:m")
        assert len(written(first)) == 2, "the same path is one sink, not two"

    def test_the_old_switch_still_means_a_file(self, monkeypatch, tmp_path, capsys):
        """`SAGE_FEEDBACK_LOG` was always a path, so `stdout` there is a file called
        that. Only the new switch reads the word as the stream."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(config, "FEEDBACK_LOG", "stdout")
        feedback.record_turn(question="q", outcome="answered", model="p:m")
        assert capsys.readouterr().out == ""
        assert len(written(tmp_path / "stdout")) == 1

    def test_nothing_is_written_when_nothing_is_configured(self, capsys, tmp_path):
        assert feedback.record_turn(question="q", outcome="answered", model="p:m") is False
        assert capsys.readouterr().out == ""
        assert not list(tmp_path.iterdir())


class TestASinkThatFailsNeverCostsATurn:
    def unwritable(self, tmp_path) -> str:
        blocker = tmp_path / "a-file"
        blocker.write_text("not a directory")
        return str(blocker / "telemetry.jsonl")

    def test_a_file_that_cannot_be_written_never_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "TELEMETRY", self.unwritable(tmp_path))
        assert feedback.record_turn(question="q", outcome="answered", model="m") is False
        assert feedback.record_call(turn_id="t", n=1, round_number=1, provider="p",
                                    model="m") is False

    def test_a_stdout_that_cannot_be_written_never_raises(self, monkeypatch):
        class Closed:
            def write(self, _text):
                raise OSError("Broken pipe")

            def flush(self):
                raise OSError("Broken pipe")

        monkeypatch.setattr(config, "TELEMETRY", "stdout")
        monkeypatch.setattr(sys, "stdout", Closed())
        assert feedback.record_turn(question="q", outcome="answered", model="m") is False

    def test_it_says_so_once_per_process_and_then_never_again(
        self, monkeypatch, tmp_path, caplog
    ):
        """A full disk would otherwise log a warning for every call of every turn."""
        monkeypatch.setattr(config, "TELEMETRY", self.unwritable(tmp_path))
        with caplog.at_level(logging.WARNING, logger="sage.telemetry"):
            for _ in range(5):
                feedback.record_turn(question="q", outcome="answered", model="m")
        warnings = [record for record in caplog.records if record.name == "sage.telemetry"]
        assert len(warnings) == 1

    def test_one_broken_sink_does_not_starve_the_others(self, monkeypatch, tmp_path):
        good = tmp_path / "good.jsonl"
        monkeypatch.setattr(config, "FEEDBACK_LOG", str(good))
        monkeypatch.setattr(config, "TELEMETRY", self.unwritable(tmp_path))
        assert feedback.record_turn(question="q", outcome="answered", model="m") is True
        assert len(written(good)) == 1

    def test_bookkeeping_that_breaks_never_reaches_the_turn(self):
        """`Calls.close` runs inside the turn's error handlers, Streamlit's rerun among
        them, where an exception of its own would replace the one being handled."""
        broken = feedback.Calls({}, session="s", provider="p", model="m")
        broken.open(1, toolless=False)  # a ledger with no counter: must not raise
        broken.close("empty")
        half = feedback.Calls({"calls": 0}, session="s", provider="p", model="m")
        half.open(1, toolless=False)
        half.close(interrupted=True)  # a ledger with no turn id: must not raise either


class TestTheRatingRowIsNotTelemetrysToDraw:
    """`SAGE_FEEDBACK_LOG` draws the 👍/👎 row; `SAGE_TELEMETRY` must not.

    Turning on observability is asking to see what the app does. A rating row appearing
    under every answer because of it would be a change to how the app looks that nobody
    asked for, which this repository treats as a regression.
    """

    SESSION = {
        "messages": [
            {"role": "user", "text": "what is my quota", "attachments": []},
            {"role": "assistant", "text": "30 GB.", "sources": [], "rating": None,
             "turn_id": "f" * 32},
        ],
        "processing": False,
    }

    def rated_buttons(self, stub) -> list[str]:
        return [key for key in stub.button_labels if str(key).startswith("rate-")]

    def test_enabled_reads_the_feedback_log_alone(self, monkeypatch):
        monkeypatch.setattr(config, "TELEMETRY", "stdout")
        assert feedback.enabled() is False
        monkeypatch.setattr(config, "FEEDBACK_LOG", "/somewhere/feedback.jsonl")
        assert feedback.enabled() is True

    def session(self) -> dict:
        return {**self.SESSION, "messages": [dict(m) for m in self.SESSION["messages"]]}

    def test_telemetry_on_draws_no_rating_row(self, monkeypatch):
        monkeypatch.setattr(config, "TELEMETRY", "stdout")
        stub = run_app(monkeypatch, client=Scripted([]), session=self.session())
        assert self.rated_buttons(stub) == []

    def test_the_feedback_log_still_draws_it(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "FEEDBACK_LOG", str(tmp_path / "feedback.jsonl"))
        stub = run_app(monkeypatch, client=Scripted([]), session=self.session())
        assert self.rated_buttons(stub), "the row a deployment asked for is still there"

    def test_a_rating_carries_the_turn_it_is_about(self, monkeypatch, tmp_path):
        log = tmp_path / "feedback.jsonl"
        monkeypatch.setattr(config, "FEEDBACK_LOG", str(log))
        stub = run_app(monkeypatch, client=Scripted([]), session=self.session(),
                       buttons={"rate-1-up": True})
        (row,) = written(log)
        assert row["kind"] == "rating" and row["verdict"] == "up"
        assert row["turn_id"] == "f" * 32
        assert row["session"] == stub.session_state["telemetry_session"]


# --- what the adapter sends and reads ------------------------------------------------


class Wire:
    """A stand-in for httpx that keeps what the adapter put on the wire."""

    def __init__(self, monkeypatch, lines=None) -> None:
        self.json: dict = {}
        self.headers: dict = {}
        wire = self
        replay = lines or ['data: {"choices":[{"delta":{"content":"ok"}}]}', "data: [DONE]"]

        class Response:
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def iter_lines(self):
                return iter(replay)

        class Client:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def stream(self, _method, _url, json=None, headers=None, **_kwargs):
                wire.json = dict(json or {})
                wire.headers = dict(headers or {})
                return Response()

        fake = ModuleType("httpx")
        fake.Client = Client
        fake.Timeout = lambda *_args, **_kwargs: None
        monkeypatch.setitem(sys.modules, "httpx", fake)


PLAIN = ProviderEntry(name="plain", kind="openai", base_url="https://x.test/v1")
DECLARED = ProviderEntry(
    name="grouping", kind="openai", base_url="https://x.test/v1",
    stream_usage=True, session_header="x-session-id", trace_field="trace",
)
TAG = CallTag(session="0" * 32, turn_id="1" * 32, round=2)


def sent(monkeypatch, entry, tag=TAG, lines=None) -> Wire:
    wire = Wire(monkeypatch, lines)
    adapter = OpenAICompatProvider(entry, "k")
    with tagged(tag):
        stream = adapter.stream("m", [{"role": "user", "content": "hi"}], None)
        chunks = list(stream)
    wire.chunks = chunks
    return wire


class TestWhatARequestSaysAboutItself:
    """`stream_options`, the session header and the trace field go only where declared.

    An unknown field is a 400 from any endpoint entitled to be strict about its own wire
    format, which is the same reason `reasoning` is declared per provider.
    """

    def test_an_entry_that_declares_nothing_sends_nothing(self, monkeypatch):
        wire = sent(monkeypatch, PLAIN)
        assert "stream_options" not in wire.json
        assert "trace" not in wire.json
        assert not any(name.lower().startswith("x-") for name in wire.headers)

    def test_an_entry_that_declares_all_three_sends_all_three(self, monkeypatch):
        wire = sent(monkeypatch, DECLARED)
        assert wire.json["stream_options"] == {"include_usage": True}
        assert wire.headers["x-session-id"] == TAG.session
        assert wire.json["trace"] == {"trace_id": TAG.turn_id, "generation_name": "round 2"}

    def test_the_names_are_the_profiles_and_not_the_packages(self, monkeypatch):
        entry = ProviderEntry(name="other", kind="openai", base_url="https://x.test/v1",
                              session_header="x-conversation", trace_field="observe")
        wire = sent(monkeypatch, entry)
        assert wire.headers["x-conversation"] == TAG.session
        assert wire.json["observe"]["trace_id"] == TAG.turn_id
        assert "x-session-id" not in wire.headers and "trace" not in wire.json

    def test_usage_alone_is_its_own_declaration(self, monkeypatch):
        entry = ProviderEntry(name="u", kind="openai", base_url="https://x.test/v1",
                              stream_usage=True)
        wire = sent(monkeypatch, entry)
        assert wire.json["stream_options"] == {"include_usage": True}
        assert "trace" not in wire.json and "x-session-id" not in wire.headers

    def test_a_request_made_outside_a_turn_carries_no_tag(self, monkeypatch):
        wire = sent(monkeypatch, DECLARED, tag=None)
        assert "trace" not in wire.json and "x-session-id" not in wire.headers
        assert wire.json["stream_options"] == {"include_usage": True}

    def test_the_identity_field_is_never_sent(self, monkeypatch):
        """OpenRouter's `user` exists to carry an end user's identity downstream."""
        assert "user" not in sent(monkeypatch, DECLARED).json

    def test_llm_start_is_what_puts_the_tag_in_force(self, monkeypatch):
        """And only while the stream is opened, which is when a request is built."""
        wire = Wire(monkeypatch)
        adapter = OpenAICompatProvider(DECLARED, "k")
        turn = llm.start(adapter, "m", [], None, tag=TAG)
        assert current_tag() is None, "the tag must not outlive the request it named"
        assert turn.consume().text == "ok"
        assert wire.json["trace"]["trace_id"] == TAG.turn_id
        assert wire.headers["x-session-id"] == TAG.session


class TestWhatAStreamSaysAboutItself:
    """The served model, why it stopped, and what it cost, read back off the stream."""

    LINES = [
        'data: {"model":"vendor/served:free","choices":[{"delta":{"content":"Hi"}}]}',
        'data: {"model":"vendor/served:free","choices":[{"delta":{},'
        '"finish_reason":"stop"}]}',
        # The OpenAI shape of the usage event: `choices` empty, which every shape check
        # in the parser skips. It must be read anyway.
        'data: {"model":"vendor/served:free","choices":[],'
        '"usage":{"prompt_tokens":12,"completion_tokens":5,"total_tokens":17}}',
        "data: [DONE]",
    ]

    def test_the_parser_reads_all_three(self):
        chunks = list(providers.parse_sse(iter(self.LINES)))
        assert {chunk.model for chunk in chunks} == {"vendor/served:free"}
        assert chunks[1].finish_reason == "stop"
        assert (chunks[-1].tokens_in, chunks[-1].tokens_out) == (12, 5)
        assert "".join(chunk.text for chunk in chunks) == "Hi"

    def test_the_turn_keeps_them_for_the_call_record(self):
        turn = llm.Turn(stream=providers.parse_sse(iter(self.LINES))).consume()
        assert turn.text == "Hi"
        assert turn.served_model == "vendor/served:free"
        assert turn.finish_reason == "stop"
        assert (turn.tokens_in, turn.tokens_out) == (12, 5)
        assert turn.first_text_at is not None

    def test_through_the_adapter_end_to_end(self, monkeypatch):
        wire = sent(monkeypatch, DECLARED, lines=self.LINES)
        assert wire.chunks[-1].tokens_out == 5

    def test_usage_on_every_event_keeps_the_last(self):
        """Gemini's OpenAI layer repeats a cumulative count on each event."""
        lines = [
            'data: {"choices":[{"delta":{"content":"a"}}],'
            '"usage":{"prompt_tokens":8,"completion_tokens":1,"total_tokens":9}}',
            'data: {"choices":[{"delta":{"content":"b"},"finish_reason":"stop"}],'
            '"usage":{"prompt_tokens":8,"completion_tokens":2,"total_tokens":10}}',
        ]
        turn = llm.Turn(stream=providers.parse_sse(iter(lines))).consume()
        assert (turn.tokens_in, turn.tokens_out) == (8, 2)

    def test_a_stream_that_reports_nothing_leaves_nothing(self):
        lines = ['data: {"choices":[{"delta":{"content":"ok"}}]}']
        turn = llm.Turn(stream=providers.parse_sse(iter(lines))).consume()
        assert (turn.served_model, turn.tokens_in, turn.tokens_out) == ("", None, None)

    def test_thinking_counted_outside_completion_is_still_output(self):
        """Vertex, measured: a one-word answer reported 1 completion token and 65 in
        total over a 7-token prompt. 58 is what it was billed for."""
        assert usage_counts(
            {"prompt_tokens": 7, "completion_tokens": 1, "total_tokens": 65,
             "completion_tokens_details": {"reasoning_tokens": 57}}
        ) == (7, 58)

    def test_a_total_that_is_the_plain_sum_changes_nothing(self):
        assert usage_counts(
            {"prompt_tokens": 23, "completion_tokens": 93, "total_tokens": 116}
        ) == (23, 93)

    @pytest.mark.parametrize("raw", [None, {}, {"prompt_tokens": "lots"},
                                     {"prompt_tokens": True}, "usage",
                                     {"prompt_tokens": float("inf")},
                                     {"prompt_tokens": float("nan")}])
    def test_anything_that_is_not_a_count_is_none_rather_than_zero(self, raw):
        """A missing count must stay missing, or someone sums it as a zero."""
        assert usage_counts(raw) == (None, None)

    def test_a_usage_block_that_is_nonsense_never_ends_the_answer(self):
        """`json.loads` accepts `Infinity`, and `int()` of it raises. Inside the parser
        a raise is the turn ending on "something went wrong" with the answer on screen."""
        lines = [
            'data: {"choices":[{"delta":{"content":"kept"}}],'
            '"usage":{"prompt_tokens":Infinity,"completion_tokens":NaN}}',
        ]
        turn = llm.Turn(stream=providers.parse_sse(iter(lines))).consume()
        assert turn.text == "kept"
        assert (turn.tokens_in, turn.tokens_out) == (None, None)

    def test_one_nonsense_count_does_not_take_the_good_ones_with_it(self):
        assert usage_counts(
            {"prompt_tokens": 8, "completion_tokens": float("nan"), "total_tokens": 9}
        ) == (8, 1)

    def test_the_mistral_sdk_reports_them_by_attribute(self):
        def stream(**_kwargs):
            choice = SimpleNamespace(delta=SimpleNamespace(content="ok", tool_calls=None),
                                     finish_reason="stop")
            usage = SimpleNamespace(prompt_tokens=4, completion_tokens=1, total_tokens=5)
            return iter([SimpleNamespace(data=SimpleNamespace(
                choices=[choice], model="mistral-small-2506", usage=usage))])

        adapter = MistralProvider.__new__(MistralProvider)
        adapter._client = SimpleNamespace(chat=SimpleNamespace(stream=stream))
        turn = llm.Turn(stream=adapter.stream("m", [], None)).consume()
        assert (turn.text, turn.served_model, turn.finish_reason) == (
            "ok", "mistral-small-2506", "stop")
        assert (turn.tokens_in, turn.tokens_out) == (4, 1)


class TestTheProfileDeclaresIt:
    def test_the_defaults_send_nothing(self):
        entry = from_mapping({"providers": [{"name": "x", "kind": "openai"}]}).provider("x")
        assert entry.stream_usage is False
        assert entry.session_header == ""
        assert entry.trace_field == ""

    def test_declared_values_are_read_and_typed(self):
        entry = from_mapping({"providers": [{
            "name": "x", "kind": "openai", "stream_usage": True,
            "session_header": " x-session-id ", "trace_field": "trace",
        }]}).provider("x")
        assert entry.stream_usage is True
        assert entry.session_header == "x-session-id", "a stray space is no header at all"
        assert entry.trace_field == "trace"

    def test_a_name_that_is_not_a_string_is_no_name(self):
        entry = from_mapping({"providers": [
            {"name": "x", "session_header": 7, "trace_field": True},
        ]}).provider("x")
        assert (entry.session_header, entry.trace_field) == ("", "")

    def test_only_the_router_provider_tags_its_requests(self, profile):
        """OpenRouter's Broadcast is the only destination these two are for, and the
        brief is that nothing else is sent them."""
        tagging = [entry.name for entry in profile.providers
                   if entry.session_header or entry.trace_field]
        assert tagging == ["openrouter"]
        entry = profile.provider("openrouter")
        assert (entry.session_header, entry.trace_field) == ("x-session-id", "trace")

    def test_usage_is_asked_for_where_it_was_measured(self, profile):
        assert all(entry.stream_usage for entry in profile.providers), (
            "all three shipped providers were probed on 2026-10-06 and answered it"
        )


# --- what a turn records -------------------------------------------------------------


class Scripted:
    """Replays turns in call order, and keeps the tag each request carried."""

    def __init__(self, turns, name="google", models=("m1",)) -> None:
        self.name = name
        self.turns = list(turns)
        self.tags: list = []
        self._models = models

    def models(self):
        return [providers.Model(self.name, model_id) for model_id in self._models]

    def stream(self, model, messages, tools, thinking=False, tool_choice="auto"):
        self.tags.append(current_tag())
        if not self.turns:
            raise AssertionError("provider called more times than scripted")
        item = self.turns.pop(0)
        if isinstance(item, BaseException):
            raise item
        yield from item


def clear_provider_keys(monkeypatch):
    """Every key the profile names, unset, so a developer's shell cannot add a provider
    to the lineup a test sees. Named from the profile, as `test_app_smoke.py` does."""
    for name in providers.names():
        variable = providers.key_var(name)
        if variable:
            monkeypatch.delenv(variable, raising=False)


def run_app(monkeypatch, *, client=None, session=None, openrouter=False, user=None,
            **stub_kwargs):
    """Import app.py once under the stub, the way `tests/test_app_smoke.py` does.

    The client is registered under its own provider name only, so the other keyed
    provider in the lineup lists nothing rather than the same models a second time.
    """
    clear_provider_keys(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    if openrouter:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    stub = stub_streamlit.install(**stub_kwargs)
    if user is not None:
        stub.user = user
    if session:
        stub.session_state.update(session)
    if client is not None:
        registry = {client.name: client}
        monkeypatch.setattr(providers, "build", lambda name, _key: registry[name])
    try:
        import app  # noqa: F401, PLC0415
    except (stub_streamlit.Rerun, stub_streamlit.Stop):
        pass
    return stub


def asking(question="what is my storage quota", attachments=(), **extra):
    return {
        "messages": [{"role": "user", "text": question,
                      "attachments": list(attachments)}],
        "processing": True,
    } | extra


class TestWhatATurnRecords:
    def test_a_tool_turn_is_one_turn_record_and_one_call_record_per_request(
        self, monkeypatch, capsys
    ):
        monkeypatch.setattr(config, "TELEMETRY", "stdout")
        client = Scripted([SEARCH, READ, ANSWER])
        stub = run_app(monkeypatch, client=client, session=asking())
        found = records(capsys.readouterr().out)
        turns = [row for row in found if row["kind"] == "turn"]
        calls = [row for row in found if row["kind"] == "call"]
        assert len(turns) == 1 and len(calls) == 3
        (turn,) = turns
        assert {row["turn_id"] for row in found} == {turn["turn_id"]}
        assert [row["n"] for row in calls] == [1, 2, 3]
        assert [row["round"] for row in calls] == [1, 2, 3]
        assert [row["tool_calls"] for row in calls] == [["search_docs"], ["read_doc"], []]
        assert all(row["ok"] is True for row in calls)
        assert turn["outcome"] == "answered" and turn["calls"] == 3
        assert turn["served_model"] == "vendor/served-model:free"
        assert (turn["tokens_in"], turn["tokens_out"]) == (120, 9)
        assert calls[-1]["finish_reason"] == "stop"
        assert turn["ttft_s"] is not None and 0 <= turn["ttft_s"] <= turn["seconds"]
        assert turn["tried"] == []
        assert len(turn["prompt"]) == 12
        assert turn["corpus"] == config.snapshot().get("user_guide_commit", "")
        # The answer it produced carries the same id, for a rating to join on.
        assert stub.session_state["messages"][-1]["turn_id"] == turn["turn_id"]
        assert stub.session_state["ledger"] is None, "the ledger goes with the record"

    def test_the_request_carried_the_same_session_turn_and_round(
        self, monkeypatch, capsys
    ):
        monkeypatch.setattr(config, "TELEMETRY", "stdout")
        client = Scripted([SEARCH, ANSWER])
        stub = run_app(monkeypatch, client=client, session=asking())
        (turn,) = [row for row in records(capsys.readouterr().out) if row["kind"] == "turn"]
        assert [tag.round for tag in client.tags] == [1, 2]
        assert {tag.turn_id for tag in client.tags} == {turn["turn_id"]}
        assert {tag.session for tag in client.tags} == {turn["session"]}
        assert turn["session"] == stub.session_state["telemetry_session"]

    def test_no_answer_text_and_no_attachment_reaches_a_turn_or_call_record(
        self, monkeypatch, capsys
    ):
        monkeypatch.setattr(config, "TELEMETRY", "stdout")
        attached = Attachment("payroll-export.csv", "text", "SECRET-ROW-9931,alice,90000",
                              size=40)
        answer = [event("The UNMISTAKABLE-ANSWER-PHRASE is 30 GB.")]
        client = Scripted([SEARCH, answer])
        run_app(monkeypatch, client=client,
                session=asking("what is in my file", attachments=[attached]))
        found = [row for row in records(capsys.readouterr().out)
                 if row["kind"] in ("turn", "call")]
        assert found
        blob = json.dumps(found)
        for secret in ("UNMISTAKABLE", "SECRET-ROW", "payroll", "alice", "storage quota"):
            assert secret not in blob, f"{secret!r} reached a record"
        (turn,) = [row for row in found if row["kind"] == "turn"]
        assert turn["attachments"] == {"count": 1, "kinds": ["text"]}

    def test_the_question_is_kept_and_kept_short(self, monkeypatch, capsys):
        monkeypatch.setattr(config, "TELEMETRY", "stdout")
        client = Scripted([[event("Answered.")]])
        run_app(monkeypatch, client=client, session=asking("why " * 600))
        (turn,) = [row for row in records(capsys.readouterr().out) if row["kind"] == "turn"]
        assert len(turn["question"]) == 1000

    def test_the_signed_in_account_is_never_the_session(self, monkeypatch, capsys):
        monkeypatch.setattr(config, "TELEMETRY", "stdout")
        client = Scripted([[event("Answered.")]])
        reader = SimpleNamespace(is_logged_in=True, email="reader@example.edu",
                                 sub="subject-identity-xyz")
        stub = run_app(monkeypatch, client=client, session=asking(), user=reader)
        assert stub.session_state["telemetry_session"] not in (
            "user:subject-identity-xyz", "reader@example.edu"
        )
        output = capsys.readouterr().out
        assert "reader@example.edu" not in output
        assert "subject-identity-xyz" not in output
        (turn,) = [row for row in records(output) if row["kind"] == "turn"]
        assert re.fullmatch(r"[0-9a-f]{32}", turn["session"])

    def test_what_the_reader_asked_for_is_recorded(self, monkeypatch, capsys):
        """The Think pill and the answer footer's Shorter, on the provider that has the
        pill, so the flag survives `composer.render_think_toggle`."""
        monkeypatch.setattr(config, "TELEMETRY", "stdout")
        client = Scripted([[event("Shorter.")]], name="openrouter",
                          models=("openrouter/free",))
        run_app(monkeypatch, client=client, openrouter=True,
                session=asking(thinking=True, steer="shorter",
                               model="openrouter:openrouter/free"))
        (turn,) = [row for row in records(capsys.readouterr().out) if row["kind"] == "turn"]
        assert turn["think"] is True and turn["steer"] == "shorter"

    def test_a_call_the_reader_cuts_off_is_recorded_as_interrupted(
        self, monkeypatch, capsys
    ):
        """A click mid-answer is a rerun raised inside the stream. The call it cut off
        is recorded as neither a success nor a failure, and the turn is not over, so
        there is no turn record yet."""
        monkeypatch.setattr(config, "TELEMETRY", "stdout")
        cut = [event("Half an "), stub_streamlit.Rerun()]

        def stream():
            for item in cut:
                if isinstance(item, BaseException):
                    raise item
                yield item

        client = Scripted([stream()])
        stub = run_app(monkeypatch, client=client, session=asking())
        found = records(capsys.readouterr().out)
        assert [row["kind"] for row in found] == ["call"]
        assert found[0]["ok"] is None and found[0]["error_kind"] == "interrupted"
        assert stub.session_state["ledger"] is not None, "the turn is still running"

    def test_a_stopped_turn_takes_its_ledger_with_it(self, monkeypatch):
        stub = run_app(monkeypatch, client=Scripted([]), session=asking(
            stop_requested=True, partial=["Half an "],
            ledger=feedback.new_ledger(),
        ))
        assert stub.session_state["ledger"] is None
        assert stub.session_state["messages"][-1].get("stopped") is True


class Lineup:
    """One provider, two models, each replaying its own script."""

    name = "google"

    def __init__(self) -> None:
        self.script: dict[str, list] = {}
        self.asked: list[str] = []
        self.tags: list = []

    def models(self):
        return [providers.Model(self.name, model_id) for model_id in ("m1", "m2")]

    def stream(self, model, messages, tools, thinking=False, tool_choice="auto"):
        self.asked.append(model)
        self.tags.append(current_tag())
        queue = self.script.get(model) or []
        if not queue:
            raise AssertionError(f"{model} was asked more often than scripted")
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        yield from item


LINEUP = Lineup()


@pytest.fixture(scope="class")
def harnessed():
    """The harness's seams, patched for one class and put back after it.

    `harness.prepare` pins `MAX_MODEL_ATTEMPTS` to one, which is right for a benchmark
    and switches off the very failover these tests are about, so each test that wants
    one sets it back for its own duration.
    """
    harness.prepare(build_provider=lambda _name, _key: LINEUP, fresh=True)
    yield LINEUP
    harness.restore()


@pytest.mark.usefixtures("harnessed")
class TestATurnAcrossTheRunsAFailoverTakes:
    """`evals/harness.py` reuses one session across script runs, as Streamlit does, so a
    failover there is what it is for a reader: the next run, on the next model."""

    @pytest.fixture(autouse=True)
    def lineup(self, monkeypatch, tmp_path):
        clear_provider_keys(monkeypatch)
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setattr(config, "MAX_MODEL_ATTEMPTS", 0)
        # A 5xx is retried inside `llm.start` before the turn hears of it, which is a
        # second request to a script with one answer in it.
        monkeypatch.setattr(config, "REQUEST_RETRIES", 0)
        self.log = tmp_path / "telemetry.jsonl"
        monkeypatch.setattr(config, "TELEMETRY", str(self.log))
        LINEUP.script = {}
        LINEUP.asked = []
        LINEUP.tags = []
        return LINEUP

    def test_a_failover_is_one_turn_with_the_failed_model_in_it(self):
        LINEUP.script = {"m1": [[]], "m2": [ANSWER]}
        record = harness.run_turn("what is my storage quota", "google:m1")
        assert record["outcome"] == "answered" and LINEUP.asked == ["m1", "m2"]
        rows = written(self.log)
        turns = [row for row in rows if row["kind"] == "turn"]
        calls = [row for row in rows if row["kind"] == "call"]
        assert len(turns) == 1, "one question, one turn record, however many runs"
        (turn,) = turns
        assert {row["turn_id"] for row in rows} == {turn["turn_id"]}
        assert turn["tried"] == [{"model": "google:m1", "error_kind": "empty"}]
        assert turn["model"] == "google:m2" and turn["calls"] == 2
        assert [(row["n"], row["model"], row["ok"], row["error_kind"]) for row in calls] == [
            (1, "m1", False, "empty"),
            (2, "m2", True, ""),
        ]
        assert {tag.turn_id for tag in LINEUP.tags} == {turn["turn_id"]}

    def test_a_turn_that_fails_everywhere_names_every_model_it_tried(self):
        error = RuntimeError("Internal Server Error")
        error.status_code = 500
        LINEUP.script = {"m1": [[]], "m2": [error]}
        harness.run_turn("what is my storage quota", "google:m1")
        rows = written(self.log)
        (turn,) = [row for row in rows if row["kind"] == "turn"]
        assert turn["outcome"] == "failed" and turn["error_kind"] == "unavailable"
        assert turn["tried"] == [
            {"model": "google:m1", "error_kind": "empty"},
            {"model": "google:m2", "error_kind": "unavailable"},
        ]
        failed = [row for row in rows if row["kind"] == "call" and row["ok"] is False]
        assert [row["status"] for row in failed] == [None, 500]

    def test_without_a_failover_the_tool_rounds_are_numbered(self):
        LINEUP.script = {"m1": [SEARCH, READ, ANSWER]}
        harness.run_turn("what is my storage quota", "google:m1")
        calls = [row for row in written(self.log) if row["kind"] == "call"]
        assert [(row["n"], row["round"]) for row in calls] == [(1, 1), (2, 2), (3, 3)]
        assert [tag.round for tag in LINEUP.tags] == [1, 2, 3]


# --- the deployment -----------------------------------------------------------------


class TestTheDeploymentTurnsItOn:
    def env(self) -> tuple[str, dict]:
        script = (ROOT / "deploy" / "cloudrun.sh").read_text(encoding="utf-8")
        found = re.search(r'--set-env-vars="([^"]*)"', script)
        assert found, "deploy/cloudrun.sh no longer passes --set-env-vars"
        return script, dict(pair.split("=", 1) for pair in found.group(1).split(","))

    def test_records_go_to_stdout_named_after_the_deployment_and_commit(self):
        script, env = self.env()
        assert env["SAGE_TELEMETRY"] == "stdout"
        assert env["SAGE_DEPLOYMENT"] == "cloudrun"
        assert env["SAGE_GIT_SHA"].startswith("$"), "computed per deploy, not written down"
        assert "git rev-parse --short" in script

    def test_it_does_not_switch_on_the_rating_row(self):
        assert "SAGE_FEEDBACK_LOG" not in self.env()[1]

    def test_the_provisioning_script_parses_and_mints_no_key(self):
        path = ROOT / "deploy" / "observability.sh"
        checked = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        assert checked.returncode == 0, checked.stderr
        script = path.read_text(encoding="utf-8")
        # Printed for a person to run, behind a `$` prompt, and never run here.
        run = [line for line in script.splitlines()
               if re.match(r"\s*gcloud\s+iam\s+service-accounts\s+keys\s+create", line)]
        assert not run, "a key is a person's decision, made by hand"
        assert "\\$ gcloud iam service-accounts keys create" in script, (
            "and the person is told how"
        )
        assert "bigquery.jobUser" not in script, "streaming inserts need no job rights"

"""Streaming and error handling, exercised against a fake Mistral SDK surface."""

import pytest

from sage import llm
from sage.providers import Chunk


def event(content=None, tool_calls=None):
    """A normalised provider chunk."""
    return Chunk(text=content or "", tool_calls=tool_calls or [])


def call(index=0, cid=None, name=None, arguments=None):
    return {
        "index": index,
        "id": cid or "",
        "name": name or "",
        "arguments": arguments or "",
    }


class FakeProvider:
    """A provider whose stream can fail the first N times."""

    name = "fake"

    def __init__(self, events, failures=0, error=None):
        self.events = events
        self.failures = failures
        self.error = error or RuntimeError("boom")
        self.calls = 0
        self.kwargs = {}

    def models(self):
        return []

    def stream(self, model, messages, tools):
        self.calls += 1
        self.kwargs = {"model": model, "messages": messages, "tools": tools}
        if self.calls <= self.failures:
            raise self.error
        yield from self.events


class TestTurn:
    def test_text_deltas_stream_and_accumulate(self):
        turn = llm.Turn(stream=iter([event("Hello "), event("world")]))
        assert list(turn.deltas()) == ["Hello ", "world"]
        assert turn.text == "Hello world"
        assert turn.tool_calls == []
        assert turn.finished

    def test_consume_blocks_and_returns_the_same_turn(self):
        """The single reader that lets the post-tool answer stream too."""
        turn = llm.Turn(stream=iter([event("a"), event("b")])).consume()
        assert turn.text == "ab"

    def test_tool_call_arguments_are_reassembled_across_chunks(self):
        events = [
            event(tool_calls=[call(0, "id-1", "search_docs", '{"que')]),
            event(tool_calls=[call(0, None, None, 'ry": "gpu jobs"}')]),
        ]
        turn = llm.Turn(stream=iter(events)).consume()
        assert turn.tool_calls == [
            {"id": "id-1", "name": "search_docs", "input": {"query": "gpu jobs"}}
        ]

    def test_parallel_tool_calls_are_kept_separate(self):
        events = [
            event(tool_calls=[call(0, "a", "search_docs", '{"query":"x"}')]),
            event(tool_calls=[call(1, "b", "read_doc", '{"path":"docs/a.md"}')]),
        ]
        turn = llm.Turn(stream=iter(events)).consume()
        assert [c["name"] for c in turn.tool_calls] == ["search_docs", "read_doc"]
        assert turn.tool_calls[1]["input"] == {"path": "docs/a.md"}

    def test_two_calls_in_one_delta_survive_a_shared_index(self):
        """Both calls arrive as index 0, because the SDK defaults the field to 0.

        mistralai 2.x declares `ToolCall.index: Optional[int] = 0`, so a model issuing
        a search and a read in one delta hands over two fragments that claim the same
        slot. Keyed on index alone, the second overwrote the first's name and id and
        their JSON was concatenated into `{"query":"x"}{"path":"y"}` — unparseable, so
        the turn ran one tool with no arguments at all: the search never happened and
        the answer shipped with an empty Sources strip.
        """
        events = [event(tool_calls=[
            call(0, "a", "search_docs", '{"query":"x"}'),
            call(0, "b", "read_doc", '{"path":"docs/a.md"}'),
        ])]
        turn = llm.Turn(stream=iter(events)).consume()
        assert [c["name"] for c in turn.tool_calls] == ["search_docs", "read_doc"]
        assert turn.tool_calls[0]["input"] == {"query": "x"}
        assert turn.tool_calls[1]["input"] == {"path": "docs/a.md"}

    def test_a_provider_that_repeats_the_id_still_assembles_one_call(self):
        """The other shape: the same id on every fragment of one call."""
        events = [
            event(tool_calls=[call(0, "a", "search_docs", '{"que')]),
            event(tool_calls=[call(0, "a", None, 'ry":"gpu"}')]),
        ]
        turn = llm.Turn(stream=iter(events)).consume()
        assert turn.tool_calls == [
            {"id": "a", "name": "search_docs", "input": {"query": "gpu"}}
        ]

    def test_two_calls_interleaved_across_chunks_stay_apart(self):
        events = [
            event(tool_calls=[call(0, "a", "search_docs", '{"q')]),
            event(tool_calls=[call(1, "b", "read_doc", '{"path"')]),
            event(tool_calls=[call(0, None, None, 'uery":"x"}'),
                              call(1, None, None, ':"docs/y.md"}')]),
        ]
        turn = llm.Turn(stream=iter(events)).consume()
        assert [c["input"] for c in turn.tool_calls] == [
            {"query": "x"}, {"path": "docs/y.md"}
        ]

    def test_text_and_tool_calls_can_arrive_together(self):
        events = [
            event("Let me look. "),
            event(tool_calls=[call(0, "a", "search_docs", '{"query":"x"}')]),
        ]
        turn = llm.Turn(stream=iter(events)).consume()
        assert turn.text == "Let me look. "
        assert len(turn.tool_calls) == 1

    def test_unparseable_arguments_degrade_to_empty_input(self):
        events = [event(tool_calls=[call(0, "a", "search_docs", "{not json")])]
        turn = llm.Turn(stream=iter(events)).consume()
        assert turn.tool_calls[0]["input"] == {}

    def test_nameless_tool_calls_are_discarded(self):
        turn = llm.Turn(stream=iter([event(tool_calls=[call(0, "a", None, "{}")])]))
        turn.consume()
        assert turn.tool_calls == []

    def test_non_chunk_events_are_skipped(self):
        assert llm.Turn(stream=iter([None, "junk", event("ok")])).consume().text == "ok"

    def test_stream_failures_are_classified(self):
        def explode():
            yield event("partial")
            raise TimeoutError("connection timed out")

        turn = llm.Turn(stream=explode())
        with pytest.raises(llm.AssistantError) as caught:
            list(turn.deltas())
        assert caught.value.kind == "network"

    def test_as_message_shapes_the_tool_call_turn(self):
        events = [event("hm", [call(0, "id-9", "read_doc", '{"path":"docs/a.md#b"}')])]
        message = llm.Turn(stream=iter(events)).consume().as_message()
        assert message["role"] == "assistant"
        assert message["content"] == "hm"
        assert message["tool_calls"][0]["type"] == "function"
        assert message["tool_calls"][0]["function"]["name"] == "read_doc"
        assert '"path"' in message["tool_calls"][0]["function"]["arguments"]


class TestStart:
    def test_the_model_and_tools_reach_the_provider(self):
        provider = FakeProvider([event("x")])
        llm.start(provider, "some-model", [{"role": "user", "content": "hi"}], [{"t": 1}])
        assert provider.kwargs["model"] == "some-model"
        assert provider.kwargs["tools"] == [{"t": 1}]

    def test_failures_surface_at_start_so_they_can_be_retried(self):
        """provider.stream is a generator, so start() must pull the first chunk."""
        provider = FakeProvider([], failures=1, error=RuntimeError("unauthorized"))
        with pytest.raises(llm.AssistantError):
            llm.start(provider, "m", [], None)
        assert provider.calls == 1

    def test_transient_failures_are_retried(self, monkeypatch):
        monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)
        error = RuntimeError("503 service unavailable")
        error.status_code = 503
        provider = FakeProvider([event("recovered")], failures=1, error=error)
        turn = llm.start(provider, "m", [], None)
        assert turn.consume().text == "recovered"
        assert provider.calls == 2

    def test_permanent_failures_are_not_retried(self):
        error = RuntimeError("unauthorized")
        error.status_code = 401
        provider = FakeProvider([], failures=5, error=error)
        with pytest.raises(llm.AssistantError) as caught:
            llm.start(provider, "m", [], None)
        assert caught.value.kind == "auth"
        assert provider.calls == 1

    def test_retries_give_up_and_surface_the_error(self, monkeypatch):
        monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)
        error = RuntimeError("rate limit exceeded")
        provider = FakeProvider([], failures=99, error=error)
        with pytest.raises(llm.AssistantError) as caught:
            llm.start(provider, "m", [], None)
        assert caught.value.kind == "rate_limit"
        assert provider.calls == llm.config.REQUEST_RETRIES + 1


class TestClassify:
    @pytest.mark.parametrize(
        ("exc", "kind"),
        [
            (RuntimeError("Invalid API key provided"), "auth"),
            (RuntimeError("Rate limit exceeded, slow down"), "rate_limit"),
            (RuntimeError("maximum context length is 32000 tokens"), "context"),
            (RuntimeError("Connection reset by peer"), "network"),
            (RuntimeError("request timed out"), "network"),
            (RuntimeError("something odd"), "unknown"),
        ],
    )
    def test_messages_are_specific(self, exc, kind):
        error = llm.classify(exc)
        assert error.kind == kind
        assert error.user_message

    def test_status_codes_take_priority(self):
        exc = RuntimeError("server exploded")
        exc.status_code = 500
        assert llm.classify(exc).kind == "unavailable"

    def test_only_transient_kinds_are_retryable(self):
        assert llm.AssistantError("network").retryable
        assert llm.AssistantError("rate_limit").retryable
        assert not llm.AssistantError("auth").retryable
        assert not llm.AssistantError("context").retryable

    def test_an_assistant_error_classifies_to_itself(self):
        original = llm.AssistantError("auth")
        assert llm.classify(original) is original

    def test_unknown_kinds_fall_back_safely(self):
        assert llm.AssistantError("nonsense-kind").kind == "unknown"


def test_tool_result_message_shape():
    message = llm.tool_result_message({"id": "x", "name": "read_doc"}, "content here")
    assert message == {
        "role": "tool",
        "tool_call_id": "x",
        "name": "read_doc",
        "content": "content here",
    }


class TestToolArgumentsAreWhateverTheModelEmitted:
    """`_parse` is the boundary between a model's free text and a dict the loop assumes.

    A model that has started repeating itself emits exactly `[[[[[…`, and `json.loads`
    answers deep nesting with `RecursionError` rather than a decode error — so it left
    `_parse`, which nothing above it expects to raise, and took the turn down as an
    unknown failure. Arguments this cannot read are already an empty dict, which each tool
    answers with its own message to the model.
    """

    def test_deeply_nested_arguments_are_an_empty_dict(self):
        assert llm._parse("[" * 60_000 + "]" * 60_000) == {}

    def test_a_deeply_nested_object_too(self):
        assert llm._parse('{"a":' * 20_000 + "1" + "}" * 20_000) == {}

    def test_ordinary_arguments_still_parse(self):
        assert llm._parse('{"query": "storage quota"}') == {"query": "storage quota"}

    def test_a_json_value_that_is_not_an_object_is_still_an_empty_dict(self):
        assert llm._parse('"[DONE]"') == {}
        assert llm._parse("[1, 2]") == {}

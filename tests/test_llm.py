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

    def stream(self, model, messages, tools, thinking=False, tool_choice="auto"):
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


class TestASpentFreeAllowanceIsNeverQuota:
    """Two providers cap a free tier, and both bodies read like something else.

    Zen's says "Rate limit exceeded. Please try again later." over a
    `FreeUsageLimitError` — so status and prose both say wait, and waiting is the one
    thing that does not work. OpenRouter's says "purchase credits to raise your
    free-model daily limit", and the word `credit` sent it to `quota`, whose branch
    matches that word and is checked before 429. Measured when a bench run hit the cap:
    the reader would have been told "This model is out of credit or its quota is used
    up. Switch to another model", with the key holding $4.44, the limit a request count
    resetting at midnight UTC, and one model row on the page to switch between.

    Both are `allowance`, and the kind earns its place: the remedy is neither waiting
    nor paying, it is another provider, which is what `View.alternative` prefers for
    this kind.
    """

    @pytest.mark.parametrize("message", [
        # OpenRouter's account-wide daily cap on free models, verbatim in shape.
        'HTTP 429 from https://openrouter.ai/api/v1/chat/completions: {"error":'
        '{"code":429,"message":"Rate limit exceeded: free-models-per-day-high-balance. '
        'To increase your free-model daily limit, purchase credits."}}',
        # The same cap as the bare error code, in case the prose is reworded.
        'HTTP 429: {"error":{"code":"free_models_per_day"}}',
        # OpenCode Zen's, which this branch was originally written for.
        'HTTP 429: {"error":{"type":"FreeUsageLimitError","message":"Rate limit '
        'exceeded. Please try again later."}}',
    ])
    def test_a_capped_free_tier_is_an_allowance(self, message):
        error = RuntimeError(message)
        error.status_code = 429
        assert llm.classify(error).kind == "allowance"

    @pytest.mark.parametrize("message,kind", [
        # A real spent balance still reads as one.
        ('HTTP 402: {"error":{"message":"Insufficient credit to make this request"}}',
         "quota"),
        # And an ordinary rate limit is still a moment's wait.
        ('HTTP 429: {"error":{"message":"Rate limit exceeded, retry in 2s"}}',
         "rate_limit"),
    ])
    def test_the_neighbours_are_unmoved(self, message, kind):
        error = RuntimeError(message)
        error.status_code = 402 if kind == "quota" else 429
        assert llm.classify(error).kind == kind


class TestAnOversizedConversationIsNeverUnknown:
    """`context` is the one kind that must not walk the lineup, so it is the one kind
    a missed classification costs the most.

    `turn.FAILOVER_KINDS` is `llm.KINDS - {"context"}`, which means anything that
    lands in `unknown` is asked of every model in turn — and an oversized request is
    the same size for all of them. Driven through the running app against the mock
    provider: a 400 the old branch did not recognise made three requests, one per
    model, and finished on "Something went wrong reaching the assistant"; the same
    body classified as `context` makes one and says to clear the chat.

    Only OpenAI writes "context length". These are the other three wordings from
    providers this deployment is configured for, copied from their own messages.
    """

    @pytest.mark.parametrize(
        "message",
        [
            # Anthropic, and so OpenRouter wherever it routes to one.
            'HTTP 400: {"error":{"type":"invalid_request_error","message":'
            '"prompt is too long: 214747 tokens > 200000 maximum"}}',
            # Gemini's OpenAI-compatible endpoint.
            'HTTP 400: {"error":{"message":"The input token count (1204587) exceeds '
            'the maximum number of tokens allowed (1048576)."}}',
            # Mistral.
            'HTTP 400: {"message":"Too many tokens in prompt: 40000 > 32000"}',
            # The one that always worked, kept so a rewrite cannot lose it.
            "This model's maximum context length is 8192 tokens",
        ],
    )
    def test_every_providers_wording_is_context(self, message):
        assert llm.classify(RuntimeError(message)).kind == "context"

    @pytest.mark.parametrize(
        "message",
        [
            # OpenAI refusing ONE oversized field, not the conversation. No
            # prompt-side word, so the size complaint alone must not claim it.
            '{"error":{"message":"string too long"}}',
            # `max_tokens` is this app's own ceiling (`config.MAX_TOKENS`), so a
            # gateway rejecting it is a misconfiguration for an operator to read in
            # the details panel — not a chat for the reader to clear.
            '{"error":{"message":"max_tokens exceeds the model limit of 8192"}}',
        ],
    )
    def test_a_size_complaint_about_something_else_is_not(self, message):
        assert llm.classify(RuntimeError(message)).kind != "context"

    def test_a_rate_limit_that_counts_tokens_is_still_a_rate_limit(self):
        """The 429 branches are checked first, and have to stay that way: a
        token-metered rate limit says "tokens" and "exceeded" and is not a
        conversation that got too long."""
        exc = RuntimeError('{"message":"Rate limit exceeded: too many tokens '
                           'per minute"}')
        exc.status_code = 429
        assert llm.classify(exc).kind == "rate_limit"


class TestATransportFailureIsNeverUnknown:
    """A dead socket is `network`: the message says to check the connection, and
    `llm.start` retries it. Reported as `unknown` it got neither."""

    @pytest.mark.parametrize(
        "message",
        [
            # httpx, when a pooled keepalive socket is closed by the gateway before
            # the response starts. "connection" is not a substring of
            # "disconnected", which is the whole reason this was missed; the
            # mid-stream form says "connection" and always classified.
            "Server disconnected without sending a response.",
            "peer closed connection without sending complete message body",
            # A DNS failure that arrives unwrapped: `socket.gaierror(-2, …)` carries
            # neither "dns" nor "connection" in its class name or its message.
            "Name or service not known",
            "Temporary failure in name resolution",
        ],
    )
    def test_transport_wordings_are_network(self, message):
        error = llm.classify(RuntimeError(message))
        assert error.kind == "network"
        assert error.retryable

    def test_a_request_timeout_status_is_network(self):
        exc = RuntimeError("HTTP 408 from https://example.invalid/v1/chat/completions")
        exc.status_code = 408
        assert llm.classify(exc).kind == "network"


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

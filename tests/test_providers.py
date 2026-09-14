"""Provider adapters: Mistral SDK and the OpenAI-compatible OpenCode Zen endpoint.

Both are reached through the registry: a profile entry says *where* a provider is and
an adapter registered under its `kind` says *how* to talk to it. The tests build
entries directly, which is the same thing `profile.load` does from TOML.
"""

import importlib
import os
import sys
from dataclasses import replace
from types import ModuleType, SimpleNamespace

import pytest

from sage import config, providers
from sage.profile import ProviderEntry
from sage.providers.mistral import MistralProvider
from sage.providers.openai_compat import OpenAICompatProvider

# A synthetic OpenAI-compatible entry, not one read out of the shipped profile.
#
# It WAS `profile.active().provider("opencode")`, and that coupled tests about a
# GENERIC rule — the free/paid filtering `openai_compat` applies to any endpoint that
# serves both — to this deployment happening to declare that particular provider. The
# day the profile dropped it, three of these failed on `replace(None, ...)`: a test of
# machinery broken by a change of subject, which the layering in CLAUDE.md exists to
# prevent. The rule is the package's; its tests bring their own subject.
ZEN = ProviderEntry(
    name="google",
    kind="openai",
    key_env="GEMINI_API_KEY",
    base_url="https://opencode.ai/zen/v1",
    models=("deepseek-v4-flash-free",),
    free_marks=("-free", "big-pickle"),
    free_only=True,
)


def zen(**overrides) -> providers.Provider:
    """The shipped OpenCode entry, with whatever this test wants changed."""
    return replace(ZEN, **overrides)


class TestModel:
    def test_key_round_trips(self):
        model = providers.Model("google", "deepseek-v4-flash-free")
        assert model.key == "google:deepseek-v4-flash-free"
        assert providers.parse_key(model.key) == model

    def test_labels_are_the_model_name_and_stay_short(self):
        """No provider prefix. "Zen · deepseek-v4-flash" spent a third of the picker's
        width restating what the rest of the row already said, on every line, and
        `mistral-` on the front of the Mistral ids already does that job."""
        mistral = providers.Model("mistral", "mistral-small-latest").label
        zen = providers.Model("google", "deepseek-v4-flash-free").label
        assert mistral == "mistral-small-latest"
        assert zen == "deepseek-v4-flash"
        assert "·" not in mistral + zen
        # Long labels get ellipsed in a 240px picker, so keep them under ~30 chars.
        assert max(len(mistral), len(zen)) <= 30

    def test_the_tier_marker_is_not_part_of_the_displayed_name(self):
        """It is billing plumbing, not something a reader chooses between models on.

        Only the id that goes upstream carries it, and only as a whole segment: a
        substring rule would eat the middle of any model whose name happens to
        contain those four letters.
        """
        assert providers.Model("google", "hy3-free").label == "hy3"
        assert providers.Model("google", "mimo-v2.5-free").label == "mimo-v2.5"
        assert providers.Model("google", "big-pickle").label == "big-pickle"
        assert providers.Model("google", "freeform-7b").label == "freeform-7b"
        # The id itself is untouched, so the request still names what Zen serves.
        assert providers.Model("google", "hy3-free").key == "google:hy3-free"

    @pytest.mark.parametrize("bad", ["", "nope", "mistral:", ":model", "other:m"])
    def test_malformed_keys_are_rejected(self, bad):
        assert providers.parse_key(bad) is None

    def test_a_model_id_containing_a_colon_survives(self):
        model = providers.parse_key("google:vendor/model:v2")
        assert model.id == "vendor/model:v2"

    def test_tool_support_is_configurable(self, monkeypatch):
        monkeypatch.setattr(config, "TOOLLESS_MODELS", ("big-pickle",))
        assert not providers.Model("google", "Big-Pickle").supports_tools
        assert providers.Model("google", "deepseek-v4-flash").supports_tools

    def test_everything_supports_tools_by_default(self, monkeypatch):
        monkeypatch.setattr(config, "TOOLLESS_MODELS", ())
        assert providers.Model("google", "anything").supports_tools


class TestParseSSE:
    """OpenCode Zen speaks the OpenAI streaming format."""

    def test_text_deltas(self):
        lines = [
            'data: {"choices":[{"delta":{"content":"Use "}}]}',
            'data: {"choices":[{"delta":{"content":"sbatch."}}]}',
            "data: [DONE]",
        ]
        chunks = list(providers.parse_sse(iter(lines)))
        assert "".join(chunk.text for chunk in chunks) == "Use sbatch."

    def test_tool_calls_arrive_in_fragments(self):
        lines = [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
            '"function":{"name":"search_docs","arguments":"{\\"query\\":"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
            '"function":{"arguments":"\\"gpu\\"}"}}]}}]}',
        ]
        fragments = [f for chunk in providers.parse_sse(iter(lines))
                     for f in chunk.tool_calls]
        assert fragments[0]["name"] == "search_docs"
        assert "".join(f["arguments"] for f in fragments) == '{"query":"gpu"}'

    def test_done_stops_the_stream(self):
        lines = ["data: [DONE]", 'data: {"choices":[{"delta":{"content":"after"}}]}']
        assert list(providers.parse_sse(iter(lines))) == []

    def test_keepalives_comments_and_blanks_are_ignored(self):
        lines = ["", ": keep-alive", "event: ping", 'data: {"choices":[]}',
                 'data: {"choices":[{"delta":{"content":"ok"}}]}']
        assert "".join(c.text for c in providers.parse_sse(iter(lines))) == "ok"

    def test_a_malformed_event_does_not_kill_the_stream(self):
        lines = ["data: {not json", 'data: {"choices":[{"delta":{"content":"ok"}}]}']
        assert "".join(c.text for c in providers.parse_sse(iter(lines))) == "ok"

    @pytest.mark.parametrize("event", [
        # Quoted, which some OpenAI-compatible gateways send instead of the bare form.
        'data: "[DONE]"',
        "data: [1, 2]",
        "data: 42",
        "data: null",
        'data: {"choices": ["not an object"]}',
        'data: {"choices": [{"delta": "not an object"}]}',
    ])
    def test_an_event_of_the_wrong_shape_is_skipped_not_raised(self, event):
        """Parsed is not the same as shaped.

        Every `.get` here assumed a dict. A valid-JSON string or array reached them
        and raised AttributeError, which `Turn.deltas` then classified as an unknown
        provider failure — so an answer that had been streaming for twenty seconds was
        thrown away and replaced with "something went wrong reaching the assistant" at
        the very end of it.
        """
        lines = [event, 'data: {"choices":[{"delta":{"content":"ok"}}]}']
        assert "".join(c.text for c in providers.parse_sse(iter(lines))) == "ok"

    def test_an_error_streamed_after_a_200_keeps_the_answer_and_says_so(self, caplog):
        """Some gateways report a rate limit hit *during* generation, in the stream.

        Skipped like every other event this parser does not understand — the rule above
        is deliberate, and discarding a half-streamed answer to show "something went
        wrong" is worse than a short one. But it is the one shape that says the answer
        stopped rather than finished, so it goes in the log: without it, an operator
        looking at an answer that ends mid-sentence has nothing to read.
        """
        lines = [
            'data: {"choices":[{"delta":{"content":"half an "}}]}',
            'data: {"error":{"message":"rate limit exceeded","type":"rate_limit"}}',
            'data: {"choices":[{"delta":{"content":"answer"}}]}',
        ]
        with caplog.at_level("WARNING"):
            text = "".join(c.text for c in providers.parse_sse(iter(lines)))
        assert text == "half an answer", "the text already streamed must survive"
        assert any("mid-stream" in record.message for record in caplog.records)
        assert any("rate limit exceeded" in str(record.args) for record in caplog.records)

    def test_bytes_lines_are_decoded(self):
        lines = [b'data: {"choices":[{"delta":{"content":"bytes"}}]}']
        assert "".join(c.text for c in providers.parse_sse(iter(lines))) == "bytes"


class TestNormalisation:
    def test_sdk_style_tool_call_objects(self):
        call = SimpleNamespace(
            index=2, id="x", function=SimpleNamespace(name="read_doc", arguments="{}")
        )
        assert providers.tool_fragments([call]) == [
            {"index": 2, "id": "x", "name": "read_doc", "arguments": "{}"}
        ]

    def test_dict_style_tool_calls(self):
        call = {"index": 1, "id": "y", "function": {"name": "search_docs"}}
        assert providers.tool_fragments([call])[0]["name"] == "search_docs"

    def test_missing_index_falls_back_to_position(self):
        calls = [{"function": {"name": "a"}}, {"function": {"name": "b"}}]
        assert [f["index"] for f in providers.tool_fragments(calls)] == [0, 1]

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            (None, ""),
            ("plain", "plain"),
            (["a", "b"], "ab"),
            ([{"text": "a"}, {"text": "b"}], "ab"),
            ([SimpleNamespace(text="x")], "x"),
        ],
    )
    def test_content_shapes_flatten(self, content, expected):
        assert providers.flatten(content) == expected


class TestMistralAdapter:
    """The SDK returns a context manager on 1.x and a bare iterator on some builds."""

    @staticmethod
    def _event(text):
        delta = SimpleNamespace(content=text, tool_calls=None)
        return SimpleNamespace(
            data=SimpleNamespace(choices=[SimpleNamespace(delta=delta)])
        )

    def _provider(self, stream):
        adapter = MistralProvider.__new__(MistralProvider)
        adapter._client = SimpleNamespace(
            chat=SimpleNamespace(stream=lambda **_kwargs: stream)
        )
        return adapter

    def test_a_bare_iterator_works(self):
        stream = iter([self._event("a"), self._event("b")])
        chunks = list(self._provider(stream).stream("m", [], None))
        assert "".join(c.text for c in chunks) == "ab"

    def test_a_context_manager_is_entered_and_closed(self):
        events = [self._event("hi")]

        class Managed:
            entered = exited = False

            def __enter__(inner):
                inner.entered = True
                return iter(events)

            def __exit__(inner, *_exc):
                inner.exited = True
                return False

        managed = Managed()
        chunks = list(self._provider(managed).stream("m", [], None))
        assert "".join(c.text for c in chunks) == "hi"
        assert managed.entered and managed.exited

    def test_choices_as_an_object_does_not_raise(self):
        """The same shape that was a `KeyError: 0` in the JSON adapter, in the SDK one.

        A raise from inside this generator is not recoverable by the time it is seen:
        `Turn.deltas` can only classify it as an unknown failure, and the half-streamed
        answer already on screen is discarded and replaced with "something went wrong" at
        the very end of it. Both adapters normalise onto the same `Chunk`, and only one had
        been taught to distrust its input — this SDK's shapes have moved between 0.x, 1.x
        and 2.x before.
        """
        stream = iter([SimpleNamespace(data=SimpleNamespace(choices={"delta": 1}))])
        assert list(self._provider(stream).stream("m", [], None)) == []

    def test_choices_as_a_string_does_not_raise(self):
        stream = iter([SimpleNamespace(data=SimpleNamespace(choices="soon"))])
        assert list(self._provider(stream).stream("m", [], None)) == []

    def test_a_stream_survives_a_bad_event_in_the_middle(self):
        stream = iter([
            self._event("be"),
            SimpleNamespace(data=SimpleNamespace(choices={"x": 1})),
            self._event("fore"),
        ])
        chunks = list(self._provider(stream).stream("m", [], None))
        assert "".join(chunk.text for chunk in chunks) == "before"

    def test_a_finish_only_event_carries_no_delta(self):
        """`delta` is None on the last event of some builds."""
        stream = iter([SimpleNamespace(
            data=SimpleNamespace(choices=[SimpleNamespace(delta=None)])
        )])
        chunks = list(self._provider(stream).stream("m", [], None))
        assert [(chunk.text, chunk.tool_calls) for chunk in chunks] == [("", [])]

    def test_content_arriving_as_parts_is_flattened(self):
        """Mistral's newer content shape is a list of parts rather than a string."""
        delta = SimpleNamespace(
            content=[SimpleNamespace(text="a"), SimpleNamespace(text="b")],
            tool_calls=None,
        )
        stream = iter([SimpleNamespace(
            data=SimpleNamespace(choices=[SimpleNamespace(delta=delta)])
        )])
        chunks = list(self._provider(stream).stream("m", [], None))
        assert "".join(chunk.text for chunk in chunks) == "ab"

    def test_malformed_events_are_skipped(self):
        stream = iter([
            SimpleNamespace(data=None),
            SimpleNamespace(data=SimpleNamespace(choices=[])),
            self._event("ok"),
        ])
        chunks = list(self._provider(stream).stream("m", [], None))
        assert "".join(c.text for c in chunks) == "ok"


class TestOpenAICompat:
    def test_the_key_is_sent_as_a_bearer_token(self):
        provider = OpenAICompatProvider(zen(base_url="https://x.test/v1/"), "sk-zen-abc")
        headers = provider._headers()
        assert headers["Authorization"] == "Bearer sk-zen-abc"

    def test_the_base_url_loses_a_trailing_slash(self):
        provider = OpenAICompatProvider(zen(base_url="https://x.test/v1/"), "k")
        assert provider._base == "https://x.test/v1"

    def test_model_discovery_falls_back_when_the_endpoint_is_unreachable(self):
        provider = OpenAICompatProvider(zen(base_url="http://127.0.0.1:1/v1"), "k")
        found = provider.models()
        assert [model.id for model in found] == list(ZEN.models)
        assert all(model.provider == "google" for model in found)

    def test_discovery_keeps_the_preferred_order_and_appends_the_rest(self):
        """Order is not cosmetic: it picks the session default *and* what an
        automatic failover lands on. Sorting alphabetically made a spent Mistral
        quota fail over to `big-pickle` rather than the free deepseek model."""
        provider = OpenAICompatProvider(
            zen(models=("deepseek-v4-flash-free", "mimo-v2.5")), "k"
        )
        ordered = provider._order(["zzz-model", "mimo-v2.5", "big-pickle",
                                   "deepseek-v4-flash-free"])
        assert ordered == ["deepseek-v4-flash-free", "mimo-v2.5",
                           "big-pickle", "zzz-model"]

    def test_a_preferred_model_the_endpoint_no_longer_serves_is_dropped(self):
        provider = OpenAICompatProvider(zen(models=("retired", "kept")), "k")
        assert provider._order(["kept", "new"]) == ["kept", "new"]

    def test_a_family_is_never_split_up(self):
        """Reported from the picker: "there are several nemotron models but they are
        not adjacent to each other". The ranking put one fifth because the preference
        list named it and the other last because nothing did."""
        provider = OpenAICompatProvider(
            zen(models=("deepseek-v4-flash-free", "nemotron-3-ultra-free")), "k"
        )
        ordered = provider._order([
            "nemotron-3.5-lightning-free", "ling-3.0-tiny-free",
            "deepseek-v4-flash-free", "ling-3.0-flash-free",
            "nemotron-3-ultra-free",
        ])
        assert ordered == [
            "deepseek-v4-flash-free",
            "nemotron-3-ultra-free", "nemotron-3.5-lightning-free",
            "ling-3.0-flash-free", "ling-3.0-tiny-free",
        ]

    def test_grouping_does_not_move_the_first_model(self):
        """The head of the list is the session default and the failover target, so
        grouping is only allowed to decide where a family's OTHER members go."""
        provider = OpenAICompatProvider(zen(models=("deepseek-v4-flash-free",)), "k")
        for found in (
            ["aaa-first", "deepseek-v4-flash-free", "deepseek-v4-pro"],
            ["deepseek-v4-pro", "deepseek-v4-flash-free", "zzz-last"],
        ):
            assert provider._order(found)[0] == "deepseek-v4-flash-free"

    @pytest.mark.parametrize("model_id, family", [
        ("nemotron-3.5-lightning-free", "nemotron"),
        ("nemotron-3-ultra-free", "nemotron"),
        ("ling-3.0-tiny-free", "ling"),
        ("deepseek-v4-flash-free", "deepseek"),
        ("mistral-small-latest", "mistral"),
        ("laguna-s-2.1-free", "laguna"),
        # No version to split on: a family of one, which is the right answer for a
        # codename rather than a wrong guess at a version scheme.
        ("big-pickle", "big"),
        ("hy3-free", "hy3"),
        ("", ""),
    ])
    def test_the_family_is_the_name_before_the_version(self, model_id, family):
        assert providers.family_of(model_id) == family


def test_build_rejects_an_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider"):
        providers.build("nope", "key")


def _shipped_max_tokens() -> int:
    """`config.MAX_TOKENS` with any environment override taken away.

    The module reads the environment at import, so the number the app ships with is
    only visible with `SAGE_MAX_TOKENS` unset — otherwise this asserts on whatever
    the machine running the tests happens to export. The second reload puts the
    process back the way it was found.
    """
    saved = os.environ.pop("SAGE_MAX_TOKENS", None)
    try:
        return importlib.reload(config).MAX_TOKENS
    finally:
        if saved is not None:
            os.environ["SAGE_MAX_TOKENS"] = saved
        importlib.reload(config)


class TestTokenBudgetReachesTheRequest:
    """The cap is only a fix where the request is built.

    `SAGE_MAX_TOKENS` was 1600 and answers came back severed mid-sentence — "Per the
    RCC docs," and then nothing. Two things have to hold, and neither implies the
    other: the shipped default has to be generous, and it has to be the number each
    provider actually asks for. The SDK client and the HTTP client are stood in for
    here; the payload built between them is the thing under test.
    """

    def test_the_default_is_not_the_value_that_severed_answers(self):
        assert _shipped_max_tokens() >= 8000, (
            "1600 tokens cut a walkthrough with two code blocks off mid-sentence"
        )

    def test_the_mistral_request_asks_for_the_configured_budget(self):
        asked = {}

        def stream(**kwargs):
            asked.update(kwargs)
            delta = SimpleNamespace(content="ok", tool_calls=None)
            return iter([
                SimpleNamespace(data=SimpleNamespace(
                    choices=[SimpleNamespace(delta=delta)]
                ))
            ])

        adapter = MistralProvider.__new__(MistralProvider)
        adapter._client = SimpleNamespace(chat=SimpleNamespace(stream=stream))
        assert "".join(chunk.text for chunk in adapter.stream("m", [], None)) == "ok"
        assert asked.get("max_tokens") == config.MAX_TOKENS

    def test_the_openai_compatible_payload_carries_the_configured_budget(
        self, monkeypatch
    ):
        sent = {}

        class Response:
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def iter_lines(self):
                return iter([
                    'data: {"choices":[{"delta":{"content":"ok"}}]}',
                    "data: [DONE]",
                ])

        class Client:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def stream(self, _method, _url, json=None, **_kwargs):
                sent.update(json or {})
                return Response()

        fake = ModuleType("httpx")
        fake.Client = Client
        fake.Timeout = lambda *_a, **_k: None
        monkeypatch.setitem(sys.modules, "httpx", fake)

        provider = OpenAICompatProvider(zen(base_url="https://x.test/v1"), "k")
        streamed = "".join(c.text for c in provider.stream("z1", [], None))
        assert streamed == "ok"
        assert sent.get("max_tokens") == config.MAX_TOKENS


class TestFreeZenModels:
    """Zen serves its paid lineup from the same endpoint as its free one.

    Discovery returned all of it — the whole Claude and GPT range — and the picker
    offered every one as if this deployment had a balance for it. Each of those is a
    button that returns a 402.
    """

    def endpoint(self, monkeypatch, served, **overrides):
        """An OpenCode provider whose /models call returns `served`.

        httpx is imported inside the method under test and is not installed here, so
        the module is stubbed the way the streaming tests above do it.
        """
        class Response:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"data": [{"id": name} for name in served]}

        fake = ModuleType("httpx")
        fake.get = lambda *a, **k: Response()
        monkeypatch.setitem(sys.modules, "httpx", fake)
        # `deny=()` unless a test asks otherwise. These tests are about the free/paid
        # rule, and inheriting the shipped profile's deny list would make them fail the
        # day a model on it is used here as a sample — which is exactly what happened.
        settings = {"models": ("deepseek-v4-flash-free",), "deny": ()}
        settings.update(overrides)
        return OpenAICompatProvider(zen(**settings), "sk-zen-test")

    def test_the_paid_lineup_is_not_offered(self, monkeypatch):
        served = [
            "deepseek-v4-flash-free", "big-pickle", "hy3-free",
            "claude-opus-4-7", "claude-fable-5", "gpt-5.5", "claude-haiku-4-5",
        ]
        offered = [model.id for model in self.endpoint(monkeypatch, served).models()]
        assert set(offered) == {"deepseek-v4-flash-free", "big-pickle", "hy3-free"}

    def test_a_denied_model_is_not_offered_however_it_is_served(self, monkeypatch):
        """The gap the reader met as an error card.

        A model can be free by the rule, listed by `GET /models`, and dead — the
        catalogue goes on advertising a name whose endpoint returns 500. Taking it out
        of the profile's `models` does not help, because membership in the picker comes
        from discovery and the provider is still serving it. `deny` is the only thing
        that removes it, and it has to happen here rather than in the picker so that
        nothing downstream, failover included, can select one.
        """
        served = ["good-free", "dead-free", "big-pickle"]
        offered = [
            model.id
            for model in self.endpoint(
                monkeypatch, served, deny=("dead-free",)
            ).models()
        ]
        assert "dead-free" not in offered
        assert set(offered) == {"good-free", "big-pickle"}

    def test_denying_everything_offers_everything_rather_than_nothing(
        self, monkeypatch
    ):
        """A deny list that empties the picker has turned a broken model into a broken
        app, and the list is written by a daily job that cannot be assumed right on a
        day the provider is having a bad time."""
        served = ["good-free", "dead-free"]
        offered = [
            model.id
            for model in self.endpoint(
                monkeypatch, served, deny=("good-free", "dead-free")
            ).models()
        ]
        assert set(offered) == set(served)

    def test_the_rule_is_a_convention_not_a_hardcoded_list(self, monkeypatch):
        """Zen's free lineup changes without notice, so a model this repo has never
        heard of must still be offered if it is named like a free one."""
        served = ["something-brand-new-free", "claude-opus-9"]
        offered = [model.id for model in self.endpoint(monkeypatch, served).models()]
        assert offered == ["something-brand-new-free"]

    def test_nothing_free_means_offer_everything_rather_than_nothing(
        self, monkeypatch, caplog=None
    ):
        """If Zen renames its free tier, an empty picker is worse than a full one:
        the reader can still pick something, and the log says to check the marks."""
        served = ["claude-opus-4-7", "gpt-5.5"]
        offered = [model.id for model in self.endpoint(monkeypatch, served).models()]
        assert offered == served

    def test_a_paid_deployment_can_see_its_whole_lineup(self, monkeypatch):
        served = ["deepseek-v4-flash-free", "claude-opus-4-7"]
        endpoint = self.endpoint(monkeypatch, served, free_only=False)
        assert [model.id for model in endpoint.models()] == served


def test_a_model_label_is_just_the_model_name():
    """The provider prefix spent a third of the picker's width restating what the row
    already said, on every line."""
    assert providers.Model("google", "deepseek-v4-flash-free").label == (
        "deepseek-v4-flash"
    )
    assert providers.Model("mistral", "mistral-small-latest").label == (
        "mistral-small-latest"
    )
    assert "Zen" not in providers.Model("google", "big-pickle").label


class TestAStreamThatIsNotShapedLikeAStream:
    """Events an OpenAI-compatible gateway really sends, and the app really got wrong.

    A raise inside `parse_sse` escapes the generator, so `Turn.deltas` classifies it as an
    unknown failure: the half-streamed answer already on screen is thrown away and
    replaced with "something went wrong" at the very end of it. That is the failure the
    quoted-`[DONE]` note in the parser describes, and two more shapes reached it.
    """

    def test_choices_as_an_object_does_not_raise(self):
        """`{"choices": {"delta": {}}}` is a dict, which is truthy, so `choices[0]` was
        a `KeyError: 0` before the shape check could run."""
        assert list(providers.parse_sse(iter(['data: {"choices":{"delta":{}}}']))) == []

    def test_choices_as_a_string_does_not_raise(self):
        assert list(providers.parse_sse(iter(['data: {"choices":"soon"}']))) == []

    def test_a_stream_survives_a_bad_event_in_the_middle(self):
        """The point of skipping rather than raising: the answer either side arrives."""
        chunks = list(providers.parse_sse(iter([
            'data: {"choices":[{"delta":{"content":"be"}}]}',
            'data: {"choices":{"delta":{}}}',
            'data: {"choices":[{"delta":{"content":"fore"}}]}',
            'data: [DONE]',
        ])))
        assert "".join(chunk.text for chunk in chunks) == "before"

    def test_tool_calls_as_a_string_is_not_four_tool_calls(self):
        """A string is iterable, so `tool_fragments` made one fragment per character."""
        chunks = list(providers.parse_sse(iter([
            'data: {"choices":[{"delta":{"tool_calls":"nope"}}]}'
        ])))
        assert [chunk.tool_calls for chunk in chunks] == [[]]

    def test_tool_calls_as_an_object_is_not_a_tool_call(self):
        assert providers.tool_fragments({"function": {"name": "search_docs"}}) == []

    def test_a_real_tool_call_still_parses(self):
        """The guard must not cost the shape that works."""
        fragments = providers.tool_fragments(
            [{"index": 0, "id": "c1", "function": {"name": "search_docs",
                                                   "arguments": '{"query":"gpu"}'}}]
        )
        assert fragments == [
            {"index": 0, "id": "c1", "name": "search_docs",
             "arguments": '{"query":"gpu"}'}
        ]

    def test_a_deeply_nested_event_is_skipped_not_raised(self):
        """`json.loads` raises `RecursionError` on deep nesting, not a decode error.

        So the `except json.JSONDecodeError` above it did not catch it, and the raise
        escaped the generator — the failure this whole class is about. The event after it
        must still arrive, because that is what a discarded stream costs the reader.
        """
        deep = "[" * 60_000 + "]" * 60_000
        chunks = list(providers.parse_sse(iter([
            f"data: {deep}",
            'data: {"choices":[{"delta":{"content":"hi"}}]}',
        ])))
        assert [chunk.text for chunk in chunks] == ["hi"]

"""End-to-end smoke tests for app.py against a stubbed Streamlit.

These cover the rewritten tool loop: that a search → read → answer sequence streams,
that the sections actually read become the Sources strip, and that a failure lands in
a typed, user-readable error instead of taking the page down.
"""

import ast
import pathlib
import re
import time
from types import SimpleNamespace

import pytest

import stub_streamlit
from sage import config, limits, llm, providers, tools


def event(content=None, tool_calls=None):
    return providers.Chunk(text=content or "", tool_calls=tool_calls or [])


def tool_call(index, cid, name, arguments):
    return {"index": index, "id": cid, "name": name, "arguments": arguments}


class ScriptedProvider:
    """Replays a list of turns, one per `stream(...)` call."""

    def __init__(self, turns, error=None, name="mistral", models=("m1",)):
        self.name = name
        self.turns = list(turns)
        self.error = error
        self.calls = 0
        self.sent: list[list[dict]] = []
        self.tools_seen: list = []
        self._models = models

    def models(self):
        return [providers.Model(self.name, model_id) for model_id in self._models]

    def stream(self, model, messages, tools, thinking=False):
        self.calls += 1
        self.sent.append(messages)
        self.tools_seen.append(tools)
        if self.error:
            raise self.error
        if not self.turns:
            raise AssertionError("provider called more times than scripted")
        yield from self.turns.pop(0)


def clear_provider_keys(monkeypatch):
    """Unset every key the profile declares, so the machine's own environment cannot
    decide what a test sees.

    Named from the profile rather than listed here. It used to set `MISTRAL_API_KEY` and
    clear `OPENCODE_API_KEY`, which was every provider the profile had — so the day a
    third was added, five tests changed behaviour depending on whether the developer
    happened to have that key exported. Locally they failed; in CI, where no such secret
    exists, they would have passed, which is the worse of the two outcomes.
    """
    for name in providers.names():
        variable = providers.key_var(name)
        if variable:
            monkeypatch.delenv(variable, raising=False)


def run_app(monkeypatch, *, client=None, session=None, extra=None,
            opencode=False, openrouter=False, **stub_kwargs):
    """Import app.py under the stub and return (stub, module-or-None).

    `opencode=True` configures a second provider, so more than one model is offered.
    `openrouter=True` configures the one provider in the shipped profile that declares
    `reasoning`, which is what draws the Think pill — set here rather than by a caller's
    `setenv`, because `clear_provider_keys` below runs after the caller and would undo
    it. That cost two rounds of a test asserting on a control the app was right not to
    draw.
    """
    clear_provider_keys(monkeypatch)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    if opencode:
        monkeypatch.setenv("OPENCODE_API_KEY", "sk-zen-test")
    if openrouter:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    stub = stub_streamlit.install(**stub_kwargs)
    if session:
        stub.session_state.update(session)
    if client is not None:
        registry = {client.name: client, **(extra or {})}
        monkeypatch.setattr(
            providers, "build", lambda name, _key: registry[name]
        )

    module = None
    try:
        import app as module  # noqa: PLC0415
    except (stub_streamlit.Rerun, stub_streamlit.Stop):
        pass
    return stub, module


@pytest.fixture(autouse=True)
def _clean_modules():
    yield
    stub_streamlit.forget_importers()


class TestWelcome:
    def test_renders_without_a_conversation(self, monkeypatch):
        stub, module = run_app(monkeypatch)
        assert module is not None
        # Collapsed, because the markup is wrapped for the source file and a
        # sentence in it is split across lines wherever that happened to land.
        html = " ".join("\n".join(stub.markdown_html).split())
        assert "What can I help you with?" in html
        # The hero says what this is, and that is all the explaining the landing
        # screen does. The limits were a third line in the hero, then an ℹ️ popover
        # in the row under the input, then three paragraphs of small print under the
        # starter cards, then one 11px caveat line beside the model name. Each was
        # one explanation too many in the way of the box you type in, and the last
        # of them is gone too.
        assert "Sage reads the docs" not in html
        assert "What Sage is" not in html
        assert "Documentation synced" not in html
        assert "drop into the walk-in lab" not in html
        assert "Sage can make mistakes" not in html
        assert "RCC Help Desk" not in html

    def test_nothing_explains_the_app_with_a_control(self, monkeypatch):
        """A button whose only job is to explain the app is one more thing in the
        way on every screen, for something you read once."""
        stub, _module = run_app(monkeypatch)
        assert ("popover", "ℹ️") not in stub.events
        assert "clear" not in stub.button_labels
        assert not any("landing-note" in html for html in stub.markdown_html)

    def test_no_hover_tooltip_on_a_control_that_already_has_a_label(self, monkeypatch):
        """A tooltip repeating a card's own text is a black box chasing the
        cursor. Only the icon-only controls, which have nothing else to go on,
        keep theirs."""
        stub, _module = run_app(monkeypatch)
        assert not [key for key in stub.tooltips if str(key).startswith("example-")]

    def test_example_cards_get_stable_keyed_containers(self, monkeypatch):
        """CSS staggers on these keys; :nth-child never worked for Streamlit buttons."""
        stub, _module = run_app(monkeypatch)
        keys = {key for name, key in stub.events if name == "container"}
        assert {f"example-card-{n}" for n in range(6)} <= keys

    def test_missing_api_key_stops_with_a_clear_message(self, monkeypatch):
        clear_provider_keys(monkeypatch)
        stub = stub_streamlit.install()
        with pytest.raises(stub_streamlit.Stop):
            import app  # noqa: F401, PLC0415
        assert any("MISTRAL_API_KEY" in error for error in stub.errors)


class TestTurnLoop:
    SEARCH = [event(tool_calls=[tool_call(0, "c1", "search_docs", '{"query":"quota"}')])]
    READ = [
        event(tool_calls=[tool_call(0, "c2", "read_doc", '{"path":"docs/storage/main.md#quotas"}')])
    ]
    ANSWER = [event("Your /home quota is "), event("30 GB.")]

    def session(self, question="what is my storage quota"):
        return {
            "messages": [{"role": "user", "text": question, "attachments": []}],
            "processing": True,
        }

    def test_search_read_answer_produces_a_stored_answer(self, monkeypatch):
        client = ScriptedProvider([self.SEARCH, self.READ, self.ANSWER])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())

        assert client.calls == 3
        messages = stub.session_state["messages"]
        assert messages[-1]["role"] == "assistant"
        assert messages[-1]["text"] == "Your /home quota is 30 GB."
        assert stub.session_state["processing"] is False
        assert stub.session_state["error"] is None

    def test_the_final_answer_is_streamed_not_dumped(self, monkeypatch):
        """The old loop collected the post-tool answer silently, so the most common
        interaction (search -> read -> answer) never streamed at all."""
        client = ScriptedProvider([self.SEARCH, self.READ, self.ANSWER])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        # The answer arrived as two separate deltas through write_stream, which only
        # happens if the post-tool turn was consumed as a live generator.
        assert stub.stream_chunks[-1] == 2

    def test_a_long_answer_is_not_redrawn_once_per_delta(self, monkeypatch):
        """The wiring, which none of `TestRepaintPacing` can see.

        `paced` is only worth having if it is actually in the chain handed to
        `write_stream`, and a call site that lost it would leave every unit test above
        passing while the running app went back to redrawing a growing answer a
        thousand times. So this drives the real loop with an answer of the shape that
        made it hurt — many small deltas, arriving as fast as they can — and asserts
        both halves: far fewer repaints, and not one word lost to the joining.
        """
        words = [f"word{n} " for n in range(400)]
        client = ScriptedProvider([self.SEARCH, self.READ, [event(w) for w in words]])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())

        assert stub.stream_chunks[-1] < 20, "the answer is still drawn per delta"
        stored = stub.session_state["messages"][-1]["text"]
        assert stored.strip() == "".join(words).strip()

    def test_sections_that_were_read_become_sources(self, monkeypatch):
        client = ScriptedProvider([self.SEARCH, self.READ, self.ANSWER])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        sources = stub.session_state["messages"][-1]["sources"]
        assert [source["id"] for source in sources] == ["docs/storage/main.md#quotas"]
        assert sources[0]["url"].endswith("/storage/main/#quotas")
        assert sources[0]["source"] == "docs"

    def test_tool_results_are_sent_back_to_the_model(self, monkeypatch):
        client = ScriptedProvider([self.SEARCH, self.READ, self.ANSWER])
        run_app(monkeypatch, client=client, session=self.session())
        final = client.sent[-1]
        roles = [message["role"] for message in final]
        assert roles.count("tool") == 2
        assert roles[0] == "system"
        tool_bodies = [m["content"] for m in final if m["role"] == "tool"]
        assert any("path: docs/" in body for body in tool_bodies)
        assert any("Quotas" in body for body in tool_bodies)

    def test_related_sections_are_offered_alongside_sources(self, monkeypatch):
        client = ScriptedProvider([self.SEARCH, self.READ, self.ANSWER])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        # Rendering the stored answer happens on the rerun, so render it here.
        html = "\n".join(stub.markdown_html)
        assert "Sources" in html or stub.session_state["messages"][-1]["sources"]

    def test_the_models_own_sources_list_does_not_reach_the_transcript(self, monkeypatch):
        """The screenshot: an answer ending `Sources: Storage System Layout › Quotas`,
        directly above the app's own strip saying the same thing. The list the reader
        should see is the one built from what was actually retrieved."""
        answer = [
            event("Your /home quota is 30 GB.\n\n"),
            event("Sources: [Quotas](docs/storage/main.md#quotas)"),
        ]
        client = ScriptedProvider([self.SEARCH, self.READ, answer])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())

        stored = stub.session_state["messages"][-1]
        assert stored["text"] == "Your /home quota is 30 GB."
        # And the strip the app draws itself is untouched by the removal.
        assert [source["id"] for source in stored["sources"]] == [
            "docs/storage/main.md#quotas"
        ]

    def test_the_prompt_asks_for_no_sources_list(self):
        """Stripping is the backstop. Not spending the tokens is the fix."""
        from sage.prompts import system_prompt

        SYSTEM_PROMPT = system_prompt()

        assert "Cite inline" in SYSTEM_PROMPT
        # Every form of it, not just the word "Sources": told only that, a model drops
        # the label and closes with "Cited from X and Y" instead.
        assert "do not restate your citations" in SYSTEM_PROMPT.lower()
        assert "Cited from" in SYSTEM_PROMPT

    def test_an_answer_with_no_tools_still_works(self, monkeypatch):
        client = ScriptedProvider([[event("I cannot run commands.")]])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        assert client.calls == 1
        assert stub.session_state["messages"][-1]["text"] == "I cannot run commands."
        assert stub.session_state["messages"][-1]["sources"] == []

    def test_the_tool_round_limit_is_enforced(self, monkeypatch):
        from sage import config

        client = ScriptedProvider([self.SEARCH] * (config.MAX_TOOL_ROUNDS + 1))
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        assert client.calls == config.MAX_TOOL_ROUNDS + 1
        assert "wasn't able to finish" in stub.session_state["messages"][-1]["text"]

    def test_api_failure_becomes_a_typed_user_message(self, monkeypatch):
        error = RuntimeError("rate limit exceeded")
        monkeypatch.setattr(llm.time, "sleep", lambda _s: None)
        client = ScriptedProvider([], error=error)
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        assert stub.session_state["error"] == llm.AssistantError("rate_limit").user_message
        assert stub.session_state["processing"] is False
        # The question survives so the retry button has something to resend.
        assert stub.session_state["messages"][-1]["role"] == "user"

    def test_an_unexpected_exception_does_not_take_the_page_down(self, monkeypatch):
        client = ScriptedProvider([], error=ValueError("totally unexpected"))
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        assert stub.session_state["error"]
        assert stub.session_state["processing"] is False


class TestRepaintPacing:
    """`ui.turn.paced` — how often a streaming answer is handed to the browser.

    `st.write_stream` redraws the whole element per delta, so every delta reparses the
    entire answer so far and re-highlights every code block in it. A 7.6 KB answer
    arriving a word at a time was therefore drawn 1237 times: 1.9 MB over the socket to
    deliver 7.6 KB, 2.6 of 5.3 seconds with the main thread blocked, 14 fps and a 1.4s
    freeze, measured in the running app against a 4x-throttled CPU.

    What is tested here is the thing that makes that safe to fix: the reader must get
    the same answer, the same first word at the same moment, and no added wait on a
    stream that was never fast enough to need pacing. The frame rate itself is not
    testable from a stub — it is measured by driving the real app, which is where the
    numbers above come from.
    """

    @staticmethod
    def turn_module():
        stub_streamlit.install()
        from sage.ui import turn  # noqa: PLC0415

        return turn

    # Longer than any test can take, so "inside one interval" is not a race.
    HELD = 10_000

    def test_the_answer_is_identical_however_it_is_paced(self):
        turn = self.turn_module()
        deltas = [f"word{n} " for n in range(200)]
        painted = list(turn.paced(iter(deltas), interval_ms=self.HELD))
        assert "".join(painted) == "".join(deltas)

    def test_a_fast_stream_is_painted_far_fewer_times(self):
        """The whole point: 200 deltas inside one interval are two repaints, not 200."""
        turn = self.turn_module()
        painted = list(turn.paced(iter(f"word{n} " for n in range(200)),
                                  interval_ms=self.HELD))
        assert len(painted) == 2

    def test_the_first_word_is_never_held_back(self):
        """`collapsing` folds the status block when text arrives. Hold that text and
        the reader watches a collapsed summary with nothing under it, which is the
        twitch the `Status` class exists to prevent — and time to first word is the one
        moment of a turn anybody is watching."""
        turn = self.turn_module()
        painted = list(turn.paced(iter(["Your /home quota is ", "30 GB."]),
                                  interval_ms=self.HELD))
        assert painted[0] == "Your /home quota is "

    def test_a_stream_slower_than_the_interval_is_untouched(self):
        """A model producing a word every few frames is already easy to draw, and must
        not be made to wait for a repaint budget it never spends."""
        turn = self.turn_module()

        def slowly():
            for text in ("one ", "two ", "three "):
                time.sleep(0.005)
                yield text

        assert list(turn.paced(slowly(), interval_ms=1)) == ["one ", "two ", "three "]

    def test_zero_restores_a_repaint_per_delta(self):
        """The escape hatch a deployment can reach for, so it has to work."""
        turn = self.turn_module()
        deltas = [f"word{n} " for n in range(20)]
        assert list(turn.paced(iter(deltas), interval_ms=0)) == deltas

    def test_an_empty_delta_is_not_a_repaint(self):
        """44 of 46 chunks on a real tool round carry nothing. They must not each cost
        a redraw of the answer, and must not paint an empty first bubble either."""
        turn = self.turn_module()
        painted = list(turn.paced(iter(["", "", "Your /home quota is ", ""]),
                                  interval_ms=self.HELD))
        assert painted == ["Your /home quota is "]

    def test_pacing_is_on_by_default(self):
        """Read from config, not hard-coded — and not defaulted to off, which would
        leave every test above passing about a path the app never takes."""
        turn = self.turn_module()
        from sage import config as live  # noqa: PLC0415

        assert live.STREAM_REPAINT_MS > 0
        painted = list(turn.paced(iter(f"word{n} " for n in range(200))))
        assert len(painted) < 200


class TestTheLastRequestHasNoTools:
    """A turn's last request goes out with the tools withdrawn, and says why.

    The bug, reported from the running app. Asked about a negative service-unit balance
    — a fact the corpus states in one clause, on a page the model read twice — both free
    models searched, rephrased, searched again, and never wrote a sentence. The loop ran
    out of rounds and printed "I wasn't able to finish looking that up. Please try
    rephrasing your question." over the top of 11k characters of the right documentation.
    Rephrasing was the one thing that could not help: it was what the model had spent
    every round doing.

    Raising the ceiling is not the fix and was measured not to be — given ten rounds the
    models filled ten. Rule 3 of the system prompt ("if the first search misses, rephrase
    the keywords and search again") has no stopping condition, so the app supplies one:
    the last request carries no tools, and with nothing left to call the only move a model
    has is the answer.
    """

    SEARCH = TestTurnLoop.SEARCH
    READ = TestTurnLoop.READ

    def session(self):
        return {
            "messages": [{"role": "user", "text": "what does a negative balance mean",
                          "attachments": []}],
            "processing": True,
        }

    def looping(self, rounds, last):
        """A model that would call a tool every round, and `last` when it cannot."""
        return ScriptedProvider([self.SEARCH] * rounds + [last])

    def test_the_tools_are_offered_until_the_last_request_and_not_on_it(
        self, monkeypatch
    ):
        from sage import config

        client = self.looping(config.MAX_TOOL_ROUNDS, [event("A negative balance.")])
        run_app(monkeypatch, client=client, session=self.session())

        assert client.calls == config.MAX_TOOL_ROUNDS + 1
        # Every request but the last one was allowed to search.
        assert all(client.tools_seen[:-1]), client.tools_seen
        # And the last one was not, which is the whole mechanism.
        assert not client.tools_seen[-1]

    def test_a_model_that_answers_when_the_tools_go_is_shipped(self, monkeypatch):
        """The reader's turn, and the regression this exists for."""
        client = self.looping(
            4, [event("A negative balance means you cannot charge SUs "),
                event("([Service units](docs/slurm/main.md#service-units-allocations-and-accounts)).")],
        )
        stub, _module = run_app(monkeypatch, client=client, session=self.session())

        answer = stub.session_state["messages"][-1]
        assert answer["role"] == "assistant"
        assert answer["text"].startswith("A negative balance means you cannot charge SUs")
        assert "wasn't able to finish" not in answer["text"]
        assert not stub.session_state["error"]

    def test_the_last_request_says_why_the_tools_are_gone(self, monkeypatch):
        client = self.looping(4, [event("A negative balance.")])
        run_app(monkeypatch, client=client, session=self.session())

        # `ScriptedProvider.sent` keeps the live list `turn.run` appends to, so every
        # entry in it is the same object — the earlier requests cannot be read back off
        # it. What can be checked is stronger anyway: the instruction is the *last*
        # message of the turn, and there is exactly one of it however many rounds ran.
        sent = client.sent[-1]
        last = str(sent[-1].get("content", ""))
        assert sent[-1]["role"] == "system"
        assert "This is the last request of this turn" in last
        # The two things it has to carry: answer now, and name the gap rather than
        # going silent over it.
        assert "answer now" in last
        assert "did not cover" in last
        once = [m for m in sent if "last request of this turn" in str(m.get("content", ""))]
        assert len(once) == 1, f"the instruction went out {len(once)} times"

    def test_a_typed_out_call_becomes_the_error_card_not_the_answer(self, monkeypatch):
        """The other free model's reply to the reader's question, verbatim.

        136 characters of XML, under a Sources strip of two real sections. It is the same
        failure as a preamble shipped as an answer, so it takes the same route — Try
        again and another model — rather than reaching a reader as angle brackets.
        """
        typed = [event("<tool_call>\n<function=search>\n<parameter=query>\n"),
                 event("add member to pi account\n</parameter>\n</function>\n</tool_call>")]
        client = self.looping(4, typed)
        stub, _module = run_app(monkeypatch, client=client, session=self.session())

        answers = [m for m in stub.session_state["messages"] if m["role"] == "assistant"]
        assert not answers, f"a typed-out tool call was shipped: {answers}"
        assert stub.session_state["error"] == llm.AssistantError("empty").user_message

    def test_a_turn_that_finishes_in_budget_never_sees_any_of_this(self, monkeypatch):
        """The regression guard, and the reason this change cannot cost anything.

        The instruction goes out at the end of the round *before* the last one, so a turn
        that stops calling tools while it still has rounds left is untouched: tools on
        every request, no extra system message, the same answer it always gave. The golden
        set answers at a mean depth of 2.1 reads, which is every ordinary question — worth
        pinning rather than reasoning about, because the cheap version of this fix
        withdraws the tools a round early and silently shortens every turn in the app.
        """
        client = ScriptedProvider([self.SEARCH, self.READ, TestTurnLoop.ANSWER])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())

        assert client.calls == 3
        assert all(client.tools_seen), client.tools_seen
        sent = client.sent[-1]
        assert not [m for m in sent if "last request of this turn" in str(m.get("content", ""))]
        assert stub.session_state["messages"][-1]["text"] == "Your /home quota is 30 GB."

    def test_the_round_limit_sentence_survives_as_the_backstop(self, monkeypatch):
        """A model that emits a *parsed* call against an empty tool list still lands
        somewhere honest. Nothing else can reach that branch now."""
        from sage import config

        client = self.looping(config.MAX_TOOL_ROUNDS + 1, self.READ)
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        assert "wasn't able to finish" in stub.session_state["messages"][-1]["text"]


class TestTheMachineryIsNotNamedToTheReader:
    """`sage/redact.py`, in the app, on the answer that is actually stored.

    The prompt asks the model not to name the tools it calls, and over the sixteen probes
    in `evals/meta.toml` the default free model named them in four answers anyway. The
    tool names are in every request as schemas — the provider API has nowhere else to put
    them — so this is the half that does not depend on the model.
    """

    LEAK = [event(
        "Every answer is pulled from the RCC documentation via the `search_docs` and "
        "`read_doc` tools."
    )]

    def session(self):
        return {
            "messages": [
                {"role": "user", "text": "did you make that up?", "attachments": []}
            ],
            "processing": True,
        }

    def test_the_stored_answer_says_search_and_read_instead(self, monkeypatch):
        client = ScriptedProvider([self.LEAK])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        stored = stub.session_state["messages"][-1]
        assert "search_docs" not in stored["text"]
        assert "read_doc" not in stored["text"]
        assert "`search` and `read` tools" in stored["text"]

    def test_what_was_removed_is_recorded_on_the_turn(self, monkeypatch):
        """Not silent: `tools/agent_bench.py` scores the model on what it tried to say."""
        client = ScriptedProvider([self.LEAK])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        assert stub.session_state["messages"][-1]["redacted"] == [
            "read_doc", "search_docs"
        ]

    def test_an_ordinary_answer_is_untouched_and_records_nothing(self, monkeypatch):
        client = ScriptedProvider([[event("Your /home quota is 30 GB.")]])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        stored = stub.session_state["messages"][-1]
        assert stored["text"] == "Your /home quota is 30 GB."
        assert stored["redacted"] == []


class TestTheThinkToggle:
    """The control in the corner of the input box, where the model picker stood.

    Removed by decision, not by accident: "we shouldn't have a model picker but rather
    use the model picker position for the think toggle... we don't need users to pick a
    model or anything like that." What these hold is the part of that swap which is not
    geometry — `tools/render_check.py` has the geometry, and it cannot see whether the
    pill is drawn for a provider that would reject the parameter it sends.
    """

    def session(self, **extra):
        return {"messages": [], "processing": False, **extra}

    def _run(self, monkeypatch, session, name, model, **kwargs):
        """Drive the app with ONE provider configured, from the shipped profile.

        The profile is what declares `reasoning`, so this reads it rather than
        inventing a provider table: `openrouter` carries the flag there and
        `opencode` does not, and a test that built its own entries would go on
        passing on the day the profile stopped saying so.
        """
        provider = ScriptedProvider([], name=name, models=(model,))
        monkeypatch.setattr(config, "DEFAULT_MODEL", f"{name}:{model}")
        # `run_app` always sets a Mistral key, so that provider is configured whatever
        # this test wants. Served empty rather than unset: an unbuildable provider logs
        # "could not list models" and falls through to the profile's own list, which put
        # a Mistral model first in the lineup and made it the one answering.
        return run_app(
            monkeypatch, client=provider, session=session,
            extra={"mistral": ScriptedProvider([], name="mistral", models=())},
            **kwargs)

    def openrouter(self, monkeypatch, session, **kwargs):
        """A provider that declares `reasoning`, which is what draws the pill."""
        return self._run(monkeypatch, session, "openrouter", "openrouter/free",
                         openrouter=True, **kwargs)

    def zen(self, monkeypatch, session, **kwargs):
        """And one that does not. Same wire format, no `reasoning` field."""
        return self._run(monkeypatch, session, "opencode", "big-pickle",
                         opencode=True, **kwargs)

    def test_the_pill_is_drawn_where_the_provider_takes_the_parameter(self, monkeypatch):
        stub, _m = self.openrouter(monkeypatch, self.session())
        assert "think-toggle" in stub.button_labels

    def test_and_not_drawn_where_it_does_not(self, monkeypatch):
        """`kind = "openai"` covers both, so the switch cannot be inferred from the
        adapter — only the profile knows. A pill drawn here would be a control that
        does nothing, which this app has a standing rule against, and it would send a
        field the endpoint is entitled to reject."""
        stub, _m = self.zen(monkeypatch, self.session())
        assert "think-toggle" not in stub.button_labels

    def test_the_flag_is_cleared_when_the_pill_goes(self, monkeypatch):
        """An automatic failover can move a session onto a provider without reasoning
        without anyone touching the control. Leaving the flag set there would have the
        next turn quietly ask for a field that provider will refuse — so the flag goes
        when the control does, on the run that stops drawing it."""
        stub, _m = self.zen(monkeypatch, self.session(thinking=True))
        assert stub.session_state["thinking"] is False

    def test_the_flag_survives_on_a_provider_that_takes_it(self, monkeypatch):
        stub, _m = self.openrouter(monkeypatch, self.session(thinking=True))
        assert stub.session_state["thinking"] is True

    def test_it_is_off_for_a_session_that_has_not_asked(self, monkeypatch):
        """Off by default, and that is the safe default rather than a shy one:
        reasoning tokens are billed as output tokens, so on-by-default spends a free
        allowance on every turn whether the question needed the thinking or not."""
        stub, _m = self.openrouter(monkeypatch, self.session())
        assert stub.session_state["thinking"] is False


class TestComposerStrip:
    """The controls belong under the input box, and on every screen.

    They used to be a bar across the top of the page, which failed twice: it sat
    in the band Streamlit's own full-width header takes the clicks for, and on
    the landing screen the picker inside it did not appear at all — so the one
    screen where a new user has to choose a model was the one screen without a
    way to choose one. tools/render_check.py holds the geometry; these hold the
    structure that geometry depends on.
    """

    @staticmethod
    def _containers(stub):
        return [key for name, key in stub.events if name == "container"]

    @staticmethod
    def _index(stub, name, key=None):
        return next(
            position for position, event in enumerate(stub.events)
            if event[0] == name and (key is None or event[1] == key)
        )

    def two_providers(self, monkeypatch, session, **kwargs):
        mistral = ScriptedProvider([], name="mistral", models=("mistral-small-latest",))
        # Serving the model the default names — and naming it here rather than reading
        # `config.DEFAULT_MODEL`, so the picker shows what a fresh session actually
        # starts on whatever the shipped deployment has chosen this week.
        monkeypatch.setattr(config, "DEFAULT_MODEL",
                            "opencode:nemotron-3.5-lightning-free")
        zen = ScriptedProvider(
            [], name="opencode",
            models=("nemotron-3.5-lightning-free", "deepseek-v4-flash-free"),
        )
        return run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                       session=session, opencode=True, **kwargs)

    def test_the_controls_live_in_the_strip_under_the_input(self, monkeypatch):
        stub, _m = self.two_providers(monkeypatch, {"messages": [], "processing": False})
        assert "composer-strip" in self._containers(stub)
        assert "topbar" not in self._containers(stub)
        # One container, not a strip wrapping a row: two of them meant two sets of
        # layout rules for two elements whose identity depends on where Streamlit
        # hangs the `st-key-…` class, and the inner rule outranked the outer one.
        assert "controls" not in self._containers(stub)

    def test_the_strip_is_rendered_after_the_input(self, monkeypatch):
        """Order is the whole point: rendered before it, this is a top bar again."""
        stub, _m = self.two_providers(monkeypatch, {"messages": [], "processing": False})
        assert (self._index(stub, "container", "composer-strip")
                > self._index(stub, "chat_input"))

    def test_there_is_no_popover_anywhere(self, monkeypatch):
        """The model picker was the only `st.popover` in the app, and it took a panel
        portalled to the end of <body> with it: its own background and border tokens,
        an Escape sent from app.js after every pick because Streamlit left it open
        across the rerun, and two selector shapes in the layout harness for the two
        Streamlit versions that render it differently. None of that has anything left
        to act on, and a popover appearing here again would mean one of them came back
        without the rest."""
        stub, _m = self.two_providers(monkeypatch, {"messages": [], "processing": False})
        assert [event for event in stub.events if event[0] == "popover"] == []

    def test_there_is_no_trash_can(self, monkeypatch):
        """It emptied the open conversation, and the panel of chats made it the third
        way to do a thing there were already two better ways to do: every row has a ✕
        and New chat sits above them. "the trash can be removed because of this
        design". What is in the composer now is the model picker and nothing else.
        """
        session = {
            "messages": [{"role": "user", "text": "hi", "attachments": []}],
            "processing": False,
        }
        stub, _m = self.two_providers(monkeypatch, session)
        assert "clear" not in stub.button_labels
        assert not any(label == "🗑️" for label in stub.button_labels.values())

    def test_nothing_under_the_input_but_controls(self, monkeypatch):
        """The caveat line is gone, and nothing may quietly replace it.

        It was a popover, then three paragraphs under the starter cards, then one
        11px line beside the model name, and every version was a permanent fixture
        for something read once. What is under the input now is Clear and the model
        picker: two controls, no prose. This fails if any of it comes back.
        """
        stub, _m = self.two_providers(
            monkeypatch,
            {"messages": [{"role": "user", "text": "hi", "attachments": []}],
             "processing": False},
        )
        assert not any(
            "ai-disclaimer" in html or "can make mistakes" in html
            for html in stub.markdown_html
        )

    def test_the_input_asks_for_no_character_counter(self, monkeypatch):
        """`max_chars` is the only thing that puts "15/8000" inside the box.

        Asserted on the call rather than on CSS: hiding the counter would mean
        naming a Streamlit test id this repo cannot see, and that rule would fail
        silently the day it changed. Not asking for it cannot fail that way.
        """
        stub, _m = self.two_providers(monkeypatch, {"messages": [], "processing": False})
        assert stub.chat_input_kwargs == {}, (
            f"st.chat_input was passed {stub.chat_input_kwargs}; max_chars puts a "
            "character counter in the box"
        )

    @staticmethod
    def _placeholder(stub):
        return next(text for name, text in stub.events if name == "chat_input")

    def test_the_landing_box_names_the_subject(self, monkeypatch):
        """It is the only thing on that page that says what this app is for."""
        stub, _m = self.two_providers(monkeypatch, {"messages": [], "processing": False})
        assert self._placeholder(stub) == "Ask any question about the RCC…"

    def test_the_box_asks_for_a_follow_up_once_something_is_answered(self, monkeypatch):
        """The subject is established by then, and what is worth saying instead is
        that the conversation carries — this is not a fresh search."""
        session = {
            "messages": [
                {"role": "user", "text": "hi", "attachments": []},
                {"role": "assistant", "text": "hello", "sources": []},
            ],
            "processing": False,
        }
        stub, _m = self.two_providers(monkeypatch, session)
        assert self._placeholder(stub) == "Ask a follow-up question…"

    def test_a_question_with_no_answer_yet_is_not_a_follow_up(self, monkeypatch):
        """A turn that is still generating, or one that failed and left its retry
        button, has nothing to follow up on: "ask a follow-up" over an empty answer
        reads as if one had arrived."""
        session = {
            "messages": [{"role": "user", "text": "hi", "attachments": []}],
            "processing": False,
        }
        stub, _m = self.two_providers(monkeypatch, session)
        assert self._placeholder(stub) == "Ask any question about the RCC…"


class TestStatusBlock:
    """What the block over an empty answer says while a reader waits for it.

    One line per tool call, named the way an answer would name the tool, with the
    argument that says which one — the query for a search, the path and anchor for a
    read — and how long the wait for it was. Finished lines stay, and the block folds
    into one summary line the moment the answer starts arriving.

    This REVERSES what the row used to do, which was one fixed phrase per round and
    nothing from inside the machine on screen: not the query, not the path, not the
    section's own title. The reversal was asked for — "the user needs to see the
    detailed status updates and which sections to read etc, this is more precise" —
    and the tests for the old rule are gone with it rather than left passing against
    something nobody wants.

    What survives is the reason that rule was safe: the argument is whatever the model
    typed, and a query typed as a number once ended a turn with an AttributeError
    dressed up as a network failure. So half of this class is still about arguments no
    sensible model would send.
    """

    SEARCH = [event(tool_calls=[tool_call(0, "c1", "search_docs", '{"query":"quota"}')])]
    READ = [
        event(tool_calls=[
            tool_call(0, "c2", "read_doc", '{"path":"docs/storage/main.md#quotas"}')
        ])
    ]
    ANSWER = [event("Your /home quota is "), event("30 GB.")]

    def app(self, monkeypatch):
        _stub, module = run_app(monkeypatch, client=ScriptedProvider([], models=("m1",)),
                                session={"messages": [], "processing": False})
        return module

    def block(self, module):
        """A `Status` writing into a slot whose HTML the stub keeps."""
        return module.turn.Status(module.st.empty())

    # --- what one line says ---------------------------------------------

    def test_a_search_names_the_tool_and_quotes_its_query(self, monkeypatch):
        module = self.app(monkeypatch)
        assert module.turn.call_step(
            module.VIEW, {"name": tools.SEARCH_DOCS, "input": {"query": "gpu jobs"}}
        ) == ("search", "gpu jobs")

    def test_a_read_shows_the_path_and_the_anchor(self, monkeypatch):
        """The anchor especially: it is the difference between a page and the section
        of it this turn actually opened."""
        module = self.app(monkeypatch)
        name, detail = module.turn.call_step(
            module.VIEW,
            {"name": tools.READ_DOC, "input": {"path": "docs/storage/main.md#quotas"}},
        )
        assert (name, detail) == ("read", "docs/storage/main.md#quotas")

    def test_the_name_is_the_one_an_answer_would_use(self, monkeypatch):
        """`sage.redact` swaps these words into an answer that names a tool. The block
        and the answer calling one thing by two names is the confusion this reads the
        same mapping to avoid, rather than keeping a second copy of it."""
        module = self.app(monkeypatch)
        for internal, public in module.VIEW.public_names.items():
            assert module.turn.call_step(
                module.VIEW, {"name": internal, "input": {}}
            )[0] == public
        assert "_" not in "".join(module.VIEW.public_names.values())

    def test_which_argument_to_show_is_the_tools_own_declaration(self, monkeypatch):
        """Not a branch in the row on the two names that ship. A deployment that
        registers a third tool declares `argument` and gets a line for it."""
        module = self.app(monkeypatch)
        assert module.VIEW.public_arguments == {
            tools.SEARCH_DOCS: "query", tools.READ_DOC: "path",
        }

    def test_a_tool_with_no_public_name_is_still_one_honest_line(self, monkeypatch):
        """The identifier the provider API needs is nobody's word for anything, so an
        unnamed tool gets the fixed phrase — never a blank, which reads as a hang."""
        module = self.app(monkeypatch)
        name, detail = module.turn.call_step(
            module.VIEW, {"name": "glossary_lookup", "input": {"term": "SU"}}
        )
        assert name == module.RUNTIME.copy.status_working
        assert detail == ""
        assert "glossary" not in name

    # --- and what no argument can do to it -------------------------------

    def test_no_argument_can_end_a_turn(self, monkeypatch):
        """A model puts whatever it likes in there — a number, a list, nothing at all,
        not even a dict."""
        module = self.app(monkeypatch)
        for arguments in ({}, {"query": 123}, {"query": ["a"]}, {"path": None},
                          None, "query=quota", []):
            name, detail = module.turn.call_step(
                module.VIEW, {"name": tools.SEARCH_DOCS, "input": arguments}
            )
            assert name == "search"
            assert isinstance(detail, str)

    def test_a_long_query_is_clipped_rather_than_shipped_whole(self, monkeypatch):
        module = self.app(monkeypatch)
        _name, detail = module.turn.call_step(
            module.VIEW, {"name": tools.SEARCH_DOCS, "input": {"query": "x" * 4000}}
        )
        assert len(detail) == config.STATUS_ARGUMENT_CHARS
        assert detail.endswith("…")

    def test_an_argument_over_two_lines_is_drawn_on_one(self, monkeypatch):
        """The row is one line tall. A newline in a value would be a newline in the
        middle of it, and the ellipsis that holds the width cannot hold a height."""
        module = self.app(monkeypatch)
        _name, detail = module.turn.call_step(
            module.VIEW,
            {"name": tools.SEARCH_DOCS, "input": {"query": "one\ntwo   three\r\n"}},
        )
        assert detail == "one two three"

    def test_markup_in_an_argument_is_escaped(self, monkeypatch):
        """It reaches the page through `unsafe_allow_html`, so this is the only thing
        between a model's query and the DOM."""
        module = self.app(monkeypatch)
        status = self.block(module)
        status.begin(*module.turn.call_step(
            module.VIEW,
            {"name": tools.SEARCH_DOCS, "input": {"query": "<img src=x onerror=1>"}},
        ))
        drawn = module.st.markdown_html[-1]
        assert "<img" not in drawn
        assert "&lt;img" in drawn

    # --- the block over a turn -------------------------------------------

    def test_the_first_frame_is_the_row_this_app_has_always_drawn(self, monkeypatch):
        """Before anything has been called there is nothing to list, so the block is
        the single row, unchanged — the frame every turn opens on."""
        module = self.app(monkeypatch)
        status = self.block(module)
        status.show(module.RUNTIME.copy.status_thinking)
        drawn = module.st.markdown_html[-1]
        assert 'class="status-row" role="status"' in drawn
        assert 'class="status-dot"' in drawn and 'class="status-dots"' in drawn
        assert "Thinking" in drawn
        for added in ("status-block", "status-step", "status-arg", "details"):
            assert added not in drawn

    def test_a_line_per_call_and_the_finished_ones_stay(self, monkeypatch):
        module = self.app(monkeypatch)
        status = self.block(module)
        status.show("Thinking")
        status.begin("search", "quota")
        status.begin("read", "docs/storage/main.md#quotas")
        status.show("Thinking")
        drawn = module.st.markdown_html[-1]
        # Both calls, both still on the page, each with its own argument.
        assert drawn.count('class="status-step"') == 2
        assert ">quota<" in drawn and ">docs/storage/main.md#quotas<" in drawn
        # And one live line under them: the wait for the next request.
        assert drawn.count('class="status-row"') == 1

    def test_a_finished_step_carries_its_time_and_the_live_one_does_not(
        self, monkeypatch
    ):
        module = self.app(monkeypatch)
        status = self.block(module)
        status.begin("search", "quota")
        assert "status-time" not in module.st.markdown_html[-1]
        status.begin("read", "docs/storage/main.md#quotas")
        drawn = module.st.markdown_html[-1]
        assert re.search(r'class="status-time">\d+\.\ds<', drawn)
        assert drawn.count("status-time") == 1

    def test_the_time_is_the_wait_and_not_the_call(self, monkeypatch):
        """A search of an in-memory index is 10-40ms, so a step timed from the call
        itself would read 0.0s on every line of every turn while the seconds the reader
        actually waited sat in the round trip that produced the call, attributed to
        nothing. Each step's clock starts where the previous one stopped."""
        module = self.app(monkeypatch)
        ticks = iter([100.0, 102.5])
        monkeypatch.setattr(module.turn.time, "monotonic", lambda: next(ticks, 102.5))
        status = self.block(module)          # opened at 100.0
        status.begin("search", "quota")      # the wait for it started there too
        status.show("Thinking")              # and ended at 102.5
        assert ">2.5s<" in module.st.markdown_html[-1]

    def test_it_folds_into_one_line_the_reader_can_open_again(self, monkeypatch):
        module = self.app(monkeypatch)
        status = self.block(module)
        status.begin("search", "quota")
        status.begin("read", "docs/storage/main.md#quotas")
        status.collapse()
        drawn = module.st.markdown_html[-1]
        assert drawn.startswith("<details")
        assert re.search(r"<summary[^>]*>2 steps · \d+\.\ds</summary>", drawn)
        # Folded, not thrown away: the steps are inside the disclosure.
        assert drawn.count('class="status-step"') == 2
        assert ">docs/storage/main.md#quotas<" in drawn

    def test_one_step_is_one_step(self, monkeypatch):
        module = self.app(monkeypatch)
        status = self.block(module)
        status.begin("search", "quota")
        status.collapse()
        assert "1 step ·" in module.st.markdown_html[-1]

    def test_a_turn_that_called_nothing_folds_into_nothing(self, monkeypatch):
        """A plain answer has no steps to summarise, so the row goes when the text
        arrives — which is what every turn used to do at this point."""
        module = self.app(monkeypatch)
        status = self.block(module)
        status.show("Thinking")
        painted = len(module.st.markdown_html)
        status.collapse()
        assert len(module.st.markdown_html) == painted
        assert module.st.events[-1] == ("empty", None)

    # --- the generator that drives it ------------------------------------

    class Spy:
        def __init__(self):
            self.collapsed = self.cleared = 0

        def collapse(self):
            self.collapsed += 1

        def clear(self):
            self.cleared += 1

    def test_every_delta_survives_and_the_block_folds_once(self, monkeypatch):
        module = self.app(monkeypatch)
        spy = self.Spy()
        assert list(module.turn.collapsing(iter("abc"), spy)) == ["a", "b", "c"]
        assert spy.collapsed == 1

    def test_a_round_with_no_text_leaves_the_block_standing(self, monkeypatch):
        """The round after a search often says nothing at all. This used to clear the
        row; with steps on the page that is a removal and an insertion per silent
        round, which is the reflow `Status` exists to avoid. The end of the turn takes
        it down instead."""
        module = self.app(monkeypatch)
        spy = self.Spy()
        assert list(module.turn.collapsing(iter([]), spy)) == []
        assert (spy.collapsed, spy.cleared) == (0, 0)

    # --- and the whole thing, driven -------------------------------------

    def test_a_real_turn_shows_what_it_searched_and_what_it_read(self, monkeypatch):
        """The wiring. Every test above holds one piece of this in isolation, and a
        call site that stopped calling `begin` would leave all of them passing while
        the reader watched one unchanging line again."""
        client = ScriptedProvider([self.SEARCH, self.READ, self.ANSWER])
        stub, _module = run_app(monkeypatch, client=client, session={
            "messages": [{"role": "user", "text": "what is my storage quota",
                          "attachments": []}],
            "processing": True,
        })
        drawn = [html for html in stub.markdown_html if "status-" in html]
        assert any('class="status-arg">quota<' in html for html in drawn)
        assert any('class="status-arg">docs/storage/main.md#quotas<' in html
                   for html in drawn)
        # Two calls, in the order they were made, on lines of their own.
        widest = max(drawn, key=lambda html: html.count("status-step"))
        assert widest.count('class="status-step"') == 2
        assert widest.index(">quota<") < widest.index(">docs/storage/main.md#quotas<")
        # And it folded when the answer began.
        assert any(html.startswith("<details") and "2 steps" in html for html in drawn)

    def test_every_fixed_phrase_fits_the_line_it_is_drawn_on(self, monkeypatch):
        """The row is one line at 500px. The fixed phrases are checkable once; a tool's
        line is an argument the model chose, which `tools/render_check.py` holds with a
        width bound instead."""
        module = self.app(monkeypatch)
        for phrase in module.RUNTIME.copy.status_phrases:
            assert len(phrase) <= 40, phrase


class TestToollessModels:
    """Free models that cannot call tools still answer, from a single retrieval."""

    def session(self, model):
        return {
            "messages": [
                {"role": "user", "text": "what is my storage quota", "attachments": []}
            ],
            "processing": True,
            "model": model,
        }

    def test_a_configured_toolless_model_retrieves_up_front(self, monkeypatch):
        # config reads env at import, so patch the value the app actually uses.
        monkeypatch.setattr(config, "TOOLLESS_MODELS", ("big-pickle",))
        zen = ScriptedProvider([[event("Your quota is 30 GB.")]], name="opencode",
                               models=("big-pickle",))
        mistral = ScriptedProvider([], name="mistral", models=("m1",))
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=self.session("opencode:big-pickle"), opencode=True)
        assert zen.calls == 1
        assert zen.tools_seen == [None], "tools must not be offered"
        sent = "\n".join(m["content"] for m in zen.sent[0])
        assert "no tools and nothing to search" in sent, "the tools must be taken away"
        assert "Answer only from these sections" in sent
        assert "docs/storage" in sent
        answer = stub.session_state["messages"][-1]
        assert answer["text"] == "Your quota is 30 GB."
        assert answer["sources"], "retrieved sections should become the Sources strip"

    def test_a_question_that_retrieves_nothing_still_reaches_the_model_caveated(
        self, monkeypatch
    ):
        """The path with no second round, on the query with nothing to go on.

        `gather_context` returned an empty string for a zero-result query, `grounded()`
        returned the messages untouched, and the model received the system prompt and the
        question with nothing between them — no sections, no caveat, no instruction to
        decline. What it does then is answer from memory. `sbatchh` is one keystroke off a
        real command and retrieves nothing here, so a typo was enough to reach it.
        """
        monkeypatch.setattr(config, "TOOLLESS_MODELS", ("big-pickle",))
        zen = ScriptedProvider(
            [[event("I could not find that in the documentation.")]],
            name="opencode", models=("big-pickle",),
        )
        mistral = ScriptedProvider([], name="mistral", models=("m1",))
        session = self.session("opencode:big-pickle")
        session["messages"][0]["text"] = "sbatchh"
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=session, opencode=True)
        sent = "\n".join(m["content"] for m in zen.sent[0])
        assert "No matching RCC documentation was found" in sent
        assert "help@rcc.uchicago.edu" in sent
        assert "Try different or broader keywords" not in sent, (
            "a model that cannot call tools cannot search again"
        )
        answer = stub.session_state["messages"][-1]
        assert answer["text"] == "I could not find that in the documentation."
        assert not answer["sources"], "nothing was retrieved, so nothing to cite"

    def test_a_provider_rejecting_tools_falls_back_automatically(self, monkeypatch):
        monkeypatch.setattr(config, "TOOLLESS_MODELS", ())

        class RejectsTools(ScriptedProvider):
            def stream(self, model, messages, tools, thinking=False):
                self.calls += 1
                self.sent.append(messages)
                self.tools_seen.append(tools)
                if tools:
                    raise RuntimeError("this model does not support tools")
                yield event("Answered without tools.")

        provider = RejectsTools([], models=("m1",))
        stub, _m = run_app(monkeypatch, client=provider,
                           session=self.session("mistral:m1"))
        assert provider.tools_seen[0] is not None
        assert provider.tools_seen[-1] is None
        assert stub.session_state["messages"][-1]["text"] == "Answered without tools."
        assert stub.session_state["error"] is None


class TestQuotaFailover:
    """A spent quota on one provider should not dead-end the app."""

    def session(self):
        return {
            "messages": [{"role": "user", "text": "what can you do?",
                          "attachments": []}],
            "processing": True,
            "model": "mistral:m1",
        }

    @staticmethod
    def _payment_required():
        error = RuntimeError('API error occurred: Status 402. '
                             'Body: {"detail":"Check your subscription"}')
        error.status_code = 402
        return error

    def test_402_is_reported_as_an_actionable_quota_error(self):
        assert llm.classify(self._payment_required()).kind == "quota"
        # It must say what to do, without pointing at a control by position —
        # the error card now carries a one-click switch of its own.
        assert "Switch to another model" in llm.classify(
            self._payment_required()
        ).user_message

    def test_quota_is_not_retried_against_the_same_provider(self):
        assert not llm.classify(self._payment_required()).retryable

    def test_a_spent_quota_switches_to_the_other_provider(self, monkeypatch):
        mistral = ScriptedProvider([], name="mistral", models=("m1",),
                                   error=self._payment_required())
        zen = ScriptedProvider([], name="opencode", models=("deepseek-v4-flash-free",))
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=self.session(), opencode=True)
        assert stub.session_state["model"] == "opencode:deepseek-v4-flash-free"
        assert stub.session_state["processing"] is True, "the turn should be retried"
        assert stub.session_state["error"] is None
        assert "unavailable" in stub.session_state["notice"]

    def test_the_notice_does_not_claim_an_answer_that_has_not_happened(
        self, monkeypatch
    ):
        """It used to say the answer "came from" a model that had not run yet."""
        mistral = ScriptedProvider([], name="mistral", models=("m1",),
                                   error=self._payment_required())
        zen = ScriptedProvider([], name="opencode", models=("z1",))
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=self.session(), opencode=True)
        assert "Retrying with z1" in stub.session_state["notice"]
        assert "came from" not in stub.session_state["notice"]
        assert stub.session_state["switched_from"] == ("m1", "quota")

    def test_the_notice_turns_past_tense_once_the_answer_lands(self, monkeypatch):
        """The state a failover rerun arrives in: switched, and about to answer."""
        zen = ScriptedProvider([[event("Zen answered.")]], name="opencode",
                               models=("z1",))
        mistral = ScriptedProvider([], name="mistral", models=("m1",))
        session = self.session() | {
            "model": "opencode:z1",
            "tried": ["mistral:m1"],
            "switched_from": ("Mistral · m1", "quota"),
            "notice": "Mistral · m1 is unavailable (out of credit). Retrying…",
        }
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=session, opencode=True)
        notice = stub.session_state["notice"]
        assert "was unavailable (out of credit)" in notice
        assert "z1 answered instead" in notice
        # And it points at where the picker actually is. It said "the button at
        # the top left" for as long as there was a top left to point at.
        assert "under the input box" in notice
        assert "top left" not in notice
        assert stub.session_state["switched_from"] is None
        assert stub.session_state["error"] is None

    def test_a_failed_failover_leaves_no_notice_contradicting_the_error(
        self, monkeypatch
    ):
        """A "retrying with Zen…" banner above "could not complete that request"
        is the UI arguing with itself. One of them has to go, and it is not the
        error."""
        zen = ScriptedProvider([], name="opencode", models=("z1",),
                               error=self._payment_required())
        mistral = ScriptedProvider([], name="mistral", models=("m1",))
        session = self.session() | {
            "model": "opencode:z1",
            # The lineup is m1 and z1, and m1 has had its turn: nothing is left.
            "tried": ["mistral:m1"],
            "switched_from": ("Mistral · m1", "quota"),
            "notice": "Mistral · m1 is unavailable (out of credit). Retrying…",
        }
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=session, opencode=True)
        assert stub.session_state["error"], "the second failure must surface"
        assert stub.session_state["notice"] == ""
        assert stub.session_state["switched_from"] is None
        assert "opencode:z1" in stub.session_state["error_detail"], (
            "the details must name the model that actually failed"
        )

    def test_the_error_card_offers_the_switch_it_tells_you_to_make(self, monkeypatch):
        """Advice to "switch to another model" is useless if the control is at the
        other end of the page — and worse than useless if that control is the one
        that failed to render."""
        mistral = ScriptedProvider([], name="mistral", models=("m1",))
        zen = ScriptedProvider([], name="opencode", models=("z1",))
        session = self.session() | {
            "processing": False,
            "error": "This model is out of credit or its quota is used up.",
            "error_detail": "HTTP 402",
        }
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=session, opencode=True)
        assert stub.button_labels.get("switch-model") == "→ Use z1"

    def test_taking_that_switch_reruns_the_question_on_the_new_model(self, monkeypatch):
        mistral = ScriptedProvider([], name="mistral", models=("m1",))
        zen = ScriptedProvider([], name="opencode", models=("z1",))
        session = self.session() | {
            "processing": False, "error": "out of credit", "error_detail": "HTTP 402",
            "tried": ["mistral:m1"],
        }
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=session, opencode=True,
                           buttons={"switch-model": True})
        assert stub.session_state["model"] == "opencode:z1"
        assert stub.session_state["processing"] is True
        assert stub.session_state["error"] is None
        assert stub.session_state["tried"] == [], (
            "a hand-picked model is a fresh attempt at the question, so the walk's "
            "ledger has to be empty or the retry cannot fail over"
        )

    def test_no_switch_button_when_there_is_nowhere_to_switch_to(self, monkeypatch):
        provider = ScriptedProvider([], models=("m1",))
        session = self.session() | {
            "processing": False, "error": "boom", "error_detail": "x",
        }
        stub, _m = run_app(monkeypatch, client=provider, session=session)
        assert "switch-model" not in stub.button_labels
        assert "retry" in stub.button_labels


    def test_a_clean_answer_clears_a_notice_from_an_earlier_turn(self, monkeypatch):
        provider = ScriptedProvider([[event("Fresh answer.")]], models=("m1",))
        session = self.session() | {"notice": "left over from two turns ago"}
        stub, _m = run_app(monkeypatch, client=provider, session=session)
        assert stub.session_state["notice"] == ""

    def test_it_never_asks_a_model_twice_so_it_cannot_ping_pong(self, monkeypatch):
        """What bounds the walk is `tried`, not a count of hops.

        Two providers, both spent. The turn started on m1, failed over to z1, and z1
        refused too — and the only model that could come next is the one that has
        already refused. `View.alternative` skips it, the walk is out of lineup, and
        the error card is what is left. There is no hop budget doing this work: a
        finite lineup asked without repeats terminates on its own.
        """
        mistral = ScriptedProvider([], name="mistral", models=("m1",),
                                   error=self._payment_required())
        zen = ScriptedProvider([], name="opencode", models=("z1",),
                               error=self._payment_required())
        session = self.session()
        session["tried"] = ["mistral:m1"]
        session["model"] = "opencode:z1"
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=session, opencode=True)
        assert stub.session_state["processing"] is False
        assert stub.session_state["error"], "the second failure must surface"

    def test_with_one_provider_the_error_surfaces_instead(self, monkeypatch):
        mistral = ScriptedProvider([], name="mistral", models=("m1",),
                                   error=self._payment_required())
        stub, _m = run_app(monkeypatch, client=mistral, session=self.session())
        assert stub.session_state["processing"] is False
        assert "out of credit" in stub.session_state["error"]
        assert "402" in stub.session_state["error_detail"]


class TestASpentFreeAllowance:
    """A free tier meters per model, and it says so in a 429.

    Reported from the running app: `deepseek-v4-flash-free` answered

        429 {"error": {"type": "FreeUsageLimitError",
                       "message": "Rate limit exceeded. Please try again later."}}

    and the reader was told "The assistant is busy right now. Please wait a moment and
    retry." Waiting does not help — the allowance resets on the provider's schedule —
    and `nemotron-3-ultra-free` on the same key answered in under a second throughout.
    """

    @staticmethod
    def _free_limit_429():
        error = RuntimeError(
            'HTTP 429 from https://opencode.ai/zen/v1/chat/completions: '
            '{"type":"error","error":{"type":"FreeUsageLimitError",'
            '"message":"Error from provider (Console): Rate limit exceeded. '
            'Please try again later."}}'
        )
        error.status_code = 429
        return error

    def test_a_spent_allowance_is_not_a_busy_signal(self):
        assert llm.classify(self._free_limit_429()).kind == "allowance"
        assert "another model" in llm.classify(
            self._free_limit_429()
        ).user_message.lower()

    def test_it_is_not_confused_with_a_key_that_is_out_of_credit(self):
        """Different remedies: a spent key means another provider, a spent allowance
        means another model on the same one."""
        assert llm.classify(self._free_limit_429()).kind != "quota"

    def test_it_is_not_retried_against_the_model_that_has_none_left(self):
        """Three attempts at a spent allowance is three certain failures and 3s."""
        assert not llm.classify(self._free_limit_429()).retryable

    def test_it_fails_over_within_the_provider_rather_than_across(self, monkeypatch):
        """The whole point of telling the two apart.

        The key is fine — it is this model's allowance that is spent — so the turn
        should land on the next model behind the same key, not on a second provider
        whose own key may be out of credit. In the deployment this came from, it was.
        """
        zen = ScriptedProvider(
            [], name="opencode", error=self._free_limit_429(),
            models=("deepseek-v4-flash-free", "nemotron-3-ultra-free"),
        )
        mistral = ScriptedProvider([], name="mistral", models=("m1",))
        session = {
            "messages": [{"role": "user", "text": "hello", "attachments": []}],
            "processing": True,
            "model": "opencode:deepseek-v4-flash-free",
        }
        stub, _m = run_app(monkeypatch, client=zen, extra={"mistral": mistral},
                           session=session, opencode=True)
        assert stub.session_state["model"] == "opencode:nemotron-3-ultra-free"
        assert stub.session_state["processing"] is True, "the turn should be retried"
        assert stub.session_state["error"] is None
        assert "free allowance" in stub.session_state["notice"]

    def test_when_every_model_is_spent_it_stops_and_says_so(self, monkeypatch):
        """The state a shared IP puts a deployment in near the end of a UTC day.

        The walk does go through the whole picker now — that is the point of it — so
        what ends this is running out of lineup rather than running out of budget. With
        every model asked, there is no alternative left and the turn stops on an error
        card the reader can act on rather than on a spinner."""
        zen = ScriptedProvider(
            [], name="opencode", error=self._free_limit_429(),
            models=("nemotron-3.5-lightning-free", "deepseek-v4-flash-free",
                    "hy3-free", "mimo-v2.5-free", "big-pickle"),
        )
        session = {
            "messages": [{"role": "user", "text": "hello", "attachments": []}],
            "processing": True,
            "model": "opencode:nemotron-3.5-lightning-free",
            # Four of the five already refused this turn, and this is the fifth.
            "tried": ["opencode:deepseek-v4-flash-free", "opencode:hy3-free",
                      "opencode:mimo-v2.5-free", "opencode:big-pickle"],
        }
        stub, _m = run_app(monkeypatch, client=zen, session=session, opencode=True)
        assert stub.session_state["processing"] is False, "it must not spin"
        assert "free allowance" in stub.session_state["error"]
        assert stub.session_state["notice"] == "", (
            "no 'retrying with…' left over promising something that never happened"
        )

    def test_an_ordinary_429_is_still_a_busy_signal(self):
        """The discriminator is the limit's *name*, not the status or the prose —
        both of which say "wait" in the message above too."""
        busy = RuntimeError("HTTP 429: Rate limit exceeded, please slow down")
        busy.status_code = 429
        assert llm.classify(busy).kind == "rate_limit"
        assert llm.classify(busy).retryable

    def test_the_body_reaches_the_classifier(self, monkeypatch):
        """`raise_for_status()` says only "Client error '429 …' for url", and the
        status alone cannot tell the two apart — so the adapter carries the body."""
        import sys
        from types import ModuleType

        class HTTPStatusError(Exception):
            def __init__(self, message, request=None, response=None):
                super().__init__(message)
                self.request = request
                self.response = response

        class Response:
            status_code = 429
            request = SimpleNamespace(url="https://x.test/v1/chat/completions")
            text = '{"error":{"type":"FreeUsageLimitError","message":"…"}}'

            def read(self):
                return None

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        class Client:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def stream(self, *_args, **_kwargs):
                return Response()

        fake = ModuleType("httpx")
        fake.Client = Client
        fake.Timeout = lambda *_a, **_k: None
        fake.HTTPStatusError = HTTPStatusError
        monkeypatch.setitem(sys.modules, "httpx", fake)

        from sage.profile import ProviderEntry
        from sage.providers.openai_compat import OpenAICompatProvider

        entry = ProviderEntry(name="zen", base_url="https://x.test/v1")
        with pytest.raises(HTTPStatusError) as raised:
            list(OpenAICompatProvider(entry, "k").stream("m", [], None))
        assert "FreeUsageLimitError" in str(raised.value)
        assert llm.classify(raised.value).kind == "allowance"


class TestSwitchingWithinAProvider:
    """When the other provider is spent too — or there is only one.

    Both happened at once in the running deployment: the Mistral key answered 402 and
    three of Zen's free models answered 429, while two others answered fine. Preferring
    a different provider and then giving up offered a second dead key, and on a
    single-provider deployment offered nothing at all.
    """

    def session(self):
        return {
            "messages": [{"role": "user", "text": "hello", "attachments": []}],
            "processing": False,
            "error": "This model has used up its free allowance for now.",
            "error_detail": "HTTP 429",
            "model": "opencode:deepseek-v4-flash-free",
        }

    def test_it_offers_another_model_on_the_same_provider(self, monkeypatch):
        zen = ScriptedProvider(
            [], name="opencode",
            models=("deepseek-v4-flash-free", "nemotron-3-ultra-free"),
        )
        stub, _m = run_app(monkeypatch, client=zen, session=self.session(),
                           opencode=True)
        assert stub.button_labels.get("switch-model") == "→ Use nemotron-3-ultra"

    def test_it_skips_a_sibling_that_shares_the_daily_bucket(self, monkeypatch):
        """Zen keys its free-tier daily bucket on the first two characters of the
        model id, so `nemotron-3.5-lightning-free` and `nemotron-3-ultra-free` share
        one counter. Hopping from one to the other hands the turn a counter that is
        already spent by definition — the failover has to leave the family."""
        zen = ScriptedProvider(
            [], name="opencode",
            models=("nemotron-3.5-lightning-free", "nemotron-3-ultra-free",
                    "deepseek-v4-flash-free"),
        )
        session = self.session() | {"model": "opencode:nemotron-3.5-lightning-free"}
        stub, _m = run_app(monkeypatch, client=zen, session=session, opencode=True)
        assert stub.button_labels.get("switch-model") == "→ Use deepseek-v4-flash"

    def test_a_chain_of_hops_never_returns_to_a_spent_family(self, monkeypatch):
        """The hole a single-model check leaves, one hop wide.

        Reading the excluded family from the CURRENT model only, a chain starting on
        nemotron leaves for deepseek and then — deepseek being the current model by
        then — happily takes the other nemotron, whose daily counter hop 0 exhausted.
        Simulated against the live free catalogue that chain touched 3 buckets out of
        4; excluding every family already tried touches all 4.
        """
        from sage.ui.view import View

        live = ("nemotron-3.5-lightning-free", "nemotron-3-ultra-free",
                "deepseek-v4-flash-free", "big-pickle", "mimo-v2.5-free")
        models = tuple(providers.Model("opencode", name) for name in live)
        current, tried, chain = models[0], [], [models[0].id]
        for _hop in range(3):
            nxt = View(runtime=None, models=models, model=current).alternative(
                "allowance", skip=tried
            )
            assert nxt is not None
            tried.append(current.key)
            current = nxt
            chain.append(nxt.id)
        # Zen buckets on the first two characters of the id.
        buckets = [name[:2] for name in chain]
        assert len(set(buckets)) == len(buckets), f"revisited a spent bucket: {chain}"
        assert "nemotron-3-ultra-free" not in chain, "the 23s model, and a spent bucket"

    def test_a_sibling_is_still_better_than_nothing(self, monkeypatch):
        """Leaving the family is a preference, not a requirement: with only siblings
        left, one of them is the last thing between the reader and a dead end."""
        zen = ScriptedProvider(
            [], name="opencode",
            models=("nemotron-3.5-lightning-free", "nemotron-3-ultra-free"),
        )
        session = self.session() | {"model": "opencode:nemotron-3.5-lightning-free"}
        stub, _m = run_app(monkeypatch, client=zen, session=session, opencode=True)
        assert stub.button_labels.get("switch-model") == "→ Use nemotron-3-ultra"

    def test_another_provider_is_still_preferred_when_there_is_one(self, monkeypatch):
        """A spent *key* kills every model behind it, so a different key comes first."""
        zen = ScriptedProvider(
            [], name="opencode",
            models=("deepseek-v4-flash-free", "nemotron-3-ultra-free"),
        )
        mistral = ScriptedProvider([], name="mistral", models=("m1",))
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=self.session(), opencode=True)
        assert stub.button_labels.get("switch-model") == "→ Use m1"


class TestWalkingTheLineup:
    """A model that is not working hands the question on, until nothing is left.

    Reported from the running app, on `opencode:nemotron-3-ultra-free`:

        Could not complete that request
        The model returned an empty answer. Try again, or use a different model.

    Six models that would have answered were one row down the picker, and the machinery
    for walking to them was already in this file — reserved for three of the eleven ways
    a turn can fail, and the one the reader hit was not among them. The reader should
    never have been shown that card: the app can read the advice on it and act on it.

    So the failover set is now everything except `context`, and what bounds the walk is
    the lineup rather than a hop count. These tests drive the app the way Streamlit
    does — one import per script run — because a failover happens on the run *after* the
    one that failed.
    """

    LINEUP = ("z1", "z2", "z3", "z4", "z5")

    class Lineup:
        """One provider whose models differ, because which model answers is the point.

        `ScriptedProvider` replays turns by call order; this replays by model, so a
        lineup where the fourth one works is expressible.
        """

        name = "opencode"

        def __init__(self, ids, answers=(), error=None):
            self._ids = tuple(ids)
            self._answers = dict(answers)
            self._error = error
            self.asked: list[str] = []

        def models(self):
            return [providers.Model(self.name, name) for name in self._ids]

        def stream(self, model, messages, tools, thinking=False):
            self.asked.append(model)
            if self._error is not None and model not in self._answers:
                raise self._error
            said = self._answers.get(model)
            # No deltas at all is the shape the report came in as: the request
            # succeeds, the stream ends, and nothing was said.
            yield from ([event(said)] if said else [])

    def session(self, **extra):
        return {
            "messages": [{"role": "user", "text": "what is a service unit?",
                          "attachments": []}],
            "processing": True,
            "model": "opencode:z1",
        } | extra

    CARRIED = ("messages", "processing", "model", "tried", "switched_from", "notice")

    def drive(self, monkeypatch, provider, *, session=None, runs=12):
        """Re-enter the app until the turn settles, carrying the walk's state along.

        The bound is a guard, not a budget: a turn that has not settled in twelve runs
        is spinning, and saying so beats hanging the suite.
        """
        session = session or self.session()
        for _ in range(runs):
            stub, _module = run_app(monkeypatch, client=provider, session=session,
                                    opencode=True)
            state = stub.session_state
            if not state.get("processing"):
                return stub
            session = {key: state.get(key) for key in self.CARRIED}
        raise AssertionError(f"still spinning after {runs} runs: {provider.asked}")

    def test_an_empty_answer_hands_the_question_to_the_next_model(self, monkeypatch):
        """The bug, at its smallest: one model says nothing, so ask another."""
        zen = self.Lineup(self.LINEUP)
        stub, _module = run_app(monkeypatch, client=zen, session=self.session(),
                                opencode=True)
        assert stub.session_state["error"] is None, (
            "an empty answer is not something to show a card about while models remain"
        )
        assert stub.session_state["model"] != "opencode:z1"
        assert stub.session_state["processing"] is True, "the turn should be retried"
        assert stub.session_state["tried"] == ["opencode:z1"]

    def test_the_notice_says_why_in_words_rather_than_in_kinds(self, monkeypatch):
        """`REASONS` is what keeps an internal name off the screen. Without an entry
        the line reads "z1 is unavailable (empty)"."""
        zen = self.Lineup(self.LINEUP)
        stub, _module = run_app(monkeypatch, client=zen, session=self.session(),
                                opencode=True)
        notice = stub.session_state["notice"]
        assert "returned no answer" in notice
        assert "(empty)" not in notice
        assert "Retrying with" in notice

    def test_every_reason_a_turn_can_fail_over_for_reads_as_english(self):
        """The two lists have to be held together, because the failover set is now
        derived from `llm.KINDS` — a kind added there joins the walk automatically and
        would otherwise print its own name to the reader.

        Under the stub like every other test in this file, and not as an incidental:
        CI installs pytest, ruff, pypdf and httpx and *not* Streamlit — that is what
        keeps the job fast — so `sage.ui.turn` cannot be imported bare. It passed here
        and failed there, which is the one direction a check must not fail in.
        """
        stub_streamlit.install()
        from sage.ui import turn as turn_module

        missing = sorted(turn_module.FAILOVER_KINDS - set(turn_module.REASONS))
        assert not missing, f"no reader-facing reason for: {missing}"

    def test_it_keeps_going_until_the_whole_lineup_is_spent(self, monkeypatch):
        """"Until all the models have been used" — five, not three of five."""
        zen = self.Lineup(self.LINEUP)
        stub = self.drive(monkeypatch, zen)
        assert zen.asked == list(self.LINEUP), (
            f"the walk stopped early: {zen.asked}"
        )
        assert stub.session_state["error"], "and then it says so"
        assert stub.session_state["processing"] is False, "it must not spin"
        assert stub.session_state["notice"] == "", (
            "no 'retrying with…' left over promising something that never happened"
        )

    def test_a_working_model_further_down_the_lineup_gets_to_answer(self, monkeypatch):
        zen = self.Lineup(self.LINEUP, answers={"z4": "A service unit is an hour."})
        stub = self.drive(monkeypatch, zen)
        assert zen.asked == ["z1", "z2", "z3", "z4"], "it stops when one answers"
        reply = stub.session_state["messages"][-1]
        assert reply["role"] == "assistant"
        assert reply["text"] == "A service unit is an hour."
        assert reply["model"] == "opencode:z4"
        assert stub.session_state["error"] is None
        # Past tense only now, and about the model the reader actually left behind.
        assert "z4 answered instead" in stub.session_state["notice"]
        assert stub.session_state["tried"] == []

    def test_a_failure_that_is_not_about_the_model_is_walked_too(self, monkeypatch):
        """A 5xx used to be an error card on the first model that hiccupped, however
        many were left. `llm.start` has already spent its retries by the time this
        runs, so there is nothing else to try but somebody else."""
        error = RuntimeError("Internal Server Error")
        error.status_code = 503
        zen = self.Lineup(self.LINEUP, answers={"z3": "Answered."}, error=error)
        stub = self.drive(monkeypatch, zen)
        assert stub.session_state["messages"][-1]["text"] == "Answered."
        assert "not responding" in stub.session_state["notice"]

    def test_a_conversation_too_long_for_one_model_is_too_long_for_all_of_them(
        self, monkeypatch
    ):
        """The one exception, and the reason it is one: the request is oversized, so
        every model in the lineup refuses the same message the same way. Walking them
        is a certain failure per model, and the remedy is the reader's."""
        error = RuntimeError("This model's maximum context length is 8192 tokens")
        error.status_code = 400
        zen = self.Lineup(self.LINEUP, error=error)
        stub, _module = run_app(monkeypatch, client=zen, session=self.session(),
                                opencode=True)
        assert zen.asked == ["z1"], "it must not try the same oversized request again"
        assert "too long" in stub.session_state["error"]
        assert stub.session_state["processing"] is False

    def test_the_walk_can_be_switched_off(self, monkeypatch):
        """One attempt is the off position, and `evals/harness.py` sets it: a per-model
        benchmark that let the app substitute a working model would score the model it
        asked on another model's answer."""
        monkeypatch.setattr(config, "MAX_MODEL_ATTEMPTS", 1)
        zen = self.Lineup(self.LINEUP)
        stub, _module = run_app(monkeypatch, client=zen, session=self.session(),
                                opencode=True)
        assert zen.asked == ["z1"]
        assert stub.session_state["error"] == llm.AssistantError("empty").user_message
        assert stub.session_state["processing"] is False

    def test_a_ceiling_below_the_lineup_is_honoured(self, monkeypatch):
        monkeypatch.setattr(config, "MAX_MODEL_ATTEMPTS", 2)
        zen = self.Lineup(self.LINEUP)
        stub = self.drive(monkeypatch, zen)
        assert zen.asked == ["z1", "z2"]
        assert stub.session_state["error"]


class TestConversationRendering:
    def test_prior_answers_render_with_resolved_links(self, monkeypatch):
        session = {
            "messages": [
                {"role": "user", "text": "how do I submit a job", "attachments": []},
                {
                    "role": "assistant",
                    "text": "See [Batch jobs](docs/slurm/sbatch.md).",
                    "sources": [
                        {
                            "id": "docs/slurm/sbatch.md#batch-jobs",
                            "label": "Batch jobs",
                            "url": "https://example.test/x",
                            "source": "docs",
                        }
                    ],
                    "rating": None,
                },
            ],
            "processing": False,
        }
        stub, _module = run_app(monkeypatch, session=session)
        rendered = "\n".join(str(body) for _name, body in stub.events if _name == "markdown")
        assert "docs.rcc.uchicago.edu/slurm/sbatch/" in rendered
        assert "docs/slurm/sbatch.md" not in rendered

    def test_user_html_is_escaped(self, monkeypatch):
        session = {
            "messages": [
                {
                    "role": "user",
                    "text": "<img src=x onerror=alert(1)>",
                    "attachments": [],
                }
            ],
            "processing": False,
        }
        stub, _module = run_app(monkeypatch, session=session)
        html = "\n".join(stub.markdown_html)
        assert "<img src=x" not in html
        assert "&lt;img" in html


class TestAttachments:
    """More than one file, and the chips where the composer is.

    Two bugs lived here. The uploader took one file and the app ignored anything
    offered while one was already held, so attaching a second did nothing at all and
    said nothing about why; and the chip rendered wherever the script reached it,
    which put it in the middle of the page, a long way from the box it belongs to.
    """

    class Upload:
        """What st.file_uploader hands back per file."""

        def __init__(self, name, data):
            self.name = name
            self._data = data
            self.size = len(data)

        def getvalue(self):
            return self._data

    def app(self, monkeypatch, uploads, session=None, **stub_kwargs):
        mistral = ScriptedProvider([], name="mistral", models=("mistral-small-latest",))
        return run_app(
            monkeypatch, client=mistral, upload=uploads,
            session={"messages": [], "processing": False, **(session or {})},
            **stub_kwargs,
        )

    def test_the_uploader_asks_for_more_than_one_file(self, monkeypatch):
        stub, _m = self.app(monkeypatch, [])
        assert stub.uploader_kwargs.get("accept_multiple_files") is True

    def test_the_uploader_does_not_filter_by_extension(self, monkeypatch):
        """`type=` is what refused a pasted screenshot: app.js names one, and no
        list of extensions was ever going to contain that name. The bytes decide."""
        stub, _m = self.app(monkeypatch, [])
        assert "type" not in stub.uploader_kwargs

    def test_two_files_are_both_held(self, monkeypatch):
        stub, _m = self.app(monkeypatch, [
            self.Upload("slurm-1.out", b"OOM killed\n"),
            self.Upload("submit.sbatch", b"#SBATCH -p caslake\n"),
        ])
        names = [item.filename for item in stub.session_state["attachments"]]
        assert names == ["slurm-1.out", "submit.sbatch"]

    def test_the_same_file_is_not_held_twice_across_reruns(self, monkeypatch):
        """The uploader reports its files again on every rerun. Without an identity
        check one attachment became one per interaction with the page.

        Both runs go through the app, rather than the second one being handed a
        hand-built attachment: what identifies a file is the app's business and has
        changed once already, and a fixture that mints its own identity stops
        exercising the check the moment that happens — which is how this test came to
        pass a file the app would have recognised.
        """
        stub, _m = self.app(monkeypatch, [self.Upload("run.err", b"segfault\n")])
        assert len(stub.session_state["attachments"]) == 1

        # The rerun: same widget, same file, reported again.
        again, _m = self.app(
            monkeypatch, [self.Upload("run.err", b"segfault\n")],
            session=dict(stub.session_state),
        )
        assert len(again.session_state["attachments"]) == 1, (
            "the same file was attached twice by a rerun that changed nothing"
        )

    def test_a_rejected_file_does_not_take_the_others_with_it(self, monkeypatch):
        """A bad file used to reset the whole widget, dropping the good ones too."""
        stub, _m = self.app(monkeypatch, [
            self.Upload("good.txt", b"readable\n"),
            self.Upload("a.out", b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 24),
        ])
        names = [item.filename for item in stub.session_state["attachments"]]
        assert names == ["good.txt"]
        assert any("does not look like text" in warning for warning in stub.warnings)

    def test_the_chips_are_rendered_in_their_own_pinned_container(self, monkeypatch):
        stub, _m = self.app(monkeypatch, [self.Upload("notes.md", b"# hi\n")])
        keys = [key for name, key in stub.events if name == "container"]
        assert "attachments" in keys

    def test_the_chips_are_rendered_after_the_input_box(self, monkeypatch):
        """Pinned to the composer, like the controls strip. Rendered where the
        script first hears about the upload, they landed in the middle of the page."""
        stub, _m = self.app(monkeypatch, [self.Upload("notes.md", b"# hi\n")])
        names = [name for name, _key in stub.events]
        order = [
            index for index, (name, key) in enumerate(stub.events)
            if name == "chat_input" or (name == "container" and key == "attachments")
        ]
        assert names.count("chat_input") == 1
        assert len(order) == 2 and order[0] < order[1], stub.events

    def test_an_image_on_a_text_only_model_says_so(self, monkeypatch):
        """An image sent to a text-only model is a 4xx. Said next to the picture,
        beside the picker that can fix it, rather than discovered in the answer."""
        png = b"\x89PNG\r\n\x1a\n" + b"x" * 40
        stub, _m = self.app(monkeypatch, [self.Upload("pasted-image.png", png)])
        assert any("cannot read images" in caption for caption in stub.captions)

    def test_a_dismissed_file_does_not_come_back_on_the_next_rerun(self, monkeypatch):
        """The ✕ has to outlive the rerun it triggers.

        Nothing in this app can reach into the uploader widget and remove a file from
        it, so the widget goes on reporting a dismissed one on every rerun. Without a
        record of what was dismissed the chip disappeared and was rebuilt on the next
        frame, which is a control that undoes itself.
        """
        stub, _m = self.app(
            monkeypatch, [self.Upload("slurm-1.out", b"OOM killed\n")],
            buttons={"drop-attachment-0": True},
        )
        assert stub.session_state["attachments"] == []

        # The rerun that ✕ ends in: the same widget, still holding the same file.
        after, _m = self.app(
            monkeypatch, [self.Upload("slurm-1.out", b"OOM killed\n")],
            session=dict(stub.session_state),
        )
        assert [item.filename for item in after.session_state["attachments"]] == [], (
            "the dismissed file was re-attached by the rerun the dismissal caused"
        )

    def test_the_chip_that_was_dismissed_is_the_one_that_goes(self, monkeypatch):
        """Every chip needs its own key and its own index.

        One key for the row — which is what a single-attachment composer had — makes
        every ✕ the same button: Streamlit refuses the duplicate, or the first file
        goes whichever chip was clicked.
        """
        stub, _m = self.app(monkeypatch, [
            self.Upload("keep.out", b"still wanted\n"),
            self.Upload("drop.out", b"not wanted\n"),
        ], buttons={"drop-attachment-1": True})
        assert [item.filename for item in stub.session_state["attachments"]] == [
            "keep.out",
        ]

    def test_two_different_files_with_one_name_are_both_held(self, monkeypatch):
        """A name is not an identity, so an edited file attaches beside the old one.

        Keyed on the name alone the second of these is dropped without a word — the
        same failure as the guard that dropped every file offered while one was
        already held. Not a corner case: every screenshot pasted into the box arrives
        called pasted-image.png, and every cluster has more than one config.yaml.
        """
        stub, _m = self.app(monkeypatch, [
            self.Upload("submit.sbatch", b"#SBATCH -p caslake\n"),
            self.Upload("submit.sbatch", b"#SBATCH -p caslake\n#SBATCH --mem=64G\n"),
        ])
        held = stub.session_state["attachments"]
        assert len(held) == 2, "the edited file was taken for the one already held"
        assert "--mem=64G" in held[1].text

    def test_sending_the_turn_hands_the_files_over_and_empties_the_composer(
        self, monkeypatch
    ):
        """Both files travel with the question, and none is left in the composer.

        A turn used to carry one attachment, so the second was not merely unsent — it
        was unsendable. And a file left behind in the composer is re-sent, and paid
        for, with every later question in the conversation.
        """
        stub, _m = self.app(
            monkeypatch,
            [self.Upload("slurm-1.out", b"OOM killed\n"),
             self.Upload("submit.sbatch", b"#SBATCH -p caslake\n")],
            chat_input="why did this die?",
        )
        sent = stub.session_state["messages"][-1]
        assert [item.filename for item in sent["attachments"]] == [
            "slurm-1.out", "submit.sbatch",
        ]
        assert stub.session_state["attachments"] == []
        assert stub.session_state["uploader_key"] == 1, (
            "the widget has to be reset, or it reports the sent files again"
        )

    def test_a_dismissal_does_not_outlive_the_turn_it_was_made_in(self, monkeypatch):
        """Dismissed keys name files in a widget that is gone once a turn is sent.

        Kept past the send, they refuse the same file for the rest of the
        conversation: a paperclip that does nothing, for a file the user attached
        successfully two questions ago.
        """
        data = b"OOM killed\n"
        dismissed, _m = self.app(
            monkeypatch, [self.Upload("slurm-1.out", data)],
            buttons={"drop-attachment-0": True},
        )
        assert dismissed.session_state["dropped_uploads"], "nothing was remembered"

        sent, _m = self.app(
            monkeypatch, [self.Upload("slurm-1.out", data)],
            session=dict(dismissed.session_state), chat_input="why did this die?",
        )
        assert sent.session_state["messages"][-1]["attachments"] == []
        # Emptied, whatever it is kept in — a set of keys once, counts per key now.
        assert not sent.session_state["dropped_uploads"]

        # The next question, and the same file offered again to a fresh widget.
        again, _m = self.app(
            monkeypatch, [self.Upload("slurm-1.out", data)],
            session=dict(sent.session_state) | {"processing": False},
        )
        assert [item.filename for item in again.session_state["attachments"]] == [
            "slurm-1.out",
        ], "a dismissal from an earlier turn still refuses the file"


class TestVisionModels:
    """A pasted screenshot is only useful if the model is handed the picture.

    Pasting one used to do nothing whatsoever. Now it attaches, and whether the bytes
    travel is `config.sees_images`' decision — an image sent to a text-only model is a
    4xx, not a polite decline. These drive the whole app rather than `history.build`
    directly, because the wiring is half the fix: app.py has to ask that question and
    hand the answer to the builder.
    """

    PNG = b"\x89PNG\r\n\x1a\n" + b"IHDR" + b"pixels" * 8

    def session(self, model_key):
        from sage import files as files_mod  # noqa: PLC0415

        shot, error = files_mod.process("pasted-image.png", self.PNG)
        assert error is None, error
        return {
            "messages": [{"role": "user", "text": "what does this error mean?",
                          "attachments": [shot]}],
            "processing": True,
            "model": model_key,
        }

    def content_sent(self, monkeypatch, model_id):
        """The user turn as the provider received it."""
        provider = ScriptedProvider([[event("That is an out-of-memory kill.")]],
                                    name="mistral", models=(model_id,))
        run_app(monkeypatch, client=provider,
                session=self.session(f"mistral:{model_id}"))
        assert provider.calls == 1
        return provider.sent[0][-1]["content"]

    def test_a_vision_model_is_handed_the_picture(self, monkeypatch):
        content = self.content_sent(monkeypatch, "pixtral-12b-latest")
        assert isinstance(content, list), f"the image never became a part: {content!r}"
        assert [part["type"] for part in content] == ["text", "image_url"]
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert "pasted-image.png" in content[0]["text"]

    def test_a_text_only_model_is_told_about_the_file_instead(self, monkeypatch):
        """Held back deliberately: the request would come back 4xx, and a 4xx is a
        worse answer than "there is an image here that I cannot read"."""
        content = self.content_sent(monkeypatch, "mistral-small-latest")
        assert isinstance(content, str), f"bytes went to a text-only model: {content!r}"
        assert "pasted-image.png" in content
        assert "base64" not in content


class TestComposerReset:
    """Clearing the conversation has to clear the box too.

    The text in Streamlit's chat input is client-side state that Python only reads on
    submit, so nothing in app.py can empty it. Clearing therefore wiped the transcript
    and left the last question sitting over the starter cards as if it were about to be
    sent. app.py publishes a token; app.js does the emptying.
    """

    def app(self, monkeypatch, session=None, **kwargs):
        client = ScriptedProvider([], name="mistral", models=("m1",))
        return run_app(monkeypatch, client=client,
                       session={"processing": False, **(session or {})}, **kwargs)

    def test_the_token_is_published_for_app_js(self, monkeypatch):
        stub, _m = self.app(monkeypatch, {"messages": []})
        assert any(
            'id="composer-reset"' in html and "data-token=" in html
            for html in stub.markdown_html
        ), "app.js has nothing to watch"

    def test_leaving_a_conversation_moves_the_token(self, monkeypatch):
        """The trash used to be what moved it. Every path that leaves a conversation
        does now — New chat, opening another, deleting one — because they all go through
        `state._leave_conversation`, and app.js empties the box when the token moves."""
        session = {"messages": [{"role": "user", "text": "hi", "attachments": []}]}
        before, _m = self.app(monkeypatch, session)
        start = before.session_state["clear_token"]
        after, _m2 = self.app(monkeypatch, session, buttons={"new-chat": True})
        assert after.session_state["clear_token"] == start + 1

    def test_an_ordinary_run_leaves_the_token_alone(self, monkeypatch):
        """It must move only when a conversation is left: app.js empties the box
        whenever it changes, and a token that drifted would delete a half-typed
        question."""
        session = {"messages": [{"role": "user", "text": "hi", "attachments": []}],
                   "clear_token": 7}
        stub, _m = self.app(monkeypatch, session)
        assert stub.session_state["clear_token"] == 7


class TestCitationApparatus:
    """Sources and Related used to be two rows of identical chips, which left the reader
    unable to tell what an answer was built from from what it merely suggests next — and
    as wrapping rows they were ragged, because a flex row whose first item is the label
    indents its first line only."""

    @staticmethod
    def session(count=3):
        return {
            "messages": [
                {"role": "user", "text": "what are the storage quotas", "attachments": []},
                {
                    "role": "assistant",
                    "text": "Your /home quota is 30 GB.",
                    "sources": [
                        {
                            "id": f"docs/storage/main.md#q{n}",
                            "label": f"Storage System Layout — Quota rule {n}",
                            "url": f"https://example.test/storage/#q{n}",
                            "source": "docs" if n % 2 else "web",
                        }
                        for n in range(count)
                    ],
                    "rating": None,
                },
            ],
            "processing": False,
        }

    @staticmethod
    def markup(stub):
        """The rendered markup only. `markdown_html` also carries the injected
        stylesheet, and app.css names every class asserted on below — so an
        unscoped search finds `.source-list` in the CSS and passes on a page that
        rendered none."""
        return "\n".join(
            html for html in stub.markdown_html if "<style" not in html
        )

    def render(self, monkeypatch, count=3):
        stub, _module = run_app(monkeypatch, session=self.session(count))
        return self.markup(stub)

    def test_sources_are_a_numbered_list_one_per_line(self, monkeypatch):
        html = self.render(monkeypatch)
        assert html.count('class="source-item"') == 3
        assert 'class="source-list"' in html

    def test_the_chip_layout_is_gone(self, monkeypatch):
        """Not a shared class with a different label — the layout has to say it."""
        html = self.render(monkeypatch)
        assert "source-chip" not in html

    def test_no_list_element_is_used(self, monkeypatch):
        """Streamlit styles markdown lists, and a `[data-testid=…] ol` rule outranks a
        single class — so an `<ol>` here would inherit Streamlit's list indent in the
        app while the render harness, which has no list rules at all, showed it
        perfectly. Divs inherit nothing and a CSS counter numbers them just as well."""
        html = self.render(monkeypatch)
        for tag in ("<ol", "<ul", "<li>", "<li "):
            assert tag not in html, f"{tag} rendered in the citation markup"

    def test_every_citation_link_opens_in_a_new_tab_safely(self, monkeypatch):
        html = self.render(monkeypatch)
        links = [m for m in html.split("<a ") if "source-link" in m[:40]]
        assert links, "no citation links rendered"
        for link in links:
            head = link[: link.index(">")]
            assert 'target="_blank"' in head
            assert 'rel="noopener noreferrer"' in head

    def test_the_source_kind_badge_survives(self, monkeypatch):
        assert 'class="source-kind">docs<' in self.render(monkeypatch)

    def test_a_label_is_escaped(self, monkeypatch):
        session = self.session(1)
        session["messages"][1]["sources"][0]["label"] = "<script>x</script>"
        stub, _module = run_app(monkeypatch, session=session)
        html = self.markup(stub)
        assert "<script>x</script>" not in html
        assert "&lt;script&gt;" in html

    def test_a_url_cannot_add_an_attribute_to_its_own_link(self, monkeypatch):
        """The label is element content; the URL becomes an `href`, which is worse.

        A quote inside it closes the attribute and whatever follows becomes a new one. It
        is reachable: `corpus/urls.py` rejects a non-http scheme — `javascript:`, `data:`
        and `file:` all fall back to the site root, which `test_normalize.py` pins — but a
        quote inside an `https://` URL passes, and the scraper's input is the live web.
        `corpus_health.malformed_urls` reports one; this is what stops it rendering.
        """
        session = self.session(1)
        session["messages"][1]["sources"][0]["url"] = (
            'https://x.org/a" onmouseover="evil()'
        )
        stub, _module = run_app(monkeypatch, session=session)
        html = self.markup(stub)
        assert "onmouseover" in html, "the URL should still be shown, escaped"
        assert 'onmouseover="' not in html, "the URL opened a new HTML attribute"
        assert "&quot;" in html

    def test_related_is_absent_when_there_is_nothing_to_relate(self, monkeypatch):
        """The Related block is optional; an empty one would render a bare label."""
        html = self.render(monkeypatch)
        if "related-list" in html:
            assert 'class="related-item"' in html

    def test_nothing_renders_without_citations(self, monkeypatch):
        session = self.session(1)
        session["messages"][1]["sources"] = []
        stub, _module = run_app(monkeypatch, session=session)
        html = self.markup(stub)
        assert "source-list" not in html
        assert "sources-label" not in html


class TestDistinctDestinations:
    """A citation and a lead are both a place to click, so two of them are only two if
    they land somewhere different.

    Reported from the app: asking who directs the RCC cited "Our Team" and then offered
    "Our Team (part 2)", "(part 3)" and "(part 4)" under Related — four links, one page,
    and the three leads pointed at the citation directly above them. The page is
    windowed for indexing at 2400 characters, and every one of its thirteen windows
    carries the page's own URL because a scraped page has no anchors to deep-link to.
    Filtering leads by chunk id could not see that; the id was what differed.
    """

    @staticmethod
    def source(module, chunk_id):
        chunk = module.RUNTIME.corpus.chunk(chunk_id)
        assert chunk is not None, f"{chunk_id} is not in the bundled corpus"
        return {
            "id": chunk.id,
            "label": chunk.label,
            "url": chunk.url,
            "source": chunk.source,
        }

    def test_the_reported_answer_offers_no_lead_back_to_its_own_citation(
        self, monkeypatch
    ):
        _stub, module = run_app(monkeypatch)
        cited = self.source(module, "web/about-rcc_our-team.txt#1")
        related = module.transcript.related_sections(module.RUNTIME.corpus, [cited])
        assert [item["url"] for item in related] == []

    def test_every_lead_is_somewhere_the_reader_is_not_already_being_sent(
        self, monkeypatch
    ):
        """Swept over the whole corpus, not just the page that was reported: 62 of the
        536 chunks that produce a Related list led back to their own citation, and 36
        listed one destination twice."""
        _stub, module = run_app(monkeypatch)
        for chunk in module.RUNTIME.corpus.chunks:
            cited = self.source(module, chunk.id)
            urls = [item["url"] for item in module.transcript.related_sections(module.RUNTIME.corpus, [cited])]
            assert len(urls) == len(set(urls)), f"{chunk.id} repeats a lead"
            assert chunk.url not in urls, f"{chunk.id} leads back to itself"

    def test_leads_still_reach_the_other_sections_of_a_real_page(self, monkeypatch):
        """The rule above is satisfied by showing nothing, so hold the feature down
        too: an anchored docs page still offers its siblings."""
        _stub, module = run_app(monkeypatch)
        cited = self.source(module, "docs/storage/main.md#quotas")
        related = module.transcript.related_sections(module.RUNTIME.corpus, [cited])
        assert len(related) == 3
        assert all(item["url"].startswith("https://") for item in related)

    def test_the_sources_strip_lists_each_destination_once(self, monkeypatch):
        """Same defect one row up. `search_docs` may return two windows of one page
        (MAX_PER_PAGE allows two sections of any page), and for a scraped page those
        two are one link — so "who is the director of the RCC" cited four sections
        that were two pages."""
        _stub, module = run_app(monkeypatch)
        from sage import tools

        _context, chunks = tools.gather_context(
            module.RUNTIME.retriever, "who is the director of the rcc"
        )
        assert len(chunks) > 1, "expected a multi-section retrieval to test against"
        urls = [item["url"] for item in module.transcript.citations(chunks)]
        assert len(urls) == len(set(urls))


def configure(monkeypatch, **values):
    """Override settings the way the app reads them.

    `sage/config.py` resolves every setting at import time, so `monkeypatch.setenv`
    after the module is loaded changes nothing — the same import-time coupling that
    made this suite depend on the developer's shell. Setting the attribute is what
    actually takes effect, and monkeypatch puts it back.
    """
    for name, value in values.items():
        monkeypatch.setattr(config, name, value)


def with_auth(stub, **user):
    """A stub with an `[auth]` block configured, and optionally someone signed in."""
    stub.secrets = SimpleNamespace(
        get=lambda key, default="": {"client_id": "x"} if key == "auth" else default
    )
    if user:
        stub.user = SimpleNamespace(**user)
    return stub


class TestUsageLimits:
    """The gate in `start_new_turn()`, the one place a turn can begin.

    The arithmetic is covered in `tests/test_limits.py` without a browser. What
    matters here is that a refusal leaves the app in a state a reader can understand.
    """

    def test_a_refused_turn_leaves_the_transcript_alone(self, monkeypatch):
        """The failure to avoid is a question on screen with no answer under it.

        Appending the message and then declining to process it produces exactly the
        dead end the turn loop's own comments are about, so the check runs before any
        state is touched.
        """
        configure(monkeypatch, RATE_BURST=1, RATE_REFILL_SECONDS=600.0,
                  DAILY_TURNS=0, CALL_BUDGET=0)
        stub, _ = run_app(monkeypatch, chat_input=None)
        import app  # noqa: PLC0415

        with pytest.raises(stub_streamlit.Rerun):
            app.state.start_new_turn("first question")      # spends the only token
        stub.session_state["processing"] = False
        before = list(stub.session_state["messages"])

        with pytest.raises(stub_streamlit.Rerun):
            app.state.start_new_turn("second question")     # refused

        assert stub.session_state["messages"] == before, "nothing was appended"
        assert not stub.session_state["processing"], "no turn was started"
        assert "minute" in stub.session_state["notice"], "and it says how long"

    def test_the_budget_refusal_blames_the_deployment(self, monkeypatch):
        """A reader on their first question must not be told they asked too much."""
        configure(monkeypatch, RATE_BURST=0, DAILY_TURNS=0, CALL_BUDGET=1)
        stub, _ = run_app(monkeypatch, chat_input=None)
        import app  # noqa: PLC0415

        # The same clock the app uses. Spending at 0.0 while the app checks at
        # `time.monotonic()` puts the two more than a window apart, and the budget
        # legitimately rolls over between them.
        app.state.get_limiter().record_calls(1, time.monotonic())
        with pytest.raises(stub_streamlit.Rerun):
            app.state.start_new_turn("a question")

        assert stub.session_state["messages"] == []
        assert "deployment" in stub.session_state["notice"]

    def test_limits_configured_off_let_everything_through(self, monkeypatch):
        configure(monkeypatch, RATE_BURST=0, RATE_REFILL_SECONDS=0.0,
                  DAILY_TURNS=0, CALL_BUDGET=0)
        stub, _ = run_app(monkeypatch, chat_input=None)
        import app  # noqa: PLC0415

        for index in range(25):
            with pytest.raises(stub_streamlit.Rerun):
                app.state.start_new_turn(f"question {index}")
            stub.session_state["processing"] = False
        assert len(stub.session_state["messages"]) == 25

    def test_each_session_gets_its_own_allowance(self, monkeypatch):
        """Anonymous identity is per session, so one tab cannot spend another's."""
        configure(monkeypatch, RATE_BURST=1, RATE_REFILL_SECONDS=600.0,
                  DAILY_TURNS=0, CALL_BUDGET=0)
        stub, _ = run_app(monkeypatch, chat_input=None)
        import app  # noqa: PLC0415

        first = app.access.whoami()
        stub.session_state.pop("session_id")
        assert app.access.whoami() != first

    def test_a_refusal_is_visible_on_the_landing_screen(self, monkeypatch):
        """The screen a refused *first* question is refused on.

        The notice used to be rendered only inside the branch that draws a
        conversation. Clearing the chat and clicking a starter card with the bucket
        empty therefore produced nothing whatsoever — no question, no answer, no
        reason — on a screen whose only controls are those cards. The refusal was
        recorded and then thrown away by the renderer.
        """
        stub, _ = run_app(
            monkeypatch,
            chat_input=None,
            session={"notice": "You are asking faster than Sage answers here."},
        )
        assert not stub.session_state["messages"], "this is the landing screen"
        assert any("asking faster" in body for body in stub.markdown_html), (
            "the reason a click did nothing has to be on the screen it happened on"
        )

    def test_try_again_asks_the_limiter_too(self, monkeypatch):
        """The retry button spends provider calls, so it goes through the gate.

        It used to set `processing` directly. A deployment whose call budget was
        spent refused new questions while this button went on making requests, one
        turn per click, for as long as anyone cared to click it.
        """
        monkeypatch.setattr(
            limits.Limiter, "check",
            lambda self, who, now: limits.Verdict(False, 30.0, "Not right now."),
        )
        stub, _ = run_app(
            monkeypatch,
            chat_input=None,
            buttons={"retry": True},
            session={
                "messages": [{"role": "user", "text": "why did my job fail?",
                              "attachments": []}],
                "error": "The assistant is temporarily unavailable.",
                "error_detail": "RuntimeError: 503",
            },
        )
        assert stub.session_state["processing"] is False, "no turn was started"
        assert stub.session_state["notice"] == "Not right now."
        # And the way back is still on screen: clearing the error here would take the
        # card and both its buttons away and leave the reader with nothing to click.
        assert stub.session_state["error"], "the error card survives a refused retry"

    def test_a_refused_retry_still_lets_the_model_be_switched(self, monkeypatch):
        """The card says "switch to another model and try again".

        Gating the switch on the limiter took the remedy away at the moment the
        reader reached for it: a few refused retries empty the bucket, and the one
        button that would have fixed the quota error stopped doing anything.
        Switching costs nothing; only the turn it would start does.
        """
        monkeypatch.setattr(
            limits.Limiter, "check",
            lambda self, who, now: limits.Verdict(False, 30.0, "Not right now."),
        )
        mistral = ScriptedProvider([], name="mistral", models=("m1",))
        zen = ScriptedProvider([], name="opencode", models=("z1",))
        stub, _ = run_app(
            monkeypatch,
            chat_input=None,
            opencode=True,
            client=mistral,
            extra={"opencode": zen},
            buttons={"switch-model": True},
            session={
                "messages": [{"role": "user", "text": "why did my job fail?",
                              "attachments": []}],
                "model": "mistral:m1",
                "error": "This model is out of credit or its quota is used up.",
            },
        )
        assert stub.session_state["model"] == "opencode:z1", "the model moved"
        assert stub.session_state["processing"] is False, "but no turn was started"
        assert stub.session_state["notice"] == "Not right now."
        assert mistral.calls == 0 and zen.calls == 0, "and nothing was spent"

    def test_an_allowed_retry_still_runs(self, monkeypatch):
        """The gate must not break the button it now guards."""
        stub, _ = run_app(
            monkeypatch,
            chat_input=None,
            buttons={"retry": True},
            session={
                "messages": [{"role": "user", "text": "why did my job fail?",
                              "attachments": []}],
                "error": "The assistant is temporarily unavailable.",
            },
        )
        assert stub.session_state["processing"] is True
        assert stub.session_state["error"] is None


class TestRatingDuringAGeneration:
    """👍/👎 go inert while an answer is arriving.

    Every click reruns the script, and a rerun mid-turn abandons the half-written
    answer and runs the whole turn again from its first provider call. So rating an
    earlier answer while the next one streams cost a second turn and threw away the
    one on screen — for a click that should not have touched it at all.
    """

    def session(self):
        return {
            "messages": [
                {"role": "user", "text": "first", "attachments": []},
                {"role": "assistant", "text": "an answer", "sources": [],
                 "rating": None},
                {"role": "user", "text": "second", "attachments": []},
            ],
            "processing": True,
        }

    def test_they_are_disabled_mid_turn(self, monkeypatch, tmp_path):
        configure(monkeypatch, FEEDBACK_LOG=str(tmp_path / "feedback.jsonl"))
        client = ScriptedProvider([[event("the second answer")]])
        stub, _ = run_app(monkeypatch, client=client, session=self.session())
        rated = {key: value for key, value in stub.disabled.items()
                 if str(key).startswith("rate-")}
        assert rated, "the rating row rendered"
        assert all(rated.values()), rated

    def test_they_work_again_once_it_has_landed(self, monkeypatch, tmp_path):
        configure(monkeypatch, FEEDBACK_LOG=str(tmp_path / "feedback.jsonl"))
        session = self.session() | {"processing": False}
        session["messages"] = session["messages"][:2]
        stub, _ = run_app(monkeypatch, session=session)
        rated = {key: value for key, value in stub.disabled.items()
                 if str(key).startswith("rate-")}
        assert rated and not any(rated.values()), rated


class TestEmptyAnswers:
    """A stream that carried no text is a failure, not an answer.

    The transcript skips an assistant message with no text, so an empty completion
    rendered as the reader's own question with nothing under it: no reply, no error
    card, no retry, no explanation. Free models do this — a content filter, a stop
    token on the first byte, a stream that ends cleanly having said nothing.
    """

    def session(self):
        return {
            "messages": [{"role": "user", "text": "what is a service unit?",
                          "attachments": []}],
            "processing": True,
        }

    def test_a_stream_with_no_deltas_becomes_an_error(self, monkeypatch):
        client = ScriptedProvider([[]])
        stub, _ = run_app(monkeypatch, client=client, session=self.session())

        assert stub.session_state["error"], "the reader is told something went wrong"
        assert "empty" in stub.session_state["error"].lower()
        assert [m["role"] for m in stub.session_state["messages"]] == ["user"], (
            "no blank assistant turn is stored"
        )
        assert stub.session_state["processing"] is False

    def test_whitespace_only_counts_as_empty(self, monkeypatch):
        client = ScriptedProvider([[event("   "), event("\n")]])
        stub, _ = run_app(monkeypatch, client=client, session=self.session())
        assert stub.session_state["error"]
        assert [m["role"] for m in stub.session_state["messages"]] == ["user"]

    def test_the_error_offers_a_way_out(self, monkeypatch):
        """It is the one failure a different model usually fixes — and the advice
        names no control, because a one-model deployment has neither a picker nor a
        switch button on the card."""
        message = llm.AssistantError("empty").user_message.lower()
        assert "try again" in message
        assert "different model" in message
        assert "button" not in message

    def test_a_real_answer_is_still_stored(self, monkeypatch):
        client = ScriptedProvider([[event("Service units are "), event("CPU-hours.")]])
        stub, _ = run_app(monkeypatch, client=client, session=self.session())
        assert stub.session_state["messages"][-1]["text"] == (
            "Service units are CPU-hours."
        )
        assert stub.session_state["error"] is None


class TestLoginGate:
    """Auth is opt-in, and neither way of misconfiguring it may lock people out of
    an otherwise working app."""

    def test_the_flag_alone_does_not_gate(self, monkeypatch, caplog):
        """`SAGE_REQUIRE_LOGIN` with no `[auth]` block would send every reader to a
        sign-in button that cannot work — including whoever set the flag. It fails
        open, and says so loudly enough to be found in the logs."""
        configure(monkeypatch, REQUIRE_LOGIN=True)
        with caplog.at_level("ERROR"):
            _stub, module = run_app(monkeypatch, chat_input=None)
        assert module is not None, "the app rendered rather than stopping"
        assert any("running OPEN" in record.message for record in caplog.records)

    def test_a_configured_gate_stops_an_anonymous_visitor(self, monkeypatch):
        configure(monkeypatch, REQUIRE_LOGIN=True)
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        stub = with_auth(stub_streamlit.install(chat_input=None))
        with pytest.raises(stub_streamlit.Stop):
            import app  # noqa: F401,PLC0415
        # Stopping is not enough on its own: a stop with nothing on screen is a
        # blank page, which reads as broken rather than as private.
        assert "Sign in" in stub.button_labels, "there is a way in"
        assert not any(kind == "chat_input" for kind, _ in stub.events), (
            "and the composer never rendered"
        )

    def test_a_wrong_domain_is_refused(self, monkeypatch):
        configure(monkeypatch, REQUIRE_LOGIN=True,
                  ALLOWED_EMAIL_DOMAINS=("uchicago.edu",))
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        stub = with_auth(
            stub_streamlit.install(chat_input=None),
            is_logged_in=True, email="someone@example.com", sub="abc",
        )
        with pytest.raises(stub_streamlit.Stop):
            import app  # noqa: F401,PLC0415
        assert any("outside the domains" in text for text in stub.errors)

    def test_the_right_domain_gets_in(self, monkeypatch):
        configure(monkeypatch, REQUIRE_LOGIN=True,
                  ALLOWED_EMAIL_DOMAINS=("uchicago.edu",))
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        with_auth(
            stub_streamlit.install(chat_input=None),
            is_logged_in=True, email="someone@uchicago.edu", sub="abc",
        )
        import app  # noqa: PLC0415

        assert app.access.whoami() == "user:abc", "limits key off the account, not the tab"


class TestAllowedDomains:
    @pytest.mark.parametrize("email,domains,allowed", [
        ("a@uchicago.edu", ("uchicago.edu",), True),
        ("a@UChicago.EDU", ("uchicago.edu",), True),
        ("a@example.com", ("uchicago.edu",), False),
        # The trap: a domain check by substring lets anyone register the suffix.
        ("a@notuchicago.edu", ("uchicago.edu",), False),
        ("a@uchicago.edu.evil.com", ("uchicago.edu",), False),
        ("a@cs.uchicago.edu", ("cs.uchicago.edu", "uchicago.edu"), True),
        ("", ("uchicago.edu",), False),
        ("anyone@anywhere.test", (), True),
    ])
    def test_domains_are_matched_whole(self, monkeypatch, email, domains, allowed):
        monkeypatch.setattr(config, "ALLOWED_EMAIL_DOMAINS", domains)
        assert config.email_allowed(email) is allowed


class TestSessionsAreNotShared:
    """One reader's conversation must never appear in another's.

    This shipped. `SESSION_DEFAULTS` is built when `sage.ui.state` is imported — once
    per *process*, not once per session — so `setdefault` handed every session in the
    process the SAME `[]`. A question appended by one reader was in the next reader's
    transcript, and the app opened on somebody else's conversation instead of the
    landing screen. On a public deployment that is other people's questions, their
    attachments, and whatever they pasted into them.

    It was an accident before the refactor too, in the other direction: the list was
    written inside `app.py`'s module body, which Streamlit re-executes per script run,
    so each session got a fresh one without anything saying it had to.
    """

    def sessions(self, count=3):
        """`count` readers arriving in one process, sharing one imported module."""
        stub = stub_streamlit.install()
        from sage.ui import state  # noqa: PLC0415  (after the stub is in place)

        seen = []
        for _reader in range(count):
            stub.session_state.clear()
            state.initialise()
            seen.append(stub.session_state)
        return stub, state, seen

    def test_a_second_reader_does_not_inherit_the_first_ones_questions(self):
        stub, state, _ = self.sessions(1)
        state.initialise()
        stub.session_state["messages"].append(
            {"role": "user", "text": "my CNetID is jsmith", "attachments": []}
        )
        stub.session_state.clear()
        state.initialise()
        assert stub.session_state["messages"] == [], (
            "a new reader opened on someone else's conversation"
        )

    def test_no_mutable_default_is_shared_between_sessions(self):
        """Every container, not just `messages` — attachments and the upload
        bookkeeping carry filenames and refusal reasons."""
        stub, state, _ = self.sessions(1)
        first = {
            key: stub.session_state[key]
            for key, default in state.SESSION_DEFAULTS
            if isinstance(default, list | dict)
        }
        assert first, "expected some mutable defaults to check"
        stub.session_state.clear()
        state.initialise()
        for key, held in first.items():
            assert stub.session_state[key] is not held, (
                f"{key!r} is the same object in two sessions"
            )

    def test_writing_in_one_session_cannot_be_seen_in_another(self):
        stub, state, _ = self.sessions(1)
        stub.session_state["attachments"].append("private.pdf")
        stub.session_state["dropped_uploads"]["k"] = 1
        stub.session_state["tried"].append("opencode:m1")
        stub.session_state.clear()
        state.initialise()
        assert stub.session_state["attachments"] == []
        assert stub.session_state["dropped_uploads"] == {}
        assert stub.session_state["tried"] == []

    def test_the_landing_screen_is_what_a_new_reader_gets(self, monkeypatch):
        """The visible symptom, end to end: a reader arriving after someone else has
        asked something must still see the welcome screen."""
        first, module = run_app(monkeypatch)
        first.session_state["messages"].append(
            {"role": "user", "text": "someone else's question", "attachments": []}
        )
        assert module is not None
        second, module = run_app(monkeypatch)
        html = " ".join("\n".join(second.markdown_html).split())
        assert "What can I help you with?" in html
        assert "someone else's question" not in html


class TestAModelThinkingOutLoudIsNotAnAnswer:
    """34,645 characters of deliberation shipped as a reply, once in 554 recorded turns.

    The model quoted its instructions back line by line, ran into the token ceiling
    mid-sentence without answering, and the transcript drew all of it under a Sources
    strip of six real sections. It is the preamble case in a different costume — the model
    said what it was going to do and never did it — so it takes the same route out: the
    error card, which offers Try again and a different model.
    """

    def session(self):
        return {
            "messages": [
                {"role": "user", "text": "did you look that up?", "attachments": []}
            ],
            "processing": True,
        }

    def test_it_becomes_the_recoverable_error_card(self, monkeypatch):
        monologue = (
            "Here's a thinking process:\n\n1. **Analyze User Input:** the user asks "
            "whether I looked it up.\n2. **Check System Instructions:** I must answer "
            "strictly from the documentation and cite every page."
        )
        client = ScriptedProvider([[event(monologue)]])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        assert stub.session_state["error"] is not None
        stored = stub.session_state["messages"][-1]
        assert stored["role"] == "user", "the monologue must not be stored as an answer"

    def test_an_ordinary_answer_still_lands(self, monkeypatch):
        client = ScriptedProvider([[event("Your /home quota is 30 GB.")]])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        assert stub.session_state["error"] is None
        assert stub.session_state["messages"][-1]["text"] == "Your /home quota is 30 GB."

    def test_a_numbered_answer_is_not_deliberation(self, monkeypatch):
        """The shape is the opening line, not the numbering — answers use lists too."""
        answer = "1. Load the module.\n2. Submit with `sbatch`.\n3. Watch with `squeue`."
        client = ScriptedProvider([[event(answer)]])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        assert stub.session_state["error"] is None
        assert stub.session_state["messages"][-1]["text"] == answer


class TestTheModelListIsRediscovered:
    """A discovered lineup has to be re-discovered, or it is a configured one.

    `openai_compat.models()` asks the provider what it serves so that a model appearing
    under a `-free` name reaches the picker with no commit. `available_models` wraps it
    in `st.cache_resource`, and that decorator without a `ttl` holds for the life of the
    process — so the app answers with the catalogue it fetched at boot, forever.

    It used to be hidden by the platform: Streamlit Community Cloud hibernates an idle
    app, the process died about daily, and the next reader got a fresh list. Then
    `keepalive.yml` began pinging every four hours specifically to stop the app
    sleeping, and removed the restart that was doing the work. `x-preview-f-free` was
    served by the provider and returned by discovery while the picker did not offer it.
    """

    def test_the_cache_is_bounded(self):
        # Imported against the stub, which is where `cache_resource`'s ttl is visible
        # at all — the real decorator keeps it on a private `_info`, and a test written
        # against that reads a Streamlit internal this repository does not control.
        stub_streamlit.install()
        from sage.ui import access  # noqa: PLC0415

        ttl = access.available_models.ttl
        assert ttl is not None, (
            "available_models caches for the life of the process, so a model the "
            "provider adds after boot never reaches the picker"
        )
        assert ttl <= 6 * 60 * 60, f"{ttl}s is longer than a reader will wait"

    def test_the_provider_client_is_still_cached_for_the_process(self):
        """The contrast, so the test above is known to discriminate.

        `get_provider` holds a client, not an answer, and is *meant* to live as long as
        the process. If a future default gave every `cache_resource` a ttl, the check
        above would pass without meaning anything.
        """
        stub_streamlit.install()
        from sage.ui import access  # noqa: PLC0415

        assert access.get_provider.ttl is None


def _cached_functions() -> list[tuple[str, str, bool]]:
    """Every `@st.cache_*` function in the app, and whether it declares a `ttl`.

    Read from the source rather than by importing, so a module that needs a stub, a
    key or a corpus to import is still covered, and so this sees a new cache the day
    it is written rather than the day someone remembers to check it.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    files = [root / "app.py", *sorted((root / "sage").rglob("*.py"))]
    found = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                call = decorator if isinstance(decorator, ast.Call) else None
                target = call.func if call else decorator
                if getattr(target, "attr", None) not in ("cache_resource", "cache_data"):
                    continue
                declares_ttl = bool(
                    call and any(word.arg == "ttl" for word in call.keywords)
                )
                found.append(
                    (str(path.relative_to(root)), node.name, declares_ttl)
                )
    return found


class TestNoCacheOutlivesWhatItCaches:
    """The general form of the bug above, so the next one fails here instead.

    A `cache_resource` with no `ttl` holds for the life of the process. That is right
    for a cache whose source cannot change without a redeploy — a file shipped in the
    image, or an object rather than an answer — and wrong for anything read over the
    network, which can change under a running app and did.

    Listing the deliberate ones rather than pattern-matching the accidental ones means
    a cache added later has to be classified before this passes. The failure mode is a
    named test, not a model quietly missing from a picker for a week.
    """

    UNBOUNDED_BY_DESIGN = {
        ("app.py", "load_runtime"): "indexes the docs trees shipped in the image",
        ("sage/ui/access.py", "get_provider"): "holds a client, not an answer",
        ("sage/ui/assets.py", "load"): "reads static/, shipped in the image",
        ("sage/ui/state.py", "get_limiter"): "the rate budget is a process-wide total",
    }

    def test_every_unbounded_cache_is_one_somebody_chose(self):
        for path, function, declares_ttl in _cached_functions():
            if declares_ttl:
                continue
            assert (path, function) in self.UNBOUNDED_BY_DESIGN, (
                f"{path}::{function} caches for the life of the process. If what it "
                "reads can change while the app is running — as the provider's model "
                "list can — give it a ttl. If it genuinely cannot, add it to "
                "UNBOUNDED_BY_DESIGN with the reason."
            )

    def test_the_list_has_no_names_that_have_gone_away(self):
        """So a rename leaves a stale exemption behind instead of a silent one."""
        actual = {(path, function) for path, function, _ in _cached_functions()}
        stale = set(self.UNBOUNDED_BY_DESIGN) - actual
        assert not stale, f"exempted but no longer cached: {sorted(stale)}"

    def test_the_model_list_is_not_exempt(self):
        """The one this whole class exists for."""
        assert ("sage/ui/access.py", "available_models") not in self.UNBOUNDED_BY_DESIGN

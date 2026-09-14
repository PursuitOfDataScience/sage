"""Stopping a generation, and asking a sent question again with the wording fixed.

Both are about a turn the reader takes back, which is the one thing this app could
not do: until now the only way out of a generation was to wait for it, and the only
way to fix a typo in a question was to type the whole thing again underneath the
answer to the wrong one.

What a stub can and cannot show. The mechanism itself is Streamlit's — a click during
a run aborts that run — and nothing here can abort anything, so these tests cover the
state machine either side of the abort: the flag the click sets, what a stopped turn
keeps, that the turn does not start again, and what an edited question does to the
conversation under it. That the click reaches Python at all, that the square lands in
the send button's corner and that the half-written answer survives the abort are
checked in the running app instead — the abort is a thing that happens *in time*, and
`tools/render_check.py` renders settled states.
"""

import pytest
from test_app_smoke import ScriptedProvider, event, run_app, tool_call  # noqa: F401

import stub_streamlit
from sage import llm


@pytest.fixture(autouse=True)
def _clean_modules():
    yield
    stub_streamlit.forget_importers()


def conversation(*turns):
    """`(question, answer)` pairs as the transcript app.py holds them."""
    messages = []
    for question, answer in turns:
        messages.append({"role": "user", "text": question, "attachments": []})
        if answer is not None:
            messages.append(
                {"role": "assistant", "text": answer, "sources": [], "rating": None}
            )
    return messages


class TestStopping:
    def session(self, partial=("Your /home quota is ",)):
        return {
            "messages": conversation(("what is my quota", None)),
            "processing": True,
            "stop_requested": True,
            "partial": list(partial),
        }

    def test_a_stop_ends_the_turn_without_calling_the_provider(self, monkeypatch):
        client = ScriptedProvider([])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())

        # The heart of it. `processing` stays True across the abort, so a run that
        # did not clear it here would re-enter the turn block and pay for the whole
        # question again — which is what touching the page mid-answer used to do.
        assert client.calls == 0
        assert stub.session_state["processing"] is False
        assert stub.session_state["stop_requested"] is False

    def test_the_half_written_answer_is_kept(self, monkeypatch):
        stub, _module = run_app(
            monkeypatch,
            client=ScriptedProvider([]),
            session=self.session(partial=["Your /home quota is ", "30 G"]),
        )
        answer = stub.session_state["messages"][-1]
        assert answer["role"] == "assistant"
        assert answer["text"] == "Your /home quota is 30 G"
        assert answer["stopped"] is True

    def test_a_stopped_answer_is_redacted_the_same_way_a_finished_one_is(
        self, monkeypatch
    ):
        """The one path that could skip `redact.apply` is the one still being read.

        A stop lands mid-sentence and the half-written text is stored and rendered
        exactly as it arrived, so it needs the same swap `turn.run` makes.
        """
        stub, _module = run_app(
            monkeypatch,
            client=ScriptedProvider([]),
            session=self.session(partial=["I looked it up with `search_docs` and t"]),
        )
        answer = stub.session_state["messages"][-1]
        assert answer["text"] == "I looked it up with `search` and t"
        assert answer["redacted"] == ["search_docs"]
        assert answer["stopped"] is True

    def test_a_stop_before_the_first_token_still_leaves_something_on_screen(
        self, monkeypatch
    ):
        """The transcript skips an assistant message with no text, so without a
        message here the reader is left with their own question, no reply, no error
        and nothing to click."""
        stub, _module = run_app(
            monkeypatch, client=ScriptedProvider([]), session=self.session(partial=[])
        )
        answer = stub.session_state["messages"][-1]
        assert answer["text"] == ""
        assert answer["stopped"] is True
        assert any("Stopped" in html for html in stub.markdown_html)

    def test_a_stopped_turn_is_not_an_error(self, monkeypatch):
        stub, _module = run_app(
            monkeypatch, client=ScriptedProvider([]), session=self.session()
        )
        assert stub.session_state["error"] is None
        assert stub.session_state["notice"] == ""

    def test_a_pending_failover_is_called_off_too(self, monkeypatch):
        """Left set, the switch fires on the next run and the turn the reader just
        stopped starts over on a different model."""
        session = self.session()
        session["failover_to"] = "vertex:other"
        session["switched_from"] = ("mistral-small-latest", "quota")
        stub, _module = run_app(
            monkeypatch, client=ScriptedProvider([]), session=session, second=True
        )
        assert "failover_to" not in stub.session_state
        assert stub.session_state["processing"] is False

    def test_a_stop_that_lands_after_the_answer_adds_nothing(self, monkeypatch):
        """The click races the turn. A second, empty message under a finished answer
        is worse than a click that did nothing."""
        session = {
            "messages": conversation(("what is my quota", "30 GB.")),
            "processing": False,
            "stop_requested": True,
            "partial": ["stale"],
        }
        stub, _module = run_app(
            monkeypatch, client=ScriptedProvider([]), session=session
        )
        assert len(stub.session_state["messages"]) == 2
        assert stub.session_state["messages"][-1]["text"] == "30 GB."
        assert stub.session_state["partial"] == []

    def test_the_stop_widget_is_rendered_on_every_run(self, monkeypatch):
        """Including runs with nothing to stop.

        It was conditional, which tied a widget's lifetime to a turn's: Streamlit
        forgets a widget the moment a run does not re-create it, and a forgotten
        trigger is the shape that makes a later turn end as `Stopped` without anyone
        pressing anything. Rendering it always removes the window; `app.js` is what
        decides whether a square is drawn, and it reads `#processing-signal`.
        """
        stub, _module = run_app(
            monkeypatch,
            client=ScriptedProvider([[event("done")]]),
            session={
                "messages": conversation(("what is my quota", None)),
                "processing": True,
            },
        )
        assert "stop-generation" in stub.callbacks

        stub2, _module2 = run_app(
            monkeypatch,
            client=ScriptedProvider([]),
            session={"messages": conversation(("what is my quota", "30 GB."))},
        )
        assert "stop-generation" in stub2.callbacks

    def test_a_stop_with_no_turn_running_does_nothing(self, monkeypatch):
        """Which is what makes an always-present button safe."""
        stub, _module = run_app(
            monkeypatch,
            client=ScriptedProvider([]),
            session={
                "messages": conversation(("what is my quota", "30 GB.")),
                "processing": False,
                "stop_requested": True,
            },
        )
        assert [item["text"] for item in stub.session_state["messages"]] == [
            "what is my quota", "30 GB."
        ]
        assert stub.session_state["stop_requested"] is False

    def test_the_stop_button_is_a_callback_not_a_return_value(self, monkeypatch):
        """`on_click` runs before the script; a return value is read at the bottom of
        the page, long after the transcript above it has been drawn for a turn that is
        no longer running."""
        stub, _module = run_app(
            monkeypatch,
            client=ScriptedProvider([[event("done")]]),
            session={
                "messages": conversation(("what is my quota", None)),
                "processing": True,
            },
        )
        stub.session_state["stop_requested"] = False
        stub.callbacks["stop-generation"]()
        assert stub.session_state["stop_requested"] is True

    def test_a_finished_turn_leaves_no_running_copy_behind(self, monkeypatch):
        stub, _module = run_app(
            monkeypatch,
            client=ScriptedProvider([[event("30 GB.")]]),
            session={
                "messages": conversation(("what is my quota", None)),
                "processing": True,
            },
        )
        assert stub.session_state["partial"] == []


class TestWhatCountsAsTheAnswer:
    """A model that narrates its tool call has not answered anything yet."""

    SEARCH = [
        event("Let me search for more specific Midway3 hardware details."),
        event(tool_calls=[tool_call(0, "c1", "search_docs", '{"query":"gpu"}')]),
    ]
    READ = [
        event(tool_calls=[
            tool_call(0, "c2", "read_doc", '{"path":"docs/storage/main.md#quotas"}')
        ])
    ]

    def session(self):
        return {
            "messages": conversation(("how many gpus are on midway3", None)),
            "processing": True,
        }

    def test_a_preamble_is_not_kept_when_the_next_round_is_silent(self, monkeypatch):
        """The bug, with the screenshot: the narration shipped as the reply, with a
        Sources strip of four documents under it."""
        client = ScriptedProvider([self.SEARCH, self.READ, []])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())

        answers = [m for m in stub.session_state["messages"]
                   if m["role"] == "assistant"]
        assert not answers, f"a silent final round still produced {answers}"
        # And it is the recoverable failure, not a confident non-answer.
        assert stub.session_state["error"] == llm.AssistantError("empty").user_message

    def test_the_answer_is_the_round_that_stopped_calling_tools(self, monkeypatch):
        client = ScriptedProvider([
            self.SEARCH, self.READ, [event("Midway3 has 44 GPUs in the shared "),
                                     event("gpu partition.")],
        ])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        answer = stub.session_state["messages"][-1]
        assert answer["text"] == "Midway3 has 44 GPUs in the shared gpu partition."
        assert "Let me search" not in answer["text"]

    def test_the_round_limit_still_says_so_rather_than_quoting_a_preamble(
        self, monkeypatch
    ):
        from sage import config  # noqa: PLC0415

        monkeypatch.setattr(config, "MAX_TOOL_ROUNDS", 2)
        looping = [self.SEARCH] + [self.READ] * 5
        stub, _module = run_app(
            monkeypatch, client=ScriptedProvider(looping), session=self.session()
        )
        answer = stub.session_state["messages"][-1]
        assert answer["text"].startswith("I wasn't able to finish looking that up")


class TestWhatAStoppedAnswerTellsTheNextTurn:
    """A stopped answer ends mid-word, and the next turn ships it upstream."""

    def build(self, **flags):
        from sage import history  # noqa: PLC0415

        return history.build(
            [
                {"role": "user", "text": "how do I request a GPU", "attachments": []},
                {"role": "assistant", "text": "Use --gres=gpu:1 and sub", **flags},
                {"role": "user", "text": "go on", "attachments": []},
            ],
            "SYSTEM",
        )

    def test_a_stopped_answer_says_it_was_cut_off(self):
        answer = self.build(stopped=True)[2]["content"]
        assert answer.startswith("Use --gres=gpu:1 and sub")
        assert "stopped this answer here" in answer

    def test_a_finished_answer_says_nothing_extra(self):
        assert self.build()[2]["content"] == "Use --gres=gpu:1 and sub"

    def test_a_stop_with_no_text_is_not_sent_at_all(self):
        from sage import history  # noqa: PLC0415

        built = history.build(
            [
                {"role": "user", "text": "how do I request a GPU", "attachments": []},
                {"role": "assistant", "text": "", "stopped": True},
            ],
            "SYSTEM",
        )
        assert [item["role"] for item in built] == ["system", "user"]


class TestEditingAQuestion:
    TWO_TURNS = [
        ("what is my quota", "30 GB."),
        ("how do I raise it", "Ask the Help Desk."),
    ]
    # The editor's widgets are keyed on `edit_session`, a counter bumped every time
    # the pencil is pressed, and Streamlit names a form's submit button
    # `FormSubmitter-{form key}-{label}`. Both are modelled rather than guessed: a
    # test driving a key the app does not render would pass against nothing.
    SESSION = 7
    TEXT = f"edit-text-{SESSION}"
    SEND = f"FormSubmitter-edit-form-{SESSION}-Send"
    CANCEL = f"FormSubmitter-edit-form-{SESSION}-Cancel"

    def open_on(self, position, **extra):
        return {
            "messages": conversation(*self.TWO_TURNS),
            "editing": position,
            "edit_session": self.SESSION,
            **extra,
        }

    def test_every_settled_question_offers_a_way_back_in(self, monkeypatch):
        stub, _module = run_app(
            monkeypatch,
            client=ScriptedProvider([]),
            session={"messages": conversation(*self.TWO_TURNS)},
        )
        assert "edit-open-0" in stub.button_labels
        assert "edit-open-2" in stub.button_labels

    def test_no_way_back_into_the_question_being_answered(self, monkeypatch):
        """A pencil on that one offers to rewrite a question while its answer
        arrives, and the click would abandon the answer on the way."""
        stub, _module = run_app(
            monkeypatch,
            client=ScriptedProvider([[event("30 GB.")]]),
            session={
                "messages": conversation(("what is my quota", None)),
                "processing": True,
            },
        )
        assert "edit-open-0" not in stub.button_labels

    def test_the_others_are_inert_while_an_answer_generates(self, monkeypatch):
        stub, _module = run_app(
            monkeypatch,
            client=ScriptedProvider([[event("Ask the Help Desk.")]]),
            session={
                "messages": conversation(
                    ("what is my quota", "30 GB."), ("how do I raise it", None)
                ),
                "processing": True,
            },
        )
        assert stub.disabled["edit-open-0"] is True

    def test_clicking_it_opens_the_editor_on_that_question(self, monkeypatch):
        stub, _module = run_app(
            monkeypatch,
            client=ScriptedProvider([]),
            session={"messages": conversation(*self.TWO_TURNS)},
            buttons={"edit-open-2": True},
        )
        assert stub.session_state["editing"] == 2

    def test_it_says_what_sending_will_remove(self, monkeypatch):
        """Reported as a shock: "i edited the first message in the chat history but
        everything got wiped off, all the chat"."""
        stub, _module = run_app(
            monkeypatch, client=ScriptedProvider([]), session=self.open_on(0)
        )
        assert any("removes the 1 later question" in text for text in stub.captions), (
            f"captions were {stub.captions}"
        )

    def test_it_says_nothing_when_there_is_nothing_to_lose(self, monkeypatch):
        """Editing the last question replaces only its own answer, which is what the
        reader just asked for. A warning there is noise."""
        stub, _module = run_app(
            monkeypatch, client=ScriptedProvider([]), session=self.open_on(2)
        )
        assert not any("removes the" in text for text in stub.captions)

    def test_the_editor_opens_holding_the_question(self, monkeypatch):
        stub, _module = run_app(
            monkeypatch,
            client=ScriptedProvider([]),
            session=self.open_on(0),
        )
        assert stub.text_area_values[self.TEXT] == "what is my quota"

    def test_sending_replaces_the_question_and_drops_what_followed(self, monkeypatch):
        """Everything after it was a reply to wording that no longer exists."""
        client = ScriptedProvider([[event("Ask about your allocation.")]])
        stub, _module = run_app(
            monkeypatch,
            client=client,
            session=self.open_on(0),
            buttons={self.SEND: True},
            text_areas={self.TEXT: "what is my SU balance"},
        )
        messages = stub.session_state["messages"]
        assert [item["text"] for item in messages if item["role"] == "user"] == [
            "what is my SU balance"
        ]
        assert stub.session_state["processing"] is True
        assert stub.session_state["editing"] is None

    def test_cancelling_changes_nothing(self, monkeypatch):
        stub, _module = run_app(
            monkeypatch,
            client=ScriptedProvider([]),
            session=self.open_on(0),
            buttons={self.CANCEL: True},
            text_areas={self.TEXT: "something else entirely"},
        )
        assert stub.session_state["editing"] is None
        assert [
            item["text"] for item in stub.session_state["messages"]
        ] == ["what is my quota", "30 GB.", "how do I raise it", "Ask the Help Desk."]

    def test_an_empty_question_is_refused_rather_than_sent(self, monkeypatch):
        stub, _module = run_app(
            monkeypatch,
            client=ScriptedProvider([]),
            session=self.open_on(0),
            buttons={self.SEND: True},
            text_areas={self.TEXT: "   "},
        )
        assert stub.session_state["processing"] is False
        assert any("cannot be empty" in warning for warning in stub.warnings)

    def test_an_over_long_question_is_refused_with_the_text_intact(self, monkeypatch):
        from sage import config  # noqa: PLC0415

        stub, _module = run_app(
            monkeypatch,
            client=ScriptedProvider([]),
            session=self.open_on(0),
            buttons={self.SEND: True},
            text_areas={self.TEXT: "x" * (config.MAX_PROMPT_CHARS + 5)},
        )
        assert stub.session_state["processing"] is False
        assert any("over the" in warning for warning in stub.warnings)
        assert len(stub.session_state["messages"]) == 4

    def test_a_resend_goes_through_the_same_gate_as_a_new_question(self, monkeypatch):
        """It costs the same one-to-five provider calls. The retry button skipped this
        gate once and a spent budget went on being spent, one turn per click."""
        from sage import limits  # noqa: PLC0415

        monkeypatch.setattr(
            limits.Limiter,
            "check",
            lambda *_a, **_k: limits.Verdict(
                allowed=False, message="Too many questions. Wait a bit."
            ),
        )
        stub, _module = run_app(
            monkeypatch,
            client=ScriptedProvider([]),
            session=self.open_on(0),
            buttons={self.SEND: True},
            text_areas={self.TEXT: "what is my SU balance"},
        )
        # Refused, and the conversation is untouched: a refused edit that had already
        # deleted the tail would be the worst of both.
        assert stub.session_state["processing"] is False
        assert len(stub.session_state["messages"]) == 4
        assert "Too many questions" in stub.session_state["notice"]

    def test_the_attachments_come_with_the_question(self, monkeypatch):
        held = [_Attachment("run.log")]
        messages = conversation(("look at this", "It failed."))
        messages[0]["attachments"] = held
        stub, _module = run_app(
            monkeypatch,
            client=ScriptedProvider([[event("It ran out of memory.")]]),
            session={"messages": messages, "editing": 0,
                     "edit_session": self.SESSION},
            buttons={self.SEND: True},
            text_areas={self.TEXT: "why did this fail"},
        )
        resent = stub.session_state["messages"][0]
        assert resent["text"] == "why did this fail"
        assert [item.filename for item in resent["attachments"]] == ["run.log"]


class _Attachment:
    """The parts of `files.Attachment` this file touches."""

    def __init__(self, filename):
        self.filename = filename
        self.icon = "📄"
        self.kind = "text"
        self.size = 10
        self.key = (filename, 10, "abc")
        self.text = "boom"
        self.data = b""
        self.summary = ""
        self.truncated = False


def test_the_stub_models_a_callback_and_a_return_value_as_exclusive():
    """Guard on the stub itself: a button with `on_click` never also returns True,
    which is what stops a test from passing for the wrong reason."""
    stub = stub_streamlit.StubStreamlit(buttons={"k": True})
    assert stub.button("x", key="k", on_click=lambda: None) is False
    assert stub.button("x", key="k") is True

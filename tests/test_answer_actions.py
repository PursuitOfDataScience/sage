"""The row of icons under an answer: copy it, run it again, shorter, longer.

What a stub can and cannot show, which is the division `test_turn_control.py` draws.
The controls the reader presses do not exist in Python at all — `app.js` injects them,
and `tools/render_check.py` runs the real `app.js` against a replica of Streamlit's DOM
and measures where the four land. What is here is the other half: the words the profile
supplies, the three clipped widgets a click arrives on, and what each one does to the
conversation.

The thing worth saying once, because it is what makes an icon safe: all three re-asks
REPLACE the answer, by re-sending the question with `replacing=`. So they are offered
on the last answer only, where there is nothing after it to lose. An icon cannot carry
the sentence `render_user_editor` has to print before it truncates a conversation, and
the design is not to need one.
"""

import pytest
from test_app_smoke import ScriptedProvider, event, run_app

import stub_streamlit
from sage import files, prompts
from sage.profile import Copy


@pytest.fixture(autouse=True)
def _clean_modules():
    yield
    stub_streamlit.forget_importers()


ASKED = "How do I request a GPU for a batch job?"


def conversation(answer="Add --gres=gpu:1 to your script.", **extra):
    """One finished turn, as `app.py` holds it."""
    message = {"role": "assistant", "text": answer, "sources": [], "rating": None}
    message.update(extra)
    return [{"role": "user", "text": ASKED, "attachments": []}, message]


def html_of(stub):
    """Every `st.markdown` on the page, collapsed — the source wraps these."""
    return " ".join("\n".join(stub.markdown_html).split())


def state_under(stub):
    """`sage.ui.state`, imported after the stub is in place and not before."""
    from sage.ui import state  # noqa: PLC0415

    return state


class TestTheWireAndTheWords:
    """What Python draws so `app.js` has something to label and something to click."""

    def test_the_hover_strings_reach_the_page(self, monkeypatch):
        stub, _ = run_app(monkeypatch, session={"messages": conversation()})
        page = html_of(stub)
        assert 'id="answer-acts"' in page
        # Read from the profile, not written out: a deployment that changes its voice
        # changes these, and a literal here would go on passing.
        for attribute, value in (
            ("data-copy", Copy().copy_hint),
            ("data-again", Copy().again_hint),
            ("data-shorter", Copy().shorter_hint),
            ("data-longer", Copy().longer_hint),
        ):
            assert f'{attribute}="{value}"' in page, attribute

    def test_all_three_re_asks_have_a_widget_behind_them(self, monkeypatch):
        stub, _ = run_app(monkeypatch, session={"messages": conversation()})
        for key in ("again", "shorter", "longer"):
            assert key in stub.button_labels, key

    def test_the_label_on_the_wire_is_the_words_the_reader_gets(self, monkeypatch):
        """The hook is clipped to a pixel and out of the tab order, so its label is
        only ever an accessible name — and it should be the same sentence `app.js`
        puts on the control that is actually pressed, not a second wording to keep
        in step with it."""
        stub, _ = run_app(monkeypatch, session={"messages": conversation()})
        assert stub.button_labels["shorter"] == Copy().shorter_hint

    def test_the_words_are_there_without_the_wires(self, monkeypatch):
        """A copy button is on every answer; the re-asks are on one.

        So the words are drawn whenever a conversation is, and `app.js` keys the three
        re-asks on the HOOKS being present instead — otherwise there is a state where
        it has a label for a button it has no wire for.
        """
        stub, _ = run_app(
            monkeypatch,
            session={
                "messages": conversation()
                + [{"role": "user", "text": "and interactively?", "attachments": []}],
                "processing": True,
            },
        )
        assert 'id="answer-acts"' in html_of(stub)
        assert "again" not in stub.button_labels

    def test_nothing_is_offered_while_an_error_card_is_up(self, monkeypatch):
        """The card offers "Try again" over the same turn, and two of those is one
        too many — the second would be the one that also drops the question."""
        stub, _ = run_app(
            monkeypatch,
            session={
                "messages": conversation(),
                "error": "The assistant is temporarily unavailable.",
            },
        )
        assert "again" not in stub.button_labels

    def test_a_stopped_answer_still_gets_them(self, monkeypatch):
        """An answer the reader cut off because it rambled is exactly when "shorter"
        is the remedy — unlike 👍/👎, which `render_assistant` suppresses there
        because rating half a sentence says nothing about the app."""
        stub, _ = run_app(
            monkeypatch,
            session={"messages": conversation(answer="Add --gres", stopped=True)},
        )
        assert "shorter" in stub.button_labels

    def test_an_answer_stopped_before_its_first_token_gets_none(self, monkeypatch):
        """There is no answer to run again, shorten or lengthen — only a question
        with the word `Stopped` under it. `app.js` withholds the copy button on the
        same test, for the same reason: a control that can only disappoint."""
        stub, _ = run_app(
            monkeypatch,
            session={"messages": conversation(answer="", stopped=True)},
        )
        assert "again" not in stub.button_labels

    def test_nothing_is_offered_before_the_first_question(self, monkeypatch):
        stub, _ = run_app(monkeypatch)
        assert "again" not in stub.button_labels
        assert 'id="answer-acts"' not in html_of(stub)


class TestWhatEachOneAsksFor:
    @pytest.mark.parametrize(
        ("key", "steer"),
        [("again", ""), ("shorter", "shorter"), ("longer", "longer")],
    )
    def test_the_question_is_re_sent_and_the_answer_replaced(
        self, monkeypatch, key, steer
    ):
        stub, _ = run_app(
            monkeypatch, buttons={key: True}, session={"messages": conversation()}
        )
        messages = stub.session_state["messages"]
        assert [message["role"] for message in messages] == ["user"], (
            "the answer is replaced, not added to: the question goes back on its own "
            "and the turn runs again under it"
        )
        assert messages[0]["text"] == ASKED
        assert stub.session_state["processing"] is True
        assert stub.session_state["steer"] == steer

    def test_the_attachments_go_back_with_the_question(self, monkeypatch):
        """They belong to the question, not to the text of it — the same reason the
        editor carries them through a rewording."""
        attached = files.Attachment(
            filename="job.sbatch", text="#SBATCH --gres=gpu:1", kind="text"
        )
        messages = conversation()
        messages[0]["attachments"] = [attached]
        stub, _ = run_app(
            monkeypatch, buttons={"shorter": True}, session={"messages": messages}
        )
        assert stub.session_state["messages"][0]["attachments"] == [attached]

    def test_an_allowed_re_ask_runs(self, monkeypatch):
        """Through `start_new_turn`, so through `may_start_turn` — and the gate must
        not break the button it guards."""
        stub, _ = run_app(
            monkeypatch, buttons={"longer": True}, session={"messages": conversation()}
        )
        assert stub.session_state["processing"] is True

    def test_a_refused_re_ask_leaves_the_answer_on_screen(self, monkeypatch):
        """`state.may_start_turn` records what happened when a re-run path skipped
        it: a deployment whose call budget was spent refused new questions while the
        button went on making requests, one per click.

        Truncating and then declining to replace is the shape of a broken app, so the
        gate is checked before any state is touched — and a steer must not be left set
        with no turn to carry it.
        """
        stub = stub_streamlit.install()
        state = state_under(stub)
        stub.session_state.update({"messages": conversation(), "steer": ""})
        monkeypatch.setattr(state, "may_start_turn", lambda: False)
        with pytest.raises(stub_streamlit.Rerun):
            state.start_new_turn(ASKED, [], replacing=0, steer="shorter")
        assert stub.session_state["messages"] == conversation()
        assert stub.session_state["steer"] == ""


class TestTheSteerBelongsToOneTurn:
    def test_an_ordinary_question_clears_it(self, monkeypatch):
        stub, _ = run_app(
            monkeypatch,
            chat_input="what about interactive jobs?",
            session={"messages": conversation(), "steer": "shorter"},
        )
        assert stub.session_state["steer"] == "", (
            "a steer that outlived its turn would shorten every answer after it"
        )

    def test_an_edited_question_clears_it(self):
        """`start_new_turn`'s keyword defaults to "", so every caller that says
        nothing clears it. That is what makes "an ordinary question is not steered"
        true by construction rather than by five call sites remembering to."""
        stub = stub_streamlit.install()
        state = state_under(stub)
        state.initialise()
        stub.session_state.update({"messages": conversation(), "steer": "longer"})
        with pytest.raises(stub_streamlit.Rerun):
            state.start_new_turn("fixed wording", [], replacing=0)
        assert stub.session_state["steer"] == ""

    def test_leaving_a_conversation_clears_it(self):
        stub = stub_streamlit.install()
        state = state_under(stub)
        state.initialise()
        stub.session_state["steer"] = "longer"
        state._leave_conversation()
        assert stub.session_state["steer"] == "", (
            "it was asked of a turn in the chat being left, so it must not follow "
            "the reader into the one they opened"
        )

    def test_stopping_a_turn_clears_it(self):
        """A stop leaves the answer on screen with the row under it, so a steer left
        set here would be picked up by whatever ran next."""
        stub = stub_streamlit.install()
        state = state_under(stub)
        state.initialise()
        stub.session_state.update(
            {
                "messages": [{"role": "user", "text": ASKED, "attachments": []}],
                "processing": True,
                "partial": ["Add "],
                "steer": "shorter",
            }
        )
        state.finish_stopped_turn("google:m1")
        assert stub.session_state["steer"] == ""

    def test_it_is_a_session_default(self):
        stub = stub_streamlit.install()
        state = state_under(stub)
        assert ("steer", "") in state.SESSION_DEFAULTS


class TestTheSteerReachesTheRequest:
    """It is appended to the message list, and where it is appended is the point."""

    def turn(self, monkeypatch, steer):
        provider = ScriptedProvider([[event("Add --gres=gpu:1.")]])
        run_app(
            monkeypatch,
            client=provider,
            session={
                "messages": [{"role": "user", "text": ASKED, "attachments": []}],
                "processing": True,
                "steer": steer,
            },
        )
        assert provider.calls == 1, "one request, so one message list to look at"
        return provider.sent[0]

    def test_it_is_the_last_thing_the_model_reads(self, monkeypatch):
        """At the END of the list, not at index 1 beside the system prompt, for the
        reason `prompts.last_round_instruction` is appended where it is: a rule about
        the shape of the answer has to be the last thing read before one is written.
        Index 1 puts it behind the whole conversation, which on a long chat is where
        instructions go to be outvoted."""
        sent = self.turn(monkeypatch, "shorter")
        assert sent[-1]["role"] == "system"
        assert sent[-1]["content"] == prompts.length_instruction("shorter")
        assert sent[-2]["role"] == "user", "and the question is still above it"

    def test_an_unsteered_turn_carries_nothing(self, monkeypatch):
        sent = self.turn(monkeypatch, "")
        assert sent[-1]["role"] == "user"
        assert not any(
            "more briefly" in message.get("content", "") for message in sent
        )

    def test_a_steered_turn_clears_it_on_the_way_out(self, monkeypatch):
        """The turn has now done what it was asked, so the next one is not asked it.

        Cleared on the SUCCESS commit rather than in the `finally`, because the reroll
        and failover paths go through that on their way to asking again — a turn
        rescued onto another model is still the turn the reader asked to be shorter,
        and has to stay shorter.
        """
        provider = ScriptedProvider([[event("Add --gres=gpu:1.")]])
        stub, _ = run_app(
            monkeypatch,
            client=provider,
            session={
                "messages": [{"role": "user", "text": ASKED, "attachments": []}],
                "processing": True,
                "steer": "longer",
            },
        )
        assert stub.session_state["steer"] == ""


class TestTheInstructionItself:
    def test_an_unknown_mode_says_nothing(self):
        """A stale `steer`, from a session left open across a deployment, must not
        put a fragment of this into a request."""
        for mode in ("", "brief", "SHORTER"):
            assert prompts.length_instruction(mode) == "", mode

    @pytest.mark.parametrize("mode", ["shorter", "longer"])
    def test_both_modes_keep_the_citations(self, mode):
        """A length rule reads as a licence to drop the apparatus, and the apparatus
        is what this app is for: `links.mark_sources` numbers each claim's marker
        against the strip below it, so an answer that stops writing `[Title](path)`
        loses the markers and the strip together."""
        said = prompts.length_instruction(mode)
        assert "[Title](path)" in said
        assert "no Sources list" in said

    @pytest.mark.parametrize("mode", ["shorter", "longer"])
    def test_neither_mode_may_mention_the_change(self, mode):
        """"Here is a shorter version" tells the reader about an instruction they
        cannot see, which is `prompts.SELF_DISCLOSURE`'s whole subject."""
        said = prompts.length_instruction(mode)
        assert "do not mention being asked for anything" in said
        assert "as if it were the only one" in said

    def test_longer_may_not_invent_anything(self):
        """The mode that can do real damage: told to write more about a corpus that
        says three sentences, a model will write more anyway. The honest alternative
        is `last_round_instruction`'s — answer what is covered, name what is not."""
        said = prompts.length_instruction("longer")
        assert "never invent" in said
        assert "not covered" in said

    def test_shorter_does_not_licence_dropping_steps(self):
        said = prompts.length_instruction("shorter")
        assert "brevity that drops half the instructions is not brevity" in said

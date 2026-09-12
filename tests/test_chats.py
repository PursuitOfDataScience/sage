"""The sidebar of conversations: what a chat is called, and what switching one costs.

The state here is the one part of this feature that can go wrong quietly. `messages` is
rebound in three places — an edited question truncates it, a clear replaces it, opening
a chat swaps it — so a record that merely aliased the live list would come unstuck from
it and the sidebar would go on listing a conversation nobody can open any more. These
hold the stash-and-load contract that avoids that, plus the two things a reader would
notice first: that a chat is named after its own first question, and that switching one
cannot happen underneath a streaming answer.
"""

import pytest
from test_app_smoke import run_app

import stub_streamlit


@pytest.fixture(autouse=True)
def _clean_modules():
    yield
    stub_streamlit.forget_importers()


def _state():
    """The state module, imported under an installed stub."""
    from sage.ui import state  # noqa: PLC0415

    return state


class TestChatTitle:
    def test_a_chat_is_named_after_its_first_question(self, monkeypatch):
        run_app(monkeypatch)
        state = _state()
        messages = [
            {"role": "user", "text": "How do I submit a GPU job?"},
            {"role": "assistant", "text": "With sbatch."},
            {"role": "user", "text": "And a second question"},
        ]
        assert state.chat_title(messages, "New chat") == "How do I submit a GPU job?"

    def test_an_empty_chat_takes_the_profile_word_for_it(self, monkeypatch):
        run_app(monkeypatch)
        state = _state()
        assert state.chat_title([], "New chat") == "New chat"
        # An assistant-only tail is not a question, and neither is a blank one.
        assert state.chat_title([{"role": "assistant", "text": "hi"}], "x") == "x"
        assert state.chat_title([{"role": "user", "text": "   "}], "x") == "x"

    def test_a_long_question_is_cut_at_a_word(self, monkeypatch):
        run_app(monkeypatch)
        state = _state()
        asked = (
            "How do I ask for four A100s and eighty gigabytes of memory on the "
            "beagle3 partition"
        )
        title = state.chat_title([{"role": "user", "text": asked}], "New chat")
        assert title.endswith("…")
        assert len(title) <= state.TITLE_CHARS + 1
        # Cut between words, not through one: the label is read, not parsed.
        assert not title[:-1].endswith(" ")
        assert asked.startswith(title[:-1])

    def test_newlines_do_not_become_a_multi_line_label(self, monkeypatch):
        """A pasted traceback is a perfectly ordinary first question."""
        run_app(monkeypatch)
        state = _state()
        title = state.chat_title(
            [{"role": "user", "text": "line one\nline two\n\nline three"}], "New chat"
        )
        assert "\n" not in title
        assert title.startswith("line one line two")


class TestSwitchingChats:
    def test_a_session_starts_with_one_chat(self, monkeypatch):
        stub, module = run_app(monkeypatch)
        assert module is not None
        assert len(stub.session_state.chats) == 1
        assert stub.session_state.chat_id == stub.session_state.chats[0]["id"]

    def test_new_chat_puts_the_old_one_away_and_opens_an_empty_one(self, monkeypatch):
        stub, _ = run_app(
            monkeypatch,
            session={
                "messages": [
                    {"role": "user", "text": "first", "attachments": []},
                    {"role": "assistant", "text": "answer", "sources": []},
                ]
            },
        )
        state = _state()
        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()

        assert stub.session_state.messages == []
        assert len(stub.session_state.chats) == 2
        stashed = stub.session_state.chats[0]["messages"]
        assert [item["text"] for item in stashed] == ["first", "answer"]
        assert stub.session_state.chat_id == stub.session_state.chats[1]["id"]

    def test_the_stash_is_not_an_alias_of_the_live_list(self, monkeypatch):
        """The whole reason the records hold their own list.

        `start_new_turn` truncates `messages` by rebinding it, so a record holding the
        same object would follow the live conversation around. Asking the same question
        of the reverse direction: what is put away must not move when what replaces it
        does.
        """
        stub, _ = run_app(
            monkeypatch,
            session={"messages": [{"role": "user", "text": "kept", "attachments": []}]},
        )
        state = _state()
        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()
        stub.session_state.messages.append(
            {"role": "user", "text": "in the new chat", "attachments": []}
        )
        assert [item["text"] for item in stub.session_state.chats[0]["messages"]] == [
            "kept"
        ]

    def test_new_chat_always_opens_one(self, monkeypatch):
        """It used to refuse on an empty conversation, so that ten presses could not
        leave ten identical blank rows — and what that read as was a dead button: "when
        clicking +new chat button, it doesn't work until a new prompt is entered in that
        session". It always opens one now, and `_stash` drops the blank being left, so
        the list still cannot fill up."""
        stub, _ = run_app(monkeypatch)
        state = _state()
        first = stub.session_state.chat_id

        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()
        assert stub.session_state.chat_id != first
        assert len(stub.session_state.chats) == 1     # the blank one went with it

        second = stub.session_state.chat_id
        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()
        assert stub.session_state.chat_id != second
        assert len(stub.session_state.chats) == 1

    def test_leaving_an_empty_conversation_drops_it(self, monkeypatch):
        """A conversation with nothing asked in it is not one, and a panel that keeps
        them fills with `Nothing asked yet` rows — one of which is visible in the
        reader's screenshot beside the chat they were actually in."""
        stub, _ = run_app(
            monkeypatch,
            session={"messages": [{"role": "user", "text": "asked", "attachments": []}]},
        )
        state = _state()
        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()
        assert len(stub.session_state.chats) == 2     # the asked one, and the new blank
        blank = stub.session_state.chat_id

        # Going back to the one with a question in it drops the blank.
        target = next(r["id"] for r in stub.session_state.chats if r["id"] != blank)
        with pytest.raises(stub_streamlit.Rerun):
            state.open_chat(target)
        assert [r["id"] for r in stub.session_state.chats] == [target]
        assert [m["text"] for m in stub.session_state.messages] == ["asked"]

    def test_opening_a_chat_swaps_the_conversation_both_ways(self, monkeypatch):
        stub, _ = run_app(
            monkeypatch,
            session={"messages": [{"role": "user", "text": "one", "attachments": []}]},
        )
        state = _state()
        first = stub.session_state.chat_id
        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()
        stub.session_state.messages.append(
            {"role": "user", "text": "two", "attachments": []}
        )
        second = stub.session_state.chat_id

        with pytest.raises(stub_streamlit.Rerun):
            state.open_chat(first)
        assert [item["text"] for item in stub.session_state.messages] == ["one"]
        with pytest.raises(stub_streamlit.Rerun):
            state.open_chat(second)
        assert [item["text"] for item in stub.session_state.messages] == ["two"]

    def test_opening_the_chat_already_open_does_nothing(self, monkeypatch):
        """Not even a rerun: it is not a switch, and a rerun would throw away the
        answer streaming into the page it is on."""
        stub, _ = run_app(monkeypatch)
        state = _state()
        state.open_chat(stub.session_state.chat_id)   # no Rerun raised

    def test_a_switch_leaves_nothing_of_the_previous_turn_behind(self, monkeypatch):
        """Every one of these belongs to the conversation being left, and a leftover
        is worse than a missing one: a failover still pending re-asks a question from
        the closed chat into the one that replaced it."""
        stub, _ = run_app(
            monkeypatch,
            session={
                "messages": [{"role": "user", "text": "q", "attachments": []}],
                "processing": True,
                "partial": ["half an ans"],
                "error": "something went wrong",
                "error_detail": "detail",
                "notice": "switched to X",
                "tried": ["mistral:m1"],
                "editing": 0,
                "dropped_uploads": {"k": 1},
                "upload_refusals": {"k": "too big"},
                "failover_to": "mistral:m2",
            },
        )
        state = _state()
        # Set after the run: `uploads.render()` reads the real shape out of this list
        # on the way past, and the test is about what a switch clears, not about what
        # an attachment is.
        stub.session_state.attachments = ["a file"]
        before = stub.session_state.uploader_key, stub.session_state.clear_token
        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()

        assert stub.session_state.processing is False
        assert stub.session_state.partial == []
        assert stub.session_state.error is None
        assert stub.session_state.error_detail == ""
        assert stub.session_state.notice == ""
        assert stub.session_state.tried == []
        assert stub.session_state.editing is None
        assert stub.session_state.attachments == []
        assert stub.session_state.dropped_uploads == {}
        assert stub.session_state.upload_refusals == {}
        assert "failover_to" not in stub.session_state
        # The uploader is reset and the composer emptied, which only app.js can do.
        assert stub.session_state.uploader_key == before[0] + 1
        assert stub.session_state.clear_token == before[1] + 1


class TestTheSidebar:
    def test_it_is_drawn_before_the_body(self, monkeypatch):
        """A control in it ends in `st.rerun()`, so a conversation drawn first is a
        conversation rendered to be thrown away."""
        stub, module = run_app(monkeypatch)
        assert module is not None
        kinds = [name for name, _ in stub.events]
        assert "sidebar" in kinds
        assert kinds.index("sidebar") < kinds.index("chat_input")

    def test_an_empty_session_names_the_conversation_not_yet_started(self, monkeypatch):
        """The panel a reader opens on the landing screen: New chat, the label, and one
        row for the conversation they have not asked anything in yet. Nothing greyed
        out, and the row does not share the button's words."""
        stub, _ = run_app(monkeypatch)
        chat_id = stub.session_state.chat_id
        assert stub.disabled["new-chat"] is False
        assert stub.button_labels[f"chat-name-{chat_id}"] == "Nothing asked yet"
        assert stub.disabled[f"chat-name-{chat_id}"] is False

    def test_a_chat_with_a_question_in_it_is_named_after_it(self, monkeypatch):
        stub, _ = run_app(
            monkeypatch,
            session={
                "messages": [
                    {"role": "user", "text": "How do I load a module?",
                     "attachments": []}
                ]
            },
        )
        chat_id = stub.session_state.chat_id
        assert stub.button_labels[f"chat-name-{chat_id}"] == "How do I load a module?"
        # And now there is a conversation to leave.
        assert "New chat" in stub.button_labels["new-chat"]
        assert stub.disabled["new-chat"] is False

    def test_no_mark_is_spent_on_saying_which_row_is_open(self, monkeypatch):
        """The stylesheet says it with a rule down the row's left edge. A ●/○ pair in
        the label said the same thing in the least legible way available, and it cost
        two characters of a title that ellipses at thirty-four."""
        stub, _ = run_app(
            monkeypatch,
            session={"messages": [{"role": "user", "text": "q", "attachments": []}]},
        )
        chat_id = stub.session_state.chat_id
        assert stub.button_labels[f"chat-name-{chat_id}"] == "q"

    def test_the_open_chat_can_be_clicked(self, monkeypatch):
        """It used to be `disabled`, which Streamlit draws greyed and with a
        not-allowed cursor — "grey and a weird forbidden sign". Clicking the
        conversation you are already in changes nothing, so there was nothing to
        protect; `open_chat` returns on it."""
        stub, _ = run_app(monkeypatch)
        chat_id = stub.session_state.chat_id
        assert stub.disabled[f"chat-name-{chat_id}"] is False
        assert stub.disabled[f"chat-act-{chat_id}"] is False

    def test_the_open_row_is_keyed_apart_from_the_rest(self, monkeypatch):
        """The one thing the stylesheet can read, and why it is not `disabled`.

        Every row is disabled while an answer is arriving, so a rule keyed on that
        emphasised the whole list and it stopped saying which chat the reader was in.
        The row's container key carries the state instead. Held here because it is a
        contract between this module and three selectors in `static/app.css`, and
        nothing else would notice it being dropped.
        """
        stub, _ = run_app(
            monkeypatch,
            session={
                "chats": [{"id": 0, "messages": []}, {"id": 1, "messages": []}],
                "chat_id": 1,
                "next_chat_id": 2,
                "messages": [{"role": "user", "text": "q", "attachments": []}],
            },
        )
        rows = [
            key for name, key in stub.events
            if name == "container" and isinstance(key, str)
            and key.startswith("chat-row-")
        ]
        assert rows == ["chat-row-open-1", "chat-row-past-0"]

    def test_the_panel_works_while_an_answer_is_arriving(self, monkeypatch):
        """Nothing is inert mid-answer, and that is the point.

        Every control here was `disabled` for the length of a turn, because a click on
        any Streamlit widget aborts the run that is streaming. What that bought was a
        panel a reader could not use exactly when they wanted to: "you can't create a
        new chat when the current session is generating the answer, which is
        problematic", and the same for switching. The click still ends the turn — there
        is no version where it does not — so what changed is that the turn now ends
        well. See `sidebar.leave`.
        """
        stub, _ = run_app(
            monkeypatch,
            session={
                "chats": [{"id": 0, "messages": []}, {"id": 1, "messages": []}],
                "chat_id": 1,
                "next_chat_id": 2,
                "messages": [{"role": "user", "text": "q", "attachments": []}],
                "processing": True,
            },
        )
        live = [
            key for key in stub.disabled
            if key == "new-chat" or key.startswith(("chat-name-", "chat-act-"))
        ]
        assert len(live) == 5, live          # New chat, plus a name and a ✕ per row
        for key in live:
            assert stub.disabled[key] is False, key

    def test_abandoning_a_turn_that_produced_nothing_keeps_the_question(
        self, monkeypatch
    ):
        """Three reports meet on this path and one state satisfies all of them.

        The reader's third screenshot was a question with the bare word `Stopped` under
        it and no answer: `finish_stopped_turn` appends that empty message on purpose,
        because someone who pressed Stop has to see that something happened, and someone
        who walked off to another chat is not looking at that screen. So nothing is
        appended here.

        Dropping the question as well — what this used to do — cost the conversation
        itself: `_stash` prunes a conversation with no messages, so a chat the reader had
        just made and just typed into vanished out of the panel behind them. "the new
        chat session will disappear. this is very confusing and annoying."

        The question stays. No assistant message, so no `Stopped`; a conversation with a
        message in it, so nothing to prune and no spare `Nothing asked yet` row; and the
        chat is still there, named after the question.
        """
        stub, module = run_app(
            monkeypatch,
            session={"messages": [{"role": "user", "text": "the question",
                                   "attachments": []}]},
        )
        from sage.ui import sidebar  # noqa: PLC0415

        stub.session_state.processing = True
        stub.session_state.partial = []          # not one token arrived
        sidebar.leave(module.VIEW)

        assert [m["text"] for m in stub.session_state.messages] == ["the question"]
        assert [m["role"] for m in stub.session_state.messages] == ["user"]
        assert stub.session_state.processing is False
        # And the conversation survives being left, because it is not a blank.
        state = _state()
        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()
        assert len(stub.session_state.chats) == 2

    def test_leaving_mid_answer_keeps_what_had_arrived(self, monkeypatch):
        """The half-written answer goes to the conversation it belongs to, marked
        `stopped`, rather than being dropped on the floor — the transcript then shows a
        part-answer with a note saying so instead of a question with nothing under it.

        `_leave_conversation` empties `partial`, so this only works because the commit
        happens first. That ordering is the whole of `sidebar.leave`.
        """
        stub, module = run_app(
            monkeypatch,
            session={
                "messages": [{"role": "user", "text": "the question", "attachments": []}],
            },
        )
        assert module is not None
        from sage.ui import sidebar  # noqa: PLC0415

        # Set after the run rather than in `session`: with `processing` already true the
        # app reaches `turn.run` on import, which needs a scripted provider it has no
        # reason to have here. What is under test is the moment the reader clicks, and
        # this is that state.
        stub.session_state.processing = True
        stub.session_state.partial = ["half an ", "answer"]
        sidebar.leave(module.VIEW)
        state = _state()
        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()

        kept = stub.session_state.chats[0]["messages"]
        assert [item["text"] for item in kept] == ["the question", "half an answer"]
        assert kept[-1]["stopped"] is True
        assert stub.session_state.messages == []
        assert stub.session_state.processing is False

    def test_leaving_with_no_turn_running_appends_nothing(self, monkeypatch):
        """`finish_stopped_turn` ignores a call with no turn in flight, which is what
        makes it safe to put in front of every control in the panel."""
        stub, module = run_app(
            monkeypatch,
            session={"messages": [{"role": "user", "text": "q", "attachments": []}]},
        )
        from sage.ui import sidebar  # noqa: PLC0415

        sidebar.leave(module.VIEW)
        assert [item["text"] for item in stub.session_state.messages] == ["q"]

    def test_the_rows_are_newest_first(self, monkeypatch):
        """The chat a reader is most likely to want back is the one they just left."""
        stub, _ = run_app(
            monkeypatch,
            session={
                "chats": [
                    {"id": 0, "messages": []},
                    {"id": 1, "messages": []},
                    {"id": 2, "messages": []},
                ],
                "chat_id": 2,
                "next_chat_id": 3,
            },
        )
        order = [
            key for name, key in stub.events
            if name == "button" and isinstance(key, str)
            and key.startswith("chat-name-")
        ]
        assert order == ["chat-name-2", "chat-name-1", "chat-name-0"]

    def test_both_slots_are_keyed_for_the_stylesheet(self, monkeypatch):
        """The row's layout hangs off these two keys — the name flexes, the ✕ does not —
        so they are a contract between this module and two selectors in app.css, and
        nothing else would notice one being renamed."""
        stub, _ = run_app(
            monkeypatch,
            session={"messages": [{"role": "user", "text": "q", "attachments": []}]},
        )
        assert stub.button_labels["chat-name-0"] == "q"
        assert stub.button_labels["chat-act-0"] == "✕"
        rows = [
            key for name, key in stub.events
            if name == "container" and isinstance(key, str)
            and key.startswith("chat-row-")
        ]
        assert rows == ["chat-row-open-0"]


class TestDeletingChats:
    def test_one_click_removes_it(self, monkeypatch):
        """One click, not two. Arming the row and waiting for a second click read as a
        broken button — "the chat doesn't go away but you need to click it again" — so
        the ✕ does what it says on the first press."""
        stub, _ = run_app(
            monkeypatch,
            session={
                "chats": [{"id": 0, "messages": [{"role": "user", "text": "one"}]},
                          {"id": 1, "messages": []}],
                "chat_id": 1,
                "next_chat_id": 2,
            },
        )
        state = _state()
        with pytest.raises(stub_streamlit.Rerun):
            state.delete_chat(0)
        assert [record["id"] for record in stub.session_state.chats] == [1]
        # The reader was not in it, so what is on their screen is untouched.
        assert stub.session_state.chat_id == 1

    def test_deleting_the_chat_being_read_opens_its_neighbour(self, monkeypatch):
        stub, _ = run_app(
            monkeypatch,
            session={
                "chats": [
                    {"id": 0, "messages": [{"role": "user", "text": "older"}]},
                    {"id": 1, "messages": [{"role": "user", "text": "newer"}]},
                ],
                "chat_id": 1,
                "next_chat_id": 2,
                "messages": [{"role": "user", "text": "newer", "attachments": []}],
            },
        )
        state = _state()
        with pytest.raises(stub_streamlit.Rerun):
            state.delete_chat(1)
        assert stub.session_state.chat_id == 0
        assert [item["text"] for item in stub.session_state.messages] == ["older"]

    def test_deleting_the_only_chat_leaves_an_empty_one(self, monkeypatch):
        """A session always has an open chat: the sidebar draws a row per record and
        `_stash` needs somewhere to put the live one."""
        stub, _ = run_app(
            monkeypatch,
            session={"messages": [{"role": "user", "text": "q", "attachments": []}]},
        )
        state = _state()
        only = stub.session_state.chat_id
        with pytest.raises(stub_streamlit.Rerun):
            state.delete_chat(only)
        assert len(stub.session_state.chats) == 1
        assert stub.session_state.chat_id != only
        assert stub.session_state.messages == []

    def test_deleting_a_chat_nobody_is_reading_keeps_the_page(self, monkeypatch):
        """The answer on screen, the error card under it and the file just attached all
        belong to a conversation this delete did not touch."""
        stub, _ = run_app(
            monkeypatch,
            session={
                "chats": [{"id": 0, "messages": []},
                          {"id": 1, "messages": []}],
                "chat_id": 1,
                "next_chat_id": 2,
                "messages": [{"role": "user", "text": "kept", "attachments": []}],
                "notice": "deepseek was unavailable",
            },
        )
        state = _state()
        with pytest.raises(stub_streamlit.Rerun):
            state.delete_chat(0)
        assert [item["text"] for item in stub.session_state.messages] == ["kept"]
        assert stub.session_state.notice == "deepseek was unavailable"

    def test_a_delete_already_gone_is_not_an_error(self, monkeypatch):
        """A stale button key. Doing nothing is right — the rerun the click already
        started redraws the panel without it."""
        stub, _ = run_app(monkeypatch)
        state = _state()
        state.delete_chat(999)          # no Rerun raised
        assert len(stub.session_state.chats) == 1


class TestAFailoverDoesNotPinTheSession:
    """`session_state.model` belongs to the turn that set it, not to the session.

    `View.can_think` gates the Think pill on the provider of the model answering NOW,
    which is right — and a failover sets that model, with nothing putting it back. So
    one hop onto a provider that takes no `reasoning` parameter took the pill off the
    page and nothing inside that conversation returned it: "the think toggle is gone
    forever. this is far worse", and it was. A control that vanishes for good is worse
    than the spent quota the failover was rescuing.

    There are two writers — `turn.run` on an automatic hop and the error card's
    "Use <model>" — and neither is the bug; not resetting was. A new question is where
    the pin stops being justified, least of all on a router that picks a model per
    request.

    Held here because it was shipped with no test at all, which is how it was possible
    to fix the same bug twice and reintroduce it once.
    """

    def test_a_new_question_returns_to_the_default_model(self, monkeypatch):
        from sage import config  # noqa: PLC0415

        stub, _ = run_app(monkeypatch, session={"messages": [], "processing": False})
        state = _state()
        stub.session_state["model"] = "somewhere:else"      # as a failover leaves it
        with pytest.raises(stub_streamlit.Rerun):
            state.start_new_turn("a fresh question")
        assert stub.session_state["model"] == config.DEFAULT_MODEL

    def test_leaving_a_conversation_returns_to_it_too(self, monkeypatch):
        """The other half: a conversation switched away from mid-failover must not hand
        the pin to whichever one replaces it."""
        from sage import config  # noqa: PLC0415

        stub, _ = run_app(
            monkeypatch,
            session={"messages": [{"role": "user", "text": "asked", "attachments": []}]},
        )
        state = _state()
        stub.session_state["model"] = "somewhere:else"
        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()
        assert stub.session_state["model"] == config.DEFAULT_MODEL

    def test_a_failover_inside_a_turn_still_sticks(self, monkeypatch):
        """The reset must not undo the thing it is scoped around. Within one turn the
        hop has to hold, or the next request walks straight back into the model that
        just refused — `failover_to` is popped by `turn.run`, not by `start_new_turn`.
        """
        stub, _ = run_app(monkeypatch, session={"messages": [], "processing": False})
        state = _state()
        stub.session_state["failover_to"] = "somewhere:else"
        with pytest.raises(stub_streamlit.Rerun):
            state.start_new_turn("a fresh question")
        assert stub.session_state.get("failover_to") == "somewhere:else"


class TestATurnAClickCutOffIsPickedUpAgain:
    """The other half of `abandon_turn`, and the second report about this path.

    Keeping the question stopped the conversation vanishing, and left a worse thing in
    its place: a question with nothing under it, for good. "now when switching from the
    new chat to the old one, the new one won't go away but the answer won't be generated
    and it will have nothing. this is bad."

    So an abandoned turn is not thrown away, it is put down — marked on the record it
    belongs to — and the next run that has the reader in that conversation picks it up.
    Which covers the two clicks that never left the conversation at all and killed the
    turn anyway: the ✕ on another row, and the name of the row already open.
    """

    @staticmethod
    def _asked(stub, module, partial=()):
        """The state at the moment of the click: a question, and a turn in flight."""
        from sage.ui import sidebar  # noqa: PLC0415

        stub.session_state.processing = True
        stub.session_state.partial = list(partial)
        sidebar.leave(module.VIEW)

    def test_a_picked_up_turn_starts_the_walk_over(self, monkeypatch):
        """The abandoned attempt's ledgers go with it.

        `tried` and `rerolls` belong to a walk that was cut off, and the turn picked up
        later is a fresh attempt at the same question rather than a continuation of that
        one. `_leave_conversation` clears both on every path that goes through it — but
        `open_chat`'s no-op branch does not, and that is the branch a reader takes by
        clicking the row they are already in. A turn resumed there inherited a spent
        re-roll budget and a list of models it would refuse to ask.
        """
        stub, module = run_app(
            monkeypatch,
            session={"messages": [{"role": "user", "text": "the question",
                                   "attachments": []}],
                     "tried": ["opencode:z1"], "rerolls": 2},
        )
        state = _state()
        here = stub.session_state.chat_id
        self._asked(stub, module)
        assert stub.session_state.tried == []
        assert stub.session_state.rerolls == 0

        # And the no-op branch, which is where it mattered: no rerun, and the turn
        # starts on this same run with both ledgers already empty.
        stub.session_state.tried = ["opencode:z1"]
        stub.session_state.rerolls = 2
        self._asked(stub, module)
        state.open_chat(here)
        assert stub.session_state.processing is True
        assert stub.session_state.tried == []
        assert stub.session_state.rerolls == 0

    def test_coming_back_to_an_abandoned_question_answers_it(self, monkeypatch):
        stub, module = run_app(
            monkeypatch,
            session={"messages": [{"role": "user", "text": "the question",
                                   "attachments": []}]},
        )
        state = _state()
        first = stub.session_state.chat_id
        self._asked(stub, module)

        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()
        assert stub.session_state.processing is False   # nothing runs in the new chat

        with pytest.raises(stub_streamlit.Rerun):
            state.open_chat(first)
        assert [item["text"] for item in stub.session_state.messages] == [
            "the question"
        ]
        assert stub.session_state.processing is True
        assert stub.session_state.partial == []

    def test_deleting_another_chat_does_not_leave_the_question_dead(self, monkeypatch):
        """The reader is still in this conversation, watching this answer. The click
        landed on a ✕ two rows down."""
        stub, module = run_app(
            monkeypatch,
            session={
                "chats": [{"id": 0, "messages": []}, {"id": 1, "messages": []}],
                "chat_id": 1,
                "next_chat_id": 2,
                "messages": [{"role": "user", "text": "the question",
                              "attachments": []}],
            },
        )
        state = _state()
        self._asked(stub, module)

        with pytest.raises(stub_streamlit.Rerun):
            state.delete_chat(0)
        assert [record["id"] for record in stub.session_state.chats] == [1]
        assert [item["text"] for item in stub.session_state.messages] == [
            "the question"
        ]
        assert stub.session_state.processing is True

    def test_clicking_the_row_already_open_keeps_the_turn(self, monkeypatch):
        """Not a switch, so nothing is left — but the click still aborted the run."""
        stub, module = run_app(
            monkeypatch,
            session={"messages": [{"role": "user", "text": "the question",
                                   "attachments": []}]},
        )
        state = _state()
        here = stub.session_state.chat_id
        self._asked(stub, module)

        state.open_chat(here)          # still no rerun: the turn runs in THIS one
        assert stub.session_state.processing is True
        assert [item["text"] for item in stub.session_state.messages] == [
            "the question"
        ]

    def test_a_part_answer_is_not_asked_again(self, monkeypatch):
        """What arrived is the turn's answer, stopped. Re-asking would put a second
        reply under a question that already has one."""
        stub, module = run_app(
            monkeypatch,
            session={"messages": [{"role": "user", "text": "the question",
                                   "attachments": []}]},
        )
        state = _state()
        first = stub.session_state.chat_id
        self._asked(stub, module, partial=["half an ", "answer"])

        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()
        with pytest.raises(stub_streamlit.Rerun):
            state.open_chat(first)
        assert [item["text"] for item in stub.session_state.messages] == [
            "the question", "half an answer",
        ]
        assert stub.session_state.processing is False

    def test_it_is_picked_up_once_and_not_on_every_visit(self, monkeypatch):
        """A mark that outlived its turn would restart the answer every time the
        reader opened the chat to read it."""
        stub, module = run_app(
            monkeypatch,
            session={"messages": [{"role": "user", "text": "the question",
                                   "attachments": []}]},
        )
        state = _state()
        first = stub.session_state.chat_id
        self._asked(stub, module)
        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()

        with pytest.raises(stub_streamlit.Rerun):
            state.open_chat(first)
        assert stub.session_state.processing is True
        # The answer lands, as it would have the first time.
        stub.session_state.messages.append(
            {"role": "assistant", "text": "an answer", "sources": []}
        )
        stub.session_state.processing = False

        # Away and back again: the chat is one to read now, not one to finish.
        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()
        with pytest.raises(stub_streamlit.Rerun):
            state.open_chat(first)
        assert stub.session_state.processing is False

    def test_picking_it_up_still_asks_the_limiter(self, monkeypatch):
        """It is a provider call like any other, so it goes through the one gate. And
        being refused keeps the mark: the question is still unanswered."""
        from sage import limits  # noqa: PLC0415

        stub, module = run_app(
            monkeypatch,
            session={"messages": [{"role": "user", "text": "the question",
                                   "attachments": []}]},
        )
        state = _state()
        first = stub.session_state.chat_id
        self._asked(stub, module)
        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()

        class _Spent:
            def check(self, _who, _now):
                return limits.Verdict(allowed=False, message="Too many questions.")

        monkeypatch.setattr(state, "get_limiter", _Spent)
        with pytest.raises(stub_streamlit.Rerun):
            state.open_chat(first)
        assert stub.session_state.processing is False
        assert stub.session_state.notice == "Too many questions."

        monkeypatch.undo()
        assert state.resume_pending() is True
        assert stub.session_state.processing is True


class TestAnErrorCardBelongsToItsConversation:
    """The other way a question ends up with nothing under it for good.

    `abandon_turn` and `resume_pending` cover the turn a click cut off. A turn that
    FAILED is the same shape from the reader's side and got there without a click:
    the error card and its Try-again button are the only way forward from a question
    with no answer, and `_leave_conversation` tears them up — correctly, because they
    belong to the conversation being left. Nothing put them back, so a trip to another
    chat and back left the question bare, with no card, no notice, and nothing to
    press. Measured in the running app against the mock provider on a 413: one user
    bubble, `stored_answers: 0`, `error_card: false`.

    So the card is stashed with the conversation, exactly as its messages are, and the
    reader finds what they left.
    """

    @staticmethod
    def _two_chats(monkeypatch):
        stub, _ = run_app(
            monkeypatch,
            session={
                "chats": [{"id": 0, "messages": [{"role": "user", "text": "older"}]},
                          {"id": 1, "messages": []}],
                "chat_id": 1,
                "next_chat_id": 2,
                "messages": [{"role": "user", "text": "the question",
                              "attachments": []}],
                "error": "Could not reach the model.",
                "error_detail": "HTTP 413",
            },
        )
        return stub, _state()

    def test_the_card_is_there_again_when_the_chat_is_reopened(self, monkeypatch):
        stub, state = self._two_chats(monkeypatch)
        with pytest.raises(stub_streamlit.Rerun):
            state.open_chat(0)
        # Cleared on the way out: it is not about the conversation being opened.
        assert stub.session_state.error is None
        assert stub.session_state.error_detail == ""

        with pytest.raises(stub_streamlit.Rerun):
            state.open_chat(1)
        assert [m["text"] for m in stub.session_state.messages] == ["the question"]
        assert stub.session_state.error == "Could not reach the model."
        assert stub.session_state.error_detail == "HTTP 413"

    def test_a_chat_with_nothing_wrong_does_not_inherit_one(self, monkeypatch):
        """The card would otherwise follow the reader around the panel."""
        stub, state = self._two_chats(monkeypatch)
        with pytest.raises(stub_streamlit.Rerun):
            state.open_chat(0)
        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()
        assert stub.session_state.error is None
        with pytest.raises(stub_streamlit.Rerun):
            state.open_chat(0)
        assert stub.session_state.error is None

    def test_deleting_the_open_chat_restores_the_neighbour_s_card(self, monkeypatch):
        """`delete_chat` opens a neighbour, which is the same arrival as a switch."""
        stub, state = self._two_chats(monkeypatch)
        with pytest.raises(stub_streamlit.Rerun):
            state.open_chat(0)          # stashes chat 1 with its card
        with pytest.raises(stub_streamlit.Rerun):
            state.delete_chat(0)        # …and lands the reader back on chat 1
        assert stub.session_state.chat_id == 1
        assert stub.session_state.error == "Could not reach the model."

    def test_a_turn_being_picked_up_clears_it(self, monkeypatch):
        """A resumed question is generating, so a card about the last attempt under it
        would describe something that is no longer happening."""
        stub, module = run_app(
            monkeypatch,
            session={"messages": [{"role": "user", "text": "the question",
                                   "attachments": []}]},
        )
        state = _state()
        first = stub.session_state.chat_id
        from sage.ui import sidebar  # noqa: PLC0415

        stub.session_state.error = "Could not reach the model."
        stub.session_state.processing = True
        stub.session_state.partial = []
        sidebar.leave(module.VIEW)
        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()
        with pytest.raises(stub_streamlit.Rerun):
            state.open_chat(first)
        assert stub.session_state.processing is True
        assert stub.session_state.error is None


class TestTheStateMachineUnderARandomWalk:
    """Every order these operations can happen in, against the invariants that must hold.

    This module grew by 220 lines in one day — an abandoned turn is now marked on its
    record and picked up later, a failed turn's error card is stashed and restored, and
    two walk ledgers are cleared in four different places. Each mechanism has its own
    tests. What none of them covers is the ORDER: abandon in one chat, fail in another,
    delete the one holding the mark, come back to the first. The bugs that survive a
    day like that are interaction bugs, and a reader finds them by using the app in an
    order nobody scripted.

    So this drives a deterministic pseudo-random walk and asserts the invariants after
    every single step. A failure prints the seed and the sequence, which is the whole
    value: the repro is the output. Calibrated rather than assumed — dropping the
    `next_chat_id` bump in `delete_chat`'s last-chat branch fails all eight seeds, and
    seed 2 reports `ask -> answer -> new -> ask -> fail -> open -> open -> new ->
    delete`, which is a sequence nobody would have written by hand.

    One invariant is currently unfalsifiable by this walk, and that is worth knowing
    rather than mistaking for coverage: the stale-mark check cannot fire, because
    `abandon_turn` clears `processing` when it sets the mark, so no answer can reach
    that conversation until `resume_pending` runs — and the first thing that does is
    pop the mark. `resume_pending`'s "answered, stopped, edited or cleared since"
    branch is therefore defensive. Removing its `record.pop` leaves all eight seeds
    green, so do not read this test as holding it.
    """

    OPERATIONS = ("ask", "answer", "fail", "abandon", "stop", "new", "open", "delete")

    @staticmethod
    def _invariants(stub, state, step):
        """What must be true of session state no matter what just happened."""
        session = stub.session_state
        chats = session["chats"]
        where = f"after {step}"

        assert chats, f"{where}: no conversations at all"
        ids = [record["id"] for record in chats]
        assert len(ids) == len(set(ids)), f"{where}: duplicate chat ids {ids}"
        assert session["chat_id"] in ids, (
            f"{where}: the open chat {session['chat_id']} is not in the list {ids}"
        )
        assert session["next_chat_id"] > max(ids), (
            f"{where}: next id {session['next_chat_id']} would collide with {ids}"
        )

        # A turn in flight is a turn about a question. `turn.run` reads
        # `messages[-1]`, so `processing` over anything else is an answer to nothing.
        if session["processing"]:
            assert session["messages"], f"{where}: processing with no messages"
            assert session["messages"][-1]["role"] == "user", (
                f"{where}: processing, but the last message is not a question"
            )

        # A mark says "this conversation is owed a turn", so it may only sit on a
        # record whose messages end in a question. A stale one re-asks a question that
        # already has a reply, every time the reader opens the chat to read it.
        for record in chats:
            if not record.get("pending"):
                continue
            held = (session["messages"] if record["id"] == session["chat_id"]
                    else record["messages"])
            assert held and held[-1]["role"] == "user", (
                f"{where}: chat {record['id']} is marked pending over {held!r}"
            )

        # No question may carry two answers, in any conversation.
        for record in chats:
            held = (session["messages"] if record["id"] == session["chat_id"]
                    else record["messages"])
            roles = [item["role"] for item in held]
            for first, second in zip(roles, roles[1:], strict=False):
                assert not (first == "assistant" and second == "assistant"), (
                    f"{where}: chat {record['id']} has two answers in a row: {roles}"
                )

    def _step(self, stub, state, module, operation, counter):
        """One operation, or a no-op where the app would not offer it."""
        session = stub.session_state
        if operation == "ask":
            if session["processing"]:
                return False
            session["messages"].append(
                {"role": "user", "text": f"question {counter}", "attachments": []}
            )
            session["processing"] = True
        elif operation == "answer":
            if not session["processing"]:
                return False
            session["messages"].append(
                {"role": "assistant", "text": f"answer {counter}", "sources": [],
                 "rating": None, "steps": [], "step_seconds": 1.0}
            )
            session["processing"] = False
            # Deliberately NOT clearing the record's `pending` mark here. The app does
            # not either: `resume_pending` is what pops it, on the next run that has
            # the reader in that conversation, and clearing it in this step would hide
            # the one bug the mark can have — outliving the turn it was set for.
        elif operation == "fail":
            if not session["processing"]:
                return False
            session["processing"] = False
            session["error"] = "Could not complete that request"
            session["error_detail"] = "HTTP 500"
            session["error_kind"] = "unavailable"
        elif operation == "abandon":
            if not session["processing"]:
                return False
            state.abandon_turn("opencode:m1", {})
        elif operation == "stop":
            if not session["processing"]:
                return False
            session["partial"] = ["half an answer"]
            state.finish_stopped_turn("opencode:m1", {})
        elif operation == "new":
            state.abandon_turn("opencode:m1", {})
            self._guard(state.new_chat)
        elif operation == "open":
            target = [r["id"] for r in session["chats"]]
            state.abandon_turn("opencode:m1", {})
            self._guard(state.open_chat, target[counter % len(target)])
        elif operation == "delete":
            target = [r["id"] for r in session["chats"]]
            state.abandon_turn("opencode:m1", {})
            self._guard(state.delete_chat, target[counter % len(target)])
        return True

    @staticmethod
    def _guard(call, *args):
        """Run something that may end in Streamlit's rerun, which is not a failure."""
        try:
            call(*args)
        except stub_streamlit.Rerun:
            pass

    @pytest.mark.parametrize("seed", [1, 2, 3, 5, 8, 13, 21, 34])
    def test_the_invariants_hold_however_the_operations_are_ordered(
        self, seed, monkeypatch
    ):
        import random  # noqa: PLC0415

        stub, module = run_app(monkeypatch)
        state = _state()
        rng = random.Random(seed)
        done: list[str] = []
        for counter in range(60):
            operation = rng.choice(self.OPERATIONS)
            if not self._step(stub, state, module, operation, counter):
                continue
            done.append(operation)
            try:
                self._invariants(stub, state, operation)
            except AssertionError as exc:
                raise AssertionError(
                    f"seed {seed}, step {len(done)}: {' -> '.join(done)}\n{exc}"
                ) from exc


class TestTheErrorCardIsOneFact:
    """`error`, `error_detail` and `error_kind` are three fields describing one thing.

    Whether a card is on screen, what it says, and what it is about — and the card's
    buttons now depend on the third, because `context` is the one kind for which "→ Use
    <model>" is a button guaranteed to fail. Clearing one without the others leaves a
    kind describing the turn before last. Nothing reads either without checking `error`
    first, so today it costs nothing; an invariant that held in four places out of five
    is one somebody relies on in the fifth.

    Found by grepping every `error = None` in `state.py` after the third field was
    added, which is the check this test replaces with a permanent one.
    """

    FIELDS = ("error", "error_detail", "error_kind")

    @staticmethod
    def _failed(stub):
        stub.session_state["error"] = "Could not complete that request"
        stub.session_state["error_detail"] = "HTTP 400 … maximum context length"
        stub.session_state["error_kind"] = "context"

    def _assert_clean(self, stub, where):
        for field in self.FIELDS:
            assert not stub.session_state[field], (
                f"{where}: {field} survived as {stub.session_state[field]!r}"
            )

    def test_a_new_question_clears_all_three(self, monkeypatch):
        stub, _module = run_app(monkeypatch)
        state = _state()
        self._failed(stub)
        # It ends in a rerun, like every path in this module that changes what is on
        # screen. The state is set before that, which is what this reads.
        with pytest.raises(stub_streamlit.Rerun):
            state.start_new_turn("what is a service unit?", [])
        self._assert_clean(stub, "after a new question")

    def test_leaving_a_conversation_clears_all_three(self, monkeypatch):
        stub, _module = run_app(monkeypatch, session={
            "messages": [{"role": "user", "text": "q", "attachments": []},
                         {"role": "assistant", "text": "a", "sources": []}],
        })
        state = _state()
        self._failed(stub)
        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()
        self._assert_clean(stub, "after opening another chat")

    def test_and_the_card_comes_back_whole_or_not_at_all(self, monkeypatch):
        """`_restore_error` stashes and restores the card so a failed turn does not
        lose its Try-again button on a trip to another chat. All three or none: a
        restored card with no kind draws a switch button for a `context` failure."""
        stub, _module = run_app(monkeypatch, session={
            "messages": [{"role": "user", "text": "q", "attachments": []}],
        })
        state = _state()
        here = stub.session_state["chat_id"]
        self._failed(stub)
        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()
        self._assert_clean(stub, "while away")
        with pytest.raises(stub_streamlit.Rerun):
            state.open_chat(here)
        assert stub.session_state["error"] == "Could not complete that request"
        assert stub.session_state["error_kind"] == "context", (
            "the card came back without the kind, so it would offer a switch button "
            "for the one failure switching cannot fix"
        )
        assert "context length" in stub.session_state["error_detail"]

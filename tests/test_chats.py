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

    def test_new_chat_on_an_empty_chat_does_nothing(self, monkeypatch):
        """Not even a record. Ten presses would otherwise leave ten identical rows to
        scroll past, and an empty chat is already what the button offers — so the
        button says so by being inert, and the function refuses the case as well."""
        stub, _ = run_app(monkeypatch)
        # Not drawn at all, rather than drawn inert: a disabled `New chat` button
        # directly above a row that also said "New chat" was two of the same words for
        # two different things.
        assert "new-chat" not in stub.button_labels
        state = _state()
        opened = stub.session_state.chat_id
        state.new_chat()            # no Rerun raised
        state.new_chat()
        assert len(stub.session_state.chats) == 1
        assert stub.session_state.chat_id == opened

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
                "switched_from": ("m1", "empty"),
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
        assert stub.session_state.switched_from is None
        assert stub.session_state.editing is None
        assert stub.session_state.attachments == []
        assert stub.session_state.dropped_uploads == {}
        assert stub.session_state.upload_refusals == {}
        assert "failover_to" not in stub.session_state
        # The uploader is reset and the composer emptied, which only app.js can do.
        assert stub.session_state.uploader_key == before[0] + 1
        assert stub.session_state.clear_token == before[1] + 1

    def test_clearing_empties_the_open_chat_without_opening_another(self, monkeypatch):
        stub, _ = run_app(
            monkeypatch,
            session={"messages": [{"role": "user", "text": "q", "attachments": []}]},
        )
        state = _state()
        opened = stub.session_state.chat_id
        with pytest.raises(stub_streamlit.Rerun):
            state.clear_conversation()
        assert stub.session_state.messages == []
        assert stub.session_state.chat_id == opened
        assert len(stub.session_state.chats) == 1
        # And in the record too, or the sidebar goes on naming an emptied chat after
        # the question it used to start with.
        assert stub.session_state.chats[0]["messages"] == []


class TestTheSidebar:
    def test_it_is_drawn_before_the_body(self, monkeypatch):
        """A control in it ends in `st.rerun()`, so a conversation drawn first is a
        conversation rendered to be thrown away."""
        stub, module = run_app(monkeypatch)
        assert module is not None
        kinds = [name for name, _ in stub.events]
        assert "sidebar" in kinds
        assert kinds.index("sidebar") < kinds.index("chat_input")

    def test_an_empty_session_offers_no_way_out_of_nothing(self, monkeypatch):
        """The panel a reader opens on the landing screen: the label, and one row for
        the conversation they have not started yet. No `New chat`, because they are on
        one, and nothing greyed out."""
        stub, _ = run_app(monkeypatch)
        chat_id = stub.session_state.chat_id
        assert "new-chat" not in stub.button_labels
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

    def test_nothing_switches_while_an_answer_is_arriving(self, monkeypatch):
        """A click is a rerun, and a rerun during a turn aborts it — that is the
        mechanism the stop button is built on. `disabled` is the only thing that keeps
        the click off the wire, so the half-written answer survives."""
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
        assert stub.disabled["new-chat"] is True
        rows = [
            key for key in stub.disabled
            if key.startswith(("chat-name-", "chat-act-"))
        ]
        assert len(rows) == 4, rows
        for key in rows:
            assert stub.disabled[key] is True, key

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

    def test_the_two_slots_keep_their_keys_when_a_delete_is_armed(self, monkeypatch):
        """The stylesheet sizes the row off these two keys — name flexes, action does
        not — so arming a delete must not change which slot is which, or the row would
        move under the cursor reaching for it."""
        stub, _ = run_app(
            monkeypatch,
            session={
                "messages": [{"role": "user", "text": "q", "attachments": []}],
                "pending_delete": 0,
            },
        )
        assert stub.session_state.chat_id == 0
        assert stub.button_labels["chat-name-0"] == "Delete this chat"
        assert stub.button_labels["chat-act-0"] == "✕"
        rows = [
            key for name, key in stub.events
            if name == "container" and isinstance(key, str)
            and key.startswith("chat-row-")
        ]
        assert rows == ["chat-row-arm-0"]


class TestDeletingChats:
    def test_the_first_click_only_arms_it(self, monkeypatch):
        """Nothing anywhere else has a copy of a conversation, so one click cannot be
        what removes it.

        And it reruns. The run that delivered the click is the one drawing the panel,
        so the row was already rendered in its old state by the time this was reached —
        without a fresh run the ✕ set a flag and changed nothing on screen.
        """
        stub, _ = run_app(monkeypatch)
        state = _state()
        before = list(stub.session_state.chats)
        with pytest.raises(stub_streamlit.Rerun):
            state.arm_delete(0)
        assert stub.session_state.pending_delete == 0
        assert stub.session_state.chats == before

    def test_the_second_click_removes_it(self, monkeypatch):
        stub, _ = run_app(
            monkeypatch,
            session={
                "chats": [{"id": 0, "messages": [{"role": "user", "text": "one"}]},
                          {"id": 1, "messages": []}],
                "chat_id": 1,
                "next_chat_id": 2,
                "pending_delete": 0,
            },
        )
        state = _state()
        with pytest.raises(stub_streamlit.Rerun):
            state.delete_chat(0)
        assert [record["id"] for record in stub.session_state.chats] == [1]
        assert stub.session_state.pending_delete is None
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

    def test_leaving_a_conversation_disarms_the_confirmation(self, monkeypatch):
        """A ✕ pressed once and then left alone is one stray click from deleting a
        conversation the reader never meant to name."""
        stub, _ = run_app(
            monkeypatch,
            session={
                "messages": [{"role": "user", "text": "q", "attachments": []}],
                "pending_delete": 0,
            },
        )
        state = _state()
        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()
        assert stub.session_state.pending_delete is None

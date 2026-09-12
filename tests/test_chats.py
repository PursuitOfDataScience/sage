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

    def test_abandoning_a_turn_that_produced_nothing_leaves_nothing(self, monkeypatch):
        """The bug in the reader's third screenshot: a conversation holding their
        question with the bare word `Stopped` under it and no answer.

        `finish_stopped_turn` appends that empty message on purpose — a reader who
        pressed Stop has to see that something happened. A reader who has walked off to
        another chat is not looking at that screen, so the turn is dropped whole, the
        question with it, and the conversation is left as it was before it was asked.
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

        assert stub.session_state.messages == []
        assert stub.session_state.processing is False
        # And with the conversation now empty, leaving it drops it — which is where the
        # spare `Nothing asked yet` row in that screenshot came from.
        state = _state()
        with pytest.raises(stub_streamlit.Rerun):
            state.new_chat()
        assert len(stub.session_state.chats) == 1

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

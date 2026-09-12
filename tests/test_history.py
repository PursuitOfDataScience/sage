import pytest

from sage import config, history
from sage.files import Attachment


def user(text, *attachments):
    """A user turn. Attachments are a list now — holding one is what made a second
    attached file look like a control that does nothing."""
    return {"role": "user", "text": text, "attachments": [a for a in attachments if a]}


def assistant(text):
    return {"role": "assistant", "text": text}


def test_system_prompt_leads():
    built = history.build([user("hi")], "SYSTEM")
    assert built[0] == {"role": "system", "content": "SYSTEM"}


def test_assistant_turns_are_kept_so_follow_ups_have_context():
    built = history.build([user("q1"), assistant("a1"), user("q2")], "S")
    assert [message["role"] for message in built] == [
        "system",
        "user",
        "assistant",
        "user",
    ]


def test_empty_turns_are_skipped():
    built = history.build([user("q"), assistant("")], "S")
    assert len(built) == 2


def test_the_latest_attachment_is_inlined():
    attachment = Attachment("paper.pdf", "pdf", "UNIQUE-BODY-TEXT", pages=3)
    built = history.build([user("summarise", attachment)], "S")
    assert "UNIQUE-BODY-TEXT" in built[-1]["content"]


def test_older_attachments_collapse_to_a_stub():
    """Asking three follow-ups about a PDF used to ship the PDF four times."""
    attachment = Attachment("paper.pdf", "pdf", "UNIQUE-BODY-TEXT", pages=3)
    messages = [
        user("summarise", attachment),
        assistant("Here is a summary."),
        user("and the conclusion?"),
    ]
    built = history.build(messages, "S")
    body = "\n".join(message["content"] for message in built)
    assert body.count("UNIQUE-BODY-TEXT") == 1

    messages.append(assistant("The conclusion is X."))
    messages.append(user("what about the method?"))
    later = history.build(messages, "S")
    joined = "\n".join(message["content"] for message in later)
    assert joined.count("UNIQUE-BODY-TEXT") == 1
    assert "paper.pdf" in joined


def test_only_the_most_recent_attachment_is_inlined():
    first = Attachment("one.txt", "text", "FIRST-BODY")
    second = Attachment("two.txt", "text", "SECOND-BODY")
    built = history.build(
        [user("a", first), assistant("ok"), user("b", second)], "S"
    )
    joined = "\n".join(message["content"] for message in built)
    assert "SECOND-BODY" in joined
    assert "FIRST-BODY" not in joined


class TestTheDialThatTurnsAttachmentTextOff:
    """`SAGE_ATTACHMENT_FULL_TEXT_TURNS=0` did the opposite of what it says.

    `config.py` documents "set it to 0 to stub every attachment" and permits it
    (`minimum=0`). The implementation was `positions[-config.ATTACHMENT_FULL_TEXT_TURNS:]`,
    and `xs[-0:]` is `xs[0:]` — the whole list. So the value that turns the feature off
    inlined *every* attachment in the conversation: the maximum where the minimum was
    asked for, 2.4x the default's payload over three files, and exactly the accumulation
    this module's docstring says it was written to remove.
    """

    def conversation(self):
        body = "SECRET-FILE-BODY"
        return [
            user("about A", Attachment("a.txt", "text", f"{body}-A")),
            assistant("Answer A."),
            user("about B", Attachment("b.txt", "text", f"{body}-B")),
            assistant("Answer B."),
            user("about C", Attachment("c.txt", "text", f"{body}-C")),
        ]

    def inlined(self, monkeypatch, turns: int) -> int:
        monkeypatch.setattr(config, "ATTACHMENT_FULL_TEXT_TURNS", turns)
        built = history.build(self.conversation(), "S")
        joined = "\n".join(str(message["content"]) for message in built)
        return joined.count("SECRET-FILE-BODY")

    def test_zero_inlines_nothing(self, monkeypatch):
        assert self.inlined(monkeypatch, 0) == 0

    def test_zero_still_names_the_files_it_stubbed(self, monkeypatch):
        """Stubbed, not silently dropped: the model has to know a file was attached."""
        monkeypatch.setattr(config, "ATTACHMENT_FULL_TEXT_TURNS", 0)
        built = history.build(self.conversation(), "S")
        joined = "\n".join(str(message["content"]) for message in built)
        assert joined.count("content is omitted here") == 3
        assert "c.txt" in joined
        assert "about C" in joined, "the question itself always survives"

    def test_one_inlines_only_the_newest(self, monkeypatch):
        assert self.inlined(monkeypatch, 1) == 1

    def test_two_inlines_the_two_newest(self, monkeypatch):
        assert self.inlined(monkeypatch, 2) == 2

    def test_zero_is_the_smallest_payload_and_not_the_largest(self, monkeypatch):
        """The property the bug inverted, stated as the ordering it must obey."""
        sizes = []
        for turns in (0, 1, 2, 3):
            monkeypatch.setattr(config, "ATTACHMENT_FULL_TEXT_TURNS", turns)
            built = history.build(self.conversation(), "S")
            sizes.append(sum(len(str(item["content"])) for item in built))
        assert sizes == sorted(sizes), f"more turns must never send less: {sizes}"
        assert sizes[0] < sizes[-1]

    def test_the_documented_meaning_still_matches_the_config_comment(self):
        """The comment is the specification here, so it is pinned to the behaviour."""
        import os

        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "sage", "config.py",
        )
        with open(path, encoding="utf-8") as handle:
            # Matched on the fragment that sits on one line, because the sentence wraps.
            assert "Set it to 0 to stub every" in handle.read(), (
                "config.py no longer documents what 0 means; keep the two in step"
            )


def test_oldest_turns_are_dropped_when_over_budget():
    big = "x" * (config.HISTORY_CHAR_BUDGET // 3)
    messages = [user(f"{big}-{n}") for n in range(6)]
    built = history.build(messages, "S")
    total = sum(len(message["content"]) for message in built)
    assert total <= config.HISTORY_CHAR_BUDGET + len("S")
    # The newest question must survive trimming.
    assert built[-1]["content"].endswith("-5")


def test_a_single_oversized_turn_is_clipped_rather_than_dropped():
    messages = [user("y" * (config.HISTORY_CHAR_BUDGET * 2))]
    built = history.build(messages, "S")
    assert len(built) == 2
    assert len(built[1]["content"]) <= config.HISTORY_CHAR_BUDGET


class TestTheQuestionSurvives:
    """The one thing a turn cannot be trimmed down to nothing.

    Attachments used to be rendered before the question, and `_trim` clips the head
    of an over-budget turn — so the question was exactly what fell off the end. Two
    30 KB logs are two legal uploads (`MAX_FILE_TEXT_CHARS` is 30 000) and one 48 KB
    turn, which is the budget: attach a job script and the `.out` it wrote, which is
    what this app is for, and the model was handed two files and no question at all.
    It answered something anyway, and nothing on screen said what had happened.
    """

    def two_logs(self):
        return [
            Attachment("submit.sbatch", "text", "X" * 30000),
            Attachment("slurm-1.out", "text", "Y" * 30000),
        ]

    def test_it_reaches_the_model_under_a_pile_of_attachments(self):
        built = history.build([user("why did my job die?", *self.two_logs())], "S")
        assert "why did my job die?" in built[-1]["content"]

    def test_the_question_comes_before_the_files(self):
        built = history.build([user("why did my job die?", *self.two_logs())], "S")
        content = built[-1]["content"]
        assert content.index("why did my job die?") < content.index("submit.sbatch")

    def test_a_clipped_turn_says_it_was_clipped(self):
        """`as_context` promises an `--- END name ---` that is no longer coming, so a
        model cannot otherwise tell a truncated file from one that ends there."""
        built = history.build([user("why?", *self.two_logs())], "S")
        assert "truncated" in built[-1]["content"][-120:]

    def test_the_budget_still_holds(self):
        built = history.build([user("why?", *self.two_logs())], "S")
        assert len(built[-1]["content"]) <= config.HISTORY_CHAR_BUDGET


def test_a_surviving_answer_is_kept_even_with_its_question_trimmed_away():
    """`[system, assistant, user]` looks wrong and is not.

    Dropping that leading answer was tried and reverted: it costs the follow-up its
    referent — "how do I raise it?" with nothing saying what `it` is — to avoid a
    shape both providers accept. And it fires on the very turn the question-first
    ordering exists to protect, where a 60 KB pair of logs has already evicted the
    question and the 68-character answer would go with it.
    """
    messages = [
        user("why did my job die?",
             Attachment("a.out", "text", "Z" * 30000),
             Attachment("b.out", "text", "Y" * 30000)),
        assistant("Your job hit the memory limit. Raise --mem to 32G."),
        user("how do I raise it?"),
    ]
    built = history.build(messages, "S")
    assert "Raise --mem to 32G." in "".join(str(m["content"]) for m in built)


def test_two_attachments_on_one_turn_both_reach_the_model():
    """One turn used to carry one file. Anything offered while a file was already
    attached was dropped, which from the outside was a control doing nothing."""
    log = Attachment("slurm-1.out", "text", "OOM-KILLED-LINE")
    script = Attachment("submit.sbatch", "text", "SBATCH-BODY")
    built = history.build([user("why did this die?", log, script)], "S")
    joined = "\n".join(str(message["content"]) for message in built)
    assert "OOM-KILLED-LINE" in joined
    assert "SBATCH-BODY" in joined


def test_an_image_is_offered_to_a_vision_model_as_a_picture():
    shot = Attachment(
        "pasted-image.png", "image", "", data=b"\x89PNG\r\n\x1a\nbody",
        mime="image/png",
    )
    built = history.build([user("what is this error?", shot)], "S", vision=True)
    parts = built[-1]["content"]
    assert isinstance(parts, list), "a vision turn is a list of parts"
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_an_image_is_not_offered_to_a_model_that_cannot_see():
    """An image sent to a text-only model is a 4xx, not a polite decline."""
    shot = Attachment(
        "pasted-image.png", "image", "", data=b"\x89PNG\r\n\x1a\nbody",
        mime="image/png",
    )
    built = history.build([user("what is this error?", shot)], "S", vision=False)
    assert isinstance(built[-1]["content"], str)
    assert "pasted-image.png" in built[-1]["content"]


# --- which models are offered the picture ----------------------------------
#
# `config.sees_images` is the switch every test above takes as given: `vision=` comes
# from it, and nothing else decides whether a screenshot travels as bytes or as a
# sentence. Kept here, beside what it switches, rather than left as the one input to
# these builds that nothing checks.


def test_a_model_that_can_see_is_recognised_from_its_id():
    assert config.sees_images("pixtral-12b-2409")
    assert config.sees_images("claude-sonnet-4-5")
    # Ids arrive spelled however a provider spells them, discovery included.
    assert config.sees_images("Pixtral-Large-Latest")


def test_a_model_that_cannot_see_is_never_guessed_at():
    """Conservative on purpose: an unlisted model gets the sentence, because the
    alternative is a 4xx on a question the user has already waited for."""
    assert not config.sees_images("mistral-small-latest")
    assert not config.sees_images("deepseek-v4-flash-free")
    assert not config.sees_images("")
    assert not config.sees_images(None)


def test_the_vision_list_is_a_deployment_setting(monkeypatch):
    """A free tier's lineup changes without notice, so learning that a model reads
    images must not need a code change."""
    monkeypatch.setattr(config, "VISION_MODELS", ("mimo",))
    assert config.sees_images("mimo-v2.5")
    assert not config.sees_images("pixtral-12b-2409")


def test_the_switch_is_what_decides_the_shape_of_the_turn():
    """The two halves wired together: what `sees_images` says about a model is what
    `build` does with the picture. Passing `vision=` by hand, as the tests above do,
    cannot catch the two disagreeing."""
    shot = Attachment(
        "pasted-image.png", "image", "", data=b"\x89PNG\r\n\x1a\nbody",
        mime="image/png",
    )
    for model, listed in (("pixtral-12b-2409", True), ("mistral-small-latest", False)):
        assert config.sees_images(model) is listed
        built = history.build(
            [user("what is this?", shot)], "S", vision=config.sees_images(model)
        )
        assert isinstance(built[-1]["content"], list) is listed, model


def test_a_screenshot_does_not_evict_the_conversation_from_the_budget():
    """Base64 image bytes are enormous. Counted against a character budget they
    would push every real turn out to make room for one screenshot."""
    huge = Attachment(
        "big.png", "image", "", data=b"\x89PNG\r\n\x1a\n" + b"x" * 200_000,
        mime="image/png",
    )
    messages = [user("first question"), assistant("first answer"),
                user("look at this", huge)]
    built = history.build(messages, "S", vision=True)
    joined = " ".join(
        part.get("text", "")
        for message in built
        for part in (message["content"] if isinstance(message["content"], list)
                     else [{"text": message["content"]}])
    )
    assert "first question" in joined, "one image evicted the whole conversation"


class TestTheQuestionSurvivesAnyBudget:
    """The budget may drop history and clip a file. It may not clip the question.

    `_trim` clips the *head* of the last message when that message alone is over budget,
    and — since `user_content` puts the question first — the head is the question. At a
    small enough budget it clipped the question itself: measured at
    `SAGE_HISTORY_CHAR_BUDGET=1`, the model was handed one character of the question and
    answered anyway. That is the failure `question_sent` was added to the bench to catch,
    and this is the floor that makes it unreachable.

    The floor is derived from the stub rendering of the same turn rather than picked: it is
    the smallest faithful form of the turn, it always carries the question whole, and
    `MAX_PROMPT_CHARS` bounds what a reader can type so honouring it cannot run away.
    """

    QUESTION = "how do I submit a batch job with a GPU on Midway3?"

    def build(self, budget: int, attachments=()):
        from sage import config

        before = config.HISTORY_CHAR_BUDGET
        config.HISTORY_CHAR_BUDGET = budget
        try:
            built = history.build(
                [{"role": "user", "text": self.QUESTION,
                  "attachments": list(attachments)}],
                "SYSTEM",
            )
        finally:
            config.HISTORY_CHAR_BUDGET = before
        return "\n".join(str(message["content"]) for message in built)

    @pytest.mark.parametrize("budget", [1, 10, 100, 400, 48000])
    def test_it_is_sent_whole_at_every_budget(self, budget):
        assert self.QUESTION in self.build(budget)

    @pytest.mark.parametrize("budget", [1, 100, 400])
    def test_and_with_a_file_far_larger_than_the_budget(self, budget):
        attachment = Attachment(filename="log.txt", kind="text", text="L" * 30000)
        sent = self.build(budget, [attachment])
        assert self.QUESTION in sent
        assert "L" * 500 not in sent, "the file should be what gives way"

    def test_a_budget_that_fits_is_still_honoured(self):
        """The floor is a floor, not a licence to ignore the setting."""
        attachment = Attachment(filename="log.txt", kind="text", text="L" * 30000)
        assert len(self.build(2000, [attachment])) < 2500

    def test_a_conversation_still_loses_its_oldest_turns_first(self):
        from sage import config

        before = config.HISTORY_CHAR_BUDGET
        config.HISTORY_CHAR_BUDGET = 200
        try:
            built = history.build([
                {"role": "user", "text": "the oldest question " * 10, "attachments": []},
                {"role": "assistant", "text": "an old answer " * 10, "sources": []},
                {"role": "user", "text": self.QUESTION, "attachments": []},
            ], "SYSTEM")
        finally:
            config.HISTORY_CHAR_BUDGET = before
        sent = "\n".join(str(message["content"]) for message in built)
        assert self.QUESTION in sent
        assert "the oldest question" not in sent

    def test_a_question_larger_than_a_reader_could_type_is_still_clipped(self):
        """The floor is bounded by `MAX_PROMPT_CHARS`, not by whatever arrives.

        `MAX_PROMPT_CHARS` is what the composer accepts, so a question above it cannot come
        from a reader — and the budget must not become optional for anything that skips the
        composer.

        Plus the two strings the app itself wraps around the question, which is the whole
        of the difference from the flat `MAX_PROMPT_CHARS` this used to assert: the floor
        has to cover `_ASKS` in front of the question and the cut note `_clip` pays for out
        of the same allowance, or a question at exactly the composer's limit comes back 71
        characters short (see the sibling test below).
        """
        from sage import config

        before = config.HISTORY_CHAR_BUDGET
        config.HISTORY_CHAR_BUDGET = 500
        try:
            built = history.build(
                [{"role": "user", "text": "y" * (config.MAX_PROMPT_CHARS * 2),
                  "attachments": []}],
                "S",
            )
        finally:
            config.HISTORY_CHAR_BUDGET = before
        frame = len(history._ASKS) + len(history._CUT_NOTE)
        assert len(built[1]["content"]) <= config.MAX_PROMPT_CHARS + frame

    @pytest.mark.parametrize("budget", [1, 500, 4000, 12000, 48000])
    def test_the_longest_question_the_composer_accepts_survives_with_a_file(
        self, budget
    ):
        """The floor was measured on a *rendering* of the turn, capped at
        `MAX_PROMPT_CHARS`, and the cap is where it came up short.

        A question of 7 999 characters is one the composer accepts. With one attachment
        and `SAGE_HISTORY_CHAR_BUDGET=4000` the old floor was the cap — 8 000 — while the
        clip needed 8 071: `_ASKS` (15) in front of the question and `_CUT_NOTE` (57) paid
        for out of the same allowance. The model was handed the question 71 characters
        short, mid-word, with nothing saying so. Measured before the fix at every budget
        below 8 071; whole at every budget after it.
        """
        from sage import config

        question = "why did my job die? " + "x" * 7979
        assert len(question) <= config.MAX_PROMPT_CHARS
        before = config.HISTORY_CHAR_BUDGET
        config.HISTORY_CHAR_BUDGET = budget
        try:
            built = history.build(
                [{"role": "user", "text": question,
                  "attachments": [Attachment("slurm-1.out", "text", "L" * 30000)]}],
                "S",
            )
        finally:
            config.HISTORY_CHAR_BUDGET = before
        assert question in built[-1]["content"]

    def test_a_stubbed_current_turn_keeps_the_question_at_its_head(self):
        """`ATTACHMENT_FULL_TEXT_TURNS = 0` stubs the CURRENT turn, and the stub used to
        put the question last — the end `_trim` cuts off.

        Nothing caps how many files one turn may carry; `MAX_ATTACHED_BYTES` bounds their
        bytes. 250 four-byte files with long names are 1 000 bytes against a 20 MB limit
        and 61 750 characters of filenames, so the stub ran past the budget and the model
        got 48 000 characters of names and no question at all — the failure
        `TestTheQuestionSurvives` records, through the rendering it did not cover.
        """
        from sage import config

        attachments = [
            Attachment("n" * 240 + f"{index:03d}.log", "text", "tiny", size=4)
            for index in range(250)
        ]
        before = config.ATTACHMENT_FULL_TEXT_TURNS
        config.ATTACHMENT_FULL_TEXT_TURNS = 0
        try:
            built = history.build(
                [{"role": "user", "text": self.QUESTION, "attachments": attachments}],
                "SYSTEM",
            )
        finally:
            config.ATTACHMENT_FULL_TEXT_TURNS = before
        sent = built[-1]["content"]
        assert sent.startswith(self.QUESTION)
        # It still says a file was attached, and `_CUT_NOTE` still says the turn was
        # cut. The closing half of that sentence is gone with the names it is cut in
        # the middle of, which is the trade this ordering makes on purpose: a model
        # missing "the content is omitted here" is guessing at a file; a model missing
        # the question is guessing at everything.
        assert "the user attached" in sent
        assert sent.endswith(history._CUT_NOTE)
        # The other half of the same fix: a floor measured on the stub grows with the
        # filenames, which put it at 61 845 against a 48 000 budget.
        frame = len(history._ASKS) + len(history._CUT_NOTE)
        assert len(sent) <= max(
            config.HISTORY_CHAR_BUDGET, config.MAX_PROMPT_CHARS + frame
        )


def _shot(name: str, kilobytes: int) -> Attachment:
    """An image attachment of roughly the given size, as the uploader would hand it."""
    return Attachment(
        name, "image", "",
        data=b"\x89PNG\r\n\x1a\n" + b"x" * (kilobytes * 1024),
        mime="image/png",
        size=kilobytes * 1024,
    )


def test_one_screenshot_is_always_sent_however_big_it_is():
    """The common case, and the reason the ceiling never refuses the first image.

    A reader who attaches one screenshot asked a question about that screenshot, and
    an image silently dropped here answers a different question. An upload too big to
    send is refused at the upload, with a message about uploading.
    """
    built = history.build([user("what is this error?", _shot("one.png", 64))],
                          "S", vision=True)
    parts = built[-1]["content"]
    assert [part["type"] for part in parts] == ["text", "image_url"]
    assert "image limit" not in parts[0]["text"]


def test_the_images_past_the_request_ceiling_are_named_rather_than_dropped(
    monkeypatch,
):
    """Nothing bounded the assembled request but the provider.

    A data URL is deliberately uncounted against the character budget — see `_length`
    — so 87 legal 240 KB images assembled a 26.6 MB request and the reader was shown
    "this conversation got too long. Clear the chat", about pictures attached to the
    question they had just asked. `config.MAX_IMAGE_REQUEST_BYTES` is the ceiling, and
    what goes over it is named in the text so the model can say what it did not get.
    """
    monkeypatch.setattr(config, "MAX_IMAGE_REQUEST_BYTES", 120_000)
    shots = [_shot(f"shot-{n}.png", 64) for n in range(1, 6)]
    built = history.build([user("compare these", *shots)], "S", vision=True)
    parts = built[-1]["content"]
    sent = [part for part in parts if part["type"] == "image_url"]
    spent = sum(len(part["image_url"]["url"]) for part in sent)
    assert 0 < len(sent) < len(shots), "the ceiling sent all of them or none"
    assert spent <= config.MAX_IMAGE_REQUEST_BYTES
    # The ones that did not go are named, in the order they were attached, so the
    # answer can say which picture it is not talking about.
    note = parts[0]["text"]
    assert "image limit" in note
    for shot in shots[len(sent):]:
        assert shot.filename in note
    for shot in shots[: len(sent)]:
        assert f"{shot.filename}." not in note.split("image limit")[-1]

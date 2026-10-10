"""A relative link in a quoted section is read against the page it was quoted from.

The User Guide writes links between its own pages the way mkdocs wants them, relative
to the page: `[connecting chapter](connection.md)`, `../../slurm/main.md`, `./faq.md`.
A section leaves its page the moment `search_docs` returns it, and an answer that quotes
it carries the link along. `links.resolve` then had only the filename to go on, and a
filename is unique until it is not.

The 2026-10-10 corpus refresh is when it stopped being unique. Upstream added an SDE2
tutorial beside the SDE3 one, the two data-transfer pages both link `connection.md`, and
there were now two of those. The refresh's own guard caught it: the faithful-answer
sweep in `test_answer_checks.py` reported both data-transfer pages as citing a page that
does not exist, and the refresh was left open for review instead of landing. In the app
the same answer would have shipped its link unlinked, and the turn would have logged an
invented citation that the model did not invent. `./faq.md` on the storage page had been
unresolvable the same way all along, among six `faq.md` files, and nothing had asked.

An answer also cites the section it quoted, so that page is what the link is relative
to: `fix_links` and `unresolved` collect the pages a text cites by id and hand them to
`resolve`. Nothing about retrieval moves. The obvious alternative, rewriting every
relative link to a full corpus path when the page is read, was measured first and
rejected: the path's directory words count as body text, and on the shipped corpus that
alone moved the SDE3 "Software" page from sixth to seventh for its own title.
"""

from __future__ import annotations

import posixpath

import pytest

from sage import corpus as corpus_mod
from sage import links
from sage.profile import Source

BASE = "https://guide.example/"


def page(title: str, heading: str, body: str) -> str:
    return f"# {title}\n\n## {heading}\n\n{body}\n"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("guide")
    pages = {
        "sde2/connection.md": page("Connection", "Logging in", "Open the SDE2 desktop."),
        "sde3/connection.md": page("Connection", "Logging in", "Open the SDE3 desktop."),
        "sde2/data-transfer.md": page(
            "Data Transfer", "Step 1",
            "Log in as described in [connecting chapter](connection.md). Only SDE2 "
            "users can reach SDE2.",
        ),
        "sde3/data-transfer.md": page(
            "Data Transfer", "Step 1",
            "Log in as described in [connecting chapter](connection.md). Only SDE3 "
            "users can reach SDE3.",
        ),
        "storage/main.md": page(
            "Storage", "Quotas", "Quota questions are in the [storage FAQ](./faq.md)."
        ),
        "storage/faq.md": page("Storage FAQ", "Checking a quota", "Run `quota`."),
        "slurm/main.md": page(
            "Slurm", "Jobs",
            "See the [Slurm FAQ](faq.md#limits) and [where files go](../storage/main.md).",
        ),
        "slurm/faq.md": page("Slurm FAQ", "Limits", "Jobs run for at most 36 hours."),
        "software/binsanity.md": page(
            "BinSanity", "Notes", "[MetaBAT2](metabat2.md) needs much less memory."
        ),
    }
    for path, text in pages.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    return corpus_mod.build(
        (Source(name="docs", path=str(root), links="mkdocs", base_url=BASE),)
    )


def answer(*cited: str, quoting: str) -> str:
    """A sentence from the documentation, then the sections it came from, as cited."""
    marks = " ".join(f"([Step]({chunk_id}))" for chunk_id in cited)
    return f"{quoting} {marks}\n"


QUOTE = "Log in as described in [connecting chapter](connection.md)."


class TestAFilenameTwoPagesShare:
    def test_it_resolves_against_the_page_the_answer_cites(self, built):
        text = answer("docs/sde3/data-transfer.md#step-1", quoting=QUOTE)
        assert f"[connecting chapter]({BASE}sde3/connection/)" in links.fix_links(
            text, built
        )
        assert links.unresolved(text, built) == []

    def test_the_other_page_gets_its_own(self, built):
        text = answer("docs/sde2/data-transfer.md#step-1", quoting=QUOTE)
        assert f"({BASE}sde2/connection/)" in links.fix_links(text, built)

    def test_with_nothing_beside_it_the_filename_is_still_not_guessed(self, built):
        assert links.resolve("connection.md", built) is None

    def test_two_cited_pages_that_could_have_written_it_are_still_a_guess(self, built):
        text = answer(
            "docs/sde2/data-transfer.md#step-1",
            "docs/sde3/data-transfer.md#step-1",
            quoting=QUOTE,
        )
        fixed = links.fix_links(text, built)
        assert "connection/" not in fixed
        assert "connecting chapter" in fixed
        # Unlinked, and not an invention either: the documentation writes it.
        assert links.unresolved(text, built) == []


class TestTheOtherRelativeShapes:
    def test_dot_slash_is_the_page_s_own_directory(self, built):
        text = answer(
            "docs/storage/main.md#quotas",
            quoting="Quota questions are in the [storage FAQ](./faq.md).",
        )
        assert f"({BASE}storage/faq/)" in links.fix_links(text, built)
        assert links.resolve("./faq.md", built) is None

    def test_an_anchor_survives_the_resolution(self, built):
        text = answer("docs/slurm/main.md#jobs", quoting="See the [Slurm FAQ](faq.md#limits).")
        assert f"({BASE}slurm/faq/#limits)" in links.fix_links(text, built)

    def test_a_link_up_a_directory_is_read_from_its_own_page(self, built):
        text = answer(
            "docs/slurm/main.md#jobs", quoting="See [where files go](../storage/main.md)."
        )
        assert f"({BASE}storage/main/)" in links.fix_links(text, built)


class TestWhatIsStillReportedAsInvented:
    def test_a_path_nobody_wrote_is_reported(self, built):
        text = answer(
            "docs/sde3/data-transfer.md#step-1",
            quoting="See [the SDE3 guide](docs/sde3/nowhere.md).",
        )
        assert links.unresolved(text, built) == ["docs/sde3/nowhere.md"]

    def test_a_broken_link_the_documentation_writes_is_not_an_invention(self, built):
        """The real BinSanity page links `metabat2.md`, which the User Guide lacks."""
        text = answer(
            "docs/software/binsanity.md#notes",
            quoting="[MetaBAT2](metabat2.md) needs much less memory.",
        )
        assert links.unresolved(text, built) == []
        assert links.fix_links(text, built).startswith("MetaBAT2 needs")


def test_every_relative_link_in_the_corpus_resolves_beside_its_own_page(real_corpus):
    """The property the refresh tripped over, asked of every link rather than one sentence.

    The faithful-answer sweep only quotes the first prose line of each section, which is
    why `./faq.md` on the storage page went unnoticed. This asks every internal link the
    bundled documentation writes: cited beside the page that wrote it, does it land
    where that page meant? A link to a page the User Guide does not have is skipped,
    because there is nowhere right for it to land.
    """
    checked = 0
    wrong = []
    for chunk in real_corpus.chunks:
        here = real_corpus.document(f"{chunk.source}/{chunk.path}")
        for match in links._MARKDOWN_LINK.finditer(chunk.text):
            target = match.group(2)
            if target.startswith(links._EXTERNAL):
                continue
            path, _, anchor = target.partition("#")
            meant = posixpath.normpath(posixpath.join(posixpath.dirname(chunk.path), path))
            document = real_corpus.document(f"{chunk.source}/{meant}")
            if document is None:
                continue
            checked += 1
            got = links.resolve(target, real_corpus, [here])
            if got != real_corpus.url_for(document, anchor):
                wrong.append((chunk.id, target, got))
    assert checked > 50, f"only {checked} relative links found to check"
    assert not wrong, wrong[:5]

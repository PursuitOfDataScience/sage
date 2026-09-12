"""Axis C, gated: the corpus properties the app depends on and cannot check at runtime.

The app's ceiling is its documents, and three of these would break answers silently. An
id `search_docs` advertises but `read_doc` cannot resolve is a dead end the model has to
recover from mid-turn. A chunk with no URL is a citation with nothing to click. A new
empty document is a topic that quietly stops being answerable.

Counts rather than absences where a count is the honest bound: the User Guide and the
scraped site overlap by construction, so duplicates cannot be forbidden — only held at
the number measured, so a new one is visible.
"""

from __future__ import annotations

import pytest

from evals import corpus_health

# Measured on the tree that introduced this file.
KNOWN_EMPTY = {
    # 0 bytes upstream, so no rclone question is answerable at all. The retrieval eval
    # has carried this as a comment since it was written.
    "docs/data_transfer/cloud/rclone.md",
    # 188 bytes of boilerplate from the scrape.
    "web/takecourse.txt",
}
# Split, because the two are not the same problem. A page indexed twice wastes a result
# slot and is fixable upstream; identical text under two different titles is shared
# boilerplate that must keep its own citation — deduplicating the index would answer a
# Booth question with a link to the BFI page.
MAXIMUM_SAME_PAGE_TWICE = 2          # measured 2 (web/midway2 under two URLs)
MAXIMUM_SHARED_BOILERPLATE = 2       # measured 2 (bfi.md and booth.md)
MAXIMUM_NEAR_DUPLICATE_PAIRS = 0     # measured 0
MINIMUM_PAGES_FINDABLE_BY_TITLE = 1.0    # measured 1.00 (was 0.939, 7 of 114)


@pytest.fixture(scope="module")
def measured(real_corpus, real_index):
    return corpus_health.measure(real_corpus, real_index)


class TestIntegrity:
    def test_every_advertised_id_resolves(self, measured):
        """`read_doc` resolves against the in-memory corpus and nothing else."""
        broken = measured["unresolvable_ids"]
        assert not broken, f"{len(broken)} ids do not resolve: {broken[:5]}"

    def test_every_chunk_has_a_url(self, measured):
        urlless = measured["chunks_without_url"]
        assert not urlless, f"{len(urlless)} chunks cannot be cited: {urlless[:5]}"

    def test_every_url_is_a_usable_web_address(self, measured):
        """A citation is the one string in this app that becomes an `href`.

        "Has a URL" was all that was asked. A space in it, two fragment markers, no
        scheme, a control character — each is a link that lands nowhere, and nothing
        downstream notices: `anchor_check.py` validates against the live site but is
        network-bound and out of the suite.
        """
        bad = measured["malformed_urls"]
        assert not bad, f"{len(bad)} unusable citation URLs: {bad[:3]}"

    def test_the_two_url_checks_partition_rather_than_overlap(self, real_corpus):
        """Absent is one finding, present-but-unusable is the other. Not both.

        `malformed_urls` reported the empty URL as "no http scheme", so every finding was
        doubled in a report that prints the two side by side — and on a corpus using
        `links = "none"`, the default scheme, for a corpus with nowhere to send the reader,
        it called every chunk an unusable citation URL. A check that fires on the app
        working as designed is a check nobody can read.
        """
        urlless = set(corpus_health.chunks_without_url(real_corpus))
        malformed = {row["id"] for row in corpus_health.malformed_urls(real_corpus)}
        assert not (urlless & malformed)

    def test_a_corpus_with_nowhere_to_link_reports_no_unusable_urls(self, tmp_path):
        """The `links = "none"` deployment, which the check used to condemn wholesale."""
        from sage import runtime  # noqa: PLC0415
        from sage.profile import Profile, Source  # noqa: PLC0415

        page = tmp_path / "a.md"
        page.write_text("# A\n\n## Doing the thing\n\n" + "Press the lever twice. " * 20)
        built = runtime.build(
            Profile(sources=(Source(name="private", path=str(tmp_path)),))
        ).corpus
        assert built.chunks
        assert corpus_health.malformed_urls(built) == []
        assert len(corpus_health.chunks_without_url(built)) == len(built.chunks)

    def test_every_source_the_profile_declares_contributed(self, measured, profile):
        """Derived from the profile rather than a hardcoded pair.

        `corpus.build` skips a source whose `reader` nothing registered — deliberately, so
        one misconfigured tree cannot take a multi-source deployment down. The cost is that
        the app boots looking healthy with a whole tree missing, and CI's own check only
        asserts that *some* chunks exist. A third source added to the profile is now
        required to contribute the day it is added, rather than the day somebody notices.
        """
        declared = {source.name for source in profile.sources}
        assert set(measured["sources"]) == declared
        for name, row in measured["sources"].items():
            assert row["chunks"] > 0, f"{name} indexed nothing"

    def test_no_profile_field_is_left_as_a_literal_brace(self, measured):
        """`prompts.render` substitutes six names and leaves the rest alone by design.

        The cost is silent: a profile author writing `{corpus_name}` — a documented field —
        sends the braces to the model. Both shipped prompts are clean; this is the check a
        second deployment needs, and it only fails on a placeholder that names a real field.
        """
        missed = [
            row["placeholder"] for row in measured["unrendered_placeholders"]
            if row["is_a_profile_field"]
        ]
        assert not missed, (
            "these name profile fields but reach the model as literal text: "
            + ", ".join(f"{{{name}}}" for name in missed)
        )

    def test_every_registry_name_the_profile_uses_exists(self, measured):
        """A typo caught as one line with the valid names beside it.

        A bad `links` scheme or `retrieval.engine` raises at boot with the registry's own
        list, which is right. A bad `reader` is skipped with a log line, so a single-source
        deployment boots and answers every question with "the documentation does not appear
        to cover it" — this app's worst state, and the one hardest to notice.
        """
        wrong = measured["unregistered_names"]
        assert not wrong, "names nothing registered: " + "; ".join(
            f"{row['kind']} {row['name']!r} at {row['where']} "
            f"(registered: {', '.join(row['registered'])})"
            for row in wrong
        )

    def test_the_tools_it_checks_are_the_ones_the_app_builds(self):
        """Read from `DEFAULT_TOOLS`, not spelled a second time here.

        Two copies of a name are two to keep in step: a deployment that registers a third
        tool had it unchecked, and renaming one of the two would have failed at boot from
        the registry while this check still called the deployment healthy.
        """
        from sage.profile import active
        from sage.tools import DEFAULT_TOOLS

        assert corpus_health.unregistered_names(active()) == []
        wrong = corpus_health.unregistered_names(
            active(), (*DEFAULT_TOOLS, "no_such_tool")
        )
        assert [row["name"] for row in wrong] == ["no_such_tool"]
        assert set(DEFAULT_TOOLS) <= set(wrong[0]["registered"])


class TestWhatTheCorpusCannotAnswer:
    def test_no_new_empty_document(self, measured):
        found = {f"{row['source']}/{row['path']}" for row in measured["empty_documents"]}
        assert found <= KNOWN_EMPTY, (
            "documents that have gone empty: " + "; ".join(sorted(found - KNOWN_EMPTY))
        )

    def test_a_document_that_filled_up_should_be_taken_off_the_list(self, measured):
        """The other direction, so the list cannot outlive the problem it records."""
        found = {f"{row['source']}/{row['path']}" for row in measured["empty_documents"]}
        filled = KNOWN_EMPTY - found
        assert not filled, (
            "no longer empty, remove from KNOWN_EMPTY: " + "; ".join(sorted(filled))
        )


class TestPagesThatYieldNothing:
    """Asked by outcome, not by file size, and read off the corpus rather than the disk.

    A page excluded on purpose never becomes a Document; a page that was read and produced
    nothing becomes one with no chunks. A first version of this walked the tree and
    reported all twelve deliberate exclusions — the publication dumps and the radiology
    scrape — as problems.
    """

    def test_only_the_known_empty_page_yields_nothing(self, measured):
        assert measured["indexing_nothing"] == [
            "docs/data_transfer/cloud/rclone.md"
        ], measured["indexing_nothing"]

    def test_deliberate_exclusions_are_not_reported(self, measured):
        reported = " ".join(measured["indexing_nothing"])
        for excluded in ("publications", "learn-radiology", "vislab"):
            assert excluded not in reported


class TestDuplication:
    def test_no_new_page_is_indexed_twice(self, measured):
        groups = measured["duplicates"]["same_page_twice"]
        assert len(groups) <= MAXIMUM_SAME_PAGE_TWICE, (
            f"{len(groups)} pages indexed twice: {groups[:3]}"
        )

    def test_shared_boilerplate_is_held_at_the_measured_count(self, measured):
        groups = measured["duplicates"]["shared_boilerplate"]
        assert len(groups) <= MAXIMUM_SHARED_BOILERPLATE, (
            f"{len(groups)} boilerplate groups: {groups[:3]}"
        )

    def test_the_two_kinds_are_told_apart(self, measured):
        """The classification is the point; a single count reads as four bugs."""
        duplicated = measured["duplicates"]
        assert len(duplicated["same_page_twice"]) + len(
            duplicated["shared_boilerplate"]
        ) == len(duplicated["exact_groups"])

    def test_near_duplicates_are_held_at_the_measured_count(self, measured):
        near = measured["duplicates"]["near"]
        assert len(near) <= MAXIMUM_NEAR_DUPLICATE_PAIRS, (
            f"{len(near)} near-duplicate pairs: {near[:3]}"
        )


class TestFindability:
    def test_most_pages_are_retrievable_by_their_own_title(self, measured):
        rate = measured["self_reachability"]["rate"]
        assert rate >= MINIMUM_PAGES_FINDABLE_BY_TITLE, (
            f"only {rate:.1%} of pages can be found by their own title"
        )

    def test_every_page_is_retrievable_by_its_own_title(self, measured):
        """There is nothing left on the list, so the list itself is the assertion.

        This used to name the two of seven worth a reader's attention and record that
        neither was fixable here. Both were. `singularity.md` is still titled `# Modules`
        upstream — the citation chip for the Singularity page still reads "Modules — …",
        and that part is still the User Guide's to fix — but the page is now retrieved at
        rank 5 for the word, behind the pages a reader typing it actually wants. The
        seventh, `MidwayGeoSpatial`, matched nothing at all in the index: a term appearing
        in no document *body* scores zero even where it does appear in the title and the
        path, because `_inverse_document_frequency` returns 0 and the scorer skips the
        term before reaching either boost. A synonym group in the profile connects the
        compound to the `gis` and `geospatial` its own prose uses, which is cheaper than
        the CamelCase split this test used to argue against — that would still touch every
        score in the index to rescue one page.
        """
        rows = measured["self_reachability"]["unreachable"]
        assert rows == [], "\n".join(
            f"{row['title']!r} -> {row['page']} (rank {row['rank']}); got "
            + ", ".join(f"{got['page']} {got['score']}" for got in row["found_instead"])
            for row in rows
        )

    def test_a_miss_says_which_page_won_and_by_how_much(self):
        """The diagnosis, held on a corpus that still has a miss in it.

        `7 are not findable, incl. one titled 'Modules'` was the whole report for four
        different causes, and a page name alone cannot tell "came seventh" from "matched
        nothing" — which need opposite fixes. Asserted against a synthetic miss rather
        than the shipped corpus, because the shipped corpus no longer has one and a check
        that cannot fail reads as a pass.

        Seven rivals, because `SEARCH_LIMIT` is six: a smaller corpus cannot produce a
        ranking miss at all. The shape left is the one no title weighting can cure — the
        page's own body never says the words in its title, and the rivals' bodies do.
        """
        from sage import retrieval
        from sage.corpus import Chunk, Corpus

        def chunk(path: str, title: str, breadcrumb: str, text: str) -> Chunk:
            return Chunk(id=f"docs/{path}#a", source="docs", path=path, doc_title=title,
                         heading="A", breadcrumb=breadcrumb, text=text,
                         url=f"https://x/{path}")

        built = Corpus(
            chunks=[
                chunk("wanted.md", "Xyzzy details",
                      "Xyzzy details \u203a Set-up and general questions \u203a Are "
                      "there any limits to running jobs",
                      "storage quota information " * 12),
            ] + [
                chunk(f"rival{n}.md", f"Rival {n}", f"Rival {n} \u203a Xyzzy details",
                      "xyzzy details are discussed at length here " * 12)
                for n in range(7)
            ],
            documents={},
        )
        # By page, not a single row: the rivals are unfindable by their own titles too
        # — a synthetic body says nothing about "Rival 3" — and that is beside the point.
        rows = {
            row["page"]: row
            for row in corpus_health.self_reachability(
                retrieval.build(built), built
            )["unreachable"]
        }
        row = rows["docs/wanted.md"]
        assert row["title"] == "Xyzzy details"
        assert row["rank"] == 8
        assert len(row["found_instead"]) == 3
        assert all(got["page"].startswith("docs/rival") for got in row["found_instead"])
        assert row["found_instead"][0]["score"] > 0

    def test_a_page_that_matches_nothing_is_told_apart_from_one_that_came_seventh(self):
        """`rank` is None for the first and a number for the second.

        `MidwayGeoSpatial` scored nothing anywhere while `web/faqs.txt` was one slot
        short, and the old row printed both as a bare page name. A synonym group fixes
        the first and a ranking change fixes the second; nothing in the report said which
        was which.
        """
        from sage import retrieval
        from sage.corpus import Chunk, Corpus

        built = Corpus(
            chunks=[
                Chunk(id="docs/a.md#a", source="docs", path="a.md",
                      doc_title="Qwghlm", heading="Qwghlm", breadcrumb="Qwghlm",
                      text="storage quota " * 20, url="https://x/#a"),
            ],
            documents={},
        )
        [row] = corpus_health.self_reachability(
            retrieval.build(built), built
        )["unreachable"]
        assert row["rank"] is None
        assert row["found_instead"] == []


class TestAdvertisedTopics:
    def test_every_topic_retrieves_something(self, measured):
        """`identity.topics` is what `search_docs` tells the model it covers."""
        empty = [row["topic"] for row in measured["topics"] if not row["top_page"]]
        assert not empty, "topics with no matching section: " + "; ".join(empty)

    @pytest.mark.xfail(reason="a one-word query scores below the floor", strict=False)
    def test_every_topic_is_answerable_without_a_caveat(self, measured):
        """Known, and worth keeping visible: a reader who types one word gets the caveat.

        `Slurm`, `storage` and `policy` score 11–19 against a floor of 20, because the
        score is an unnormalised sum and a single common term earns very little of it.
        Not a missing topic — a property of short queries. An xpass here means short
        queries have been normalised, which would be worth noticing.
        """
        caveated = [row["topic"] for row in measured["topics"] if not row["confident"]]
        assert not caveated, "caveated topics: " + "; ".join(caveated)


class TestEveryUnreachablePageIsReportedTheSameWay:
    """One list, one shape. `tools/scorecard.py` reads `row["page"]` from every entry.

    The empty-title branch appended a bare string while the branch below it appended a
    dict, so a page whose title is missing took the whole card down with `TypeError:
    string indices must be integers` — a crash in the report about the corpus, caused by
    the corpus. Latent today because every bundled page has a title.
    """

    def index_of(self, doc_title: str):
        from sage import retrieval
        from sage.corpus import Chunk, Corpus

        built = Corpus(
            chunks=[Chunk(id="docs/x.md#a", source="docs", path="x.md",
                          doc_title=doc_title, heading="A", breadcrumb="A",
                          text="body " * 40, url="https://x/#a")],
            documents={},
        )
        return retrieval.build(built), built

    def test_an_untitled_page_is_a_row_like_any_other(self):
        index, built = self.index_of("")
        rows = corpus_health.self_reachability(index, built)["unreachable"]
        # An untitled page has nothing to search for, so the diagnosis fields are the
        # empty ones rather than absent — the shape is the point of this class.
        assert rows == [
            {"page": "docs/x.md", "title": "", "rank": None, "found_instead": []}
        ]
        assert [row["page"] for row in rows] == ["docs/x.md"]

    def test_the_shipped_corpus_reports_one_shape_too(self, measured):
        rows = measured["self_reachability"]["unreachable"]
        assert all(isinstance(row, dict) and "page" in row for row in rows), rows

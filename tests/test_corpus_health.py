"""Axis C, gated: the corpus properties the app depends on and cannot check at runtime.

The app's ceiling is its documents, and three of these would break answers silently. An
id `search_docs` advertises but `read_doc` cannot resolve is a dead end the model has to
recover from mid-turn. A chunk with no URL is a citation with nothing to click. A new
empty document is a topic that quietly stops being answerable.

Two kinds of assertion, kept apart because the weekly corpus refresh has to treat them
differently. The integrity checks hold for any corpus: an id that does not resolve is a
bug whatever the documents say. The rest are findings ABOUT the documents (which pages
are empty, which sections repeat, which pages their own title cannot find), and those are
held to `evals/corpus_baseline.json`, exactly and in both directions, so a new one is
visible and a fixed one comes off the record. On an ordinary change the corpus is fixed,
so a finding that moves is the code moving it. The refresh re-measures them on the corpus
it is about to land and commits the file with it, so an upstream edit changes what is
expected instead of failing the run: the 2026-10-10 refresh was stopped by three of these
for content nobody here could have changed.
"""

from __future__ import annotations

import os

import pytest

from evals import corpus_health

BASELINE = corpus_health.load_baseline()
UPDATE = "python tools/corpus_check.py --update"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def held(name: str, found: list, explain=None) -> None:
    """`found` is what the baseline records for `name`, or the failure says what to do."""
    expected = BASELINE[name]
    if found == expected:
        return
    appeared = [item for item in found if item not in expected]
    went = [item for item in expected if item not in found]
    lines = [f"{name} moved: {len(appeared)} appeared, {len(went)} went."]
    lines += [f"  + {explain(item) if explain else item}" for item in appeared]
    lines += [f"  - {item}" for item in went]
    lines.append(
        f"If docs/ or web/ changed, `{UPDATE}` records it (the weekly refresh does this "
        "itself). If they did not, the code moved this: run it only if that was the "
        "point, and say why in the commit message."
    )
    pytest.fail("\n".join(lines))


@pytest.fixture(scope="module")
def measured(real_corpus, real_index):
    return corpus_health.measure(real_corpus, real_index)


class TestIntegrity:
    def test_every_advertised_id_resolves(self, measured):
        """`read_doc` resolves against the in-memory corpus and nothing else."""
        broken = measured["unresolvable_ids"]
        assert not broken, f"{len(broken)} ids do not resolve: {broken[:5]}"

    def test_every_chunk_has_a_url(self, measured, real_corpus):
        """Every chunk whose source promised one, which is not every chunk.

        `chunks_without_url` reports all of them on purpose (the card prints what was
        measured), so the scheme a source *declared* is the thing to assert against.
        `links = "none"` says the tree is published nowhere and the honest citation is
        no link at all; the RCC deployment has one (`kb`, the help-desk notes), and over
        the raw list this failed for the app working exactly as designed. The failure it
        was written for is unchanged: a `docs` or `web` chunk with no URL, because the
        path did not match the scheme or `base_url` was never set.
        """
        silent = {s.name for s in real_corpus.sources if s.links == "none"}
        by_id = {chunk.id: chunk for chunk in real_corpus.chunks}
        urlless = [
            chunk_id
            for chunk_id in measured["chunks_without_url"]
            if by_id[chunk_id].source not in silent
        ]
        assert not urlless, f"{len(urlless)} chunks cannot be cited: {urlless[:5]}"

    def test_every_url_is_a_usable_web_address(self, measured):
        """A citation is the one string in this app that becomes an `href`.

        "Has a URL" was all that was asked. A space in it, two fragment markers, no
        scheme, a control character: each is a link that lands nowhere, and nothing
        downstream notices: `anchor_check.py` validates against the live site but is
        network-bound and out of the suite.
        """
        bad = measured["malformed_urls"]
        assert not bad, f"{len(bad)} unusable citation URLs: {bad[:3]}"

    def test_the_two_url_checks_partition_rather_than_overlap(self, real_corpus):
        """Absent is one finding, present-but-unusable is the other. Not both.

        `malformed_urls` reported the empty URL as "no http scheme", so every finding was
        doubled in a report that prints the two side by side, and on a corpus using
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

        `corpus.build` skips a source whose `reader` nothing registered, deliberately, so
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

        The cost is silent: a profile author writing `{corpus_name}`, a documented field,
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
        to cover it": this app's worst state, and the one hardest to notice.
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
    def test_the_empty_documents_are_the_ones_on_record(self, measured):
        """Both directions, so the list cannot outlive the problem it records.

        `docs/data_transfer/cloud/rclone.md` is 0 bytes upstream, so no rclone question
        is answerable at all, and `web/takecourse.txt` is 188 bytes of boilerplate from
        the scrape. A page that fills up comes off the record as surely as a new empty
        one goes on it.
        """
        held(
            "empty_documents",
            sorted(f"{row['source']}/{row['path']}" for row in measured["empty_documents"]),
        )


class TestPagesThatYieldNothing:
    """Asked by outcome, not by file size, and read off the corpus rather than the disk.

    A page excluded on purpose never becomes a Document; a page that was read and produced
    nothing becomes one with no chunks. A first version of this walked the tree and
    reported all twelve deliberate exclusions (the publication dumps and the radiology
    scrape) as problems.
    """

    def test_the_pages_that_yield_nothing_are_the_ones_on_record(self, measured):
        held("indexing_nothing", sorted(measured["indexing_nothing"]))

    def test_deliberate_exclusions_are_not_reported(self, measured):
        reported = " ".join(measured["indexing_nothing"])
        for excluded in ("publications", "learn-radiology", "vislab"):
            assert excluded not in reported


class TestDuplication:
    """Counts, not absences: the User Guide and the scraped site overlap by construction.

    Split, because the two are not the same problem. A page indexed twice wastes a result
    slot and is fixable in the scrape; identical text under two different titles is shared
    boilerplate that must keep its own citation, because deduplicating the index would
    answer a Booth question with a link to the BFI page. The SDE2 and SDE3 tutorials are
    the same kind of thing: two systems, one set of instructions, two pages to cite.
    """

    def test_the_pages_indexed_twice_are_the_ones_on_record(self, measured):
        held(
            "same_page_twice",
            sorted(sorted(group) for group in measured["duplicates"]["same_page_twice"]),
        )

    def test_the_shared_boilerplate_is_the_one_on_record(self, measured):
        held(
            "shared_boilerplate",
            sorted(sorted(group) for group in measured["duplicates"]["shared_boilerplate"]),
        )

    def test_the_two_kinds_are_told_apart(self, measured):
        """The classification is the point; a single count reads as four bugs."""
        duplicated = measured["duplicates"]
        assert len(duplicated["same_page_twice"]) + len(
            duplicated["shared_boilerplate"]
        ) == len(duplicated["exact_groups"])

    def test_the_near_duplicates_are_the_ones_on_record(self, measured):
        held(
            "near_duplicates",
            sorted(sorted((row["a"], row["b"])) for row in measured["duplicates"]["near"]),
        )


class TestFindability:
    def test_the_pages_their_own_title_cannot_find_are_the_ones_on_record(self, measured):
        """Each page asked for by its own title, against the list of the ones that fail.

        This list reached empty once, and the history of how is worth keeping. Of the
        seven on it, `singularity.md` is still titled `# Modules` upstream (its citation
        chip still reads "Modules", and that part is the User Guide's to fix) but was
        retrieved at rank 5 for the word. `MidwayGeoSpatial` matched nothing at all: a term
        appearing in no document *body* scores zero even where it does appear in the title
        and the path, because `_inverse_document_frequency` returns 0 and the scorer skips
        the term before reaching either boost. A synonym group in the profile connects the
        compound to the `gis` and `geospatial` its own prose uses, which is cheaper than a
        CamelCase split that would touch every score in the index to rescue one page.

        Then the 2026-10-10 refresh brought an SDE2 tutorial whose Spack section says
        `module` and `software` a dozen times in a few lines, and two one-word titles fell
        to eighth behind it: `Modules` (`singularity.md` again) and `Software`, which five
        pages now share. Neither is something the code here got worse at, so they are on
        the record rather than failing every refresh until someone edits a constant, and
        the failure below names the page that won and its score when one is added.
        """
        rows = {row["page"]: row for row in measured["self_reachability"]["unreachable"]}

        def explain(page: str) -> str:
            row = rows[page]
            return (
                f"{page} (titled {row['title']!r}, rank {row['rank']}); got "
                + ", ".join(f"{got['page']} {got['score']}" for got in row["found_instead"])
            )

        held("unfindable_by_title", sorted(rows), explain)

    def test_a_miss_says_which_page_won_and_by_how_much(self):
        """The diagnosis, held on a corpus that still has a miss in it.

        `7 are not findable, incl. one titled 'Modules'` was the whole report for four
        different causes, and a page name alone cannot tell "came seventh" from "matched
        nothing", which need opposite fixes. Asserted against a synthetic miss rather
        than the shipped corpus, because the shipped corpus no longer has one and a check
        that cannot fail reads as a pass.

        Seven rivals, because `SEARCH_LIMIT` is six: a smaller corpus cannot produce a
        ranking miss at all. The shape left is the one no title weighting can cure: the
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
        # (a synthetic body says nothing about "Rival 3"), and that is beside the point.
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
        Not a missing topic: a property of short queries. An xpass here means short
        queries have been normalised, which would be worth noticing.
        """
        caveated = [row["topic"] for row in measured["topics"] if not row["confident"]]
        assert not caveated, "caveated topics: " + "; ".join(caveated)


class TestEveryUnreachablePageIsReportedTheSameWay:
    """One list, one shape. `tools/scorecard.py` reads `row["page"]` from every entry.

    The empty-title branch appended a bare string while the branch below it appended a
    dict, so a page whose title is missing took the whole card down with `TypeError:
    string indices must be integers`: a crash in the report about the corpus, caused by
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
        # empty ones rather than absent; the shape is the point of this class.
        assert rows == [
            {"page": "docs/x.md", "title": "", "rank": None, "found_instead": []}
        ]
        assert [row["page"] for row in rows] == ["docs/x.md"]

    def test_the_shipped_corpus_reports_one_shape_too(self, measured):
        rows = measured["self_reachability"]["unreachable"]
        assert all(isinstance(row, dict) and "page" in row for row in rows), rows


class TestTheRecordIsKeptByTheRefresh:
    """The baseline stops a refresh failing only because the refresh writes it."""

    def test_the_refresh_rewrites_it_before_the_tests_run_and_commits_it(self):
        path = os.path.join(ROOT, ".github", "workflows", "refresh-corpus.yml")
        with open(path, encoding="utf-8") as handle:
            workflow = handle.read()
        update = workflow.index("tools/corpus_check.py --update")
        assert update < workflow.index("run: pytest -q")
        staged = next(line for line in workflow.splitlines() if "git add -A --" in line)
        assert "evals/corpus_baseline.json" in staged

    def test_what_moved_is_what_changed_and_nothing_else(self, tmp_path):
        before = {"empty_documents": ["docs/a.md"], "shared_boilerplate": [["x#1", "y#1"]]}
        after = {"empty_documents": ["docs/a.md", "docs/b.md"], "shared_boilerplate": []}
        assert corpus_health.moved(before, after) == {
            "empty_documents": {"appeared": ["docs/b.md"], "went": []},
            "shared_boilerplate": {"appeared": [], "went": [["x#1", "y#1"]]},
        }
        assert corpus_health.moved(after, after) == {}
        path = tmp_path / "baseline.json"
        corpus_health.save_baseline(after, str(path))
        assert corpus_health.load_baseline(str(path)) == after

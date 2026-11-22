import pytest

from sage import retrieval, tools


def runner(index) -> tools.ToolRunner:
    """A turn's tool runner over a given index, built the way the app builds one."""
    return tools.build(index).runner()


def test_search_returns_paths_the_model_can_read_back(real_index):
    out = runner(real_index).run(tools.SEARCH_DOCS, {"query": "storage quota"})
    assert "path: docs/" in out
    assert "snippet:" in out


def test_empty_search_is_reported_not_crashed(real_index):
    out = runner(real_index).run(tools.SEARCH_DOCS, {"query": ""})
    assert "No matching RCC documentation" in out


def test_hopeless_search_points_at_the_help_desk(real_index):
    out = runner(real_index).run(tools.SEARCH_DOCS, {"query": "zzzz qqqq xxxx"})
    assert "Help Desk" in out


def test_reading_a_section_returns_it_with_a_breadcrumb(real_index):
    tool = runner(real_index)
    out = tool.run(READ := tools.READ_DOC, {"path": "docs/slurm/sbatch.md#managing-jobs"})
    assert READ == "read_doc"
    assert "Batch jobs › Managing jobs" in out
    assert "Sections on this page:" in out


def test_reads_are_recorded_as_sources(real_index):
    tool = runner(real_index)
    tool.run(tools.READ_DOC, {"path": "docs/slurm/sbatch.md#managing-jobs"})
    tool.run(tools.READ_DOC, {"path": "docs/slurm/sbatch.md#managing-jobs"})
    assert len(tool.sources) == 1
    assert tool.sources[0].url.endswith("#managing-jobs")


def test_reading_a_whole_page_works(real_index):
    out = runner(real_index).run(tools.READ_DOC, {"path": "docs/glossary.md"})
    assert "Glossary" in out


def test_a_long_page_returns_an_outline_instead_of_being_silently_cut(real_index):
    out = runner(real_index).run(tools.READ_DOC, {"path": "docs/slurm/sbatch.md"})
    assert "Sections on this page:" in out
    assert "read_doc again" in out


class TestTheToollessPathIsToldTheSameThing:
    """Zero results reached two paths and only one of them said so.

    `search_docs` returns "No matching documentation was found …". `gather_context`
    inserted its caveat under `if caveat and blocks`, so a query matching *nothing*
    returned an empty string, `grounded()` saw no context and passed the question to the
    model with the system prompt and nothing else. The model then answered from its own
    memory, with no caveat and no sources: on the one path that has no second round in
    which to notice.

    `sbatchh` is the demonstration: one keystroke off a real command, zero results here.
    """

    QUERY = "sbatchh"

    def test_the_query_really_does_retrieve_nothing(self, real_index):
        """Reproduce first: without this, the two tests below cannot fail."""
        assert real_index.search(self.QUERY) == []

    def test_the_tool_path_says_so(self, real_index):
        out = runner(real_index).run(tools.SEARCH_DOCS, {"query": self.QUERY})
        assert "No matching RCC documentation was found" in out

    def test_the_toolless_path_says_so_too(self, real_index, profile):
        context, chunks = tools.gather_context(
            real_index, self.QUERY, identity=profile.identity
        )
        assert "No matching RCC documentation was found" in context
        assert chunks == []

    def test_it_is_not_told_to_search_again(self, real_index, profile):
        """The one clause that differs, because it is the one it cannot act on."""
        context, _chunks = tools.gather_context(
            real_index, self.QUERY, identity=profile.identity
        )
        assert "keywords" not in context
        assert "Try different" in runner(real_index).run(
            tools.SEARCH_DOCS, {"query": self.QUERY}
        )

    def test_both_still_hand_over_the_contact(self, real_index, profile):
        context, _chunks = tools.gather_context(
            real_index, self.QUERY, identity=profile.identity
        )
        assert profile.identity.contact in context

    def test_a_weak_but_non_empty_retrieval_still_carries_its_caveat(
        self, real_index, profile
    ):
        """The case that already worked, held down while the empty one was fixed."""
        context, chunks = tools.gather_context(
            real_index,
            "wie beantrage ich mehr Speicher fuer meinen Job",
            identity=profile.identity,
        )
        assert chunks, "expected a weak-but-non-empty retrieval to test against"
        assert context.startswith(tools.RETRIEVAL_WARNING)

    def test_a_good_query_is_untouched(self, real_index, profile):
        context, chunks = tools.gather_context(
            real_index, "how do I submit a batch job", identity=profile.identity
        )
        assert len(chunks) > 1
        assert tools.RETRIEVAL_WARNING not in context
        assert "No matching" not in context

    def test_the_sentence_is_built_once(self, profile):
        """Both callers, one function: the wording cannot drift between them."""
        with_retry = tools.nothing_found(profile.identity)
        without = tools.nothing_found(profile.identity, retry=False)
        assert with_retry == without.replace(
            "was found.", "was found. Try different or broader keywords.", 1
        )

    def test_a_deployment_with_no_contact_offers_no_pointer(self):
        from sage.profile import Identity  # noqa: PLC0415

        plain = tools.nothing_found(Identity(), retry=False)
        assert "point the user at" not in plain
        assert plain.startswith("No matching documentation was found.")


class TestPathSafety:
    """Reads resolve against the index, so a filesystem path cannot be reached."""

    def test_traversal_is_not_resolvable(self, real_index):
        for probe in (
            "docs/../../etc/passwd",
            "docs/../app.py",
            "/etc/passwd",
            "web/../../../../etc/hosts",
        ):
            out = runner(real_index).run(tools.READ_DOC, {"path": probe})
            assert "not in the documentation index" in out or "invalid path" in out

    def test_unknown_source_is_rejected(self, real_index):
        out = runner(real_index).run(tools.READ_DOC, {"path": "secrets/key.md"})
        assert "not in the documentation index" in out

    def test_missing_path_is_rejected(self, real_index):
        out = runner(real_index).run(tools.READ_DOC, {"path": ""})
        assert "invalid path" in out

    def test_nothing_outside_the_index_is_ever_recorded(self, real_index):
        tool = runner(real_index)
        tool.run(tools.READ_DOC, {"path": "docs/../app.py"})
        assert tool.sources == []


def test_unknown_tool_name_is_reported(real_index):
    assert "Unknown tool" in runner(real_index).run("rm_rf", {})


class TestArgumentsAreWhateverTheModelTyped:
    """`llm._parse` guarantees a dict and nothing about what is in it.

    A weak model typing its query as a number (`{"query": 123}`) used to raise
    AttributeError out of `.strip()`, which ended the turn with an error card blaming
    the network for a mistake the model made.
    """

    @pytest.mark.parametrize("query", [123, 4.5, ["gpu", "jobs"], {"q": "x"}, True])
    def test_a_search_argument_of_any_type_answers(self, real_index, query):
        assert runner(real_index).run(tools.SEARCH_DOCS, {"query": query})

    @pytest.mark.parametrize("path", [123, ["docs/slurm/sbatch.md"], {"p": 1}])
    def test_a_read_argument_of_any_type_answers(self, real_index, path):
        assert "Error" in runner(real_index).run(tools.READ_DOC, {"path": path})

    def test_a_missing_argument_is_not_searched_for_as_the_word_none(self, real_index):
        tool = runner(real_index)
        assert tool.run(tools.SEARCH_DOCS, {}) == tool.run(
            tools.SEARCH_DOCS, {"query": ""}
        )


def test_tool_schemas_are_well_formed(real_index):
    schemas = tools.build(real_index).schemas
    names = {schema["function"]["name"] for schema in schemas}
    assert names == {tools.SEARCH_DOCS, tools.READ_DOC}
    for schema in schemas:
        function = schema["function"]
        assert schema["type"] == "function"
        assert function["description"]
        assert function["parameters"]["required"]


def test_the_schema_describes_this_deployments_corpus(real_index, profile):
    """The description is what tells a model when to reach for the tool, so it names
    the corpus, and it gets the name from the profile, not from this repository."""
    search = next(
        schema for schema in tools.build(real_index).schemas
        if schema["function"]["name"] == tools.SEARCH_DOCS
    )
    assert profile.identity.corpus_name in search["function"]["description"]


def test_a_deployment_can_register_a_tool_of_its_own(real_index):
    """The registry is the seam: a third tool is a factory and a name, and the
    schemas the provider is sent follow from the set, not from a constant."""

    class Weather:
        name = "weather"

        def __init__(self, retriever, identity):
            self.identity = identity

        @property
        def schema(self):
            return {"type": "function", "function": {"name": self.name}}

        def run(self, arguments, record):
            return "cold"

    tools.factories.register("weather", Weather)
    try:
        toolset = tools.build(real_index, names=(tools.SEARCH_DOCS, "weather"))
        assert [s["function"]["name"] for s in toolset.schemas] == [
            tools.SEARCH_DOCS, "weather"
        ]
        assert toolset.runner().run("weather", {}) == "cold"
    finally:
        tools.factories.remove("weather")


def test_runner_works_on_an_empty_index():
    from sage.corpus import Corpus

    tool = runner(retrieval.Index(Corpus()))
    assert "No matching" in tool.run(tools.SEARCH_DOCS, {"query": "anything"})


class TestAPageWithNothingInIt:
    """A page that is in the index and has nothing in it.

    `docs/data_transfer/cloud/rclone.md` was one: 0 bytes upstream, so it produced no
    chunks and no search result offered it, but it was exactly the path a model would
    guess for an rclone question, and `read_doc` resolves documents by name. It used to
    answer with a header and one blank line, which reads as a page that failed to load
    and leaves the model's own memory as the best thing in its context.

    The 2026-11-21 refresh deleted that file and left no empty page in the corpus, so
    the page is put back here, on top of the real index. Asking for the deleted path
    instead would pass every assertion below for the wrong reason: a path that is not in
    the index is an error too, and records no source either.
    """

    EMPTY = "docs/data_transfer/cloud/rclone.md"

    @pytest.fixture(scope="class")
    def index(self, real_corpus):
        from sage.corpus import Corpus, Document

        empty = Document(
            source="docs",
            path="data_transfer/cloud/rclone.md",
            title="Rclone",
            url="https://docs.rcc.uchicago.edu/data_transfer/cloud/rclone/",
            text="",
        )
        assert empty.id == self.EMPTY
        corpus = Corpus(
            chunks=real_corpus.chunks,
            documents={**real_corpus.documents, empty.id: empty},
            sources=real_corpus.sources,
        )
        return retrieval.build(corpus)

    def test_it_says_so_instead_of_returning_a_header_and_nothing(self, index):
        out = runner(index).run("read_doc", {"path": self.EMPTY})
        assert out.startswith("Error:")
        assert "no content" in out
        assert "search_docs" in out

    def test_nothing_is_recorded_as_a_source(self, index):
        """Nothing was read, so the Sources strip must not offer the reader a blank page."""
        tool = runner(index)
        tool.run("read_doc", {"path": self.EMPTY})
        assert tool.sources == []

    def test_a_page_with_content_still_reads(self, index):
        tool = runner(index)
        out = tool.run("read_doc", {"path": "docs/slurm/sbatch.md"})
        assert out.startswith("=== ")
        assert tool.sources

"""The tools the model can call, and the thing that runs them.

A tool is an object with a `name`, a `schema` the provider is sent, and a `run` that
returns text. Two ship — search the index, read one section — and they are built by
factories in a registry, so a deployment that wants a third (look up a term, check a
status page, query an API the documentation describes) registers one and names it:

    from sage.tools import factories, Toolset
    factories.register("glossary", lambda retriever, identity: Glossary(...))

Reads resolve against the in-memory corpus rather than the filesystem, so the old
`realpath` traversal guard is no longer the thing standing between a crafted `path`
argument and an arbitrary file — only ids that were indexed can resolve at all.
Unknown ids get an error string the model can recover from.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from . import config
from .corpus import Chunk
from .profile import Identity
from .profile import active as _active
from .registry import Registry
from .retrieval import Retriever

logger = logging.getLogger(__name__)

SEARCH_DOCS = "search_docs"
READ_DOC = "read_doc"

# How a weak retrieval announces itself at the top of a search result. Named here rather
# than written twice, because `ToolRunner` counts them and `SearchDocs.format` writes them.
RETRIEVAL_WARNING = "RETRIEVAL WARNING:"

# What a tool calls to say "the answer may now cite this section". Passing it in
# rather than letting a tool reach for the runner keeps a custom tool from having to
# know how sources are deduplicated.
Record = Callable[[Chunk], None]


class Tool(Protocol):
    name: str
    #: What to call this tool in front of a reader. `name` is an identifier the provider
    #: API needs and nobody else can use; this is the word an answer that mentions the
    #: tool at all should have used instead, and `sage.redact` swaps one for the other.
    #: Optional: a tool that leaves it empty is simply never substituted.
    label: str

    @property
    def schema(self) -> dict: ...

    def run(self, arguments: dict, record: Record) -> str: ...


# name -> (retriever, identity) -> Tool
factories: Registry = Registry("tool")

# The two a documentation assistant is built out of. A profile that wants a different
# set says so; this is the default because search-then-read is what the prompt
# describes and what the retrieval eval measures.
DEFAULT_TOOLS = (SEARCH_DOCS, READ_DOC)


def _text(value) -> str:
    """A tool argument as a string, whatever the model made it.

    `None` becomes empty rather than "None", which would go on to be searched for.
    """
    return "" if value is None else str(value)


def _outline(document) -> str:
    if not document.outline:
        return ""
    shown = document.outline[:60]
    more = "" if len(document.outline) == len(shown) else "\n  … (outline truncated)"
    return "Sections on this page:\n" + "\n".join(shown) + more


# --- search ----------------------------------------------------------------


def nothing_found(identity: Identity, *, retry: bool = True) -> str:
    """"No matching documentation was found" — the sentence, built once.

    Two paths reach zero results and only one of them used to say so. `search_docs`
    returned this; the tool-less path returned an empty context and `grounded()` handed
    the model the system prompt and the question with nothing between them, so a reader
    who typed `sbatchh` — one keystroke off a real command, and zero results on this
    corpus — got an answer from the model's own memory, with no caveat and no sources.
    That is the refusal gate missing exactly where it matters most: the tool loop can
    search again, and this path has no second round. `gather_context`'s own docstring
    already said so, and handled only the *weak* case, not the empty one.

    `retry` is the one clause that differs, because it is the one thing that depends on
    the caller: telling a model that cannot call tools to try different keywords is
    telling it to do something it has no way of doing.
    """
    again = " Try different or broader keywords." if retry else ""
    pointer = (
        f" and point the user at the {identity.contact_label} ({identity.contact})"
        if identity.has_contact
        else ""
    )
    return (
        f"No matching {identity.qualifier}documentation was found.{again} If the topic "
        f"genuinely is not covered, say so plainly{pointer} rather than guessing "
        "specifics."
    )


class SearchDocs:
    """Rank the corpus for a query and describe the best sections."""

    name = SEARCH_DOCS
    label = "search"

    def __init__(self, retriever: Retriever, identity: Identity) -> None:
        self.retriever = retriever
        self.identity = identity

    @property
    def _about(self) -> str:
        topics = self.identity.topics.strip()
        return f" about {topics}" if topics else ""

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    f"Search {self.identity.corpus_name} for sections relevant to "
                    "the user's question. Returns ranked results, each with a "
                    "`path`, a section title and a snippet. Call this FIRST for any "
                    f"{self.identity.qualifier}question{self._about}, then read the "
                    "most promising result with read_doc."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Keywords or a natural-language question, e.g. "
                                "'sbatch GPU job' or 'scratch quota purge policy'."
                            ),
                        }
                    },
                    "required": ["query"],
                },
            },
        }

    def no_results(self) -> str:
        return nothing_found(self.identity)

    def format(self, results, caveat: str = "") -> str:
        if not results:
            return self.no_results()
        lines = []
        if caveat:
            # Ahead of the results, not after them: a model reads top-down, and a
            # warning underneath six confident-looking rows arrives too late to
            # change the answer.
            lines += [f"{RETRIEVAL_WARNING} {caveat}", ""]
        lines += [
            f"Top matching {self.identity.qualifier}documentation sections. "
            "Call read_doc with the exact `path` to read one in full.",
            "",
        ]
        for result in results:
            lines.append(f"- path: {result.id}")
            lines.append(
                f"  section: {result.chunk.breadcrumb}  (source: {result.source})"
            )
            lines.append(f"  snippet: {result.snippet}")
        return "\n".join(lines)

    def run(self, arguments: dict, record: Record) -> str:
        query = _text(arguments.get("query")).strip()
        logger.info("search_docs(%r)", query)
        results = self.retriever.search(query)
        assessment = self.retriever.assess(query, results)
        if not assessment.confident:
            logger.info("weak retrieval for %r (top %.1f, unseen %s)",
                        query, assessment.top_score, assessment.unknown_terms)
        return self.format(results, assessment.caveat())


# --- read ------------------------------------------------------------------


class ReadDoc:
    """Return one indexed section, or a long page's outline, in full."""

    name = READ_DOC
    label = "read"

    def __init__(self, retriever: Retriever, identity: Identity) -> None:
        self.retriever = retriever
        self.identity = identity

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "Read one documentation section in full. Pass the exact `path` "
                    "from a search_docs result (for example "
                    f"'{self.identity.path_example}'). Dropping the '#section' part "
                    "returns the whole page, or its outline if the page is very long."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": (
                                "The exact `path` value from a search_docs result."
                            ),
                        }
                    },
                    "required": ["path"],
                },
            },
        }

    def run(self, arguments: dict, record: Record) -> str:
        path = _text(arguments.get("path")).strip()
        if not path or "/" not in path:
            return (
                "Error: invalid path. Pass the exact `path` from a search_docs "
                f"result, e.g. '{self.identity.path_example}'."
            )

        corpus = self.retriever.corpus
        chunk = corpus.chunk(path)
        if chunk is not None:
            record(chunk)
            document = corpus.document(f"{chunk.source}/{chunk.path}")
            outline = _outline(document) if document else ""
            header = f"=== {chunk.breadcrumb} ({chunk.id}) ==="
            return "\n\n".join(part for part in (header, chunk.text, outline) if part)

        document = corpus.document(path.split("#", 1)[0])
        if document is None:
            return (
                f"Error: '{path}' is not in the documentation index. "
                "Run search_docs again and use a `path` exactly as returned."
            )

        if not document.text.strip():
            # A page that exists and says nothing. `docs/data_transfer/cloud/rclone.md` is
            # 0 bytes in the upstream snapshot, and it is a name a model would guess for an
            # rclone question — so this is reachable without any search result offering it.
            # Returned as an error rather than as a header with nothing under it: an empty
            # read looks like a page that failed to load, and the model's own best guess
            # about a blank section is the one thing this app must not encourage. No
            # source is recorded either, because nothing was read.
            return (
                f"Error: '{document.id}' is in the index but has no content. "
                "Run search_docs and read a different section."
            )

        first = next(
            (item for item in corpus.chunks if item.path == document.path), None
        )
        if first is not None:
            record(first)

        header = f"=== {document.title} ({document.id}) ==="
        if len(document.text) <= config.MAX_DOC_CHARS:
            return f"{header}\n\n{document.text}"

        intro = document.text[: config.MAX_DOC_CHARS // 3]
        return (
            f"{header}\n\nThis page is long; here is the beginning plus its outline. "
            "Call read_doc again with 'path#section-anchor' for a specific section.\n\n"
            f"{intro}\n\n{_outline(document)}"
        )


factories.register(SEARCH_DOCS, SearchDocs)
factories.register(READ_DOC, ReadDoc)


# --- the set, and running it ------------------------------------------------


class Toolset:
    """The tools this deployment offers, and their schemas.

    Built once per runtime and shared; a `ToolRunner` is per turn, because it is what
    remembers which sections the turn actually read.
    """

    def __init__(self, tools: list[Tool]) -> None:
        self.tools = tools
        self.by_name = {tool.name: tool for tool in tools}

    @property
    def schemas(self) -> list[dict]:
        return [tool.schema for tool in self.tools]

    @property
    def public_names(self) -> dict[str, str]:
        """Internal name -> reader-facing name, for `sage.redact`.

        Built from the tools themselves rather than written down anywhere, so a
        deployment that registers a third tool has it covered by giving that tool a
        `label` — and a tool with none is left out, which is the same as saying "this
        name may appear in an answer".
        """
        return {
            tool.name: getattr(tool, "label", "")
            for tool in self.tools
            if getattr(tool, "label", "")
        }

    def runner(self) -> ToolRunner:
        return ToolRunner(self)


def build(
    retriever: Retriever,
    identity: Identity | None = None,
    names: tuple[str, ...] = DEFAULT_TOOLS,
) -> Toolset:
    who = identity or _active().identity
    return Toolset([factories.get(name)(retriever, who) for name in names])


class ToolRunner:
    """Executes tool calls for one turn and records which sections were read."""

    def __init__(self, toolset: Toolset) -> None:
        self.toolset = toolset
        self.sources: list[Chunk] = []
        self.queries: list[str] = []
        self.last_read: str = ""
        # How many searches this turn came back caveated. The one number about the
        # refusal gate that a *deployment* can produce: offline, `tools/gate_check.py`
        # measures it against 45 labelled questions somebody wrote, and this says how
        # often it fires on the questions readers actually ask. Read off the tool result
        # rather than plumbed through the Tool protocol, so a custom tool needs to know
        # nothing about it.
        self.caveats: int = 0

    def _remember(self, chunk: Chunk) -> None:
        if all(existing.id != chunk.id for existing in self.sources):
            self.sources.append(chunk)
        # The label of the section most recently exposed, for the status line.
        self.last_read = chunk.label

    def run(self, name: str, arguments: dict) -> str:
        tool = self.toolset.by_name.get(name)
        if tool is None:
            return f"Unknown tool: {name}"
        # `_text(...)` inside each tool because a tool argument is whatever the model
        # typed. `llm._parse` guarantees a dict and nothing about what is in it, and a
        # model that types its query as a number — `{"query": 123}` — used to end the
        # turn with an AttributeError dressed up as "something went wrong reaching the
        # assistant".
        if name == SEARCH_DOCS:
            self.queries.append(_text(arguments.get("query")).strip())
        result = tool.run(arguments, self._remember)
        if name == SEARCH_DOCS and result.startswith(RETRIEVAL_WARNING):
            self.caveats += 1
        return result


def gather_context(
    retriever: Retriever,
    query: str,
    limit: int | None = None,
    identity: Identity | None = None,
):
    """One-shot retrieval for models that cannot call tools.

    Returns (context_text, chunks). The chunks become the answer's Sources strip,
    exactly as if the model had read them itself.

    The caveat matters more here than in the tool loop: a model that cannot call tools
    cannot search again when the context is wrong, so if retrieval was weak, being told
    so is the only thing between it and an invented answer.

    Which is why the empty case is a sentence and not an empty string. `if caveat and
    blocks` meant a query matching *nothing* — the one case where the model has least to
    go on — was the one case that travelled with no warning at all: `grounded()` saw an
    empty context and passed the question through untouched. Both paths now say the same
    thing when there is nothing to say.
    """
    results = retriever.search(query, limit or config.SEARCH_RESULTS)
    who = identity or _active().identity
    if not results:
        return nothing_found(who, retry=False), []
    blocks = [
        f"=== {result.chunk.breadcrumb} ({result.chunk.id}) ===\n{result.chunk.text}"
        for result in results
    ]
    caveat = retriever.assess(query, results).caveat()
    if caveat:
        blocks.insert(0, f"{RETRIEVAL_WARNING} {caveat}")
    return "\n\n".join(blocks), [result.chunk for result in results]

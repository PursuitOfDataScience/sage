"""What a corpus is, once it has been read: chunks, documents, and their sources.

Kept apart from the readers that produce it and the builder that walks the trees, so
that a reader can import the shapes it returns without importing the walk, and a test
can build a corpus out of literals without touching the filesystem at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..profile import Source
from . import urls


@dataclass
class Chunk:
    #: `{source}/{path}#{anchor}` — this app's own name for the section, and what
    #: `search_docs` hands the model to cite. Unique by construction: a heading that
    #: repeats on a page gets `-1`, `-2` appended so two sections are never one id.
    id: str
    source: str
    path: str
    doc_title: str
    heading: str
    breadcrumb: str
    text: str
    #: Where the reader goes, which is **not** `id` with the prefix swapped. The two use
    #: different suffixes for a repeated heading and neither is a typo: mkdocs-material
    #: numbers its second `AlphaFold 2` `#alphafold-2_1`, while an id here counts the
    #: parts an oversized section splits into as well and so reads `alphafold-2-1`. So
    #: `alphafold.md#alphafold-2-1` is a real id whose URL ends `#alphafold-2_1`, and
    #: `links.resolve` goes through the index to get from one to the other rather than
    #: rewriting the string. Comparing an *id* against the published page's ids reports
    #: working citations as broken; `tools/anchor_check.py` checks these.
    #:
    #: This used to say a repeated heading "publishes at one anchor on the site", and it
    #: does not — `alphafold.md` carries `AlphaFold 2` and `AlphaFold 3` three times
    #: each, the site publishes six anchors, and every chunk cited the bare two. Four of
    #: those sections were unreachable from any citation and two citations landed a
    #: reader at the first occurrence of the right name. `corpus.readers` numbers them
    #: the way `toc.unique` does now.
    url: str

    @property
    def label(self) -> str:
        """Short human label for a citation chip."""
        if self.heading and self.heading != self.doc_title:
            return f"{self.doc_title} — {self.heading}"
        return self.doc_title


@dataclass
class Document:
    source: str
    path: str
    title: str
    url: str
    text: str
    outline: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.source}/{self.path}"


@dataclass
class Corpus:
    """Everything the retriever and the citation layer are allowed to know about.

    `sources` travels with the chunks rather than being looked up from the active
    profile at the point of use. That is what lets one process serve two corpora, and
    it is what stops a scoring prior — "the maintained guide outranks the scraped
    site" — from being a fact about the deployment's configuration read at some later
    moment, when the configuration may have moved on.
    """

    chunks: list[Chunk] = field(default_factory=list)
    documents: dict[str, Document] = field(default_factory=dict)
    sources: tuple[Source, ...] = ()

    def chunk(self, chunk_id: str) -> Chunk | None:
        return self._by_id.get(chunk_id)

    def document(self, doc_id: str) -> Document | None:
        return self.documents.get(doc_id)

    def source(self, name: str) -> Source | None:
        return next((item for item in self.sources if item.name == name), None)

    def weight(self, name: str) -> float:
        """The scoring prior for a tree. Unknown trees are neutral, not excluded."""
        found = self.source(name)
        return found.weight if found else 1.0

    def url_for(self, document: Document, anchor: str = "") -> str:
        """Re-derive a document's URL with an anchor on it.

        Used when the model cites `docs/slurm/sbatch.md#gpu-jobs` as a path rather
        than naming an indexed chunk: the document knows where it was published, and
        the anchor comes from the citation. A source this corpus does not recognise
        falls back to the URL recorded at index time, which is the honest answer —
        the anchor cannot be placed without knowing the scheme.
        """
        found = self.source(document.source)
        if found is None:
            return document.url
        return urls.build(found, document.path, anchor, document.url)

    def __post_init__(self) -> None:
        self._by_id = {chunk.id: chunk for chunk in self.chunks}

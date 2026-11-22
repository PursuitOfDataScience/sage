"""Discover, clean and chunk the documentation corpus.

Three seams, in the order a file passes through them:

* **`profile.Source`**: which trees exist, what they are called, and what is in them.
* **`readers`**: how a file in one of those trees becomes a document and its chunks.
* **`urls`**: where that document is published, which is what a citation links to.

`build()` walks the trees and does none of that work itself. It used to: the walk
branched on the literal source names "docs" and "web" to pick a chunker, to decide
whether a file's own URL mattered, and to decide which exclusion rule applied: three
places a second corpus had to be threaded through, in a function whose job is to open
files.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

from ..profile import Source, active
from . import readers as readers_module
from . import urls
from .model import Chunk, Corpus, Document
from .readers import read, readers
from .urls import schemes

logger = logging.getLogger(__name__)

__all__ = [
    "Chunk",
    "Corpus",
    "Document",
    "Source",
    "build",
    "read",
    "readers",
    "schemes",
    "summarize",
    "url_for",
    "urls",
]


def url_for(source: Source, rel_path: str, anchor: str = "") -> str:
    """The published URL for a path in a source tree, under that tree's scheme."""
    return urls.build(source, rel_path, anchor)


def _host(url: str) -> str:
    try:
        return urlsplit(url).netloc.lower()
    except ValueError:
        return ""


def _is_excluded(source: Source, rel_path: str, url: str) -> bool:
    if any(rel_path.endswith(name) for name in source.exclude_files):
        return True
    return bool(url) and _host(url) in source.exclude_hosts


def build(sources: tuple[Source, ...] | None = None) -> Corpus:
    """Scan the configured source trees and return a fully chunked corpus."""
    if sources is None:
        sources = active().sources
    chunks: list[Chunk] = []
    documents: dict[str, Document] = {}
    skipped = 0

    for source in sources:
        if not os.path.isdir(source.path):
            logger.warning("Source tree missing, skipping: %s", source.path)
            continue
        if not readers.has(source.reader):
            logger.error(
                "Source %r asks for reader %r, which nothing registered; skipping it. "
                "Registered readers: %s",
                source.name, source.reader, ", ".join(readers.names()),
            )
            continue

        extensions = tuple(source.extensions)
        for root, _dirs, names in os.walk(source.path):
            for name in sorted(names):
                if extensions and not name.lower().endswith(extensions):
                    continue
                full = os.path.join(root, name)
                rel = os.path.relpath(full, source.path).replace(os.sep, "/")
                try:
                    with open(full, encoding="utf-8", errors="replace") as handle:
                        raw = handle.read()
                except OSError as exc:
                    logger.warning("Unreadable document %s: %s", full, exc)
                    continue

                if _is_excluded(source, rel, readers_module.probe_url(source, raw)):
                    skipped += 1
                    continue

                document, page_chunks = read(source, rel, raw)
                if not page_chunks:
                    # Surfaces upstream gaps: a 0-byte page in the User Guide (as
                    # docs/data_transfer/cloud/rclone.md was until 2026-11-21) is a
                    # document nothing can cite.
                    logger.warning("No indexable content in %s", document.id)
                documents[document.id] = document
                chunks.extend(page_chunks)

    logger.info(
        "Corpus built: %d chunks across %d documents (%d excluded)",
        len(chunks),
        len(documents),
        skipped,
    )
    return Corpus(chunks=chunks, documents=documents, sources=tuple(sources))


def summarize(corpus: Corpus) -> str:
    """One-line description used in logs and the About panel."""
    return f"{len(corpus.documents)} pages · {len(corpus.chunks)} sections"

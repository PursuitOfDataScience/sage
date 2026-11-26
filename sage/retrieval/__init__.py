"""Retrieval: one interface, one engine shipped, and the seam between them.

    from sage import corpus, retrieval
    index = retrieval.build(corpus.build())

`build` reads the engine's name from the profile, so swapping BM25 for something
else is a line of TOML and a module that registers itself:

    # myengine.py
    from sage.retrieval import engines
    engines.register("embeddings", lambda corpus, retrieval, doc="": MyIndex(...))

Importing `sage.retrieval.bm25` here is what puts the built-in engine in the
registry, and `sage.retrieval.rerank` adds `bm25+rerank` the same way. A third-party
engine registers itself on import too, which its own module has to arrange, because
this package cannot import what it has not heard of.
"""

from __future__ import annotations

from .. import config
from ..corpus import Corpus
from ..profile import Profile, Retrieval
from ..profile import active as _active
from . import rerank  # noqa: F401 (registers `bm25+rerank`)
from .base import Assessment, Result, Retriever, engines
from .bm25 import Index
from .text import Vocabulary, snippet, stem

__all__ = [
    "Assessment",
    "Index",
    "Result",
    "Retriever",
    "Vocabulary",
    "build",
    "engines",
    "snippet",
    "stem",
    "vocabulary",
]


def vocabulary(profile: Profile | None = None) -> Vocabulary:
    """The subject's words, as the active profile has them."""
    return Vocabulary((profile or _active()).retrieval, config.SYNONYM_WEIGHT)


def build(
    corpus: Corpus,
    retrieval: Retrieval | None = None,
    documentation: str = "",
) -> Retriever:
    """The engine the profile asks for, over this corpus."""
    profile = _active()
    settings = retrieval or profile.retrieval
    return engines.get(settings.engine)(
        corpus, settings, documentation or profile.identity.documentation
    )

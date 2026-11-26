"""BM25 finds the candidates, a rerank model orders them, and the gate stays lexical.

Registered as `bm25+rerank`. A cross-encoder reads the query and each candidate
section together, which is a different bet from the embeddings that were measured
against this corpus on 2026-10-15 and tied BM25: those replaced the lexical score, this
only reorders what the lexical score already found. So recall cannot drop (the same
sections come back, in a different order), and what it can move is which section is
first.

Two things it must not touch, and does not:

* **The refusal gate.** `assess` is BM25's own, computed from BM25's own ordering, so
  `Assessment.confident` sees exactly the scores it saw before. A rerank score is a
  relevance probability on a different scale, and the gate's thresholds (20/26) were
  measured against the lexical one; mixing them would refuse or admit questions for a
  reason nobody measured.
* **An answer.** If the rerank request fails, times out, or comes back in a shape this
  module does not recognise, the search returns BM25's order, logged once. Retrieval
  that runs in milliseconds locally must never become the reason a question went
  unanswered.

The provider that serves the model is named in the profile (`[retrieval]
rerank_provider`), so the key and base URL come from that provider's entry and nothing
here knows which company it is.
"""

from __future__ import annotations

import logging

from .. import config, env
from ..corpus import Corpus
from ..profile import Retrieval
from ..profile import active as _active
from .base import Assessment, Result, engines
from .bm25 import Index
from .bm25 import build as build_bm25

logger = logging.getLogger(__name__)

#: How much of a section the rerank model reads. Its title carries most of the
#: signal and the opening of the text most of the rest, and a request of twenty
#: whole sections would be a large one to make for every search.
DOCUMENT_CHARS = 1500


class Reranked:
    """The `Retriever` interface over a BM25 index, with the order decided by a model."""

    def __init__(self, base: Index, *, model: str, url: str, key: str,
                 depth: int, timeout: float = 8.0) -> None:
        self.base = base
        self.corpus: Corpus = base.corpus
        self.model = model
        self.url = url
        self.key = key
        self.depth = max(depth, 1)
        self.timeout = timeout
        self._warned = False
        #: Searches that fell back to BM25's order, so a measurement can say how many
        #: of its numbers are the model's and how many are BM25's.
        self.fallbacks = 0

    def __getattr__(self, name: str):
        # Everything else the tools and checks read off an index (`total`, the
        # vocabulary) is the BM25 index's, unchanged: only the order is new.
        if name == "base":
            raise AttributeError(name)
        return getattr(self.base, name)

    def search(self, query: str, limit: int | None = None) -> list[Result]:
        limit = limit or config.SEARCH_RESULTS
        candidates = self.base.search(query, max(limit, self.depth))
        if len(candidates) < 2 or not (self.model and self.url and self.key):
            return candidates[:limit]
        order = self._order(query, candidates)
        if order is None:
            return candidates[:limit]
        return _capped([candidates[index] for index in order], limit)

    def assess(self, query: str, results: list[Result] | None = None) -> Assessment:
        # BM25's results, not the ones passed in: the gate is measured against the
        # lexical ordering, so it is computed from it whatever order the reader sees.
        return self.base.assess(query)

    def _order(self, query: str, candidates: list[Result]) -> list[int] | None:
        """The candidates' indexes, most relevant first, or None to keep BM25's order."""
        documents = [
            f"{item.chunk.breadcrumb or item.chunk.doc_title}\n{item.chunk.text}"
            [:DOCUMENT_CHARS]
            for item in candidates
        ]
        try:
            import httpx  # noqa: PLC0415

            response = httpx.post(
                self.url,
                json={"model": self.model, "query": query, "documents": documents,
                      "top_n": len(documents)},
                headers={"Authorization": f"Bearer {self.key}"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            ranked = response.json().get("results")
            seen: list[int] = []
            for item in ranked if isinstance(ranked, list) else ():
                index = item.get("index") if isinstance(item, dict) else None
                if isinstance(index, int) and not isinstance(index, bool) and (
                    0 <= index < len(candidates) and index not in seen
                ):
                    seen.append(index)
            if not seen:
                raise ValueError("no usable ranking in the response")
            # Anything the model did not rank keeps its BM25 place, after the rest.
            return seen + [index for index in range(len(candidates)) if index not in seen]
        except Exception as exc:  # noqa: BLE001 (an answer is never worth a ranking)
            self.fallbacks += 1
            if not self._warned:
                logger.warning("Rerank unavailable (%s); using BM25's order", exc)
                self._warned = True
            return None


def _capped(results: list[Result], limit: int) -> list[Result]:
    """At most `config.MAX_PER_PAGE` sections of one page, as BM25 itself returns.

    The cap is applied again after reordering because the candidate pool is deeper
    than the result set, and its tail is where BM25 parked the sections it had capped.
    Overflow backfills at the end, in the model's order, as `Index._spread` does.
    """
    cap = max(1, config.MAX_PER_PAGE)
    kept: list[Result] = []
    deferred: list[Result] = []
    seen: dict[str, int] = {}
    for item in results:
        page = f"{item.chunk.source}/{item.chunk.path}"
        if seen.get(page, 0) >= cap:
            deferred.append(item)
            continue
        seen[page] = seen.get(page, 0) + 1
        kept.append(item)
        if len(kept) >= limit:
            return kept
    return (kept + deferred)[:limit]


def build(corpus: Corpus, retrieval: Retrieval, documentation: str = "") -> Reranked:
    base = build_bm25(corpus, retrieval, documentation)
    entry = _active().provider(retrieval.rerank_provider)
    if entry is None:
        logger.warning("Rerank provider %r is not in the profile; using BM25 alone",
                       retrieval.rerank_provider)
    url = f"{entry.base_url.rstrip('/')}/rerank" if entry and entry.base_url else ""
    key = env.text(entry.key_env) if entry and entry.key_env else ""
    return Reranked(base, model=retrieval.rerank_model, url=url, key=key,
                    depth=retrieval.rerank_depth)


engines.register("bm25+rerank", build)

"""`bm25+rerank`: the model decides the order, BM25 decides everything else.

Offline: a stand-in for httpx answers the rerank request, so these say what the engine
does with an answer, not whether a model gives good ones. That second question was
measured against the golden set on 2026-11-26 and is why the shipped profile keeps
`engine = "bm25"` (see `sage/retrieval/rerank.py`).
"""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from sage import retrieval
from sage.profile import Retrieval
from sage.retrieval import rerank

QUERY = "how do I submit a batch job"


@pytest.fixture(scope="module")
def base(real_corpus, profile):
    return retrieval.build(real_corpus, profile.retrieval)


def engine(base, **overrides):
    settings = {"model": "vendor/rerank", "url": "https://gw.test/api/v1/rerank",
                "key": "k", "depth": 12}
    settings.update(overrides)
    return rerank.Reranked(base, **settings)


def fake_httpx(monkeypatch, answer):
    sent = []

    class Response:
        def raise_for_status(self):
            if isinstance(answer, Exception):
                raise answer

        def json(self):
            return answer

    def post(url, json=None, headers=None, timeout=None):
        sent.append({"url": url, "json": json, "headers": headers})
        return Response()

    fake = ModuleType("httpx")
    fake.post = post
    monkeypatch.setitem(sys.modules, "httpx", fake)
    return sent


def test_the_models_order_is_the_order_returned(monkeypatch, base):
    candidates = base.search(QUERY, 12)
    reversed_order = list(range(len(candidates)))[::-1]
    sent = fake_httpx(monkeypatch, {"results": [{"index": i, "relevance_score": 1.0}
                                                for i in reversed_order]})
    index = engine(base)
    results = index.search(QUERY, 3)
    assert len(sent) == 1
    assert sent[0]["json"]["query"] == QUERY
    assert len(sent[0]["json"]["documents"]) == len(candidates)
    assert results[0].id == candidates[-1].id
    assert index.fallbacks == 0


def test_the_gate_is_bm25s_whatever_the_order(monkeypatch, base):
    candidates = base.search(QUERY, 12)
    fake_httpx(monkeypatch, {"results": [{"index": i} for i in range(len(candidates))][::-1]})
    index = engine(base)
    reordered = index.search(QUERY)
    assert index.assess(QUERY, reordered) == base.assess(QUERY)


@pytest.mark.parametrize("answer", [RuntimeError("HTTP 422"), {"results": "nope"},
                                    {"results": [{"index": 99}]}, {}])
def test_any_failure_is_bm25s_order(monkeypatch, base, answer):
    fake_httpx(monkeypatch, answer)
    index = engine(base)
    assert [item.id for item in index.search(QUERY, 4)] == [
        item.id for item in base.search(QUERY, 4)]
    assert index.fallbacks == 1


def test_no_key_means_no_request(monkeypatch, base):
    sent = fake_httpx(monkeypatch, {"results": []})
    index = engine(base, key="")
    assert [item.id for item in index.search(QUERY, 4)] == [
        item.id for item in base.search(QUERY, 4)]
    assert sent == []


def test_a_partial_ranking_keeps_the_rest_in_bm25_order(monkeypatch, base):
    candidates = base.search(QUERY, 12)
    fake_httpx(monkeypatch, {"results": [{"index": 2}]})
    results = engine(base).search(QUERY, len(candidates))
    assert results[0].id == candidates[2].id
    assert len({item.id for item in results}) == len(results)


def test_the_index_attributes_tools_read_are_the_base_indexes(base):
    assert engine(base).total == base.total


def test_the_profile_reads_the_settings():
    from sage.profile import from_mapping

    settings = from_mapping({"retrieval": {
        "engine": "bm25+rerank", "rerank_model": " vendor/rerank ",
        "rerank_provider": "openrouter", "rerank_depth": 0,
    }}).retrieval
    assert settings == Retrieval(engine="bm25+rerank", rerank_model="vendor/rerank",
                                 rerank_provider="openrouter", rerank_depth=20)


def test_the_shipped_profile_keeps_bm25(profile):
    """Measured, not assumed: see the module docstring of `sage/retrieval/rerank.py`."""
    assert profile.retrieval.engine == "bm25"

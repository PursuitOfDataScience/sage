"""BM25 over the chunked corpus — the engine this repository ships.

The previous scorer was `+8` title / `+5` path / `+min(count, 5)` body with no IDF
and no length normalization, so a 71 KB publication dump competed on equal footing
with a focused 2 KB page and a term appearing in 100 documents weighed the same as
one appearing in 2. BM25 fixes both, and the profile's synonyms cover the case
keyword search cannot: users describe symptoms ("my job got killed") while docs
describe mechanisms ("OOM", "time limit").

Registered as `bm25`. Everything specific to *this* way of scoring — the k1/b
constants, the title and path boosts, the two confidence thresholds — is read here
and nowhere else, so a second engine is not obliged to have an opinion about them.
"""

from __future__ import annotations

import math
from collections import Counter

from .. import config
from ..corpus import Corpus
from ..profile import Retrieval, active
from .base import Assessment, Result, engines
from .text import (
    _ALNUM_SPLIT,
    STOPWORDS,
    Vocabulary,
    mentions,
    names_a_thing,
    reads_like_a_report,
    snippet,
)

#: The most of the title boost that title-length normalisation may take away, as a
#: fraction. Not in `config` with the other dials on purpose: it is not a knob anybody
#: should be turning per deployment, it is the bound that keeps `_title_weight` from
#: moving a score across `MIN_CONFIDENT_SCORE`. See `_title_weight` for the measurement.
TITLE_LENGTH_FLOOR = 0.75


class Index:
    """In-memory BM25 index. Built once per process and cached by the UI layer."""

    def __init__(
        self,
        corpus: Corpus,
        vocabulary: Vocabulary | None = None,
        documentation: str = "",
    ) -> None:
        self.corpus = corpus
        self.vocabulary = vocabulary or Vocabulary(
            active().retrieval, config.SYNONYM_WEIGHT
        )
        self.documentation = documentation or active().identity.documentation
        self._frequencies: list[Counter[str]] = []
        self._lengths: list[int] = []
        self._titles: list[set[str]] = []
        self._paths: list[set[str]] = []
        self._document_frequency: Counter[str] = Counter()

        tokenize = self.vocabulary.tokenize
        for chunk in corpus.chunks:
            counts = Counter(tokenize(chunk.text))
            self._frequencies.append(counts)
            self._lengths.append(max(sum(counts.values()), 1))
            self._titles.append(set(tokenize(chunk.breadcrumb)))
            self._paths.append(set(tokenize(chunk.path.replace("/", " "))))
            self._document_frequency.update(counts.keys())

        self.total = len(corpus.chunks)
        self.average_length = (
            sum(self._lengths) / self.total if self.total else 1.0
        )
        self.average_title_length = (
            sum(len(title) or 1 for title in self._titles) / self.total
            if self.total
            else 1.0
        )
        self._title_weights = [
            self._title_weight(len(title) or 1) for title in self._titles
        ]

    def _title_weight(self, length: int) -> float:
        """How much one matching title term is worth, given how long the title is.

        The body field is length-normalised and the title field was not, so the title
        boost was a flat `+idf * TITLE_BOOST` per matching term however much of the title
        that term accounted for. A breadcrumb is the whole path of headings — "Running
        Jobs FAQ › Set-up and general questions › Are there any limits to running jobs on
        Midway?" — so a page that merely *contains* the reader's word somewhere in its
        heading trail collected exactly the credit of a page whose title IS that word.

        That is what "pages findable by their own title" was measuring. A reader typing
        `FAQs` got four sections of three `faq.md` pages, all scoring an identical 19.769
        on `faq` in a fifteen-token breadcrumb, and the page actually titled "FAQs" came
        seventh. Same for the four pages titled "Software" and for `Accessing RCC
        clusters`, which lost to two sections of a GIS tutorial whose breadcrumb happens
        to read "Section I: Connecting to Midway Cluster".

        So the title field gets BM25's own normalisation, against the mean title length
        rather than the mean document length — `b` is `BM25_B`, the same shape the body
        already uses.

        `TITLE_LENGTH_FLOOR` is the part that is not textbook, and it is here because
        this score is consumed by an absolute threshold as well as by a sort. Deflating a
        long title's boost lowers the top score of queries that were never about
        findability, and `MIN_CONFIDENT_SCORE` is a flat 20 on an unnormalised scale:
        unclamped, "why did job 41235567 fail" fell from just above the floor to just
        below it and started refusing a question the corpus answers. The floor bounds how
        much of the boost normalisation may take away, which leaves the ranking win intact
        — measured, the clamp costs nothing on any of the six Axis A numbers and holds the
        same result anywhere in 0.68–0.80.
        """
        norm = 1 - config.BM25_B + config.BM25_B * length / (
            self.average_title_length or 1.0
        )
        return max(TITLE_LENGTH_FLOOR, 1.0 / norm) if norm > 0 else 1.0

    def _inverse_document_frequency(self, term: str) -> float:
        frequency = self._document_frequency.get(term, 0)
        if not frequency:
            return 0.0
        return math.log(1 + (self.total - frequency + 0.5) / (frequency + 0.5))

    def search(self, query: str, limit: int | None = None) -> list[Result]:
        limit = config.SEARCH_RESULTS if limit is None else limit
        weights = self.vocabulary.expand(query)
        if not weights or not self.total:
            return []

        scored: list[tuple[float, int]] = []
        for position, chunk in enumerate(self.corpus.chunks):
            counts = self._frequencies[position]
            length = self._lengths[position]
            title = self._titles[position]
            path = self._paths[position]
            title_weight = self._title_weights[position]
            score = 0.0
            matched = False

            for term, weight in weights.items():
                idf = self._inverse_document_frequency(term)
                if not idf:
                    continue
                frequency = counts.get(term, 0)
                if frequency:
                    matched = True
                    denominator = frequency + config.BM25_K1 * (
                        1 - config.BM25_B
                        + config.BM25_B * length / self.average_length
                    )
                    score += weight * idf * frequency * (config.BM25_K1 + 1) / denominator
                if term in title:
                    matched = True
                    score += weight * idf * config.TITLE_BOOST * title_weight
                if term in path:
                    matched = True
                    score += weight * idf * config.PATH_BOOST

            if matched and score > 0:
                # The prior travels with the corpus, because it is a statement about
                # these trees — a maintained guide against a scraped site — and not a
                # setting of the scorer.
                score *= self.corpus.weight(chunk.source)
                scored.append((score, position))

        scored.sort(key=lambda item: (-item[0], self.corpus.chunks[item[1]].id))
        return [
            Result(
                chunk=self.corpus.chunks[position],
                score=round(score, 4),
                snippet=snippet(
                    self.corpus.chunks[position].text, weights, config.SNIPPET_CHARS
                ),
            )
            for score, position in self._spread(scored, limit)
        ]

    def _knows(self, term: str) -> bool:
        """Is this term part of the subject's vocabulary?

        Three ways in, and the third is not about the corpus at all. A term the profile's
        synonym table names is vocabulary the *deployment* has declared — `scavenge` is in
        the RCC profile's groups and appears nowhere in the bundled pages, because the
        documentation calls the same thing preemptible. Refusing to answer over a word the
        profile itself supplies would be the app disagreeing with its own configuration.
        """
        return (
            bool(self._document_frequency.get(term))
            or term in self.vocabulary.synonyms
            or any(term in title for title in self._titles)
        )

    def _near_miss(self, term: str) -> bool:
        """A spelling of something the corpus does know: `favourite` for `favorite`.

        An unfamiliar word one edit away from a term the corpus uses repeatedly is a
        misspelling or a regional variant, not a new topic. Without this, "why is my
        favourite command not available" — the User Guide's own FAQ heading, in British
        spelling — was told the documentation does not cover it.

        Six characters and a single edit, against a term the corpus uses in at least two
        sections. Short words are excluded deliberately: `book` is one edit from `boot`,
        which appears 27 times, and "how do I book a study room" is not a question about
        booting. `named_topics` is decided before this is consulted, so `midway4` — one
        edit from `midway3` — never reaches it.
        """
        if len(term) < 6:
            return False
        letters = "abcdefghijklmnopqrstuvwxyz"
        candidates = {term[:index] + term[index + 1:] for index in range(len(term))}
        candidates |= {
            term[:index] + letter + term[index + 1:]
            for index in range(len(term))
            for letter in letters
        }
        candidates |= {
            term[:index] + term[index + 1] + term[index] + term[index + 2:]
            for index in range(len(term) - 1)
        }
        candidates.discard(term)
        return any(self._document_frequency.get(word, 0) >= 2 for word in candidates)

    def _versioned_unknown(self, term: str) -> bool:
        """`midway4` where the corpus knows `midway`: a version of a name that is not.

        This is the half of the digit rule that was missing. Skipping every term with a
        digit in it is right for a job ID — `41235567` has no name to recognise, and
        counting one as an unseen topic told a reader asking why their job failed that
        the RCC has no documentation about it. But a cluster that does not exist and a
        partition that does not exist are *named* things with a number welded on, so the
        same rule made `midway4`, `bigmem3` and `scratch2` invisible to the one check
        that could have caught them.

        The name part must be known and the whole term must not: that is what separates
        "you have named a variant of something real that does not exist" from a
        UUID (`4bd2c1a8` has no name part) and from `project2` (which the corpus knows).
        """
        split = _ALNUM_SPLIT.match(term)
        if not split:
            return False
        return self._knows(self.vocabulary.stem(split.group(1)))

    def assess(self, query: str, results: list[Result] | None = None) -> Assessment:
        """Judge a query's retrieval without re-ranking it."""
        if results is None:
            results = self.search(query)
        surface = self.vocabulary.surface_forms(query)
        shapes = {
            mention.stem: mention
            for mention in mentions(query, self.vocabulary.stem)
        }

        unknown = []
        named = []
        for term, weight in self.vocabulary.expand(query).items():
            if weight < 1.0:
                continue          # a synonym the reader never typed
            if self._knows(term):
                continue
            if term in STOPWORDS or surface.get(term, term) in STOPWORDS:
                # A corpus not containing "how" says nothing about what it covers, and an
                # unseen stopword has never been why a question was unanswerable. On a
                # corpus whose prose is all declarative — most machine-generated
                # documentation — "how", "do" and "I" are all unseen, and three unseen
                # words against strong evidence refused every question asked of it.
                continue
            versioned = self._versioned_unknown(term)
            if any(character.isdigit() for character in term) and not versioned:
                # A job ID or a node number is not a topic the documentation could
                # have a section about. `_versioned_unknown` is the exception: see above.
                continue
            mention = shapes.get(term)
            named_thing = mention is not None and names_a_thing(
                mention, versioned=versioned
            )
            if not named_thing and self._near_miss(term):
                continue          # a spelling of something the corpus does know
            word = surface.get(term, term)
            unknown.append(word)
            if named_thing:
                # The reader's own spelling, the same one `unknown_terms` carries, so
                # `named_topics` is a strict subset of it rather than the same words in
                # different casing — which is a trap for anything comparing the two.
                #
                # A system, scheduler or package the corpus has never heard of. Held
                # apart from the rest because evidence cannot outweigh it: no amount of
                # scoring on the other words makes this documentation cover Frontera.
                named.append(word)

        top = results[0].score if results else 0.0
        runner_up = results[1].score if len(results) > 1 else 0.0
        return Assessment(
            top_score=top,
            margin=round(top - runner_up, 4),
            unknown_terms=tuple(unknown),
            named_topics=tuple(named),
            reporting=reads_like_a_report(query),
            documentation=self.documentation,
            min_confident_score=config.MIN_CONFIDENT_SCORE,
            strong_score=config.STRONG_SCORE,
        )

    def _spread(
        self, scored: list[tuple[float, int]], limit: int
    ) -> list[tuple[float, int]]:
        """The best `limit`, but no more than `MAX_PER_PAGE` sections of one page.

        Without this, a third of the golden-set questions came back with all of the
        top three from a single page: a search asked for six sections and really
        returned two pages' worth, so the model saw one page's view of the answer and
        never learned that another page contradicted or completed it.

        The cap is a trade, not a free win, and the thing it trades away is invisible
        to a page-level eval: every slot given to a second page is a slot taken from
        the depth of the first. `MAX_PER_PAGE` is the dial. See config for what the
        measurements said about where to set it.

        Overflow is deferred, not discarded: once every page has had its share the
        leftovers backfill in score order, so a query that genuinely only matches one
        page still returns a full set of results rather than a short list.
        """
        if limit <= 0:
            return []
        cap = max(1, config.MAX_PER_PAGE)
        kept: list[tuple[float, int]] = []
        deferred: list[tuple[float, int]] = []
        seen: Counter[str] = Counter()
        for score, position in scored:
            chunk = self.corpus.chunks[position]
            page = f"{chunk.source}/{chunk.path}"
            if seen[page] >= cap:
                deferred.append((score, position))
                continue
            seen[page] += 1
            kept.append((score, position))
            if len(kept) >= limit:
                return kept
        return (kept + deferred)[:limit]


def build(corpus: Corpus, retrieval: Retrieval, documentation: str = "") -> Index:
    return Index(
        corpus, Vocabulary(retrieval, config.SYNONYM_WEIGHT), documentation
    )


engines.register("bm25", build)

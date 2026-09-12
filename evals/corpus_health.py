"""Axis C: what the corpus can and cannot answer, before any model is involved.

The app's ceiling is its documents. No prompt, model or ranking change can answer a
question the corpus does not contain, so a benchmark that measures the app without
measuring the corpus attributes the corpus's limits to the app — and the corpus is the
cheaper thing to fix.

Reachability is reported with its own ceiling attached, and no percentage is offered when
the ceiling is below the chunk count. An earlier version of this reported "20.6% of
chunks reachable" from 50 questions at six results each — 300 slots for 572 chunks —
which is a statement about the question set that reads as a statement about the index.
"""

from __future__ import annotations

import hashlib
import os
import re

from sage import config
from sage.profile import active as _active

from . import identifiers, questions

SEARCH_LIMIT = 6
TINY_DOC_BYTES = 200
SHINGLE = 5
NEAR_DUPLICATE = 0.8


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _shingles(text: str) -> set[str]:
    words = _normalise(text).split()
    if len(words) < SHINGLE:
        return {" ".join(words)} if words else set()
    return {
        " ".join(words[index:index + SHINGLE])
        for index in range(len(words) - SHINGLE + 1)
    }


def sources(corpus) -> dict:
    out: dict[str, dict] = {}
    for chunk in corpus.chunks:
        bucket = out.setdefault(chunk.source, {"chunks": 0, "chars": 0, "pages": set()})
        bucket["chunks"] += 1
        bucket["chars"] += len(chunk.text)
        bucket["pages"].add(chunk.path)
    return {
        name: {
            "chunks": row["chunks"], "chars": row["chars"], "pages": len(row["pages"])
        }
        for name, row in out.items()
    }


def empty_documents() -> list[dict]:
    """Files on disk with nothing in them — a topic the app cannot answer at all.

    Walked from the profile's own source list, so the paths are the ones the corpus was
    built from, environment overrides included.
    """
    found = []
    for source in _active().sources:
        root = source.path
        if not os.path.isdir(root):
            continue
        for base, _dirs, files in os.walk(root):
            for name in sorted(files):
                if not any(name.endswith(ext) for ext in source.extensions):
                    continue
                full = os.path.join(base, name)
                size = os.path.getsize(full)
                if size < TINY_DOC_BYTES:
                    found.append(
                        {
                            "source": source.name,
                            "path": os.path.relpath(full, root),
                            "bytes": size,
                        }
                    )
    return found


def indexing_nothing(corpus) -> list[str]:
    """Pages the builder accepted and got no chunks out of.

    `empty_documents` asks how big a file is; this asks what came out of it, which is the
    question that matters and the one that survives a change to the reader. A 5 KB page
    that indexes to nothing — a reader that stops recognising a heading style, a section
    below `MIN_CHUNK_CHARS` after normalisation — is caught only here, and `self_reachability`
    cannot see it either, because a page with no chunks never enters the list to check.

    Read off the corpus rather than by walking the disk, which is what makes it exact: a
    page excluded on purpose (`exclude_files`, `exclude_hosts` — the publication dumps and
    the radiology scrape) never becomes a Document at all, while a page that was read and
    yielded nothing becomes one with no chunks. A first attempt walked the tree and
    reported all twelve deliberate exclusions as problems.
    """
    with_chunks = {f"{chunk.source}/{chunk.path}" for chunk in corpus.chunks}
    return sorted(page for page in corpus.documents if page not in with_chunks)


def duplicates(corpus) -> dict:
    """Sections that say the same thing twice.

    Two costs, both already paid once here. A duplicate takes one of the six result slots
    the model is handed, and it arrives in the Sources strip as the same page listed
    twice — which is what "Show each destination once" and "Stop citing the same section
    twice" were both about. The User Guide and the scraped website overlap by
    construction, so cross-source pairs are expected; the count is what matters.
    """
    exact: dict[str, list[str]] = {}
    titles: dict[str, set[str]] = {}
    for chunk in corpus.chunks:
        digest = hashlib.sha1(_normalise(chunk.text).encode()).hexdigest()
        exact.setdefault(digest, []).append(chunk.id)
        titles.setdefault(digest, set()).add(chunk.doc_title)

    # Near-duplicates, compared only within a length band so this stays fast enough to
    # belong in a check rather than a job.
    prints = [(chunk, _shingles(chunk.text)) for chunk in corpus.chunks]
    prints.sort(key=lambda pair: len(pair[1]))
    near: list[dict] = []
    for index, (chunk, marks) in enumerate(prints):
        if not marks:
            continue
        for other, other_marks in prints[index + 1:]:
            if len(other_marks) > len(marks) * 1.35:
                break
            if not other_marks:
                continue
            overlap = len(marks & other_marks) / len(marks | other_marks)
            if overlap >= NEAR_DUPLICATE and _normalise(chunk.text) != _normalise(other.text):
                near.append(
                    {
                        "a": chunk.id,
                        "b": other.id,
                        "overlap": round(overlap, 2),
                        "cross_source": chunk.source != other.source,
                    }
                )
                break
    # Two very different things, and counting them together makes the number unreadable.
    # Identical text under ONE title is a page indexed twice — `web/midway2.txt` and
    # `web/support-and-services_midway2.txt` are the same RCC page at two URLs — and it
    # wastes a result slot. Identical text under DIFFERENT titles is shared boilerplate:
    # `bfi.md` and `booth.md` document two databases with the same Globus instructions,
    # and each must keep its own citation. Deduplicating the index would have answered a
    # Booth question with a link to the BFI page.
    repeated = [ids for ids in exact.values() if len(ids) > 1]
    same_page = [
        ids for digest, ids in exact.items()
        if len(ids) > 1 and len(titles[digest]) == 1
    ]
    return {
        "exact_groups": repeated,
        "same_page_twice": same_page,
        "shared_boilerplate": [ids for ids in repeated if ids not in same_page],
        "near": near,
    }


def reachability(index, asked: list[str]) -> dict:
    """How much of the index a realistic question set ever surfaces.

    Reported with the ceiling, because the ceiling is usually the binding constraint:
    `len(asked) * SEARCH_LIMIT` is the most that *could* be touched, and a percentage
    computed without it says nothing about dead index weight.
    """
    touched: set[str] = set()
    for question in asked:
        touched.update(result.chunk.id for result in index.search(question, SEARCH_LIMIT))
    ceiling = len(asked) * SEARCH_LIMIT
    return {
        "questions": len(asked),
        "touched": len(touched),
        "ceiling": ceiling,
        "total": index.total,
        "measurable": ceiling >= index.total,
    }


def self_reachability(index, corpus) -> dict:
    """Can each page be found by asking for it by its own title?

    The honest version of the reachability question, and it took two tries. Asking the 77
    labelled questions and reporting "160 of 572 chunks surfaced" says nothing about the
    index — 77 questions at six results is a ceiling of 462 — so that number stays
    unmeasurable by construction.

    The obvious next attempt, one query per *section*, measured the wrong thing too: it
    reported 72 sections unreachable, and they were sections like `sbatch.md#batch-jobs`
    losing to two siblings of their own page. That is `MAX_PER_PAGE` doing its job, not
    dead weight — the page is retrieved and `read_doc` reaches the section by anchor. A
    metric that moves when the cap moves is a statement about the cap.

    Page granularity is unaffected by it: the cap allows two sections of any page and this
    needs one. A page that cannot be retrieved when the query *is* its own title is weight
    the index carries and no reader can reach.
    """
    titles: dict[str, str] = {}
    for chunk in corpus.chunks:
        titles.setdefault(f"{chunk.source}/{chunk.path}", chunk.doc_title)

    unreachable = []
    for page, title in titles.items():
        if not title.strip():
            # The same shape as the branch below, because a list of two shapes is one
            # `row["page"]` away from a crash — and that is exactly what `scorecard.py`
            # does with it: an untitled page would have taken the whole card down with
            # `TypeError: string indices must be integers` rather than printing a row.
            unreachable.append(_miss(page, title, [], None))
            continue
        results = index.search(title, SEARCH_LIMIT)
        found = {f"{result.chunk.source}/{result.chunk.path}" for result in results}
        if page not in found:
            unreachable.append(_miss(page, title, results, _rank(index, title, page)))
    total = len(titles) or 1
    return {
        "pages": len(titles),
        "unreachable": unreachable,
        "rate": (total - len(unreachable)) / total,
    }


#: How deep to look for a page that lost, to tell "came seventh" from "never matched at
#: all". Those two are different defects with different fixes and the check could not
#: distinguish them: `MidwayGeoSpatial` scored nothing anywhere while `web/faqs.txt` was
#: one slot short, and both printed as the same bare page name.
RANK_DEPTH = 200


def _rank(index, title: str, page: str) -> int | None:
    """Where the page the reader asked for actually came, or None if it never matched."""
    for position, result in enumerate(index.search(title, RANK_DEPTH)):
        if f"{result.chunk.source}/{result.chunk.path}" == page:
            return position + 1
    return None


def _miss(page: str, title: str, results: list, rank: int | None) -> dict:
    """One unfindable page, with enough attached to say *why* without a second run.

    `page` and `title` are what they always were — `tools/scorecard.py` and
    `tools/corpus_check.py` both read them and neither may be edited from here — and the
    three fields after them are the diagnosis.

    This is the part that made the number unactionable. "7 are not findable, incl. one
    titled 'Modules'" names one page out of seven and gives no cause for any of them, so
    the four distinct defects underneath it were invisible: a title shared by four
    different pages (`Software`), a one-word title losing to longer breadcrumbs that
    merely contain the word (`FAQs`), a page that came seventh of six (`Accessing RCC
    clusters`), and a CamelCase compound that matched nothing in the index at all
    (`MidwayGeoSpatial`). Each needs a different fix and the list said only "seven".

    `got` is the top three with their scores, because the competitor is the evidence: the
    `FAQs` miss was four sections of three *other* FAQ pages tied at an identical 19.769
    on one word of a fifteen-word breadcrumb, which says "the title field is not
    length-normalised" and nothing else does.
    """
    return {
        "page": page,
        "title": title,
        #: Rank of the page asked for, or None when nothing in it matched the title.
        "rank": rank,
        "found_instead": [
            {
                "page": f"{result.chunk.source}/{result.chunk.path}",
                "breadcrumb": result.chunk.breadcrumb,
                "score": round(result.score, 3),
            }
            for result in results[:3]
        ],
    }


def topic_coverage(index) -> list[dict]:
    """Every topic the profile advertises, asked about in its own words.

    `identity.topics` is what `search_docs` tells the model it covers. A topic that comes
    back caveated is a promise the app breaks on the one question a reader most expects
    it to handle — though note that a one-word query is a hard case for an unnormalised
    score, which is itself worth knowing.
    """
    names = [
        part.strip()
        for part in re.split(r",| or ", _active().identity.topics)
        if part.strip()
    ]
    out = []
    for name in names:
        assessment = index.assess(name)
        top = index.search(name, 1)
        out.append(
            {
                "topic": name,
                "confident": bool(assessment.confident),
                "score": round(assessment.top_score, 1),
                "top_page": top[0].chunk.path if top else "",
            }
        )
    return out


def unresolvable_ids(corpus) -> list[str]:
    """Every chunk id must resolve back to its chunk.

    `read_doc` resolves against the in-memory corpus and nothing else, so an id
    `search_docs` can advertise but `read_doc` cannot resolve is a dead end the model has
    to recover from. The existing suite checks this for the first twelve golden cases;
    this checks all of them.
    """
    return [chunk.id for chunk in corpus.chunks if corpus.chunk(chunk.id) is None]


def chunks_without_url(corpus) -> list[str]:
    return [chunk.id for chunk in corpus.chunks if not chunk.url]


def malformed_urls(corpus) -> list[dict]:
    """Citation targets that are not usable web addresses.

    "Has a URL" was the only thing asked, and a citation is the one string in this app
    that becomes an `href`. A URL with a space in it, two fragment markers, a control
    character or no scheme is a link that lands nowhere — and unlike a wrong *page*,
    nothing downstream notices: `tools/anchor_check.py` validates against the live site
    but is network-bound and out of the suite.

    Having *no* URL is `chunks_without_url` above, and this used to report it too, as "no
    http scheme". The two are printed side by side, so every finding was doubled — and
    worse than doubled on a corpus where the empty URL is correct. `links = "none"` is a
    supported scheme and the default one, for a corpus with nowhere to send the reader; a
    deployment using it saw every chunk it owns listed as an unusable citation URL, which
    is a check crying wolf about the app working as designed. The two now partition:
    absent is reported once, present-but-unusable is reported here.
    """
    found = []
    for chunk in corpus.chunks:
        url = chunk.url
        if not url:
            continue
        why = ""
        if not url.startswith(("http://", "https://")):
            why = "no http scheme"
        elif url != url.strip() or " " in url:
            why = "whitespace"
        elif url.count("#") > 1:
            why = "two fragment markers"
        elif any(ord(character) < 32 for character in url):
            why = "control character"
        if why:
            found.append({"id": chunk.id, "url": url[:80], "why": why})
    return found


def unregistered_names(profile, tool_names=None) -> list[dict]:
    """Names the profile hands to a registry that nothing has registered.

    Each of the five seams fails differently on a typo, and only two of them fail in a way
    anybody would notice. A bad `links` scheme or `retrieval.engine` raises at boot with the
    registry's own list of valid names, which is the right behaviour. A bad `reader` is
    deliberate the other way: `corpus.build` logs it and skips that source, so a
    multi-source deployment keeps working — and a single-source one boots looking healthy
    and answers every question with "the documentation does not appear to cover it", which
    is this app's worst state.

    So the names are checked directly, before anything is built, where a typo is one line
    with the valid names next to it rather than an empty corpus.
    """
    # `sage.corpus.readers` the *name* is the registry, not the module — the package
    # rebinds it. The URL schemes keep theirs inside the module.
    from sage.corpus import readers as reader_registry
    from sage.corpus.urls import schemes as url_registry
    from sage.providers import adapters
    from sage.retrieval import engines
    from sage.tools import DEFAULT_TOOLS, factories

    tool_names = DEFAULT_TOOLS if tool_names is None else tool_names
    wrong = []

    def check(kind: str, where: str, name: str, registry) -> None:
        if name and name not in registry:
            wrong.append(
                {
                    "kind": kind,
                    "where": where,
                    "name": name,
                    "registered": list(registry.names()),
                }
            )

    for source in profile.sources:
        check("reader", f"sources.{source.name}", source.reader, reader_registry)
        check("url scheme", f"sources.{source.name}", source.links, url_registry)
    check("retrieval engine", "retrieval", profile.retrieval.engine, engines)
    for entry in profile.providers:
        check("provider kind", f"providers.{entry.name}", entry.kind, adapters)
    # From `DEFAULT_TOOLS` rather than written out here. Two names spelled a second time
    # is two names to keep in step: a deployment that registers a third tool had it
    # unchecked, and renaming one of these would have failed with a registry error from the
    # app while this check still reported the deployment healthy.
    for name in tool_names:
        check("tool", "tools", name, factories)
    return wrong


def unrendered_placeholders(profile) -> list[dict]:
    """`{placeholder}` left in the rendered system prompt, naming a real profile field.

    `prompts.render` substitutes a fixed list of six names and leaves anything else alone
    on purpose — a prompt is prose a non-programmer edits, and a stray brace in
    `${SLURM_JOB_ID}` must read as a brace rather than raise on the first turn. The cost of
    that choice is silent: six `Identity` fields are never substituted, so a profile author
    writing `{corpus_name}` — a documented field, and a reasonable thing to want in a
    prompt — sends a literal `{corpus_name}` to the model on every turn with nothing saying
    so.

    Both shipped prompts are clean. This is for the second deployment, which is the one
    that would meet it.
    """
    import dataclasses
    import re

    from sage import prompts

    known = {field.name for field in dataclasses.fields(profile.identity)}
    rendered = prompts.system_prompt(profile)
    return [
        {"placeholder": name, "is_a_profile_field": name in known}
        for name in sorted(set(re.findall(r"\{(\w+)\}", rendered)))
    ]


def measure(corpus, index) -> dict:
    asked = [case.text for case in questions()] + [case.text for case in identifiers()]
    return {
        "unregistered_names": unregistered_names(_active()),
        "unrendered_placeholders": unrendered_placeholders(_active()),
        "chunks": index.total,
        "sources": sources(corpus),
        "empty_documents": empty_documents(),
        "indexing_nothing": indexing_nothing(corpus),
        "duplicates": duplicates(corpus),
        "reachability": reachability(index, asked),
        "self_reachability": self_reachability(index, corpus),
        "topics": topic_coverage(index),
        "unresolvable_ids": unresolvable_ids(corpus),
        "chunks_without_url": chunks_without_url(corpus),
        "malformed_urls": malformed_urls(corpus),
        "freshness": config.snapshot(),
    }

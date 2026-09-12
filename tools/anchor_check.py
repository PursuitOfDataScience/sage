#!/usr/bin/env python3
"""Check every citation anchor this app generates against the published site.

A citation that opens the right page at the wrong place is invisible from inside
the repository: the URL is well-formed, the page is real, and the only way to know
the `#fragment` misses is to ask the published HTML what ids it actually has.

Two bugs shipped for want of this check, both silent:

* `plain_heading()` deleted underscores, so the three corpus headings that contain
  an identifier — `EVP_KDF_ctrl`, `ssh_exchange_identification`, `<job_id>` —
  generated anchors mkdocs has never published. Those are exactly the FAQ entries a
  reader reaches by pasting an error message.
* the mkdocs URL scheme special-cased only a top-level `index`, so `software/index.md` was
  cited to `software/index/`, which is a 404. mkdocs with `use_directory_urls`
  publishes `<dir>/index.md` at `<dir>/`.

Two more, both found by the same question asked a third time (2026-09-12):

* mkdocs **deduplicates a repeated heading** — `alphafold.md` carries `AlphaFold 2`
  three times and the site publishes `#alphafold-2`, `#alphafold-2_1` and
  `#alphafold-2_2`. Every chunk this app builds for that heading links to the bare
  slug, so two sections of that page are unreachable from any citation and a reader
  who clicks the third one lands on the first. Nothing here could see it: the anchor
  exists, so the membership test passes. `DUPLICATED` reports it, and it counts
  against the exit status, because a citation that opens the right page at the wrong
  place is the exact failure this file was written for. The suffix is the chunker's
  to assign — `readers.read_markdown` builds the anchor from `slugify(heading)` alone
  and would need mkdocs' `unique()` rule, `_1` from the second occurrence on.
* a page that **301s** is the docs having moved, not our slug being wrong, and the
  two are indistinguishable from a `BROKEN` line. Redirects are still followed, but
  the final URL is now compared against the one we publish and reported as `MOVED`.

What it does NOT cover, so the next reader does not have to measure it again:
sources whose scheme is `embedded` (the 55 scraped `web/*.txt` pages, 43 distinct
URLs) are skipped entirely — that scheme drops the anchor, so those pages are never
fetched and a dead scrape URL is nobody's finding here. Chunks with no heading are
skipped too (7 of 489 in the docs tree). An anchor counts as present if ANY element
on the page carries that id, not only an `<h1>`–`<h6>`; that is deliberate, and as of
today no anchor depends on it — all 479 that resolve resolve to a real heading id.

Network-bound and therefore not part of the test suite: run it after touching
`slugify`, `plain_heading` or a URL scheme, and when the corpus is refreshed.

    python tools/anchor_check.py            # every anchor this app generates
    python tools/anchor_check.py --limit 20 # a quick sample
    python tools/anchor_check.py --cited report/transcripts.jsonl   # and what models wrote

The last one closes a gap nothing else can see. The anchors above are the app's own, built
by `slugify` from headings it indexed; a *model* writes its citations by hand, and it can
cite a real page at an anchor that does not exist there — the reader clicks and lands at the
top of the page with no sign anything went wrong. Measured over 514 recorded answers: 336
anchored citations, 14 of them pointing at an anchor that is not a chunk id, and asking the
published site settled what an offline check could not — `#faq` and `#basic-usage` are real
sections this app's chunker does not emit, while `#midway3---shared` and
`#service-units-allocations-and-accounts` are inventions. So roughly half of that class is a
false positive offline, which is why this lives here, behind the network, rather than in
`evals/checks.py`.

Exit status is 1 if any anchor or page is unreachable, so CI can gate on it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sage import corpus as corpus_mod  # noqa: E402
from sage import links, profile  # noqa: E402

# `id="..."` on any element. mkdocs-material puts the heading id on the <h_> itself,
# but permalink anchors and admonitions carry ids too and a match against any of them
# is still a working deep link.
_ID = re.compile(r'\sid="([^"]+)"')


# mkdocs' own duplicate suffix for a heading that repeats on one page. Python-Markdown's
# `toc.unique()` appends `_1` from the second occurrence on — an underscore, where this
# app's chunk ids use `-1`, which is why the two cannot be compared as strings.
_SUFFIX = re.compile(r"_\d+$")


def _fetch(url: str, timeout: float):
    """(ids, status, final_url) for one page; ids is None when it could not be read."""
    import httpx

    try:
        # Redirects are followed so a base-URL change is a *warning* here rather than
        # a wall of failures: what this tool is asking is "does the anchor exist".
        # Where it landed is returned as well, because a page that moved is the
        # documentation having been reorganised and not this app slugifying wrongly,
        # and a `BROKEN` line cannot tell those apart.
        response = httpx.get(url, follow_redirects=True, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — any network failure reads the same
        return None, repr(exc)[:80], url
    if response.status_code != 200:
        return None, str(response.status_code), str(response.url)
    return set(_ID.findall(response.text)), "200", str(response.url)


def _deduplicated(anchors, ids: set[str]) -> list[tuple[str, list[str], list[str]]]:
    """Anchors mkdocs disambiguated that this app does not cite.

    The site's second `AlphaFold 2` is `#alphafold-2_1`; ours was `#alphafold-2` for
    every occurrence, so two sections of that page were unreachable from any citation
    and a reader clicking the third landed on the first. Nothing here could see it —
    the anchor exists, so the membership test passes.

    The finding is what the page publishes MINUS what we cite, not the mere presence
    of `<anchor>_1`. That was this function's first form and it was right for exactly
    as long as the reader always cited the bare slug: `corpus.readers` now numbers
    repeated headings the way `toc.unique` does, and a check that went on reporting a
    page it had already got right would have to be ignored to be lived with.
    """
    cited = set(dict.fromkeys(anchors))
    found: list[tuple[str, list[str], list[str]]] = []
    for anchor in sorted(cited):
        extra = sorted(
            i for i in ids if _SUFFIX.sub("", i) == anchor and i != anchor
        )
        missing = [i for i in extra if i not in cited]
        if missing:
            found.append((anchor, extra, missing))
    return found


_CITATION = re.compile(r"\]\(\s*([^)\s]+?)\s*\)")


def _cited(path: str | None, built) -> list[tuple[str, str, str]]:
    """Anchors a model wrote, from a saved `transcripts.jsonl`, as (label, where, url).

    Resolved through `links.resolve`, so a target the app could not turn into a URL is
    already somebody else's finding — `checks.invented_citations` reports it, and this
    would only report it a second time in a different voice.
    """
    if not path:
        return []
    found: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            for match in _CITATION.finditer(str(record.get("text") or "")):
                target = match.group(1)
                if target.startswith("http") or "#" not in target or target in seen:
                    continue
                seen.add(target)
                url = links.resolve(target, built)
                if url:
                    found.append((target, f"cited by {record.get('model', '?')}", url))
    print(f"{len(found)} distinct anchored citations read from {os.path.basename(path)}")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0,
                        help="check only the first N pages (0 = all)")
    parser.add_argument("--cited", metavar="TRANSCRIPTS",
                        help="also check the anchors *models* cited in a saved "
                             "transcripts.jsonl, which no offline check can judge")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()

    try:
        import httpx  # noqa: F401
    except ImportError:
        print("httpx is not installed; skipping the anchor check.")
        return 0

    built = corpus_mod.build()
    # Only trees whose URL scheme places an anchor have anchors worth checking: a
    # scraped mirror cites whole pages, and a private corpus cites nothing. Read from
    # the profile rather than from one hardcoded base URL, so a deployment that adds a
    # third documentation site gets it checked without editing this file.
    bases = tuple(
        source.base_url
        for source in profile.active().sources
        if source.base_url and source.links in ("mkdocs", "direct")
    )
    wanted: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for path, heading, url in _cited(args.cited, built):
        if "#" in url:
            base, anchor = url.split("#", 1)
            wanted[base].append((path, heading, anchor))
    for chunk in built.chunks:
        if not bases or not chunk.url.startswith(bases) or "#" not in chunk.url:
            continue
        if not chunk.heading:
            continue
        base, anchor = chunk.url.split("#", 1)
        wanted[base].append((chunk.path, chunk.heading, anchor))

    pages = sorted(wanted)
    if args.limit:
        pages = pages[: args.limit]
    print(f"{len(pages)} pages, {sum(len(wanted[p]) for p in pages)} anchors")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        fetched = dict(
            zip(pages, pool.map(lambda u: _fetch(u, args.timeout), pages), strict=True)
        )

    unreachable, broken, duplicated, moved, checked = [], [], [], [], 0
    for base in pages:
        ids, status, final = fetched[base]
        if final.rstrip("/") != base.rstrip("/"):
            moved.append((base, final))
        if ids is None:
            unreachable.append((base, status))
            continue
        for path, heading, anchor in wanted[base]:
            checked += 1
            if anchor not in ids:
                broken.append((path, heading, anchor))
        for anchor, extra, missing in _deduplicated(
            (a for _, _, a in wanted[base]), ids
        ):
            where = next(p for p, _, a in wanted[base] if a == anchor)
            duplicated.append((where, anchor, extra, missing))

    for base, final in moved:
        print(f"  MOVED  {base}\n     now: {final}")
    for base, status in unreachable:
        print(f"  UNREACHABLE ({status})  {base}")
    for path, heading, anchor in broken:
        print(f"  BROKEN  {path}\n     heading: {heading[:80]}\n     anchor : #{anchor}")
    for path, anchor, extra, missing in duplicated:
        published = ", ".join(f"#{i}" for i in extra)
        never = ", ".join(f"#{i}" for i in missing)
        print(
            f"  DUPLICATED  {path}\n     site has: #{anchor}, {published}"
            f"\n     uncited : {never}"
        )

    print(
        f"\nchecked {checked} anchors on {len(pages) - len(unreachable)} pages: "
        f"{len(broken)} broken, {len(duplicated)} deduplicated by mkdocs, "
        f"{len(unreachable)} pages unreachable, {len(moved)} pages moved"
    )
    return 1 if broken or duplicated or unreachable else 0


if __name__ == "__main__":
    raise SystemExit(main())

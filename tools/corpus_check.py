#!/usr/bin/env python3
"""Axis C: what the corpus can and cannot answer, before any model is involved.

    python tools/corpus_check.py
    python tools/corpus_check.py --save report/corpus.json
    python tools/corpus_check.py --update [--changes moved.json]

The measuring lives in `evals/corpus_health.py` so `pytest` can gate the parts that
should never regress: an id that stops resolving, a chunk that loses its URL, a new
empty document. This file is the report.

`--update` rewrites `evals/corpus_baseline.json`, the findings that belong to the
documents rather than the code (which pages are empty, which sections repeat, which
pages their own title cannot find), and prints what moved. The weekly corpus refresh
runs it before its guards, so a corpus that changed upstream is held to what it now
says. Anywhere else, run it only when a change to the code moved one of them on
purpose, and say in the commit message which and why.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from evals import corpus_health  # noqa: E402
from sage import corpus as corpus_mod  # noqa: E402
from sage import retrieval  # noqa: E402


def report(measured: dict) -> None:
    print(f"corpus     {measured['chunks']} chunks")
    for name, row in sorted(measured["sources"].items()):
        print(f"   {name:6s} {row['pages']:4d} pages  {row['chunks']:4d} chunks  "
              f"{row['chars'] / 1000:8.1f}k chars")

    empty = measured["empty_documents"]
    print(f"\nempty documents ({len(empty)}): topics nothing can answer")
    for row in empty:
        print(f"   {row['bytes']:5d} bytes  {row['source']}/{row['path']}")

    wrong = measured["unregistered_names"]
    if wrong:
        print(f"\nUNREGISTERED NAMES ({len(wrong)}): a typo the five seams fail on "
              "differently, and only two of them loudly")
        for row in wrong:
            print(f"   {row['kind']} {row['name']!r} at {row['where']}; "
                  f"registered: {', '.join(row['registered'])}")

    braces = measured["unrendered_placeholders"]
    if braces:
        print(f"\nUNRENDERED PLACEHOLDERS ({len(braces)}): sent to the model as literal text")
        for row in braces:
            note = "a profile field that is never substituted" if row["is_a_profile_field"] \
                   else "not a profile field; a typo or an intentional brace"
            print(f"   {{{row['placeholder']}}}: {note}")

    nothing = measured["indexing_nothing"]
    print(f"\nindexed nothing ({len(nothing)}): read, and no section came out")
    for page in nothing:
        print(f"   {page}")
    if nothing:
        print("   -> asked by outcome rather than by file size, so a reader that stops "
              "recognising a heading style shows up here rather than nowhere.")

    duplicated = measured["duplicates"]
    near = duplicated["near"]
    across = sum(1 for row in near if row["cross_source"])
    print(f"\nduplicate sections   one page indexed twice "
          f"{len(duplicated['same_page_twice'])}   shared boilerplate "
          f"{len(duplicated['shared_boilerplate'])}   near-duplicate pairs "
          f"{len(near)} ({across} across sources)")
    for group in duplicated["same_page_twice"]:
        print(f"   same page, two entries: {group}")
    for group in duplicated["shared_boilerplate"]:
        print(f"   shared boilerplate (keep both, they cite different pages): {group}")
    if duplicated["same_page_twice"]:
        print("   -> a page indexed twice wastes one of six result slots. The fix is in "
              "the scrape, not the app: dropping one copy in the index would have to "
              "choose which URL a citation points at.")

    reach = measured["reachability"]
    print(f"\nreachability   {reach['touched']} of {reach['total']} chunks surfaced by "
          f"{reach['questions']} questions")
    if reach["measurable"]:
        print(f"   {reach['touched'] / reach['total']:.1%} of the index is reachable")
    else:
        print(f"   NOT MEASURABLE: {reach['questions']} questions x "
              f"{corpus_health.SEARCH_LIMIT} results is a ceiling of {reach['ceiling']} "
              f"chunks, below the {reach['total']} indexed. A percentage here would "
              "describe the question set, not the index.")

    reachable = measured["self_reachability"]
    print(f"   asked for by its own title: {reachable['rate']:.1%} of "
          f"{reachable['pages']} pages are retrievable "
          f"({len(reachable['unreachable'])} are not)")
    for row in reachable["unreachable"]:
        print(f"      unreachable: {row['page']}  (titled {row['title']!r})")

    print("\ntopics the profile advertises")
    for row in measured["topics"]:
        print(f"   {'ok      ' if row['confident'] else 'CAVEATED'} {row['score']:6.1f}  "
              f"{row['topic']:14s} -> {row['top_page']}")
    if any(not row["confident"] for row in measured["topics"]):
        print("   -> a one-word query scores low because the floor is an unnormalised "
              "sum, not because the topic is missing. Worth knowing: a reader who types "
              "one word gets the caveat.")

    broken = measured["unresolvable_ids"]
    urlless = measured["chunks_without_url"]
    malformed = measured["malformed_urls"]
    print(f"\nintegrity   ids that do not resolve {len(broken)}   "
          f"chunks with no URL {len(urlless)}   "
          f"unusable URLs {len(malformed)}")
    for row in malformed[:5]:
        print(f"   {row['why']}: {row['id']} -> {row['url']}")
    for identifier in broken[:5]:
        print(f"   unresolvable: {identifier}")
    for identifier in urlless[:5]:
        print(f"   no url: {identifier}")

    snapshot = measured["freshness"]
    print("\nfreshness  " + (json.dumps(snapshot) if snapshot else "no snapshot recorded"))


def update(measured: dict, changes_path: str | None) -> None:
    """Rewrite the baseline from this run, and say what moved."""
    before = (
        corpus_health.load_baseline()
        if os.path.exists(corpus_health.BASELINE)
        else {}
    )
    after = corpus_health.baseline(measured)
    changes = corpus_health.moved(before, after)
    corpus_health.save_baseline(after)
    where = os.path.relpath(corpus_health.BASELINE, ROOT)
    if not changes:
        print(f"\nbaseline   {where}: nothing moved")
    else:
        print(f"\nbaseline   {where} rewritten; {len(changes)} finding(s) moved")
        for key, row in changes.items():
            print(f"   {key}: {len(row['appeared'])} appeared, {len(row['went'])} went")
            for item in row["appeared"]:
                print(f"      + {item}")
            for item in row["went"]:
                print(f"      - {item}")
    if changes_path:
        with open(changes_path, "w", encoding="utf-8") as handle:
            json.dump(changes, handle, indent=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", help="write this run's numbers here")
    parser.add_argument("--update", action="store_true",
                        help="rewrite evals/corpus_baseline.json from this run")
    parser.add_argument("--changes", help="with --update, write what moved here as JSON")
    parsed = parser.parse_args()
    if parsed.changes and not parsed.update:
        parser.error("--changes needs --update")

    built = corpus_mod.build()
    if not built.chunks:
        print("no documentation trees available", file=sys.stderr)
        return 2
    measured = corpus_health.measure(built, retrieval.build(built))
    report(measured)

    if parsed.update:
        update(measured, parsed.changes)
    if parsed.save:
        with open(parsed.save, "w", encoding="utf-8") as handle:
            json.dump(measured, handle, indent=1)
        print(f"\nsaved to {parsed.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Assemble the assistant from the shipped profile, and fail if it does not work.

The composition root, not its pieces: this is the one check that the profile the
repository ships still assembles into a working assistant, with its source trees found,
its reader and URL scheme registered, its engine built and its tools bound to that index.

    python tools/assembly_check.py

Run from the repository root, where the profile's relative paths point. `ci.yml` runs it
in the job that installs only `requirements.txt`, and `refresh-corpus.yml` runs it on a
freshly refreshed corpus before anything is merged, so there is one copy to keep right.
"""

from __future__ import annotations

import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from sage import runtime  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    sage = runtime.build()
    problems = []
    if not sage.corpus.chunks:
        problems.append("no chunks indexed")
    if not sage.retriever.search("storage quota"):
        problems.append("search returned nothing for 'storage quota'")
    if len(sage.tool_schemas) != 2:
        problems.append(f"expected 2 tool schemas, got {len(sage.tool_schemas)}: "
                        f"{sage.tool_schemas}")
    for problem in problems:
        print(f"FAILED: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("profile:", sage.profile.origin, "->", sage.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Write the commit message and pull request body for one corpus refresh.

    python tools/refresh_report.py DIR [--stamp docs_snapshot.json] [--date 2026-10-10]

`.github/workflows/refresh-corpus.yml` collects what the run produced into DIR and calls
this once the guards have run. It reads, all optional except the first:

    web-summary.json   the scraper's run summary (tools/rcc-web-scrape.py --summary)
    stamp-before.json  docs_snapshot.json as it was on main before the run
    docs-changes.txt   `git diff --cached --name-status --no-renames -- docs`
    ug-commits.txt     how many upstream User Guide commits the range covers
    guards.txt         one "name outcome" line per guard, outcome as GitHub reports it
    metrics.txt        tools/metrics.py --against output
    corpus.txt         tools/corpus_check.py output

and writes title.txt, message.txt (the commit message) and body.md into the same DIR.
A guard is anything that has to pass for the refresh to merge itself, and the body says
which did not, so the pull request a person is asked to review explains why.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

UPSTREAM = "https://github.com/rcc-uchicago/user-guide"
LIMIT = 15000          # characters of any one pasted output; GitHub caps a body at 65536
GUARD_NAMES = {
    "ruff": "ruff check .",
    "pytest": "pytest -q",
    "assembly": "tools/assembly_check.py",
    "metrics": "tools/metrics.py --against (golden-set recall must not drop)",
    "corpus_check": "tools/corpus_check.py",
}
OUTCOMES = {"success": "passed", "failure": "**FAILED**", "skipped": "skipped",
            "cancelled": "cancelled", "": "not run"}


def _read(directory: str, name: str) -> str:
    try:
        with open(os.path.join(directory, name), encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def _json(directory: str, name: str) -> dict:
    text = _read(directory, name)
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _plain(text: str) -> str:
    """No em dash goes into a commit or a pull request this repository writes, and pasted
    tool output can carry one (a page title, a report heading). A spaced one reads as a
    colon there, any other as a comma."""
    em = chr(0x2014)
    return text.replace(f" {em} ", ": ").replace(em, ", ")


def _clip(text: str) -> str:
    text = text.strip()
    if len(text) <= LIMIT:
        return text
    return text[:LIMIT] + f"\n... ({len(text) - LIMIT} more characters in the run log)"


def guards(directory: str) -> list[tuple[str, str]]:
    rows = []
    for line in _read(directory, "guards.txt").splitlines():
        name, _space, outcome = line.strip().partition(" ")
        if name:
            rows.append((name, outcome.strip()))
    return rows


def docs_changes(directory: str) -> dict[str, list[str]]:
    changes: dict[str, list[str]] = {"A": [], "M": [], "D": []}
    for line in _read(directory, "docs-changes.txt").splitlines():
        status, _tab, path = line.partition("\t")
        if path:
            changes.setdefault(status[:1], []).append(path)
    return changes


def build(directory: str, stamp_path: str, day: str) -> tuple[str, str, str]:
    """(title, commit message, pull request body)."""
    run = _json(directory, "web-summary.json")
    before = _json(directory, "stamp-before.json")
    after = _json("", stamp_path) if stamp_path else {}
    old, new = before.get("user_guide_commit") or "?", after.get("user_guide_commit") or "?"
    commits = _read(directory, "ug-commits.txt").strip()
    docs = docs_changes(directory)
    checks = guards(directory)
    failed = [name for name, outcome in checks if outcome != "success"]

    added, changed = run.get("added", []), run.get("changed", [])
    removed, failures = run.get("removed", []), run.get("failed", [])
    span = f"{old}..{new}" if old != new else f"unchanged at {new}"
    web = (f"web {len(added)} added, {len(changed)} changed, {len(removed)} removed, "
           f"{len(failures)} failed")
    title = f"Corpus refresh {day}: User Guide {span}, {web}"

    docs_line = (f"docs/: {len(docs['A'])} added, {len(docs['M'])} changed, "
                 f"{len(docs['D'])} removed")
    range_line = (f"User Guide {old}..{new}" + (f", {commits} upstream commits" if commits else "")
                  + f": {UPSTREAM}/compare/{old}...{new}" if old != new
                  else f"User Guide unchanged at {new}")
    pages_line = (f"Website: {run.get('fetched', 0)} of {run.get('listed', 0)} listed pages "
                  f"fetched; {len(added)} added, {len(changed)} changed, {len(removed)} "
                  f"removed, {len(failures)} failed; "
                  f"{len(run.get('available_not_included', []))} sitemap pages available, "
                  "not included.")
    message = "\n".join([title, "", range_line + ".", docs_line + ".", pages_line, "",
                         "Opened by .github/workflows/refresh-corpus.yml."])

    if failed:
        verdict = ("**Left open for review**: " + ", ".join(GUARD_NAMES.get(name, name)
                                                           for name in failed)
                   + " did not pass, so this was not merged and Deploy was not run.")
    else:
        verdict = ("**Merging**: every guard passed and golden-set recall did not drop. "
                   "Deploy is dispatched once this lands on main.")

    body = [f"## Corpus refresh, {day}", "", verdict, "",
            "| | |", "| :- | :- |",
            f"| User Guide | {range_line.removeprefix('User Guide ')} |",
            f"| docs/ | {docs_line.removeprefix('docs/: ')} |",
            f"| web/ | {run.get('fetched', 0)} fetched, {len(added)} added, {len(changed)} "
            f"changed, {len(removed)} removed, {len(failures)} failed |", ""]

    body += ["### Guards", "", "| guard | result |", "| :- | :- |"]
    body += [f"| `{GUARD_NAMES.get(name, name)}` | {OUTCOMES.get(outcome, outcome)} |"
             for name, outcome in checks] or ["| (none recorded) | |"]
    body.append("")

    body += ["### Website pages", ""]

    def listing(label: str, rows: list[str]) -> None:
        body.append(f"**{label}** ({len(rows)})" + (":" if rows else ""))
        body.extend(f"- {row}" for row in rows)
        body.append("")

    listing("Added", added)
    listing("Changed", changed)
    listing("Removed", [f"`{row['file']}`: {row['reason']}" for row in removed])
    listing("Failed", [f"{row['url']}: {row['error']} (failed run {row.get('runs', 1)}, "
                       f"file {row.get('file', 'kept')})" for row in failures])
    if run.get("redirected"):
        listing("Redirected", [f"{row['url']} -> {row['final_url']}"
                               for row in run["redirected"]])
    if run.get("blocked"):
        listing("Blocked by robots.txt", run["blocked"])
    if run.get("stale_listing"):
        listing("Listed in web_pages.toml with no file any more (drop the line, or leave it "
                "to be fetched again when the sitemap shows a change)", run["stale_listing"])
    available = run.get("available_not_included", [])
    body += [f"<details><summary>Available, not included ({len(available)}): in the "
             "sitemap and not in web_pages.toml. Add a page under [allow] to start fetching "
             "it, or under [deny] to stop it being listed here.</summary>", ""]
    body += [f"- {url}" for url in available] + ["", "</details>", ""]

    body += ["### User Guide files", ""]
    if any(docs.values()):
        body += [f"<details><summary>{docs_line}</summary>", ""]
        for status, label in (("A", "added"), ("M", "changed"), ("D", "removed")):
            body += [f"- {label}: `{path}`" for path in docs.get(status, [])]
        body += ["", "</details>", ""]
    else:
        body += ["No file under docs/ changed.", ""]

    metrics = _read(directory, "metrics.txt")
    body += ["### Retrieval metrics, before and after", "",
             "```text", _clip(metrics) or "(not run)", "```", ""]
    corpus = _read(directory, "corpus.txt")
    body += ["### corpus_check", "", "<details><summary>What the refreshed corpus can and "
             "cannot answer</summary>", "", "```text", _clip(corpus) or "(not run)", "```",
             "", "</details>", ""]
    body.append("Opened by `.github/workflows/refresh-corpus.yml`; CI does not run on pull "
                "requests a workflow opens, so the guards above ran in that workflow.")
    return _plain(title), _plain(message), _plain("\n".join(body) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("directory")
    parser.add_argument("--stamp", default="docs_snapshot.json")
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parsed = parser.parse_args()
    title, message, body = build(parsed.directory, parsed.stamp, parsed.date)
    for name, text in (("title.txt", title + "\n"), ("message.txt", message + "\n"),
                       ("body.md", body)):
        with open(os.path.join(parsed.directory, name), "w", encoding="utf-8") as handle:
            handle.write(text)
    print(title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

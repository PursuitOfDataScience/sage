#!/usr/bin/env bash
#
# refresh-docs.sh: refresh the docs/ and web/ trees the Sage app (app.py) answers from.
#
# The app is RAG-only and reads a bundled snapshot of the RCC User Guide (docs/, markdown)
# and the RCC website (web/, scraped .txt). That keeps it self-contained and deployable,
# and it goes stale. This re-syncs the snapshot from its sources and records a stamp
# (docs_snapshot.json) saying when, and from which upstream commit.
#
#   1. User Guide : git pull (or clone) github.com/rcc-uchicago/user-guide, then mirror
#                   its docs/ into ./docs
#   2. Website    : with --scrape, tools/rcc-web-scrape.py updates ./web in place from the
#                   pages web_pages.toml lists, keeping per-page state in
#                   web_manifest.json. When its circuit breaker trips it writes nothing.
#
# Without --scrape, web/ is mirrored from RCC_WEB_MIRROR if that directory exists.
#
# Every failure exits nonzero, before the stamp is written. The weekly workflow
# (.github/workflows/refresh-corpus.yml) runs this unattended, and a run that quietly
# carried on from a stale checkout would publish it as fresh. docs/ and web/ are backed
# up before anything is overwritten. Needs outbound internet, which RCC compute and
# login nodes do not have.
#
# docs_snapshot.json is rewritten only when something changed (docs/, web/,
# web_manifest.json, or the upstream commit), so a quiet week leaves the tree clean and
# the workflow has nothing to commit. Fields: refreshed_at, user_guide_commit,
# docs_files and web_files as before, plus web_refreshed_at, sitemap_urls and the
# web_pages_fetched/changed/removed/failed counts of the --scrape run that wrote it.
#
# Usage:
#   ./refresh-docs.sh            # pull the User Guide and sync docs/
#   ./refresh-docs.sh --scrape   # and refresh web/ from the website

set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Defaults are repo-relative so anyone can run this. They were once hardcoded to one
# person's home and /project paths, which made the script unusable by anyone else.
UG_REPO="${RCC_USER_GUIDE_REPO:-$APP_DIR/.user-guide}"              # canonical git checkout
UG_REMOTE="${RCC_USER_GUIDE_REMOTE:-https://github.com/rcc-uchicago/user-guide.git}"
CANON_WEB="${RCC_WEB_MIRROR:-$UG_REPO/web}"                         # without --scrape only
SCRAPER="${RCC_WEB_SCRAPER:-$APP_DIR/tools/rcc-web-scrape.py}"
PAGES="${RCC_WEB_PAGES:-$APP_DIR/web_pages.toml}"
MANIFEST="${RCC_WEB_MANIFEST:-$APP_DIR/web_manifest.json}"
BACKUP_DIR="$APP_DIR/.doc-backups"
SUMMARY="${RCC_WEB_SUMMARY:-$BACKUP_DIR/web-summary.json}"          # the scraper's run report
PYTHON="${PYTHON:-python3}"
STAMP="$APP_DIR/docs_snapshot.json"
KEEP_BACKUPS=5
DO_SCRAPE=0
case "${1:-}" in
    "")         ;;
    --scrape)   DO_SCRAPE=1 ;;
    -h|--help)
        cat <<USAGE
Usage: ${0##*/} [--scrape]

Sync docs/ from the upstream RCC User Guide and rewrite docs_snapshot.json.

  --scrape    also refresh web/ from the website (tools/rcc-web-scrape.py)
  -h, --help  show this and do nothing
USAGE
        exit 0 ;;
    *)
        # Anything else used to fall through to a full sync, so a mistyped flag, `--help`
        # included, silently rewrote the corpus.
        printf 'Unknown argument: %s\nTry: %s --help\n' "$1" "${0##*/}" >&2
        exit 2 ;;
esac

log()  { printf '\n=== %s ===\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
fail=0

if command -v sha256sum >/dev/null 2>&1; then SHA=(sha256sum); else SHA=(shasum -a 256); fi

# One digest for a file or a whole tree (names and contents both), or "none" if absent.
digest() {
    if [ -f "$1" ]; then
        "${SHA[@]}" < "$1" | cut -d' ' -f1
    elif [ -d "$1" ]; then
        (cd "$1" && find . -type f ! -path './.git/*' -print0 | LC_ALL=C sort -z \
            | xargs -0 "${SHA[@]}") | "${SHA[@]}" | cut -d' ' -f1
    else
        echo none
    fi
}

# mirror SRC/ -> DST/ exactly (removes files deleted upstream). rsync if available,
# else empty and copy. The fallback empties a directory built from environment
# variables, so the destination is checked to sit inside APP_DIR first.
mirror() {
    local src="$1" dst="$2"
    [ -d "$src" ] || { warn "refusing to replace '$dst': source '$src' is not a directory"; return 1; }
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --delete --exclude '.git' "$src/" "$dst/"
        return
    fi
    case "$dst" in
        "$APP_DIR"/?*) : ;;
        *) warn "refusing to replace '$dst': outside $APP_DIR"; return 1 ;;
    esac
    mkdir -p "$dst" && find "$dst" -mindepth 1 -delete && cp -a "$src/." "$dst/" || return 1
    if [ -e "$dst/.git" ]; then find "$dst/.git" -delete || return 1; fi
}

# 0. What can be checked without the network, so a bad setup fails before it costs
#    anything and before anything is touched.
if [ -e "$UG_REPO" ] && [ ! -d "$UG_REPO/.git" ]; then
    die "$UG_REPO exists but is not a git checkout. Move it aside, or point RCC_USER_GUIDE_REPO at a checkout."
fi
command -v "$PYTHON" >/dev/null 2>&1 || die "$PYTHON not found; set PYTHON to a Python 3.11+ interpreter."
if [ "$DO_SCRAPE" -eq 1 ]; then
    [ -f "$SCRAPER" ] || die "scraper not found at $SCRAPER."
    [ -f "$PAGES" ] || die "page list not found at $PAGES."
    "$PYTHON" -c "import requests, bs4" 2>/dev/null \
        || die "the scraper needs requests and beautifulsoup4: $PYTHON -m pip install requests beautifulsoup4"
fi

# 1. Connectivity preflight.
log "Connectivity check"
curl -sS -o /dev/null --max-time 15 https://github.com >/dev/null 2>&1 \
    || die "no outbound HTTPS (github.com unreachable). Run from an internet-connected host."
echo "OK: internet reachable."

# 2. User Guide: clone if missing, else fast-forward pull. A pull that fails is fatal:
#    syncing from the checkout that is already here would stamp old docs as fresh.
log "User Guide: update checkout ($UG_REPO)"
if [ -d "$UG_REPO/.git" ]; then
    before=$(git -C "$UG_REPO" rev-parse --short=7 HEAD) || die "cannot read HEAD in $UG_REPO."
    git -C "$UG_REPO" pull --ff-only \
        || die "git pull failed in $UG_REPO (local changes or diverged history); docs/ is unchanged."
    after=$(git -C "$UG_REPO" rev-parse --short=7 HEAD) || die "cannot read HEAD in $UG_REPO."
    if [ "$before" = "$after" ]; then echo "Already up to date ($after)."; else echo "Updated $before -> $after."; fi
else
    echo "Cloning $UG_REMOTE -> $UG_REPO"
    git clone --depth 1 "$UG_REMOTE" "$UG_REPO" || die "clone of $UG_REMOTE failed."
fi
[ -d "$UG_REPO/docs" ] || die "$UG_REPO has no docs/ directory; docs/ is unchanged."
ug_commit=$(git -C "$UG_REPO" rev-parse --short=7 HEAD) || die "cannot read HEAD in $UG_REPO."

# 3. Back up docs/, web/ and the two records before anything is overwritten.
log "Back up docs/ and web/"
mkdir -p "$BACKUP_DIR" || die "cannot create $BACKUP_DIR."
items=()
for item in docs web docs_snapshot.json web_manifest.json; do
    [ -e "$APP_DIR/$item" ] && items+=("$item")
done
stamp=$(date +%Y%m%d-%H%M%S)
if [ "${#items[@]}" -gt 0 ]; then
    tar czf "$BACKUP_DIR/docs-web-$stamp.tar.gz" -C "$APP_DIR" "${items[@]}" \
        || die "backup failed; aborting before anything is synced."
    echo "Backed up to $BACKUP_DIR/docs-web-$stamp.tar.gz"
    # The names are timestamps, so newest first by name is newest first by age.
    find "$BACKUP_DIR" -maxdepth 1 -name 'docs-web-*.tar.gz' | LC_ALL=C sort -r \
        | tail -n +$((KEEP_BACKUPS + 1)) | xargs -r rm -f
fi
docs_before=$(digest "$APP_DIR/docs")
web_before=$(digest "$APP_DIR/web")
manifest_before=$(digest "$MANIFEST")

# 4. Website, in place. The scraper writes web/ and the manifest together or not at all,
#    so stopping here leaves both as they were.
if [ "$DO_SCRAPE" -eq 1 ]; then
    log "Website: refresh web/ from the pages in ${PAGES#"$APP_DIR"/}"
    mkdir -p "$(dirname "$SUMMARY")" || die "cannot create $(dirname "$SUMMARY")."
    rm -f "$SUMMARY"
    "$PYTHON" "$SCRAPER" "$APP_DIR/web" --pages "$PAGES" --manifest "$MANIFEST" --summary "$SUMMARY" \
        || die "the scraper failed or refused to write (see above); web/, the manifest and docs/ are unchanged."
fi

# 5. docs/ from the User Guide checkout.
log "Sync docs/ from $UG_REPO/docs"
mirror "$UG_REPO/docs" "$APP_DIR/docs" || die "could not sync docs/ from $UG_REPO/docs."
echo "docs/: $(find "$APP_DIR/docs" -name '*.md' | wc -l | tr -d ' ') markdown files"

# 6. Without --scrape, web/ comes from a mirror made elsewhere, when there is one.
if [ "$DO_SCRAPE" -eq 0 ]; then
    log "Sync web/ from $CANON_WEB"
    if [ -d "$CANON_WEB" ]; then
        mirror "$CANON_WEB" "$APP_DIR/web" || die "could not sync web/ from $CANON_WEB."
        echo "web/: $(find "$APP_DIR/web" -name '*.txt' | wc -l | tr -d ' ') text files"
    else
        warn "$CANON_WEB not found: web/ left unchanged (run with --scrape to refresh it from the website)."
        fail=1
    fi
fi

# 7. The stamp, rewritten only when something changed.
log "Snapshot stamp ($STAMP)"
changed=0
[ "$(digest "$APP_DIR/docs")" = "$docs_before" ] || changed=1
[ "$(digest "$APP_DIR/web")" = "$web_before" ] || changed=1
[ "$(digest "$MANIFEST")" = "$manifest_before" ] || changed=1
"$PYTHON" - "$STAMP" "$SUMMARY" "$ug_commit" "$changed" "$DO_SCRAPE" \
    "$(date '+%Y-%m-%d %H:%M %Z')" \
    "$(find "$APP_DIR/docs" -name '*.md' | wc -l)" \
    "$(find "$APP_DIR/web" -name '*.txt' 2>/dev/null | wc -l)" <<'PY' || die "could not write $STAMP."
import json
import os
import sys

path, summary_path, commit, changed, scraped, now, docs_files, web_files = sys.argv[1:9]
try:
    with open(path, encoding="utf-8") as handle:
        old = json.load(handle)
except (OSError, ValueError):
    old = {}
old = old if isinstance(old, dict) else {}
if changed == "0" and old.get("user_guide_commit") == commit:
    print(f"Nothing changed (User Guide still at {commit}); the stamp is left as it was.")
    raise SystemExit(0)

web = ("web_refreshed_at", "sitemap_urls", "web_pages_fetched", "web_pages_changed",
       "web_pages_removed", "web_pages_failed")
stamp = {
    "refreshed_at": now,
    "user_guide_commit": commit,
    "docs_files": int(docs_files),
    "web_files": int(web_files),
    **{key: old.get(key) for key in web},
}
if scraped == "1":
    with open(summary_path, encoding="utf-8") as handle:
        run = json.load(handle)
    stamp.update({
        "web_refreshed_at": now,
        "sitemap_urls": run["sitemap_urls"],
        "web_pages_fetched": run["fetched"],
        "web_pages_changed": len(run["added"]) + len(run["changed"]),
        "web_pages_removed": len(run["removed"]),
        "web_pages_failed": len(run["failed"]),
    })
with open(path + ".tmp", "w", encoding="utf-8") as handle:
    json.dump(stamp, handle, indent=2)
    handle.write("\n")
os.replace(path + ".tmp", path)
print(json.dumps(stamp, indent=2))
PY

log "Done"
if [ "$fail" -ne 0 ]; then
    echo "Completed WITH WARNINGS: see messages above."
    exit 1
fi
echo "Docs refreshed. The app rebuilds its search index on next start (cache cleared on restart)."

#!/usr/bin/env bash
# Say something the moment an edit repaints the app.
#
# `tests/test_palette.py` catches a repaint at `pytest` time, and CI catches it at
# review time. Both are after the fact: the change is written, the reasoning that
# produced it is gone, and what comes back is a failing assertion rather than "you
# just turned the send button pink." This runs the same check the instant one of the
# three files that decide how the app looks is edited, and hands the drift straight
# back to whoever made the edit, while they still know why they made it.
#
# Wired up in .claude/settings.json as a PostToolUse hook on Edit/Write/MultiEdit.
# Exit 2 is the code that feeds stderr back to the model rather than to a log.
#
# THAT MATCHER IS THE HOLE IN THIS GUARD, and it is not in this file. `Bash` is not in
# it, so `sed -i s/800000/a03030/ static/app.css` does not call this hook at all —
# measured: the identical repaint made with sed produced no output whatever, while
# `palette_check` reported it immediately. Any agent told to prefer shell tools for
# edits therefore has the guard switched off by default. Widening the matcher to
# `Edit|Write|MultiEdit|Bash` is a one-line change to .claude/settings.json and is the
# owner's call; this end of it is ready for the day it is made, because a guard that
# watches one way of writing a file is a guard with a door beside it.
#
# On the interpreter: `python3` on this cluster is 3.6.8 and has no `tomllib`, and
# there is no `jq`. A hook written the obvious way would exit non-zero on its own
# plumbing, be wrapped in `|| true` to quieten it, and then pass forever. So the
# interpreter is searched for, and NOT finding one is reported rather than swallowed —
# a guard that silently turns itself off is worse than no guard, which is the whole
# lesson this file exists to encode.
set -uo pipefail

payload=$(cat)
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

find_python() {
    local candidate
    for candidate in \
        "${CONDA_PREFIX:-}/bin/python" \
        "/software/python-miniforge-25.3.0-el8-x86_64/envs/AI/bin/python" \
        "$(command -v python3 2>/dev/null || true)" \
        "$(command -v python 2>/dev/null || true)"
    do
        [ -n "$candidate" ] && [ -x "$candidate" ] || continue
        if "$candidate" -c 'import tomllib' 2>/dev/null; then
            printf '%s' "$candidate"
            return 0
        fi
    done
    return 1
}

python_bin=$(find_python) || python_bin=""

# Any python parses the payload; only the check itself needs tomllib.
#
# Every path out of the parsing below used to be `exit 0`: no python to parse with, a
# payload that is not JSON, a reader that errored. Measured, feeding this hook the
# string `this is not json` with a repaint sitting in app.css exited 0 and said
# nothing — the guard turning itself off in exactly the circumstances its own header
# says are worse than not having it. Parsing a payload is plumbing, and plumbing
# failing is not evidence that the stylesheet is fine. So a payload this cannot read
# falls through to checking the files anyway (it costs ~50ms and there is no false
# alarm available to it: it speaks only if something HAS drifted), and the only silent
# exit left is the one that means "a file this does not watch was edited".
reader=${python_bin:-$(command -v python3 2>/dev/null || true)}

edited=""
if [ -n "$reader" ]; then
    edited=$(printf '%s' "$payload" | "$reader" -c '
import json, sys
try:
    event = json.load(sys.stdin)
except Exception:
    print("?")
    sys.exit(0)
data = event.get("tool_input") or {}
response = event.get("tool_response") or {}
path = data.get("file_path") or (response.get("filePath") if isinstance(response, dict) else "")
# A Bash payload carries a command rather than a path (see the matcher note above).
if not path:
    command = data.get("command") or ""
    if any(name in command for name in ("app.css", "app.js", "config.toml")):
        path = "?"
print(path or "")
' 2>/dev/null) || edited="?"
else
    edited="?"
fi

# Matched on the tail of the path, and on the bare relative path as well: `*/static/…`
# alone does not match `static/app.css`, which is what an edit reported relative to the
# repo root looks like. Measured: that payload with a repaint in place exited 0 in
# silence. Claude Code sends an absolute path today; a wrapper, a different harness or
# a future version need not.
case "$edited" in
    '?') ;;
    */static/app.css|*/static/app.js|*/.streamlit/config.toml) ;;
    static/app.css|static/app.js|.streamlit/config.toml) ;;
    *) exit 0 ;;
esac

if [ -z "$python_bin" ]; then
    what=$edited
    [ "$what" = "?" ] && what="one of the three files that decide how this app looks"
    echo "ui-guard: edited $what, but found no Python with tomllib, so the palette" >&2
    echo "check did NOT run. Activate the env and run it by hand before trusting this" >&2
    echo "edit:  source /software/python-miniforge-25.3.0-el8-x86_64/bin/activate AI" >&2
    echo "       python tools/palette_check.py" >&2
    exit 2
fi

drift=$("$python_bin" "$repo/tools/palette_check.py" 2>&1) && exit 0

{
    echo "ui-guard: that edit changed how the app looks."
    echo
    printf '%s\n' "$drift"
    # Only when there IS a baseline entry to move. `palette_check` also reports the
    # two files disagreeing about a custom property, or app.js naming a colour, and
    # neither of those is a repaint to accept — it says so itself, and this paragraph
    # underneath it said the opposite.
    case "$drift" in
        *"do not agree on"*) ;;
        *)
            echo
            echo "If the change was asked for, accept it deliberately:"
            echo "  python tools/palette_check.py --update"
            echo "and commit tools/palette_baseline.json with the change. If it was not asked"
            echo "for, say so and put it back — do not update the baseline to silence this."
            ;;
    esac
} >&2
exit 2

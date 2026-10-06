"""Where a record goes once `sage.feedback` has written it: stdout, a file, or nowhere.

Two switches name the sinks, and a record goes to every one that is set. With neither
set nothing is stored at all, which is the default, so a deployment that asks for
nothing keeps nothing.

* `SAGE_FEEDBACK_LOG` is a file. It is the older of the two, and it also draws the
  rating row under an answer, which is why it is not the only switch.
* `SAGE_TELEMETRY` is "stdout" or a file. "stdout" is for a platform that collects a
  container's output, which is what Cloud Run does: each record is one line of JSON,
  with a `severity` and a short `message` in front of its fields, and Cloud Logging
  turns that into a structured entry it can filter, count and route.

The one rule here is that a record can never cost a reader anything. Every write is
wrapped; a failure is logged once per process and never again, because a full disk
would otherwise write a warning for every call of every turn; and nothing touches the
network, so a slow collector cannot hold a turn open. A pipe the platform drains and a
local file are the only places a line can go.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading

from . import config

logger = logging.getLogger(__name__)

STDOUT = "stdout"

# One line at a time. Streamlit runs every session's script in a thread of its own, and
# two records interleaved mid-line are two lines no log collector can parse.
_LOCK = threading.Lock()
_warned = False


def sinks() -> tuple[tuple[str, str], ...]:
    """Every configured sink, each once, as `(kind, target)`: the stream, then files.

    Only `SAGE_TELEMETRY` reads "stdout" as the stream. `SAGE_FEEDBACK_LOG` was always
    a file path and still is, so a deployment that set it to a file called `stdout`
    keeps writing that file, which is why a sink is a kind and a target rather than a
    bare string that could mean either. A path named by both switches is one sink.
    """
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    telemetry = config.TELEMETRY.strip()
    if telemetry.lower() == STDOUT:
        found.append((STDOUT, ""))
        telemetry = ""
    for path in (config.FEEDBACK_LOG, telemetry):
        if not path:
            continue
        key = os.path.abspath(path)
        if key not in seen:
            seen.add(key)
            found.append(("file", path))
    return tuple(found)


def emit(record: dict) -> bool:
    """Give `record` to every configured sink. True if any took it. Never raises."""
    written = False
    for kind, target in sinks():
        try:
            if kind == STDOUT:
                _to_stdout(record)
            else:
                _to_file(target, record)
            written = True
        except Exception as exc:  # noqa: BLE001 (a record is never worth a turn)
            _failed(target or kind, exc)
    return written


def severity(record: dict) -> str:
    """WARNING for a turn or a call that failed, INFO for everything else.

    A call cut off by the reader (`ok` is None) is not a failure: nothing went wrong
    that an operator could fix.
    """
    kind = record.get("kind")
    if kind == "turn" and record.get("outcome") == "failed":
        return "WARNING"
    if kind == "call" and record.get("ok") is False:
        return "WARNING"
    return "INFO"


def summary(record: dict) -> str:
    """The short line a log viewer shows for the entry. Never the question."""
    kind = record.get("kind", "")
    if kind == "turn":
        outcome = str(record.get("outcome", ""))
        why = f" ({record['error_kind']})" if record.get("error_kind") else ""
        return (
            f"turn {outcome}{why}: {record.get('model', '')}, "
            f"{record.get('calls', 0)} call(s), {_seconds(record.get('seconds'))}"
        )
    if kind == "call":
        ok = record.get("ok")
        state = "ok" if ok else ("interrupted" if ok is None else "failed")
        why = f" ({record['error_kind']})" if ok is False and record.get("error_kind") else ""
        served = record.get("served_model") or ""
        asked = f"{record.get('provider', '')}:{record.get('model', '')}"
        return (
            f"call {record.get('n', '')} {state}{why}: {asked}"
            f"{f' served by {served}' if served else ''}, {_seconds(record.get('seconds'))}"
        )
    if kind == "miss":
        return f"miss: {len(record.get('queries') or [])} search(es), nothing to cite"
    if kind == "rating":
        return f"rating: {record.get('verdict', '')}"
    return str(kind)


def _seconds(value) -> str:
    return f"{value:.2f}s" if isinstance(value, (int, float)) else "?s"


def _to_stdout(record: dict) -> None:
    # `severity` and `message` first, because a human reading the raw stream reads left
    # to right, and both are what Cloud Logging lifts out of the payload. ASCII-escaped,
    # because a question in any language must not meet a stdout whose encoding cannot
    # spell it; a JSON parser reads the escapes back as the same characters.
    line = json.dumps(
        {"severity": severity(record), "message": summary(record), **record},
        ensure_ascii=True,
        default=str,
    )
    with _LOCK:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def _to_file(path: str, record: dict) -> None:
    line = json.dumps(record, ensure_ascii=False, default=str)
    directory = os.path.dirname(path)
    with _LOCK:
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _failed(sink: str, exc: Exception) -> None:
    global _warned
    if _warned:
        return
    _warned = True
    logger.warning(
        "Could not write a record to %s (%s). Records that cannot be written are "
        "dropped, and this is the only warning this process will log about it.",
        sink, exc,
    )

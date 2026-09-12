#!/usr/bin/env python3
"""A local stand-in for OpenCode Zen, so the real app can be run without a key.

`tools/render_check.py` renders settled states against a replica of Streamlit's DOM.
It cannot see anything that is about time: the moment a turn lands and the page grows
underneath the reader, an empty completion, a refused upload, a rate-limited click.
Those need the actual app, and the actual app needs a provider.

The OpenCode adapter in `sage/providers/` is a plain OpenAI-compatible HTTP client,
so pointing it at this is enough — no key, no network, no code in the app that exists
only for tests:

    python tools/mock_provider.py 8799 &
    OPENCODE_API_KEY=sk-zen-test OPENCODE_BASE_URL=http://127.0.0.1:8799/v1 \\
    SAGE_DEFAULT_MODEL=opencode:mock-fast-free \\
    streamlit run app.py --server.port 8502 --server.headless true

What the next turn does is read from a control file on every request, so a driver
script can switch scenarios between turns without restarting anything:

    echo '{"mode": "tools"}'            > /tmp/mock_provider.json   # search → read → answer
    echo '{"mode": "empty"}'            > /tmp/mock_provider.json   # a completion with no text
    echo '{"mode": "empty", "empty_except": ["mock-toolless-free"]}' \
                                        > /tmp/mock_provider.json   # …except one model
    echo '{"status": 402}'              > /tmp/mock_provider.json   # out of credit
    echo '{"mode": "long", "pace": 0.1}'> /tmp/mock_provider.json   # a slow, long answer
    echo '{"mode": "quiet"}'            > /tmp/mock_provider.json   # 40 empty deltas, then text

Every request is appended to the log file, which is how you check what the app
actually sent upstream — the message roles, whether tools were offered, and whether
the question survived the history budget.

Model ids end in `-free` on purpose: `config.is_free_zen_model` is what the picker
filters on, and a lineup with nothing free in it is a different screen.
"""

from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONTROL = os.environ.get("MOCK_CONTROL", "/tmp/mock_provider.json")
LOG = os.environ.get("MOCK_LOG", "/tmp/mock_provider.jsonl")

MODELS = ["mock-fast-free", "mock-verbose-free", "mock-toolless-free", "paid-premium"]

ANSWER = (
    "To submit a batch job on Midway3 you write a short shell script and hand it to "
    "`sbatch`.\n\n```bash\n#!/bin/bash\n#SBATCH --account=pi-yourpi\n"
    "#SBATCH --partition=caslake\n#SBATCH --time=01:00:00\n\nmodule load python\n"
    "python train.py\n```\n\nSubmit it with `sbatch myjob.sbatch`, and read "
    "[Batch jobs](docs/slurm/sbatch.md) for the full set of flags.\n"
)


def control() -> dict:
    try:
        with open(CONTROL, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def note(payload: dict) -> None:
    try:
        with open(LOG, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
    except OSError:
        pass


def sse(obj: dict) -> bytes:
    return b"data: " + json.dumps(obj).encode() + b"\n\n"


def delta(text: str = "", tool_calls=None, finish=None) -> dict:
    body: dict = {}
    if text:
        body["content"] = text
    if tool_calls is not None:
        body["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": body, "finish_reason": finish}],
    }


def call(index: int, identifier: str, name: str, arguments: str) -> dict:
    return {
        "index": index, "id": identifier, "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        """Quiet: the driver reads the request log, not the console."""

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802  (BaseHTTPRequestHandler's spelling)
        if self.path.rstrip("/").endswith("/models"):
            self._json(200, {"data": [{"id": name} for name in MODELS]})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        try:
            request = json.loads(self.rfile.read(length) if length else b"{}")
        except ValueError:
            request = {}
        messages = request.get("messages") or []
        note({
            "at": time.time(),
            "model": request.get("model"),
            "tools": bool(request.get("tools")),
            "roles": [message.get("role") for message in messages],
            "last": str(messages[-1].get("content") if messages else "")[:400],
        })

        settings = control()
        status = int(settings.get("status", 0) or 0)
        if status:
            self._json(status, {"error": {
                "message": settings.get("error", "mock failure"), "type": "mock"}})
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        pace = float(settings.get("pace", 0.0) or 0.0)
        try:
            for chunk in self._events(settings, request, messages):
                self.wfile.write(chunk)
                self.wfile.flush()
                if pace:
                    time.sleep(pace)
        except (BrokenPipeError, ConnectionResetError):
            return
        self.close_connection = True

    def _events(self, settings, request, messages):
        mode = settings.get("mode", "plain")
        # Which round of the tool loop this is: one tool result per round already sent.
        rounds = sum(1 for message in messages if message.get("role") == "tool")
        tools = bool(request.get("tools"))

        if mode == "tools" and tools and rounds == 0:
            # Split across two deltas, which is the shape a real stream arrives in.
            yield sse(delta(tool_calls=[call(0, "c1", "search_docs", "")]))
            yield sse(delta(tool_calls=[
                {"index": 0, "function": {"arguments": '{"query": "sbatch"}'}}]))
            yield sse(delta(finish="tool_calls"))
        elif mode == "tools" and tools and rounds == 1:
            yield sse(delta(tool_calls=[
                call(0, "c2", "read_doc", '{"path": "docs/slurm/sbatch.md"}')]))
            yield sse(delta(finish="tool_calls"))
        elif mode == "parallel" and tools and rounds == 0:
            # Both calls in ONE delta, both claiming index 0 — the mistralai 2.x
            # shape that used to collapse into a single call with no arguments.
            yield sse(delta(tool_calls=[
                call(0, "c1", "search_docs", '{"query": "sbatch"}'),
                call(0, "c2", "read_doc", '{"path": "docs/slurm/sbatch.md"}'),
            ]))
            yield sse(delta(finish="tool_calls"))
        elif mode == "preamble" and tools and rounds == 0:
            # Narrate the tool call, then call it. Several real free models do this,
            # and it is the first half of the bug where that narration became the
            # whole answer.
            yield sse(delta(text="Let me search for more specific Midway3 "
                                 "hardware details."))
            yield sse(delta(tool_calls=[call(0, "c1", "search_docs", '{"query":"gpu"}')]))
            yield sse(delta(finish="tool_calls"))
        elif mode == "preamble" and tools:
            # And the second half: the round after the search says nothing at all.
            yield sse(delta(finish="stop"))
        elif mode == "loop" and tools:
            # Never stops asking, which is what MAX_TOOL_ROUNDS is for.
            yield sse(delta(tool_calls=[
                call(0, f"c{rounds}", "search_docs", '{"query": "quota"}')]))
            yield sse(delta(finish="tool_calls"))
        elif mode == "quiet":
            # What a real stream actually looks like. Measured against
            # `nemotron-3.5-lightning-free` on a tool round: 46 chunks, of which 44 carried
            # neither text nor a tool call. This mock sent one, so nothing offline ever
            # exercised the shape the live path gets on every turn — and two things depend
            # on it: `llm.start` pulls the first chunk to surface auth failures early, and
            # `clearing` holds the status row until the first chunk with *text* in it.
            for _ in range(int(settings.get("quiet_deltas", 40))):
                yield sse(delta())
            for word in (settings.get("text") or ANSWER).split(" "):
                yield sse(delta(text=word + " "))
            yield sse(delta(finish="stop"))
        else:
            text = settings.get("text") or ANSWER
            if mode == "long":
                text = "\n\n".join(f"Paragraph {n}. {ANSWER}" for n in range(6))
            if mode == "empty":
                # Every model says nothing, unless it is named in `empty_except` —
                # which is how a lineup where the *fourth* model works is expressible,
                # and that is the shape the app's failover walk has to be driven
                # through. One flat mode could only show the walk ending in the error
                # card, never the answer that is the point of walking.
                text = "" if request.get("model") not in (
                    settings.get("empty_except") or []
                ) else text
            words = text.split(" ") if text else []
            for start in range(0, len(words), 3):
                yield sse(delta(text=" ".join(words[start:start + 3]) + " "))
            yield sse(delta(finish="stop"))
        yield b"data: [DONE]\n\n"


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    print(f"mock provider on http://127.0.0.1:{port}/v1 "
          f"(control: {CONTROL}, log: {LOG})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()

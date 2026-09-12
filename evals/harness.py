"""Run one real turn through the app's own loop, and record what happened.

The point of this module is that it measures **the app**, not a copy of it. There is a
version of an agent benchmark that reimplements `history.build` → `llm.start` → tool
rounds → final text in forty lines and measures that; it drifts from `sage/ui/turn.py`
the first time the real loop changes, and then it is measuring a fiction. So this
drives `app.py` itself, exactly as `tests/test_app_smoke.py` does — the same stubbed
Streamlit, the same session state, the same `turn.run` — with a real provider behind it
and instrumentation around the seams.

What that buys, beyond fidelity: the record includes the answer **after**
`links.strip_inline_citations` and `strip_source_footer` have rewritten it, which is
the text a reader actually gets, and the raw text before them, which is the only way
to see what those 840 lines of regular expressions removed.

    from evals import harness
    harness.prepare()                                   # once per process
    record = harness.run_turn("how do I submit a job", "opencode:big-pickle")

Everything network-bound is in the provider. Point `OPENCODE_BASE_URL` at
`tools/mock_provider.py` and the whole harness runs offline, which is how
`tests/test_bench_harness.py` proves the instrument measures what it claims to.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# The stubbed Streamlit is the app's only headless driver and it lives with the tests,
# which is the right place for it — it is a test double, not a shipped module. Rather
# than copy three hundred lines here, the tests directory goes on the path.
if os.path.join(ROOT, "tests") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "tests"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import stub_streamlit  # noqa: E402
from sage import config, links, llm, providers, redact, runtime  # noqa: E402
from sage import tools as tools_module  # noqa: E402
from sage.profile import active as _active  # noqa: E402

# How many script runs one question may take. A turn that fails over asks the next
# model on the *following* run — that is what `failover_to` and `st.rerun()` mean — so a
# harness that imports the app once would record the failure and never see the answer.
#
# Six was sized against the app's old three-hop ceiling. The app now walks the whole
# lineup, but this harness pins each turn to the model it was asked about
# (`config.MAX_MODEL_ATTEMPTS = 1`, set in `prepare`), so no hop happens here at all
# and six is headroom rather than a bound. The pin is the point: a per-model benchmark
# that let the app substitute a working model would score the model it asked on another
# model's answer, and the record it writes — `model` beside `answered_by` — would be
# the only trace of it.
MAX_SCRIPT_RUNS = 6


@dataclass
class Trace:
    """Everything the seams saw during one question."""

    calls: int = 0
    tools_offered: list[bool] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    first_byte: float | None = None
    first_text: float | None = None
    raw_answers: list[str] = field(default_factory=list)
    #: The model's own words, before `redact.apply` took the machinery's names out of
    #: them. `raw_answers` is captured one step later, at the citation strip, so without
    #: this the benchmark could not see what the model actually wrote — and a check that
    #: looks for a recited line of the prompt would miss the ones that name a tool,
    #: because the delivered answer has the name swapped for a plain word.
    said: list[str] = field(default_factory=list)
    #: Every tool result verbatim. This — not the chunks behind the Sources strip — is
    #: what the model actually read: `read_doc` on a path with no anchor returns the whole
    #: page but records only its first chunk, so evidence rebuilt from `sources` was
    #: missing most of what the turn saw and the answer checks reported flags as
    #: "unsupported" that the model had read three paragraphs earlier.
    tool_results: list[str] = field(default_factory=list)
    started: float = 0.0
    # The last request's shape. Kept rather than the request itself: a multi-turn
    # conversation carrying two attachments is most of a megabyte, and what is wanted
    # from it is its size, its roles, and whether the question is still in it.
    sent_chars: int = 0
    sent_roles: list[str] = field(default_factory=list)
    sent_text: str = ""

    def stamp(self, which: str) -> None:
        if getattr(self, which) is None:
            setattr(self, which, round(time.monotonic() - self.started, 3))

    def record_request(self, messages: list[dict]) -> None:
        flat = "\n".join(str(message.get("content", "")) for message in messages)
        self.sent_chars = len(flat)
        self.sent_roles = [str(message.get("role", "")) for message in messages]
        self.sent_text = flat

    def question_was_sent(self, question: str) -> bool:
        return question.strip().lower() in self.sent_text.lower()


_TRACE = Trace()


class Recorder:
    """A real provider with a tally around it.

    Wraps rather than replaces: the stream, the errors and the model list are the
    provider's own. What is added is when the first byte arrived, when the first *text*
    arrived (which is what a reader waits for, and is not the same thing on a turn that
    opens with a tool call), and how many requests the question really cost.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.name = inner.name
        self._models: list | None = None

    def models(self):
        # Cached because every script run rebuilds `access.available_models`, and a
        # benchmark that re-discovered the lineup once per question would spend a
        # request per question on it and measure the discovery call's latency too.
        if self._models is None:
            try:
                self._models = self._inner.models()
            except Exception as exc:  # a lineup that cannot be listed is data
                _TRACE.errors.append(f"models: {type(exc).__name__}: {exc}")
                self._models = []
        return self._models

    def stream(self, model, messages, tools):
        _TRACE.calls += 1
        _TRACE.tools_offered.append(bool(tools))
        _TRACE.record_request(messages)
        try:
            for chunk in self._inner.stream(model, messages, tools):
                _TRACE.stamp("first_byte")
                if getattr(chunk, "text", ""):
                    _TRACE.stamp("first_text")
                yield chunk
        except Exception as exc:
            _TRACE.errors.append(f"{type(exc).__name__}: {exc}")
            raise


_PROVIDERS: dict[str, Recorder] = {}
_RUNTIME: runtime.Runtime | None = None
_ORIGINALS: dict[str, object] = {}


def restore() -> None:
    """Put the patched seams back.

    Not housekeeping: these are patches on modules the whole process shares, so a test
    that prepared the harness and did not restore it would hand `sage.providers.build`
    to every test file that ran afterwards. `tests/test_bench_harness.py` restores in a
    fixture teardown for exactly that reason.
    """
    if not _ORIGINALS:
        return
    providers.build = _ORIGINALS["providers.build"]
    runtime.build = _ORIGINALS["runtime.build"]
    tools_module.ToolRunner.run = _ORIGINALS["ToolRunner.run"]
    links.strip_inline_citations = _ORIGINALS["strip_inline_citations"]
    redact.apply = _ORIGINALS["redact.apply"]
    config.MAX_MODEL_ATTEMPTS = _ORIGINALS["config.MAX_MODEL_ATTEMPTS"]
    _ORIGINALS.clear()
    _PROVIDERS.clear()


def prepare(build_provider=None, *, fresh: bool = False) -> runtime.Runtime:
    """Patch the seams and build the index once. Idempotent unless `fresh`.

    Every patch is on a module `stub_streamlit.forget_importers()` leaves alone
    (`sage.providers`, `sage.runtime`, `sage.tools`, `sage.links`, `sage.redact`), which
    is why they survive the re-import that each script run performs. Patching anything
    under `sage.ui` would silently come undone on the second question.
    """
    global _RUNTIME

    if fresh:
        restore()
        _RUNTIME = None

    if _RUNTIME is None:
        _RUNTIME = runtime.build()

    if _ORIGINALS:
        return _RUNTIME

    _ORIGINALS.update(
        {
            "providers.build": providers.build,
            "runtime.build": runtime.build,
            "ToolRunner.run": tools_module.ToolRunner.run,
            "strip_inline_citations": links.strip_inline_citations,
            "redact.apply": redact.apply,
            "config.MAX_MODEL_ATTEMPTS": config.MAX_MODEL_ATTEMPTS,
        }
    )
    # One model per turn, whatever the app would do for a reader. The app walks the
    # lineup when a model fails in a way another model might not — an empty stream, a
    # spent allowance, a 5xx — which is right in front of a reader and exactly wrong in
    # front of a benchmark: the record would name the model that was asked and carry
    # another model's answer, and `answered_by` would be the only trace of it.
    #
    # Patched on `config` for the reason `_toolless` explains, and it holds across the
    # script runs one turn may take because `sage.config` survives
    # `forget_importers()`. It is in `_ORIGINALS` because that durability is also how
    # it would leak: a test file that prepared the harness and did not restore would
    # hand a lineup-of-one to every test that ran afterwards, `tests/test_app_smoke.py`
    # included, where failing over is the thing being measured.
    config.MAX_MODEL_ATTEMPTS = 1
    make = build_provider or _ORIGINALS["providers.build"]

    def build(name: str, api_key: str):
        if name not in _PROVIDERS:
            _PROVIDERS[name] = Recorder(make(name, api_key))
        return _PROVIDERS[name]

    providers.build = build
    # The app asks for a Runtime once per script run, and indexing 572 chunks per
    # question would dominate the wall clock of a benchmark that is measuring models.
    runtime.build = lambda profile=None: _RUNTIME

    inner_run = tools_module.ToolRunner.run

    def run(self, name, arguments):
        started = time.monotonic()
        result = inner_run(self, name, arguments)
        _TRACE.tool_calls.append(
            {
                "name": name,
                "arguments": arguments,
                "seconds": round(time.monotonic() - started, 3),
                "chars": len(result),
                # The one thing a tool result says about the model rather than the
                # index: a path it made up comes back as an error it has to recover
                # from, and that recovery is what the loop is being measured on.
                "error": result.startswith("Error:") or result.startswith("Unknown tool"),
                "no_results": "No matching" in result[:200],
            }
        )
        _TRACE.tool_results.append(result)
        return result

    tools_module.ToolRunner.run = run

    inner_strip = links.strip_inline_citations

    def strip(text, sources=None):
        # The last moment the model's own words exist. `turn.run` stores the rewritten
        # text, so without this there is nothing to compare the rewrite against.
        _TRACE.raw_answers.append(text)
        return inner_strip(text, sources)

    links.strip_inline_citations = strip

    inner_redact = redact.apply

    def apply(text, names):
        # One step earlier still. What the strip sees has already had the machinery's
        # names taken out of it, and "did this model recite a line of its prompt?" is a
        # question about what the model wrote, not about what survived.
        _TRACE.said.append(text)
        return inner_redact(text, names)

    redact.apply = apply

    return _RUNTIME


def _reinstall(stub) -> None:
    """Put the *same* stub back after forgetting the app, which is one script run.

    `stub_streamlit.install()` would make a new one, and a new one has empty session
    state — so a failover, which is carried from one run to the next in
    `st.session_state.failover_to`, could never happen.
    """
    stub_streamlit.forget_importers()
    sys.modules["streamlit"] = stub
    sys.modules["streamlit.components"] = stub.components
    sys.modules["streamlit.components.v1"] = stub.components.v1


def _kinds_by_message() -> dict[str, str]:
    """User-facing error text back to the kind that produced it.

    `turn.run` puts `exc.user_message` in session state and keeps the kind to itself.
    Reading it back out of the message is how the bench reports *why* a model failed
    without reaching into the turn, and the table is built the same way the exception
    builds the message so a reworded message cannot silently stop matching.
    """
    operator = _active().identity.operator
    return {
        text.replace("{operator}", operator): kind
        for kind, text in llm._MESSAGES.items()
    }


@contextlib.contextmanager
def without_tools(model_key: str):
    """Make one model tool-less for the duration, the way a deployment can.

    The app has two ways of answering and the benchmark could only drive one. A model in
    `SAGE_TOOLLESS_MODELS` — or any model whose provider rejects a request carrying tools
    — is answered by `turn.grounded`: one retrieval up front, inlined into a system
    message, no second round. That path has its own prompt, its own caveat handling and
    its own citation contract, and none of it was ever measured; the bug fixed in d74178f
    lived there, where a query matching nothing reached the model as silence.

    Patched on `config` rather than on the environment because `sage/config.py` resolves
    every setting at import, which is the same reason `tests/test_app_smoke.py` does it
    this way. `sage.config` survives `forget_importers()` (it drops only `streamlit`,
    `app` and `sage.ui.*`), so the patch holds across the script runs one turn may take.
    """
    mark = model_key.split(":", 1)[-1].strip().lower() or model_key.strip().lower()
    before = config.TOOLLESS_MODELS
    config.TOOLLESS_MODELS = (*before, mark)
    try:
        yield
    finally:
        config.TOOLLESS_MODELS = before


def run_turn(
    question: str,
    model_key: str,
    *,
    expect: str = "answer",
    must_mention: tuple[str, ...] = (),
    pages: tuple[str, ...] = (),
    attachments: list | None = None,
    stub_kwargs: dict | None = None,
    toolless: bool = False,
) -> dict:
    """Ask one question on one model, and return everything observable about it.

    `expect` is `"answer"` for a question the corpus covers and `"caveat"` for one it
    does not; it is carried into the record because the answer checks are asymmetric — a
    fenced command block is right on one side and a defect on the other.

    `toolless` runs the same question down the other path — see `without_tools`. The
    record says which one it went down either way, read off what the provider was
    actually offered rather than off this flag, so a model that failed over to the
    grounded path on its own is labelled correctly too.
    """
    stub = stub_streamlit.install(**(stub_kwargs or {}))
    with without_tools(model_key) if toolless else contextlib.nullcontext():
        return _drive(
            stub, question, model_key,
            expect=expect, must_mention=must_mention, pages=pages,
            attachments=attachments,
        )


def run_conversation(
    turns: list[dict], model_key: str, *, toolless: bool = False, **shared
) -> list[dict]:
    """Several questions in one session, which is where a retrieval agent rots.

    One stub for the whole conversation, so `st.session_state.messages` accumulates
    exactly as it does for a reader: the follow-up is answered with the earlier turns in
    the request, and `history.build` trims them under the same budget. A harness that
    re-installed between questions would measure a series of first questions.

    Each turn is `{"text": ..., "pages": (...), "must_mention": (...), "expect": ...}`.
    """
    stub = stub_streamlit.install()
    records = []
    with without_tools(model_key) if toolless else contextlib.nullcontext():
        for position, turn in enumerate(turns):
            record = _drive(
                stub,
                str(turn["text"]),
                model_key,
                expect=str(turn.get("expect", "answer")),
                must_mention=tuple(turn.get("must_mention", ())),
                pages=tuple(turn.get("pages", ())),
                attachments=turn.get("attachments"),
                **shared,
            )
            record["turn_index"] = position
            record["conversation_length"] = len(turns)
            records.append(record)
    return records


def _drive(
    stub,
    question: str,
    model_key: str,
    *,
    expect: str = "answer",
    must_mention: tuple[str, ...] = (),
    pages: tuple[str, ...] = (),
    attachments: list | None = None,
) -> dict:
    """One turn against an existing stub. The whole measurement lives here.

    Kept separate from `run_turn` so a conversation can reuse the same session, and so
    the state reset below happens in exactly one place. That reset mirrors
    `state.start_new_turn`, minus the limiter: `tried` belongs to the turn that just
    ended, and a second question that inherits it would believe every model had
    already refused it.
    """
    global _TRACE

    sage = prepare()
    _TRACE = Trace(started=time.monotonic())

    state = stub.session_state
    state.setdefault("messages", [])
    state["messages"].append(
        {"role": "user", "text": question, "attachments": list(attachments or [])}
    )
    state["processing"] = True
    state["model"] = model_key
    state["error"] = None
    state["error_detail"] = ""
    state["notice"] = ""
    state["tried"] = []
    state["switched_from"] = None
    before = len(state["messages"])

    runs = 0
    fatal = ""
    while runs < MAX_SCRIPT_RUNS:
        runs += 1
        if runs > 1 or "app" in sys.modules:
            _reinstall(stub)
        try:
            import app  # noqa: F401, PLC0415
        except (stub_streamlit.Rerun, stub_streamlit.Stop):
            pass
        except BaseException as exc:  # noqa: BLE001 — a crash is a result, not a stop
            fatal = f"{type(exc).__name__}: {exc}"
            break
        if not state.get("processing"):
            break

    # Six script runs was a bound, not an outcome, and a turn that hit it was reported as
    # whatever happened to be in session state — usually "nothing", indistinguishable from
    # a model that returned an empty answer. A benchmark must not blame a model for the
    # harness running out of runs, so this is its own outcome.
    unfinished = bool(state.get("processing"))
    elapsed = round(time.monotonic() - _TRACE.started, 3)
    messages = state.get("messages") or []
    reply = (
        messages[-1]
        if len(messages) >= before and messages[-1].get("role") == "assistant"
        else {}
    )
    text = str(reply.get("text") or "")
    sources = list(reply.get("sources") or [])
    error = state.get("error")

    if fatal:
        outcome = "crashed"
    elif unfinished:
        outcome = "unfinished"
    elif text.strip():
        outcome = "answered"
    elif error:
        outcome = "refused"
    else:
        outcome = "nothing"

    # What the turn actually read, in the order it read it. Keyed by position rather than
    # by chunk id because a whole-page read has no single chunk behind it.
    evidence = {
        f"tool-{position}": result
        for position, result in enumerate(_TRACE.tool_results)
    }
    # Pages resolved through the corpus rather than sliced off the id. A chunk id is
    # `{source}/{path}#{anchor}` and a gold label is `{path}`; cutting the prefix by hand
    # made every gold comparison miss, silently, and read as a model that never cited the
    # right page.
    cited_pages = set()
    for source in sources:
        chunk = sage.corpus.chunk(str(source.get("id", "")))
        if chunk is not None:
            # Still added: a model that cannot call tools is handed its context up front
            # by `gather_context`, so there are no tool results to read it from.
            evidence.setdefault(chunk.id, chunk.text)
            cited_pages.add(chunk.path)

    # What the answer *links to*, beside what the turn read. The Sources strip is built
    # from `read_doc` alone, so a model that cites a page from a search snippet without
    # reading it gives the reader a working link and this record nothing to show for it.
    cited = sorted(links.cited_pages(text, sage.corpus))

    searches = [
        call for call in _TRACE.tool_calls if call["name"] == tools_module.SEARCH_DOCS
    ]
    reads = [call for call in _TRACE.tool_calls if call["name"] == tools_module.READ_DOC]

    return {
        "question": question,
        "model": model_key,
        "expect": expect,
        "pages": list(pages),
        "must_mention": list(must_mention),
        "attachments": [item.filename for item in (attachments or [])],
        "outcome": outcome,
        "error": error or "",
        "error_kind": _kinds_by_message().get(error or "", "" if not error else "unknown"),
        "fatal": fatal,
        "text": text,
        "raw": _TRACE.raw_answers[-1] if _TRACE.raw_answers else "",
        # The model's own words, one step before `raw`.
        "said": _TRACE.said[-1] if _TRACE.said else "",
        # Names of the machinery `redact.apply` took out before the reader saw them. The
        # answer above is therefore clean whatever the model said, so without this the
        # benchmark would score every model as discreet the day the redaction shipped —
        # a fix hiding the measurement of itself.
        "redacted": list(reply.get("redacted") or []),
        "sources": sources,
        "source_pages": sorted(cited_pages),
        "cited_pages": cited,
        "evidence": evidence,
        "answered_by": str(reply.get("model") or ""),
        "notice": str(state.get("notice") or ""),
        "script_runs": runs,
        "unfinished": unfinished,
        "provider_calls": _TRACE.calls,
        "tools_offered": any(_TRACE.tools_offered),
        # Which of the app's two answering paths this turn went down, named rather than
        # left to be inferred from the flag above. Read off what the provider was offered,
        # so a model that was *asked* with tools and rejected them — `turn.run` falls back
        # within the same turn — is recorded as having answered the way it really did.
        "path": "tools" if any(_TRACE.tools_offered) else "grounded",
        "rounds": len(_TRACE.tools_offered),
        "tool_calls": list(_TRACE.tool_calls),
        "searches": len(searches),
        "reads": len(reads),
        "queries": [str(call["arguments"].get("query", "")) for call in searches],
        "read_errors": sum(1 for call in reads if call["error"]),
        "empty_searches": sum(1 for call in searches if call["no_results"]),
        "tool_chars": sum(call["chars"] for call in _TRACE.tool_calls),
        "stream_chunks": list(stub.stream_chunks),
        "seconds": elapsed,
        "first_byte": _TRACE.first_byte,
        "first_text": _TRACE.first_text,
        "provider_errors": list(_TRACE.errors),
        # What actually went upstream on the last request. The history budget trims
        # oldest-first and once clipped a turn at exactly the point the question began,
        # leaving the model two files and no question — so whether the question survived
        # is measured rather than assumed.
        "sent_chars": _TRACE.sent_chars,
        "sent_roles": list(_TRACE.sent_roles),
        "question_sent": _TRACE.question_was_sent(question),
    }

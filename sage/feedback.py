"""What the app writes down about itself. `sage.telemetry` decides who reads it.

Four kinds of record, one function each, and the first two are for whoever writes the
documentation while the last two are for whoever runs the app:

* `rating`: a reader's 👍/👎 on an answer, quoting the answer.
* `miss`: a turn whose searches found nothing it could cite, which is a documentation
  backlog in disguise.
* `turn`: one line per question, saying how it ended, what it cost, and which models it
  went through on the way.
* `call`: one line per model request, so a turn's latency and its tokens can be taken
  apart call by call.

Every record carries the same header (`header`), so the four join: a schema version,
the kind, the time, which deployment and commit wrote it, the session, and the turn.
The session is a random id minted per browser session (`state.initialise`). It is
never the signed-in account and never the rate limiter's key, so a log of these says
what happened in a conversation without saying whose it was.

Nothing is written unless a sink is configured, and with the defaults none is: the
default deployment stores nothing.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import time
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone

from . import config, telemetry

logger = logging.getLogger(__name__)

#: The record schema. Bumped when a field changes meaning, never when one is added, so
#: a query written against version 1 keeps working on every version 1 record.
SCHEMA = 1


def enabled() -> bool:
    """Whether the 👍/👎 row is drawn under an answer.

    `SAGE_FEEDBACK_LOG` alone decides it, and `SAGE_TELEMETRY` deliberately does not: a
    deployment that switches on observability has asked to see what the app does, not
    for a control on the page.
    """
    return bool(config.FEEDBACK_LOG)


def header(kind: str, *, session: str = "", turn_id: str = "") -> dict:
    """The fields every record starts with."""
    return {
        "v": SCHEMA,
        "kind": kind,
        "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "deploy": config.DEPLOYMENT,
        "git_sha": config.GIT_SHA,
        "session": session,
        "turn_id": turn_id,
    }


def _write(kind: str, payload: dict, *, session: str = "", turn_id: str = "") -> bool:
    return telemetry.emit(
        {**header(kind, session=session, turn_id=turn_id), **payload}
    )


@functools.cache
def corpus_commit() -> str:
    """The upstream commit the indexed documentation was taken from, read once.

    Once per process, because the corpus is built once per process too: the snapshot
    on disk can only change under a running app by someone refreshing it by hand, and
    the index that answers is still the one built at boot.
    """
    return str(config.snapshot().get("user_guide_commit", "") or "")


def fingerprint(text: str) -> str:
    """Twelve hex characters of the SHA-256 of `text`, or "" for no text.

    Enough to say whether two turns were answered under the same system prompt, which
    is the question a prompt change raises, without putting the prompt in every line.
    """
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def attachment_kinds(attachments: Iterable) -> dict:
    """How many files were attached and what kinds they were, and nothing else.

    `kind` is the only attribute read, so no file name and no byte of content can reach
    a record through here: a reader's screenshot of their terminal is theirs.
    """
    kinds = [str(getattr(item, "kind", "") or "") for item in attachments or ()]
    return {"count": len(kinds), "kinds": sorted(set(filter(None, kinds)))}


def record_rating(
    verdict: str, question: str, answer: str, sources: list[dict],
    *, session: str = "", turn_id: str = "",
) -> bool:
    return _write(
        "rating",
        {
            "verdict": verdict,
            "question": question[:1000],
            "answer": answer[:4000],
            "sources": [source.get("id", "") for source in sources],
        },
        session=session, turn_id=turn_id,
    )


def record_miss(
    queries: list[str], question: str, *, session: str = "", turn_id: str = ""
) -> bool:
    """A turn whose searches returned nothing useful."""
    return _write(
        "miss",
        {"queries": queries[:10], "question": question[:1000]},
        session=session, turn_id=turn_id,
    )


def record_turn(
    *,
    question: str,
    outcome: str,
    model: str,
    error_kind: str = "",
    rounds: int = 0,
    searches: int = 0,
    sections: int = 0,
    caveats: int = 0,
    sources: int = 0,
    redacted: int = 0,
    seconds: float = 0.0,
    session: str = "",
    turn_id: str = "",
    system_prompt: str = "",
    served_model: str = "",
    tried: Iterable[dict] = (),
    think: bool = False,
    steer: str = "",
    calls: int = 0,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    ttft_s: float | None = None,
    attachments: dict | None = None,
) -> bool:
    """One line of mechanics per turn: what it cost and how it ended.

    Everything under `evals/` measures this app against questions somebody wrote down.
    That is a guess at what readers ask, and it is the only guess in the whole programme
    that cannot be checked offline, so this is the other end of it. A week of these says
    which questions arrive, how many rounds they really take, how often the refusal gate
    fires on live traffic against the 86.7% it scores on the labelled set, and which of
    `llm.classify`'s failure kinds a deployment actually sees.

    No answer text, and no ratings: `record_rating` already handles the reader's verdict
    and quotes them. What is here is arithmetic plus the question, which is what turns a
    log into a question set, and the question is logged because `record_miss` and
    `record_rating` already log it, so this adds no new kind of disclosure. Attachments
    are a count and a list of kinds (`attachment_kinds`), never a name or a byte.

    `tried` is every model that failed before the one that answered, in order, each as
    `{model, error_kind}`; on a failed turn it is all of them, the last included. A
    router asked again after an empty answer appears once per attempt, under the same
    id, because each attempt was a separate model behind it. `seconds` and `ttft_s` run
    from the moment the turn began, on its first script run, so a turn rescued by a
    failover is charged for the model that failed as well as the one that answered.
    """
    return _write(
        "turn",
        {
            "question": question[:1000],
            "outcome": outcome,
            "model": model,
            "error_kind": error_kind,
            "rounds": rounds,
            # Sections the turn exposed, against `sources`: the destinations the reader
            # is shown, which is fewer whenever two sections share a page.
            "searches": searches,
            "sections": sections,
            "caveats": caveats,
            "sources": sources,
            # How many names of the machinery `redact.apply` took out of this answer.
            # Zero on an ordinary turn; a run of them means the models being served are
            # answering questions about themselves and the prompt is not holding.
            "redacted": redacted,
            "seconds": round(seconds, 3),
            # Which documentation and which prompt the answer was built from. A change in
            # either is the first thing to rule out when the numbers move.
            "corpus": corpus_commit(),
            "prompt": fingerprint(system_prompt),
            "served_model": served_model,
            "tried": [
                {"model": str(item.get("model", "")),
                 "error_kind": str(item.get("error_kind", ""))}
                for item in tried
            ],
            "think": bool(think),
            "steer": steer or "",
            "calls": calls,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "ttft_s": None if ttft_s is None else round(ttft_s, 3),
            "attachments": attachments or attachment_kinds(()),
        },
        session=session, turn_id=turn_id,
    )


def record_call(
    *,
    turn_id: str,
    n: int,
    round_number: int,
    provider: str,
    model: str,
    served_model: str = "",
    ok: bool | None = True,
    error_kind: str = "",
    status: int | None = None,
    finish_reason: str = "",
    ttft_s: float | None = None,
    seconds: float = 0.0,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    tool_calls: Iterable[str] = (),
    toolless: bool = False,
    session: str = "",
) -> bool:
    """One line per model request: who was asked, who answered, how long, how much.

    `ok` is False for a call the turn could not use, which is a refused request and also
    a stream the app refused to ship (an empty answer, a monologue, a classifier's
    verdict all end as `empty`). It is None for a call the reader cut off by touching the
    page, which is neither: `error_kind` says `interrupted`, and nothing an operator can
    fix happened. `tool_calls` is the tools' NAMES, never their arguments, which are the
    model's paraphrase of the question.
    """
    return _write(
        "call",
        {
            "n": n,
            "round": round_number,
            "provider": provider,
            "model": model,
            "served_model": served_model,
            "ok": ok,
            "error_kind": error_kind,
            "status": status,
            "finish_reason": finish_reason,
            "ttft_s": None if ttft_s is None else round(ttft_s, 3),
            "seconds": round(seconds, 3),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tool_calls": [str(name) for name in tool_calls],
            "toolless": bool(toolless),
        },
        session=session, turn_id=turn_id,
    )


# --- one turn's account of itself --------------------------------------------


def new_ledger(
    *, attachments: Iterable = (), thinking: bool = False, steer: str = ""
) -> dict:
    """A turn's ledger: made on its first script run, kept until its record is written.

    A turn is not one script run. A failover asks the next model on the run after the
    one that failed, so the calls of one question are spread over as many runs as models
    were asked, and only something in session state can add them up. This is that
    something, as a plain dict for the reason `turn.Status.record` gives: it lives in
    session state, where a dataclass is one refactor away from a value the next version
    of the code cannot read.

    The turn id is a fresh UUID in hex, which is also the shape a W3C trace id takes,
    so an observability backend downstream of a provider's broadcast can use it as one.
    `think`, `steer` and the attachments are what the reader asked for, taken when the
    turn began.
    """
    return {
        "turn_id": uuid.uuid4().hex,
        "started": time.monotonic(),
        "tried": [],
        "calls": 0,
        "tokens_in": None,
        "tokens_out": None,
        "served_model": "",
        "think": bool(thinking),
        "steer": steer or "",
        "attachments": attachment_kinds(attachments),
    }


class Calls:
    """The model calls of one script run, each recorded once as it ends.

    One call is in flight at a time, because the tool loop makes one request at a time:
    `open` starts it, `attach` hands it the stream it opened, and `close` writes its
    record and adds it to the turn's ledger, however it ended. Closing twice is closing
    once, and neither method ever raises, because the places that close a call include
    the turn's own error handlers, where a second exception would replace the one being
    handled, and one of those is Streamlit's rerun.
    """

    def __init__(self, trace: dict, *, session: str, provider: str, model: str) -> None:
        self.trace = trace
        self.session = session
        self.provider = provider
        self.model = model
        self._open: dict | None = None

    def open(self, round_number: int, *, toolless: bool) -> None:
        try:
            self.trace["calls"] += 1
            self._open = {
                "n": self.trace["calls"],
                "round": round_number,
                "toolless": toolless,
                "opened": time.monotonic(),
                "reply": None,
            }
        except Exception:  # noqa: BLE001 (bookkeeping must not take a turn down)
            logger.debug("Could not open a call record", exc_info=True)
            self._open = None

    def attach(self, reply) -> None:
        """The `llm.Turn` the call opened, which is where everything it said is kept."""
        if self._open is not None:
            self._open["reply"] = reply

    def close(self, kind: str = "", status: int | None = None, *,
              interrupted: bool = False) -> None:
        """Record the call in flight, if there is one. `kind` is why it failed."""
        call, self._open = self._open, None
        if call is None:
            return
        try:
            reply = call["reply"]
            served = str(getattr(reply, "served_model", "") or "")
            tokens_in = getattr(reply, "tokens_in", None)
            tokens_out = getattr(reply, "tokens_out", None)
            first = getattr(reply, "first_text_at", None)
            names = [
                str(item.get("name", ""))
                for item in getattr(reply, "tool_calls", None) or []
                if isinstance(item, dict) and item.get("name")
            ]
            if tokens_in is not None:
                self.trace["tokens_in"] = (self.trace["tokens_in"] or 0) + tokens_in
            if tokens_out is not None:
                self.trace["tokens_out"] = (self.trace["tokens_out"] or 0) + tokens_out
            self.trace["served_model"] = served
            record_call(
                session=self.session,
                turn_id=self.trace["turn_id"],
                n=call["n"],
                round_number=call["round"],
                provider=self.provider,
                model=self.model,
                served_model=served,
                ok=None if interrupted else not kind,
                error_kind="interrupted" if interrupted else kind,
                status=status,
                finish_reason=str(getattr(reply, "finish_reason", "") or ""),
                ttft_s=None if first is None else first - call["opened"],
                seconds=time.monotonic() - call["opened"],
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                tool_calls=names,
                toolless=call["toolless"],
            )
        except Exception:  # noqa: BLE001 (bookkeeping must not take a turn down)
            logger.debug("Could not record a call", exc_info=True)

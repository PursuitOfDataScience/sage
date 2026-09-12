"""Runtime knobs.

Numbers and switches only. What the assistant is *about* — its name, its documents,
the URL its citations point at, the address it hands out when the documentation
cannot help — lives in `sage/profile.py` and the TOML file it loads, because those
are the things a second deployment has to change and none of them are settings.

Every value here can be overridden by an environment variable so a deployment can be
retuned without touching code. This module must stay importable without Streamlit.
"""

from __future__ import annotations

import json

from .env import flag as _env_flag
from .env import integer as _env_int
from .env import items as _env_list
from .env import number as _env_float
from .env import text as _env_text

# --- model -----------------------------------------------------------------

# Which provider/model a fresh session starts on, as "provider:model-id". The
# provider half has to name an entry in the profile's provider list.
#
# OpenRouter's free router, because the model this used to name stopped answering.
# `opencode:nemotron-3.5-lightning-free` was chosen for being the fastest thing on Zen's
# free tier at 2.2s; measured again on 2026-08-28 it returns an empty stream, and so does
# `nemotron-3-ultra-free` behind it — the same two models on OpenRouter return zero
# chunks too, so this is the model family and not the gateway. `openrouter/free` answered
# six of six with a tool call, median 1.4s, by routing each request to whichever free
# model is actually up. See `profiles/rcc.toml` for what that trades away.
DEFAULT_MODEL = _env_text("SAGE_DEFAULT_MODEL", "openrouter:openrouter/free")

# Substrings marking models that cannot call tools. Those answer from a single
# retrieval pass instead of the search/read loop. The app also falls back
# automatically if a provider rejects a request because of tools.
TOOLLESS_MODELS = _env_list("SAGE_TOOLLESS_MODELS", ())

# Substrings marking models that can be handed a picture. Deliberately short and
# conservative: an image sent to a text-only model is a 4xx, not a graceful refusal,
# so anything not listed here gets told the file is attached and left unread rather
# than gambling with the request. Extend it as a deployment learns its own lineup.
VISION_MODELS = _env_list("SAGE_VISION_MODELS", ("pixtral", "claude"))


def sees_images(model: str) -> bool:
    lowered = (model or "").lower()
    return any(mark and mark.lower() in lowered for mark in VISION_MODELS)


# Generous on purpose. 1600 was the old value and it cut answers off mid-sentence —
# "Per the RCC docs," and then nothing — which is worse than a long answer in every
# way: the reader cannot tell a finished thought from a severed one, and asking again
# costs another full request. A walkthrough with two code blocks and a Sources strip
# runs well past 1600, and no answer this app gives is improved by being truncated.
MAX_TOKENS = _env_int("SAGE_MAX_TOKENS", 8000, minimum=1)
TEMPERATURE = _env_float("SAGE_TEMPERATURE", 0.2, minimum=0.0)
# Four, not six. Every round is another provider call carrying everything read so
# far, so the cost of a turn grows faster than the round count: the tail rounds were
# the most expensive and the least productive. The retrieval eval answers its golden
# set at a mean depth of 2.1 reads, so four leaves headroom over twice what a real
# question needs, and caps the worst case at five calls instead of seven.
MAX_TOOL_ROUNDS = _env_int("SAGE_MAX_TOOL_ROUNDS", 4, minimum=1)
# Total characters of tool output one turn may accumulate, across every round.
# `history.build()` trims to HISTORY_CHAR_BUDGET once, *before* the loop, and the
# loop then appended up to MAX_TOOL_ROUNDS reads of MAX_DOC_CHARS each with nothing
# checking again — six 20k reads put 120k on top of a 48k budget, and the reader was
# told "this conversation got too long" about a conversation of one question.
TOOL_RESULT_CHAR_BUDGET = _env_int("SAGE_TOOL_RESULT_CHAR_BUDGET", 60000, minimum=1)
REQUEST_RETRIES = _env_int("SAGE_REQUEST_RETRIES", 2, minimum=0)
# How many models one turn may ask before it gives up, counting the one it started on.
#
# 0 means the whole lineup, and that is the default because the alternative was a dead
# end the reader could do nothing about. A model that answers nothing at all — the
# request succeeds, the stream carries no text — used to end the turn with "the model
# returned an empty answer, try a different model" while six models that would have
# answered sat one row down the picker, and the failover machinery that walks to them
# already existed and was reserved for three of the eleven ways a turn can fail.
#
# Bounded only by the lineup, so the worst case is real and worth stating: a model that
# fails *after* a full tool loop costs MAX_TOOL_ROUNDS + 1 provider calls, so a lineup
# of eight can spend forty on one question. That is the price of not dead-ending, and
# it is the same key CALL_BUDGET is there to protect — set that if the arithmetic
# matters more than the answer. Set this to 1 to switch failover off entirely, which is
# what `evals/harness.py` does so a per-model benchmark measures the model it asked.
MAX_MODEL_ATTEMPTS = _env_int("SAGE_MAX_MODEL_ATTEMPTS", 0, minimum=0)

# --- chunking --------------------------------------------------------------
#
# Whole-file reads used to be truncated at 15k chars, which silently cut 62% of
# docs/slurm/sbatch.md — the single most important page in the corpus. Indexing
# heading-sized chunks removes the need to truncate at all.

MAX_CHUNK_CHARS = _env_int("SAGE_MAX_CHUNK_CHARS", 6000, minimum=1)
MIN_CHUNK_CHARS = _env_int("SAGE_MIN_CHUNK_CHARS", 120, minimum=1)
# Cap for reading a whole page. Pages above it return an outline plus their
# opening, so the model asks for the section it actually needs.
MAX_DOC_CHARS = _env_int("SAGE_MAX_DOC_CHARS", 20000, minimum=1)
# For a reader with no heading structure to cut on, which is windowed instead.
WEB_CHUNK_CHARS = _env_int("SAGE_WEB_CHUNK_CHARS", 2400, minimum=1)
WEB_CHUNK_OVERLAP = _env_int("SAGE_WEB_CHUNK_OVERLAP", 240, minimum=0)

# --- search ----------------------------------------------------------------

SEARCH_RESULTS = _env_int("SAGE_SEARCH_RESULTS", 6, minimum=1)
# Sections of a single page allowed in one result set. A third of the golden-set
# questions used to come back with all of the top three from one page, so a search
# asking for six sections really returned two pages and the model saw one page's view.
#
# 2 rather than "off", and rather than 1, from the numbers. Measured on the 34 golden
# cases, changing nothing else (depth = sections of the *right* page among the six the
# model is handed, which page-level recall cannot see):
#
#     cap    recall@5  recall@3   p@1    MRR    depth
#      1       100%      100%    82.4%  0.897   1.18
#      2       100%     97.1%    82.4%  0.893   2.15
#      3      97.1%     97.1%    82.4%  0.892   2.88
#     off     97.1%     97.1%    82.4%  0.887   3.56
#
# 2 is where "which queue should I submit to" — the repository's one recorded lexical
# gap — first reaches the top five, against its strict two-page expectation. It costs
# 1.4 sections of depth on average to get there. 1 buys recall@3 as well and takes
# depth down to almost nothing, which is too much to pay: a model handed one section
# per page has pointers, not evidence.
MAX_PER_PAGE = _env_int("SAGE_MAX_PER_PAGE", 2, minimum=1)
SNIPPET_CHARS = _env_int("SAGE_SNIPPET_CHARS", 240, minimum=1)

# When retrieval should admit it is weak, so the model can decline instead of
# answering from whatever happened to match. Two thresholds, because one cannot do it:
# measured over the 34 golden-set questions and a set of labelled out-of-scope probes,
# answerable questions run down to a top score of 22.8 and out-of-scope ones run up to
# 23.9, so the score alone overlaps.
#
# What separates them is the score *together with* whether the query contains a word
# the corpus has never seen. Below MIN_CONFIDENT_SCORE retrieval is weak whatever the
# words; between the two, an unseen word decides it; above STRONG_SCORE the evidence
# outweighs the unseen word, which is what stops "my CNetID is jsmith and I cannot log
# in" (40.0) and "why did job 41235567 fail" (28.3) from being told the documentation
# does not cover them.
#
# Both are pinned by tests/test_search.py::TestAssessment, on the labelled queries the
# numbers came from. Moving either constant fails them, which is the point: the last
# version of this idea shipped a threshold that no test constrained at all.
MIN_CONFIDENT_SCORE = _env_float("SAGE_MIN_CONFIDENT_SCORE", 20.0, minimum=0.0)
STRONG_SCORE = _env_float("SAGE_STRONG_SCORE", 26.0, minimum=0.0)

BM25_K1 = _env_float("SAGE_BM25_K1", 1.5, minimum=0.0)
BM25_B = _env_float("SAGE_BM25_B", 0.75, minimum=0.0)
TITLE_BOOST = _env_float("SAGE_TITLE_BOOST", 2.5, minimum=0.0)
PATH_BOOST = _env_float("SAGE_PATH_BOOST", 1.2, minimum=0.0)
# 0.8 measured best on tests/test_retrieval_eval.py (recall@3 94%→97%, p@1 76%→79%)
# without raising scores for off-topic queries. Re-run that eval if you change it.
SYNONYM_WEIGHT = _env_float("SAGE_SYNONYM_WEIGHT", 0.8, minimum=0.0)

# --- conversation ----------------------------------------------------------

# Rough character budget for the history sent upstream. Trimming happens oldest
# first; the system prompt and the current question are never dropped.
HISTORY_CHAR_BUDGET = _env_int("SAGE_HISTORY_CHAR_BUDGET", 48000, minimum=1)
# How many of the most recent attachment-bearing turns keep their file text in full.
# Older ones collapse to a stub naming the file, which is what stops four uploads riding
# along on every turn of a long conversation.
#
# Not "a PDF is never re-uploaded": while a file is still the most recent attachment it is
# re-sent on each follow-up, and it has to be — stub it and "what does page 3 say?" has
# nothing to read. What the bound removes is the *accumulation*. Set it to 0 to stub every
# attachment, which makes follow-ups about a file impossible; 1 is the useful floor.
ATTACHMENT_FULL_TEXT_TURNS = _env_int("SAGE_ATTACHMENT_FULL_TEXT_TURNS", 1, minimum=0)
MAX_PROMPT_CHARS = _env_int("SAGE_MAX_PROMPT_CHARS", 8000, minimum=1)

# The shortest gap between two repaints of an answer that is still streaming.
#
# `st.write_stream` redraws the element once per delta, and the whole element: every
# repaint hands the browser the entire answer so far, which re-parses all of it and
# re-highlights every code block in it from scratch. Cost per repaint therefore grows
# with the answer, and a long reply arrives in a few thousand deltas, so the work is
# quadratic in something the reader cannot see.
#
# Measured against a 7.6 KB answer streamed a word at a time, on a CPU throttled 4x to
# stand in for a slower laptop: 1237 deltas moved 1.9 MB over the socket, held the main
# thread for 2.6 of the 5.3 seconds it took, ran at 14 fps and froze once for 1.4s.
# Almost all of that is re-rendering text that had already been rendered.
#
# So deltas that arrive inside the same interval are painted together. Nothing is
# dropped or reordered and the finished answer is identical; what changes is how many
# times the browser is asked to draw it. 40ms is 25 repaints a second — well above the
# rate a throttled browser was actually managing, so the text flows at least as evenly
# as it did while costing an order of magnitude less to draw.
#
# 0 restores a repaint per delta.
STREAM_REPAINT_MS = _env_int("SAGE_STREAM_REPAINT_MS", 40, minimum=0)

# --- uploads ---------------------------------------------------------------

MAX_UPLOAD_BYTES = _env_int("SAGE_MAX_UPLOAD_BYTES", 10 * 1024 * 1024, minimum=1)
# What an image is shrunk to before it is sent, not what may be uploaded. 1568px is
# the longest edge the major vision APIs downscale to on receipt, so anything above
# it is paid for twice — once in upload and once in the request — and discarded.
IMAGE_MAX_EDGE = _env_int("SAGE_IMAGE_MAX_EDGE", 1568, minimum=64)
# Below this an image is left alone whatever its dimensions: re-encoding a small
# sharp PNG as JPEG to save a few KB is a bad trade for a screenshot of text.
IMAGE_MAX_BYTES = _env_int("SAGE_IMAGE_MAX_BYTES", 256 * 1024, minimum=1)
# Across all files on one turn, which the per-file limit above does not bound: four
# 9 MB screenshots are four legal uploads and one 50 MB request, and the only thing
# that stopped it was the provider's own 413 — surfaced to the reader as "this
# conversation got too long. Clear the chat", about a conversation of one question.
MAX_ATTACHED_BYTES = _env_int("SAGE_MAX_ATTACHED_BYTES", 20 * 1024 * 1024, minimum=1)
MAX_FILE_TEXT_CHARS = _env_int("SAGE_MAX_FILE_TEXT_CHARS", 30000, minimum=1)

# --- limits ----------------------------------------------------------------
#
# On by default, and deliberately so. The failure this guards against is not abuse
# but arithmetic: one shared key, one public URL, and a turn that costs up to
# MAX_TOOL_ROUNDS + 1 provider calls. A key spent at lunchtime does not slow the app
# down, it ends it for everyone until a human notices.
#
# The defaults are set to be invisible to a reader using this as intended. An answer
# takes 20–60s to read, so sustained demand is well under the refill rate, and the
# burst covers the real case of already knowing your next two questions.

# Questions a reader may fire back-to-back before the sustained rate applies.
RATE_BURST = _env_int("SAGE_RATE_BURST", 5, minimum=0)
# One token back per this many seconds: 15s ≈ 4/min sustained, ≈ 20 per 5 minutes.
RATE_REFILL_SECONDS = _env_float("SAGE_RATE_REFILL_SECONDS", 15.0, minimum=0.0)
# Per person per day. Generous: it is a backstop against a loop, not a quota.
DAILY_TURNS = _env_int("SAGE_DAILY_TURNS", 100, minimum=0)
DAILY_WINDOW_SECONDS = _env_float("SAGE_DAILY_WINDOW_SECONDS", 86_400.0, minimum=1.0)
# Provider calls for the WHOLE deployment per window. 0 = no budget, which is the
# default only because the right number depends on a plan this repo cannot see.
# Set it from real spend: daily budget ÷ measured cost per call. Until it is set,
# nothing bounds what the shared key can be charged in a day.
CALL_BUDGET = _env_int("SAGE_CALL_BUDGET", 0, minimum=0)
BUDGET_WINDOW_SECONDS = _env_float("SAGE_BUDGET_WINDOW_SECONDS", 86_400.0, minimum=1.0)

# --- access ----------------------------------------------------------------
#
# Off unless configured, because turning it on without an OIDC provider in
# `.streamlit/secrets.toml` would lock everyone out of a working app, including
# whoever set the variable. The UI's login gate checks both.
REQUIRE_LOGIN = _env_flag("SAGE_REQUIRE_LOGIN", False)
# Email domains allowed past the login gate. Empty = any account the provider
# authenticates, which for a Google client means the whole internet — so set it.
ALLOWED_EMAIL_DOMAINS = _env_list("SAGE_ALLOWED_EMAIL_DOMAINS", ())


def email_allowed(email: str) -> bool:
    """Is this address inside one of the allowed domains? Empty list allows all."""
    if not ALLOWED_EMAIL_DOMAINS:
        return True
    lowered = (email or "").strip().lower()
    return any(
        lowered.endswith("@" + domain.strip().lower().lstrip("@"))
        for domain in ALLOWED_EMAIL_DOMAINS
        if domain.strip()
    )


# --- ops -------------------------------------------------------------------

LOG_LEVEL = _env_text("LOG_LEVEL", "WARNING").upper()
# Set to a writable path to collect thumbs-up/down as JSON lines. Unset = no sink.
FEEDBACK_LOG = _env_text("SAGE_FEEDBACK_LOG", "")
SNAPSHOT_FILE = _env_text("SAGE_SNAPSHOT_FILE", "./docs_snapshot.json")


def snapshot() -> dict:
    """Docs freshness stamp written by refresh-docs.sh. Never raises."""
    try:
        with open(SNAPSHOT_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

# Sage — running improvement list

Candidates for improvement, gathered by reading the tree. **Not a plan of record and
not a decision** — nothing here has been agreed, prioritised or costed, and several
items are explicitly marked as needing measurement before anyone acts on them.

Kept at the repository root deliberately: `profiles/rcc.toml` indexes `./docs` and
`./web` only, so a file here cannot end up in the corpus and start appearing in
answers.

Appended to on each pass. Every item carries a `file:line` anchor so it can be checked
rather than taken on trust.

Legend: **[V]** verified by running something here · **[R]** read from the code ·
**[?]** plausible, needs measurement before adoption

---

## Iteration 1 — 2026-09-08

### Retrieval

1. **[V] `_near_miss` cannot see a dropped letter.** `sage/retrieval/bm25.py:_near_miss`
   builds deletions, substitutions and transpositions of the reader's term — but not
   insertions. So the corpus word being *longer* than what was typed is unreachable.
   Ran it: `favourite→favorite` True, `moduel→module` True, but
   `partiton→partition` False, `instal→install` False, `directoy→directory` False.
   Dropping a letter is at least as common as adding one, and the whole point of the
   function is that a typo shouldn't trigger "the documentation does not cover it".
   Fix is one more candidate set (26 insertions × L+1 positions), same guard.

2. **[R] No inverted index — every query scores every chunk.** `bm25.py Index.search`
   runs `for position, chunk in enumerate(self.corpus.chunks)` and loops the expanded
   terms inside. A posting list (`term → [(position, frequency)]`) built in `__init__`
   from `self._frequencies`, which it already has, would touch only chunks containing
   a query term. Scores stay bit-identical, so the retrieval eval is the regression
   test. Fine at ~90 docs; it is the thing that stops a bigger corpus being viable,
   and it is on the hot path of `gate_check.py --sweep`.

3. **[R] `expand(query)` is computed twice per tool call.** `search` computes
   `weights = self.vocabulary.expand(query)`; `assess` computes
   `self.vocabulary.expand(query)` again on the same string. `SearchDocs.run` calls
   both back to back (`sage/tools.py`). Threading the weights through `assess` removes
   a full tokenize + synonym walk per search.

4. **[R] `scored.sort()` sorts the whole matched set to take `limit`.**
   `heapq.nlargest` with the same `(-score, chunk.id)` key does less work. Small, but
   free.

5. **[?] `MAX_PER_PAGE` is global where the trade is query-dependent.** `_spread`'s own
   docstring concedes "every slot given to a second page is a slot taken from the depth
   of the first". A query with a large `margin` (one page clearly dominant) wants depth;
   a flat score distribution wants breadth. Making the cap a function of the margin is
   directly measurable on the existing retrieval eval.

6. **[?] A rerank stage the interface is already designed for.**
   `sage/retrieval/base.py`'s module docstring explicitly names "asks a reranker to
   reorder BM25's output" as a registry citizen. A no-new-dependency version — rescore
   the top ~20 on phrase proximity and heading match — is cheap to try and gated behind
   `engines.register`, so it can ship dark and be compared.

7. **[?] Corpus-mined synonym candidates.** `Vocabulary` synonyms are hand-written in
   `profiles/rcc.toml`. A `tools/` script that proposes candidates from heading/body
   co-occurrence and opens a PR would follow the pattern `.github/workflows/lineup.yml`
   already established for keeping the profile true — a human still approves the diff.

### The answering loop

8. **[R] The tool-less path searches only the last question, so follow-ups retrieve
   nothing.** `sage/ui/turn.py:331` `grounded()` calls
   `gather_context(runtime.retriever, question, ...)` where `question` is
   `messages[-1]["text"]`. "How do I raise it?" has no lexical content — BM25 gets
   stopwords. The tool path is fine (the model sees history and writes its own query);
   this path has no second round, which is exactly where it hurts most. Cheapest fix:
   search the last question plus the previous user turn, or plus the section labels the
   previous answer cited.

9. **[R] Nothing notices a repeated search.** `ToolRunner.queries` accumulates every
   query but no one compares them. The observed failure is on record in
   `sage/ui/turn.py`: "given ten rounds both models on the lineup filled ten,
   rephrasing the same query five times." Returning "you already searched that — same
   results, read one or answer" on an exact repeat converts a wasted provider call into
   a useful instruction.

10. **[?] Tell the model the round budget one round early.** Withdrawing tools on the
    last request was the right fix and is documented as such. A complementary nudge on
    the penultimate round ("one search left") costs nothing and targets the same
    behaviour without raising the ceiling — which the same comment records as having
    been tried and not binding.

11. **[R] `gather_context` re-sends the same chunk text every turn.** No dedupe against
    what earlier turns already shipped, so a multi-turn tool-less conversation pays for
    the same sections repeatedly against `HISTORY_CHAR_BUDGET`.

### Cost and providers

12. **[V] No token accounting anywhere.** Grepped: no `usage`, `include_usage`,
    `stream_options`, `prompt_tokens` or `completion_tokens` under `sage/`. An
    OpenAI-compatible endpoint will return a usage block on a stream when asked
    (`stream_options={"include_usage": true}`), and `sage/providers/openai_compat.py`
    is the one place it would land. This is the single missing input for the cost axis
    `EVAL.md:915` says it wants.

13. **[V] `provider_calls` is in the bench, not in live logging.** `EVAL.md:915` reads
    "`provider_calls` is recorded per turn ... the field is already there." It is there
    in `evals/harness.py:531` and `tools/agent_bench.py`. It is **not** a parameter of
    `sage.feedback.record_turn`, which takes rounds/searches/sections/caveats/sources/
    redacted/seconds. `turn.py` already counts the calls (`get_limiter().record_calls(1,
    …)` per request), so the number exists and is discarded. Either pass it through or
    correct the sentence in EVAL.md.

14. **[V] `Retry-After` is never read.** `sage/llm.py start()` retries a `rate_limit`
    with a hard `2**attempt` backoff. The only `retry_after` in the tree is the app's
    own limiter (`sage/limits.py:41`). On OpenRouter's free tier the per-minute cap is
    20/min, so a 2 s backoff is very likely to be refused again; the provider's own
    header is strictly better information than a guess.

15. **[R] No prompt caching.** The system prompt (profile prompt + `SELF_DISCLOSURE`) is
    a large, stable prefix rebuilt per turn by `history.build`, which is the ideal
    caching shape. Nothing in `sage/providers/` carries cache-control.

16. **[R] `MAX_TOKENS` and `TEMPERATURE` are global across every model.**
    `config.py:58-59`. A per-model override — the pattern `VISION_MODELS` and
    `TOOLLESS_MODELS` already use — would let a small free model get a tighter budget
    than a paid one.

17. **[R] Retry count is bounded; retry wall-time is not.** `REQUEST_RETRIES=2` with
    `2**attempt` sleeps, multiplied by `MAX_MODEL_ATTEMPTS` failover, is an unbounded
    stretch of a blocked Streamlit thread from the reader's side. Capping total retry
    seconds reads better than capping attempts.

### Observability

18. **[R] The feedback sink is a local append-only file.** `sage/feedback.py` writes to
    `SAGE_FEEDBACK_LOG`. `EVAL.md` already notes it "needs a durable sink to survive a
    restart" on a hibernating platform. A sink registry — the sixth registry, matching
    the five the architecture already has — lets a deployment point it elsewhere without
    editing `feedback.py`.

19. **[V] `Limiter.snapshot()` is called by nothing but its own test.** It exists,
    handles the `RATE_BURST=0` case correctly, and is documented as being for "an
    operator asking 'how close are we?'". Grepped every `.py` outside `tests/`: the only
    hits are an unrelated JS function in `render_check.py` and `config.snapshot()` in
    `corpus_health.py`. Nothing in `sage/ui/` or `app.py` touches it. A built instrument
    with no dial attached — the same class of dead code as the `prune()` that
    `limits.py`'s own comment says "nothing else called".

### Repo, CI, and this environment

20. **[V] Dev-tool versions are unpinned, and the drift is already real.** `ci.yml:24`
    is `pip install --disable-pip-version-check pytest ruff pypdf httpx` — no versions.
    `CLAUDE.md` records ruff 0.15.18; this container has 0.15.8. A new ruff minor adds
    rules and turns CI red on a commit nobody touched. `requirements.txt` handles the
    runtime deps with lower bounds and says outright "Generate a lockfile ... for
    reproducible deploys", which has not happened. Pin the dev tools; add the lockfile.

21. **[V] A web session cannot run the checks CLAUDE.md requires before pushing.**
    This container has no `streamlit` and no `pytest` — only ruff. `CLAUDE.md` says to
    `source /software/python-miniforge-25.3.0-el8-x86_64/bin/activate AI`, which does not
    exist here; that path is the owner's machine. So "Run the first three before pushing"
    is unsatisfiable from a Claude Code web session. A `SessionStart` hook that pip-installs
    the test deps would fix it, and `.claude/settings.json` currently registers only the
    `PostToolUse` ui-guard. This is the one item on the list that changes whether the
    other work can be validated.

22. **[?] `render_check.py` is ~10 minutes for 660 renders.** Shard it across a CI matrix,
    or select the subset whose selectors the diff actually touches. `CLAUDE.md` already
    works around the duration by allowing a local run to substitute — which is a process
    fix for a runtime problem.

### Product

23. **[R] Nothing survives a refresh.** State is Streamlit session state
    (`sage/ui/state.py`); no persistence, no shareable transcript. For a documentation
    assistant the obvious want is pasting an answer with its citations into a ticket.

24. **[R] The corpus is indexed once at boot.** `app.py` wraps `runtime.build` in
    `st.cache_resource`, so a docs update needs a restart. An mtime check, or a refresh
    driven off `SAGE_SNAPSHOT_FILE`, would pick up new pages without a redeploy.

25. **[?] Local chunks have no overlap.** `WEB_CHUNK_OVERLAP=240` exists for scraped
    pages; `MAX_CHUNK_CHARS`/`MIN_CHUNK_CHARS` for markdown have no equivalent, so an
    answer straddling a heading boundary is split. Measurable on the retrieval eval.

26. **[?] Source weight is a static per-source prior.** `corpus.weight(source)` is "a
    maintained guide against a scraped site". A per-document signal — last-modified, or
    how often the page is cited in accepted answers — would be finer-grained and the
    feedback log already carries what is needed to compute the second one.

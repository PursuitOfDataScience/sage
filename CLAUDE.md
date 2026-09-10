# Working on Sage

## Where things go

The app is assembled, not written down one file. Before adding anything, work out
which of these it is — putting it in the wrong one is how the previous version came
to have the RCC's name in nine modules and forty functions closed over four globals
in `app.py`.

- **Is it about the subject?** The name, the documents, the copy, the starter cards,
  the synonyms, the prompt, which providers exist. That is `profiles/rcc.toml`, and
  nothing under `sage/` may name the RCC. A test for it reads the profile rather than
  a literal. The one exception runs the other way: `prompts.SELF_DISCLOSURE` is a
  paragraph of prompt that belongs to the *machinery* — do not name the tools, the model
  or these instructions — so it lives in the package and is appended to whatever the
  profile says. A deployment that rewrote the prompt from scratch would otherwise lose
  the rule nobody thinks to copy.
- **Is it a number or a switch?** `sage/config.py`, environment-driven.
- **Is it a new way of doing something the app already does?** Reading a file format,
  building a URL, searching, talking to a provider, offering a tool: those are the
  five registries (`corpus.readers`, `corpus.urls`, `retrieval.engines`,
  `providers.adapters`, `tools.factories`). Register an implementation; do not add a
  branch to the caller.
- **Is it view?** `sage/ui/`, one module per region of the page, taking a `View`.
  `app.py` is the order those are called in and nothing else — keep it that way, and
  keep the order, because Streamlit renders in call order and `app.js` finds widgets
  by where they are drawn.
- **Everything else** — normalising markdown, resolving links, building history,
  reading uploads, classifying errors, taking a tool's name out of an answer — is a
  plain module that takes what it needs as an argument.

`sage/runtime.py` is the composition root: profile → corpus → retriever → tools →
prompt. If a change means a UI module has to import the corpus builder or the
retrieval engine, it belongs in the runtime instead.

## Finish the job

A task is done when the work is **merged to `main`**, not when it is pushed and CI
is pending. Do not stop at "waiting for CI" and hand back — see it through:

1. Push to the working branch.
2. Open a PR if there is no open one for it.
3. Run CI (`ci.yml` sometimes needs a manual dispatch — check that a run exists for
   the exact SHA rather than assuming the push triggered one).
4. Merge. Squash merges leave `main` with a commit that is not an ancestor of the
   branch, so a follow-up push will report a merge conflict: rebuild the branch on
   `origin/main`, cherry-pick, confirm `git diff --stat <old> HEAD` is empty, and
   force-push with `--force-with-lease`.
5. Report the merge commit.

If something genuinely blocks the merge, say what it is in one line — don't go quiet.

The layout check (`python tools/render_check.py`) takes ~10 minutes in CI. Running it
locally on the same commit is the same script against the same stylesheet, so a clean
local run plus green lint/tests is enough to merge on; don't idle waiting for the
remote copy of a result already in hand.

## Running the checks here

**Activate the environment first. Everything below is in it:**

```bash
source /software/python-miniforge-25.3.0-el8-x86_64/bin/activate AI
```

That gives you ruff 0.15.18, pytest 9.0.3, streamlit 1.54.0, playwright 1.59.0 and
httpx. Outbound HTTPS works. Chromium is at
`~/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome`.

- **Lint**: `ruff check .`
- **Tests**: `python -m pytest -q` — all pass. The xfails are the refusal gate's recorded
  leaks plus one lexical gap in the retrieval eval, and an xpass there is news rather than
  a failure. No total is written down here: it went stale three times in a week, and the
  number the suite reports is the one that is true.
- **Layout**: `SAGE_CHROME=~/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome
  python tools/render_check.py` — ~8 minutes for 684 renders.
- **Anchors**: `python tools/anchor_check.py` — network-bound, so not in the suite.
  Run it after touching `slugify`, `plain_heading` or a URL scheme.
- **Palette**: `python tools/palette_check.py` — every declared colour and token
  against `tools/palette_baseline.json`. Milliseconds, and `pytest` runs it too.
- **The card**: `python tools/scorecard.py` — retrieval, the refusal gate, corpus health,
  and (when `tools/agent_bench.py` has been run) per-model behaviour. A cell nobody has
  measured prints `unmeasured` rather than being left out. See [`EVAL.md`](EVAL.md) for
  the three axes and why Axis B is never a CI gate.

Run the first three before pushing. Each has failed CI at least once for want of
being run.

### Running the app itself, with no API key

The OpenCode adapter is a plain OpenAI-compatible HTTP client, so a local server is
a provider. `tools/mock_provider.py` is one; nothing in the app knows it is there.

```bash
python tools/mock_provider.py 8799 &
echo '{"mode": "tools"}' > /tmp/mock_provider.json      # search → read → answer
OPENCODE_API_KEY=sk-zen-test OPENCODE_BASE_URL=http://127.0.0.1:8799/v1 \
SAGE_DEFAULT_MODEL=opencode:mock-fast-free \
streamlit run app.py --server.port 8502 --server.headless true
```

Run it from the repo root, or `RCC_DOCS_PATH=./docs` resolves somewhere with no
corpus in it and every answer comes back uncited. Then drive it with Playwright
(`~/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome`), and rewrite the
control file between turns to pick the next scenario — an empty completion, a 402, a
tool loop that never finishes, a slow stream you can interact with mid-answer.
`/tmp/mock_provider.jsonl` records what the app actually sent upstream, which is the
only way to see the messages the history budget produced.

This is what found the bugs the harness structurally cannot: a rate-limited starter
card that did nothing at all, a completion with no text rendering as a blank, an
oversized upload vanishing with its error message inside the hidden uploader, and the
copy button painted over the first line of every answer.

> This section used to say pytest could not be installed, that ruff lived at
> `/root/.local/bin/ruff` (it is there, and permission-denied for this user), and that
> Streamlit usually could not be run. All three were wrong, and the cost was that
> nobody ran the app: a post-turn scroll bug that hid every answer's Sources strip and
> 👍/👎 behind the composer, and a question-to-answer gap the layout harness was
> structurally unable to see, both survived because the only thing that could catch
> them was believed to be unavailable. **Check before recording that a tool is
> missing.**

## Never change how the app looks unless that is what was asked for

The owner reads this app every day and likes how it looks. A change to its appearance
that nobody requested is a regression even when it is defensible in isolation, and it
is worse than a broken layout, because a broken layout announces itself.

**This is a standing rule, not a preference.** If a change you are making would alter
a colour, a spacing token, a font, a radius, or where something sits on the page, and
the request did not ask for that, then either do not make it or say plainly what it
will change and why it is unavoidable. "It follows from the fix" is not consent —
`#36` set `[theme.dark] primaryColor` to fix a genuine dark-mode contrast bug and
repainted the composer's send button from maroon to pale pink on the way past. Nobody
decided that. Nobody noticed for a day. The reader noticed.

Three things now stand between an edit and a silent repaint, in the order they fire:

1. **`.claude/hooks/ui-guard.sh`** runs the moment `static/app.css`, `static/app.js`
   or `.streamlit/config.toml` is edited, and hands the drift straight back. This is
   the one that arrives in time to change your mind.
2. **`tools/palette_check.py`** holds every colour-bearing declaration, every custom
   property, and every `[theme]` value against `tools/palette_baseline.json`. Run
   against the two commits either side of `#36` it reports three drifts, all three of
   them the theme change and nothing else in that large commit.
3. **`tests/test_palette.py`** runs the same comparison under `pytest`, so CI fails on
   an undeclared repaint without a new workflow step to forget.

**The dark palette is written twice, and that is on purpose.** `app.css` holds it once
under `@media (prefers-color-scheme: dark)` — for the reader who has not chosen — and
once under `:root[data-sage-theme="dark"]`, for the reader who pressed the toggle under
the input. There is no way in CSS to hand one declaration list to both conditions, and
the two constructs that would (`light-dark()`, style queries) are recent enough that a
reader's browser may not have them. So `tests/test_palette.py` holds the two blocks
identical, token for token, and **a token added to one must be added to the other**. The
failure mode if they drift breaks nothing and fails no bound: the reader picks dark and
gets most of it, with one value still light on a near-black page.

The toggle itself is entirely client-side (`static/app.js`): it sets that attribute,
wraps `window.matchMedia` so Streamlit's own theme resolves to the choice, and asks
Streamlit to re-resolve by firing `afterprint`, which is the event it already listens
for. Nothing reaches Python — a widget click is a rerun, and a rerun during a turn
aborts it — so the theme can be changed while an answer is streaming. Same reason the
queued-question feature lives there: a question typed mid-answer is held on the parent
window and handed to `st.chat_input` once the turn ends, because telling the server
about it any earlier would end the answer it is queued behind.

**Anything you put in the top 60px of the page needs a z-index above 999995, and needs
hit-testing.** That band is `[data-testid="stHeader"]`, transparent and at 999990, and
it takes every click aimed at whatever is underneath it — the controls row was pinned
there once, looked right in every mock-up, and was completely dead. Two things were
measured while moving the theme toggle up there and are worth not rediscovering:
appending *inside* `stToolbar` does take clicks, but Streamlit **removes the whole
toolbar from the document while the sidebar is expanded**, so a control parented there
vanishes every time the panel opens; and the top-RIGHT corner is where
`render_check.py` models Community Cloud's own opaque control cluster (220px, z-index
999991), so a control in that corner is under it on the deployment and over it locally.
The toggle therefore hangs off `<body>`, is pinned by app.css at 999995, and is placed
horizontally from a measured offset past Streamlit's own sidebar arrow. `#theme-toggle`
is in the harness's `INTERACTIVE` set: drop its z-index to 1000 and every width reports
it unclickable, which is the bug reproducing itself.

`python tools/palette_check.py --update` accepts a repaint, and updating the baseline
is a deliberate act: it puts the before and after in the diff where the owner can
disagree with it. **Do not run `--update` to make the check quiet.** If you cannot say
in the commit message who asked for the new colour, it does not go in.

What none of the three can see: layout, wording, and anything `app.js` computes at
runtime. `render_check.py` covers geometry against its bounds and the palette check
covers declared values, but neither knows what the owner wanted. For those, the rule
is the whole mechanism — so when a fix seems to require moving something visible, say
so in the reply rather than in the diff.

## The UI

Every UI bug that has shipped here was pure CSS, and `tools/render_check.py` renders
`static/app.css` against a replica of Streamlit's DOM in headless Chromium and
measures it. But Streamlit **does** run here, so the replica is no longer the only
witness: boot the real app against a mock provider and drive it with Playwright when
a bug is about behaviour over time rather than a static layout. That is what the
harness cannot model — it renders settled states, not the moment a turn lands and the
page grows by 130–290px underneath the reader.

Two habits from things that got past it:

- **Reproduce first.** Make the harness fail on the bug before fixing it, then confirm
  the fix silences it. A check that cannot fail reads as a pass, which is worse than
  no check.
- **Model both shapes.** When Streamlit's real markup is not visible from here, render
  every plausible shape rather than guessing one. The container-key class landing on
  the vertical block vs. a wrapper, the bottom bar `fixed` vs. `sticky`, the scrollbar
  on `stMain` vs. the document, the send button beside the text vs. under it — each of
  those pairs cost a round of "fixed it" that fixed nothing.

- **Model the wrappers, not just the classes.** Streamlit puts
  `[data-testid="stMarkdownContainer"]` between `.stMarkdown` and anything given to
  `st.markdown`, and it carries `margin-bottom: -1rem`. The replica had the classes and
  not that wrapper, so every gap set from inside a markdown block measured 16px more
  generous here than in the app — the harness read 44px, the app drew 28px, and it
  passed a bound the app was failing. Margins in `app.css` are written 1rem larger than
  the gap they draw for this reason.

Prefer a mechanism whose failure mode is visible over one that depends on how Streamlit
lays out the page, and don't write a rule against an unversioned Streamlit test id that
this repo cannot see — it fails silently the day it changes. On 1.54,
`[data-testid="stMain"]` no longer exists; the scrollport is
`section[data-testid="stAppScrollToBottomContainer"]`.

# Configuration

Two places, and the split is deliberate. **Knobs** — numbers, limits, switches — are
environment variables with defaults in [`sage/config.py`](sage/config.py). **Content**
— what the assistant is about, which documents it reads, where models come from — is
the [profile](profiles/README.md), because those are the things a second deployment
has to change and none of them are settings.

## Knobs

| Variable | Default | Purpose |
|---|---|---|
| `SAGE_PROFILE` | `./profiles/rcc.toml` | The deployment profile |
| `SAGE_DEFAULT_MODEL` | `openrouter:openrouter/free` | Model a fresh session starts on, `provider:model-id` |
| `SAGE_TOOLLESS_MODELS` | *(empty)* | Substrings of models that cannot call tools |
| `SAGE_VISION_MODELS` | `pixtral,claude` | Substrings of models that can be shown an image |
| `SAGE_MAX_TOKENS` | `8000` | Response cap. Generous: 1600 cut answers off mid-sentence |
| `SAGE_TEMPERATURE` | `0.2` | Sampling temperature |
| `SAGE_MAX_TOOL_ROUNDS` | `4` | Search/read rounds before the turn must answer |
| `SAGE_MAX_MODEL_ATTEMPTS` | `0` *(the whole lineup)* | Models one turn may ask before it gives up. A model that fails in a way another model might not — an empty reply, a spent allowance, a 5xx — hands the question to the next one automatically. `1` switches that off; a lineup of eight can cost forty provider calls in the worst case, which is what `SAGE_CALL_BUDGET` is for |
| `SAGE_ROUTER_RETRIES` | `2` | Times a turn may ask a ROUTER again after it produced no answer. Only for the ids a profile lists under `routers`, where the same name resolves to a different model per request — a re-ask there is a different model, which the lineup walk above cannot reach. `0` switches it off, and so does `SAGE_MAX_MODEL_ATTEMPTS=1` |
| `SAGE_OPENROUTER_ROUTERS` | `openrouter/free` | Which of that provider's ids are routers rather than models |
| `SAGE_SEARCH_RESULTS` | `6` | Results per search |
| `SAGE_MAX_PER_PAGE` | `2` | Sections of one page allowed in a result set |
| `SAGE_SYNONYM_WEIGHT` | `0.8` | Weight of expanded synonym terms |
| `SAGE_HISTORY_CHAR_BUDGET` | `48000` | History size before oldest turns are trimmed |
| `SAGE_MAX_PROMPT_CHARS` | `8000` | Longest question accepted |
| *(no variable)* | `openrouter/free` → `enigma` | The name the reader is shown, set by `labels` in the profile. See [Naming a model](#naming-a-model) — it has no environment override on purpose |
| `SAGE_OPENROUTER_FREE_MARKS` | `openrouter/free` | Which OpenRouter models enter the lineup. The default is the router's own id, so exactly one does; `:free` would pull in all 18 free models and hand their upkeep back to you |
| `SAGE_OPENROUTER_FREE_ONLY` | `1` | Off, the lineup holds all 387 models OpenRouter fronts, most of which need a balance |
| `SAGE_ZEN_DENY` | *(see profile)* | Model ids never offered, however the provider lists them. For a model that is served and cannot answer — maintained by `lineup.yml`, and cleared when the model answers again |
| `SAGE_STREAM_REPAINT_MS` | `40` | Shortest gap between repaints of a streaming answer. Deltas arriving inside one interval are drawn together, because `write_stream` redraws the whole answer every time. `0` = one repaint per delta |
| `SAGE_STATUS_ARGUMENT_CHARS` | `160` | How much of a tool's argument the progress block shows — the query searched for, and the *title* of the section read, since a corpus path is this repo's name for a file and not the documentation's. A ceiling on what a model can put in the page, not a layout number: the row ellipses whatever is too wide for the window it is in. Raised from 96, which ellipsed the longest title the shipped docs produce |
| `SAGE_MAX_UPLOAD_BYTES` | `10485760` | Upload size limit, per file |
| `SAGE_MAX_ATTACHED_BYTES` | `20971520` | Upload size limit, across one turn |
| `SAGE_IMAGE_MAX_EDGE` | `1568` | Longest edge an image is downscaled to before it is sent |
| `SAGE_MAX_IMAGE_REQUEST_BYTES` | `4194304` *(4 MiB)* | Ceiling on the assembled base64 image bytes in one request. Base64 inflates by a third, so a legal `SAGE_MAX_ATTACHED_BYTES` of uploads can become a 26 MB request no model accepts — and a data URL is deliberately uncounted against the character budget, so nothing else bounded it. What fits is sent; the rest are named in the text, and the first image always goes |
| `SAGE_FEEDBACK_LOG` | *(unset)* | JSONL sink for 👍/👎, zero-result queries, and one mechanics line per turn (outcome, rounds, searches, caveats, names redacted, seconds). Unset = nothing recorded |
| `LOG_LEVEL` | `WARNING` | Python log level |

The full set, with the measurements behind each default, is in
[`sage/config.py`](sage/config.py) — it is written to be read.

## Variables the shipped profile declares

These exist because [`profiles/rcc.toml`](profiles/rcc.toml) asks for them by name
(`path_env`, `models_env`, `key_env`, …). Your profile declares its own, or none.

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | *(one key required)* | OpenRouter key (`sk-or-v1-…`). The free router needs no balance |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenAI-compatible endpoint |
| `SAGE_OPENROUTER_MODELS` | `openrouter/free` | Fallback list if `GET /models` fails |
| `MISTRAL_API_KEY` | *(one key required)* | Mistral API key |
| `OPENCODE_API_KEY` | *(one key required)* | OpenCode Zen key (`sk-zen-…`), free tier |
| `OPENCODE_BASE_URL` | `https://opencode.ai/zen/v1` | OpenAI-compatible endpoint |
| `SAGE_MISTRAL_MODELS` | small/medium/large | Mistral models in the lineup |
| `SAGE_OPENCODE_MODELS` | deepseek-v4-flash-free, … | Fallback list if `GET /models` fails |
| `SAGE_ZEN_FREE_ONLY` | `1` | Offer only Zen's free models. `0` for a paid balance |
| `SAGE_ZEN_FREE_MARKS` | `-free,big-pickle` | How a free Zen model is recognised |
| `RCC_DOCS_PATH` | `./docs` | User Guide markdown source |
| `RCC_WEB_PATH` | `./web` | Scraped website text source |
| `RCC_DOCS_BASE_URL` | `https://docs.rcc.uchicago.edu/` | Where citations point |
| `SAGE_EXCLUDE_HOSTS` | radiology + vislab hosts | Scraped hosts to keep out of the index (`SAGE_EXCLUDE_HOSTS=` indexes everything) |
| `SAGE_EXCLUDE_FILES` | publication lists | Files to keep out of the index |

Any of these keys can go in `.streamlit/secrets.toml` (gitignored) instead of the
environment — on Streamlit Community Cloud that is **Settings → Secrets**, as
`OPENROUTER_API_KEY = "sk-or-v1-..."`. At least one is needed; set several and the
lineup holds all of them, and an automatic failover can cross between them.

## Providers

Both shipped adapters normalise onto the same streaming chunk, so nothing downstream
knows which is in use.

- **Mistral** — the official SDK.
- **OpenRouter** — `https://openrouter.ai/api/v1`, and the entry is one model id:
  `openrouter/free`, OpenRouter's *Free Models Router*, shown as **`enigma`** wherever
  the app names a model at all, because the served id names a billing arrangement rather
  than a model — see [Naming a model](#naming-a-model). It picks a free model per
  request from whatever is currently up, filtered to the ones supporting the parameters
  the request carries, so a tool-calling turn is never routed to a model that cannot
  call a tool. This is the provider that needs no lineup maintenance — see
  [When the lineup moves](#when-the-lineup-moves).

  Measured before it was trusted (2026-08-28, six requests, the app's own question and
  tool schema): six tool calls out of six, median 1.4s, routed across five different
  free models — one of which answered `429 … temporarily rate-limited upstream` when
  asked directly in the same minute. It absorbs the upstream failures rather than
  passing them on, which is the point.

  What it costs: the model changes turn to turn, so speed and answer quality vary in a
  way a pinned model's do not, and the reader cannot tell which model wrote what they
  are reading. Availability over consistency, deliberately.
- **OpenCode Zen** — the OpenAI-compatible endpoint at `https://opencode.ai/zen/v1`.
  Its model list comes from `GET /models` at runtime, because a free tier's lineup
  changes without notice; the profile's list is only the fallback. Zen serves its paid
  lineup from the same endpoint, so the app keeps only the free ones — matched by
  naming convention (`-free`, plus stealth codenames) rather than a hardcoded list,
  since the lineup moves. `SAGE_ZEN_FREE_ONLY=0` takes everything, for a deployment
  with a balance. The tier marker is part of the id sent upstream and of the filter
  that reads it, but not of `Model.label`: it is billing plumbing, and no part of what
  the model is.

Models that cannot call tools answer from a **single retrieval pass** instead of the
search/read loop — searched up front, matching sections in the prompt, still cited.
Set `SAGE_TOOLLESS_MODELS`, or let the app detect it: a provider that rejects tools is
retried that way.

The **Think** pill in the corner of the input box sends OpenRouter's `reasoning`
parameter, which a provider entry turns on with `reasoning = true` — declared per
provider rather than read off `kind`, because `kind = "openai"` covers both OpenRouter
and Zen and only one of them has heard of the field; an unknown key is a 400 from any
endpoint entitled to be strict about its own wire format. Of the three shipped providers
only OpenRouter has it, and the same flag decides whether the pill is drawn at all: it
is read off the model answering *now*, so a failover onto Mistral or Zen takes the pill
off the page for that turn rather than leaving a control that does nothing, and a new
question — which resets the session to `SAGE_DEFAULT_MODEL` — is what brings it back.
What it costs is output tokens, since reasoning tokens are billed as output, and the
request asks for the transcript to be *excluded*: the model still thinks, and nothing in
this app can display a transcript anyway. There is no environment override and no effort
dial, because `reasoning_effort` is supported by only a minority of the models the router
picks from — a low/medium/high setting would be honoured on some turns and ignored on
others, with nothing on screen able to say which.

### Naming a model

A model's name — `Model.label` — is normally its served id with the tier marker taken
off, because billing plumbing is not part of a name. That is not enough for an id that is
not a name at all: `openrouter/free` says which free tier the request draws on, and the
model behind it is a different one every turn, so no specific model name would be right
either.

So a provider entry may carry `labels`, a mapping of served id to the word the reader
sees:

```toml
labels = { "openrouter/free" = "enigma" }
```

The name reaches fewer places than it did. The model picker was where a reader read it
every turn, and `#84` removed it, so nothing on the page names the model answering as a
matter of course: what is left is the error card's "→ Use <model>" button, and the line
saying an attached image will not be looked at, which renders only once a failover has
landed on a model that cannot see one. `labels` still earns its keep on both.

The id is untouched everywhere it counts — upstream, in `Model.key`, in the feedback
log, in `tools/agent_bench.py`, and in the error card's technical-details panel — so
nothing that measures a model ends up measuring a nickname. There is deliberately no
`SAGE_*` override: a mapping cannot be spelled in an environment variable without
inventing a syntax to get wrong, and a deployment that wants different names has a
profile of its own.

### A note on the free tier

OpenCode Zen meters free models per **IP address**, per model, per UTC day, before
authentication — your key is not what is counted, and on a shared network neither is
your traffic. It also gives its own CLI a larger daily allowance than other clients,
chosen by `User-Agent`. `profiles/README.md` has the measurements and the
`user_agent` setting that exists because of them.

The practical consequence: treat the free models as a fallback. A funded key (Zen's
paid models are metered per key, per minute) or a provider that meters per account is
what makes a shared deployment dependable.

### When the lineup moves

**On OpenRouter, nothing at all — including by this repository.** Its entry is the
router, and `free_marks` is the router's own id, so `free_only` narrows the 387 models
OpenRouter fronts to exactly that one and discovery cannot widen it. There is no
fallback list to go stale, no retirement clock (a free model going dark is the router's
problem, and demonstrably its behaviour), and no stealth codename to hunt, because
OpenRouter publishes exact per-model pricing and every zero-priced model it serves says
so in its id. `lineup.yml` therefore runs with `--provider opencode`: unscoped, the 386
models the rule does not match would land in the stealth-codename queue and every run
would spend its whole probe budget asking paid models whether they are secretly free.

Widening that rule to `:free` would offer all 18 of OpenRouter's free models — the
suffix is exact in both directions — and would put them back under the maintenance
below, which is the arrangement the router was chosen to avoid. On the sweep it was
measured against, nine of those eighteen were rate-limited or dead.

The rest of this section is about Zen. Nothing has to be done there either for a model
that appears or disappears. The lineup is built from
`GET /models` and filtered by `free_marks`, so a model Zen starts serving free under a
`-free` name is in it the moment it exists — `muse-spark-1.2-contributor-free` was in the
lineup before the profile named it — and `SAGE_DEFAULT_MODEL` naming something no
longer served falls through to the first discovered option rather than failing.

`tools/lineup_check.py` covers the four things that rule cannot do on its own, and
`.github/workflows/lineup.yml` runs it daily:

| It catches | Because |
| --- | --- |
| A free model published under a **stealth codename** | The rule cannot invent the next `big-pickle`. Reported for a human; the tool never edits `free_marks` |
| A model that is **served but cannot answer** | `north-mini-code-free` was in the list and answering 401 from Zen's upstream. A list-only check calls that healthy |
| **How long** a model has been gone | The profile keeps a model that broke today, on the grounds that outages end. The ledger makes that a date instead of a hunch |
| The repo's **own record going false** | The fallback list matters only on the day discovery fails, which is the worst day to find out it is stale |

```bash
python tools/lineup_check.py                    # drift only — no key, no requests
python tools/lineup_check.py --probe            # + one completion per unclassified name
python tools/lineup_check.py --probe --update   # + append served free models
```

`GET /models` needs no key, so the drift half costs nothing and needs no secret. Probes
run only against names the ledger has not classified before — the one-time sweep of
Zen's 55 paid models took 6.5s and spent no allowance, since a paid model on a free key
is refused before it generates — so a day the lineup does not move costs nothing.

Two things it will not do. It **never reorders or removes**: the first entry of the
profile's list is what a fresh session starts on and what an automatic failover lands
on, which is a judgement no catalogue listing can make. And it is **never a CI gate**,
for the reason [`EVAL.md`](EVAL.md) gives about Axis B — a free tier rotating its lineup
is not this repository's fault, and a check that is red most weeks gets loosened until
it is quiet. It opens a pull request when there is an edit to make and updates one issue
when there is not.

One trap worth knowing if you write your own probe: it must ask for `SAGE_MAX_TOKENS`,
not a small number. A reasoning model spends the budget on thinking it does not emit —
`muse-spark-1.2-contributor-free` at `max_tokens=200` returns `completion_tokens: 200`
and an empty completion, three times out of three, and reads as a dead endpoint.

## Server settings

[`.streamlit/config.toml`](.streamlit/config.toml). The theme is stated **twice**,
under `[theme.light]` and `[theme.dark]`, so Streamlit keeps following the browser's
colour scheme: setting any `[theme]` value at all makes the theme a custom one, whose
`base` defaults to light, and `static/app.css` would then go dark on a dark-mode
device while Streamlit painted a white page underneath it. `server.maxUploadSize` is
deliberately larger than `SAGE_MAX_UPLOAD_BYTES` for a related reason — Streamlit
renders its own "file is too large" inside the uploader widget, which this app hides,
so the app has to be the one that refuses.

The typeface is stated there too, and it has to be: `[theme] font` and
`[theme] codeFont` are the only things that reach Streamlit's own widgets, while
`--font-sans` / `--font-mono` in `static/app.css` are the only things that reach the
markup this app writes itself. Both name IBM Plex, and `tests/test_streamlit_config.py`
holds the two files to the same families. The faces are five OFL woff2 files in
[`static/fonts/`](static/fonts) rather than a Google Fonts URL, so an offline
deployment renders correctly and no third party sees the reader — which is why
`server.enableStaticServing` must stay `true`: the `app/static/…` urls under
`[[theme.fontFaces]]` 404 without it, and a 404 there is not an error anywhere. The
page simply renders in the browser's default sans.

## Sharing a deployment

One key, one public URL, and a turn that costs up to `SAGE_MAX_TOOL_ROUNDS + 1`
provider calls. A spent key does not make the app slower, it ends it for everyone
until a human notices — so there are two limits, protecting two different things.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SAGE_RATE_BURST` | `5` | Questions one person may ask back-to-back before the sustained rate applies |
| `SAGE_RATE_REFILL_SECONDS` | `15` | One question back per this many seconds (≈4/min sustained, ≈20 per 5 min) |
| `SAGE_DAILY_TURNS` | `100` | Questions per person per day. A backstop against a loop, not a quota |
| `SAGE_CALL_BUDGET` | `0` (off) | **Provider calls for the whole deployment** per window. See below |
| `SAGE_BUDGET_WINDOW_SECONDS` | `86400` | The window the budget resets over |
| `SAGE_TOOL_RESULT_CHAR_BUDGET` | `60000` | Total tool output one turn may accumulate across all rounds |

Set any of them to `0` to switch that limit off.

**The per-person limits are a token bucket, not a fixed window**, because a window is
worse at both ends: it lets someone spend a whole allowance at 11:59 and another at
12:00, and it refuses a legitimate quick follow-up that lands just inside a boundary.
The defaults are invisible to normal use — an answer takes 20–60s to read, so
sustained demand is well under the refill rate.

**`SAGE_CALL_BUDGET` is the one that protects the key, and it is off by default** only
because the right number depends on a plan this repo cannot see. Set it from real
spend: `daily budget ÷ measured cost per call`. Note it counts *calls*, not questions —
one question is one to `MAX_TOOL_ROUNDS + 1` requests, so a limit counted in messages
says nothing about what the key is charged. Until it is set, nothing bounds a day's
spend.

Counters live in memory, shared across sessions in the one process Streamlit runs.
They reset when the app restarts — which on a platform that hibernates idle apps is
roughly daily. A deployment that needs the budget to survive a restart needs external
storage.

### Requiring a login

Off unless configured, and the highest-leverage control here by some distance: it
turns "anyone with the URL" into "people with an account you named".

| Variable | Default | Meaning |
| --- | --- | --- |
| `SAGE_REQUIRE_LOGIN` | `0` | Require a signed-in account |
| `SAGE_ALLOWED_EMAIL_DOMAINS` | *(empty = any)* | Comma-separated domains allowed past the gate |

Needs an OIDC provider in `.streamlit/secrets.toml`
([Streamlit's guide](https://docs.streamlit.io/develop/concepts/connections/authentication)):

```toml
[auth]
redirect_uri = "https://your-app.example/oauth2callback"
cookie_secret = "a long random string"
client_id = "…"
client_secret = "…"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

Then `SAGE_REQUIRE_LOGIN=1` and `SAGE_ALLOWED_EMAIL_DOMAINS=your-org.edu`. **Leave the
domain list empty and a Google client authenticates the entire internet**, so set it.
Setting the flag *without* an `[auth]` block does not lock the app — it runs open and
logs an error, because the alternative is a sign-in button that cannot work, locking
out whoever set the flag.

Signing in also makes the limits enforceable rather than advisory: anonymous readers
are keyed by session, and a new private window is a new session. Identity is never
keyed on IP address — campus NAT and a VPN put hundreds of people behind one, so a
per-IP cap either does nothing or locks out a whole building.

One consequence worth deciding on deliberately: with a login, the feedback log becomes
attributable to named people, and readers paste job scripts into this app.

## Keeping the bundled corpus fresh

`docs/` and `web/` are a snapshot of the upstream
[`user-guide`](https://github.com/rcc-uchicago/user-guide) repo. Run from an
internet-connected host:

```bash
./refresh-docs.sh            # sync docs + web, stamp docs_snapshot.json
./refresh-docs.sh --scrape   # also re-scrape the RCC website
```

Paths are repo-relative and overridable with `RCC_USER_GUIDE_REPO`, `RCC_WEB_MIRROR`
and `RCC_WEB_SCRAPER`. The website scraper is **not** vendored here, so `--scrape`
needs `RCC_WEB_SCRAPER` pointed at it. The sync date and upstream commit land in
`docs_snapshot.json`.

This script is specific to that corpus. Another deployment keeps its documents fresh
however it likes — the app only ever reads the trees the profile names.

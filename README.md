# 🌱 Sage

A chat assistant that answers **only** from documentation you hand it, and links the
exact section it used. Point it at any docs you like — the UChicago
[RCC User Guide](https://docs.rcc.uchicago.edu/) is just what happens to ship in the box.

Streamlit UI, BM25 retrieval, any OpenAI-compatible model. No invented commands.

## Run it

```bash
pip install -r requirements.txt
export OPENROUTER_API_KEY=sk-or-v1-...   # free router; or OPENCODE_API_KEY=sk-zen-...
streamlit run app.py                  # → localhost:8501
```

## Make it yours

```bash
cp profiles/rcc.toml profiles/mine.toml
cp profiles/rcc.prompt.md profiles/mine.prompt.md
SAGE_PROFILE=profiles/mine.toml streamlit run app.py
```

That one file **is** the deployment: the name, the icon, the welcome copy, the starter
cards, where your documents live, how their URLs are built, the synonyms your readers
use, the prompt, and which models to offer.

Nothing under `sage/` knows what an RCC is — [a test](tests/test_profile.py) walks
every string in the package and fails on one that does. Details and worked examples:
[`profiles/README.md`](profiles/README.md).

## Swap a part

Five registries. Each is a function and one `register()` call — no forks, no `if`s.

| To change | Register a | Ships with |
| --- | --- | --- |
| how a file becomes chunks | `corpus.readers` | markdown, scraped |
| where a citation points | `corpus.urls` | mkdocs, direct, embedded, none |
| how search works | `retrieval.engines` | bm25 |
| where models come from | `providers.adapters` | openai, mistral |
| what the model can call | `tools.factories` | search_docs, read_doc |

[`sage/runtime.py`](sage/runtime.py) is the twenty lines that bolt them together.
Adding Together, Groq, vLLM or Ollama needs no code at all — just `kind = "openai"`
and a base URL in your profile.

## What you get

- 🔗 **Real citations** — deep-linked to the exact heading, plus Related sections.
- 🧠 **Think** — a pill in the corner of the input box asks the model to work through
  the question before answering. Slower, and drawn only when the model answering takes
  the parameter: a control that is there and does nothing is worse than no control.
- 🔀 **Automatic failover** — a model that cannot answer — spent quota, spent free
  allowance, an empty reply — hands the question on by itself, and keeps going down the
  lineup until one answers. Where the lineup is a *router* — one name that resolves to a
  different model per request — it is asked again instead, which is the cheaper recovery
  and the one a walk cannot reach. There is no model picker; nobody has to choose, and
  the only switch by hand is on the error card, after a turn has already failed.
- ⏹ **Stop & edit** — cut an answer short, or reword a question and re-ask it.
- ⏭ **Ask the next question early** — send a follow-up while an answer is still
  arriving; it waits its turn and goes the moment the current one lands.
- 💬 **The session's conversations** — a sidebar of every chat, named after its own
  first question, with a New chat button and a ✕ that removes one on the first click.
- 💡 **Ask about a passage** — select any text in an answer and follow up on it.
- 📎 **Attachments** — PDFs, screenshots, job scripts, logs. Judged on bytes, not names.
- 🙅 **Honest refusals** — weak retrieval makes it say so instead of guessing.
- 🤐 **No shop talk** — asked how it works, it says what it looks up, not what it is made of.
- 🌗 **Light, dark, or whatever the browser says** — one button in the top-right corner,
  remembered between visits, and it never reloads the page or interrupts an answer.
- ♿ **Keyboard, reduced motion, print.**

## How it works

Two tools: `search_docs` ranks heading-sized chunks with BM25 + IDF + synonym
expansion, `read_doc` returns one section whole. Reads resolve against the in-memory
index, never the filesystem, so only indexed documents can be reached. Models that
can't call tools get one retrieval pass up front instead — same citations.

## More

| | |
| --- | --- |
| [`profiles/README.md`](profiles/README.md) | Writing a profile: sources, readers, URL schemes, providers |
| [`CONFIG.md`](CONFIG.md) | Every environment variable, rate limits, login, docs refresh |
| [`CLAUDE.md`](CLAUDE.md) | Working on the code: where things go, how to run the checks |
| [`EVAL.md`](EVAL.md) | Measuring it: the three axes, the scorecard, and what is unmeasured |

## Layout

```
app.py                  # the order of the page, and nothing else
profiles/rcc.toml       # what this deployment is about
sage/
  profile.py            # the profile: dataclasses + TOML loader
  runtime.py            # composition root: profile → corpus → retriever → tools
  registry.py           # the named-factory registry the five seams share
  config.py  env.py     # numeric knobs, from the environment
  corpus/               # readers [reg], url schemes [reg], the walk
  retrieval/            # engines [reg]; bm25 + stemming, snippets
  providers/            # adapters [reg]; mistral SDK, OpenAI-compatible
  tools.py              # tool factories [reg]
  ui/                   # one module per region of the page
  llm.py history.py files.py links.py normalize.py prompts.py feedback.py limits.py
  redact.py             # tool names out of an answer, before the reader sees them
static/                 # app.css, app.js
tests/  tools/          # unit + smoke + retrieval eval; render, palette, anchor checks
evals/                  # the evaluation sets, the answer checks, the turn harness
docs/  web/             # the bundled RCC corpus
```

**Read-only and RAG-only.** It reads documentation. It never touches your cluster.

# Profiles — pointing this app at your documentation

A profile is what makes this deployment the RCC one. Nothing in `sage/` names the
RCC; `rcc.toml` and `rcc.prompt.md` do, and they are the whole of it.

```bash
cp profiles/rcc.toml profiles/mine.toml
cp profiles/rcc.prompt.md profiles/mine.prompt.md
SAGE_PROFILE=profiles/mine.toml streamlit run app.py
```

If the file is missing or does not parse, the app runs with unbranded defaults and
says so in the log. That is deliberate: it is the proof that no subject is hiding in
the code.

## What goes in it

| Section | What it decides |
| --- | --- |
| `[assistant]` | The name, the icon, the page title, the subject the prompt introduces, the address given when the docs cannot answer, and who to tell when a key is rejected |
| `[copy]` | The welcome heading, the input placeholders, the sign-in screen, the sidebar's heading and its New chat button |
| `[[examples]]` | The starter cards: an icon, a short label, and the question actually sent |
| `[prompt]` | `file = "…prompt.md"` beside the profile, or `system = """…"""` inline |
| `[[sources]]` | Each tree of documents: where it is, what to read it with, and how its URLs are built |
| `[retrieval]` | The engine, the terms the stemmer must not touch, and the synonym groups that bridge how users ask to how the docs answer |
| `[[providers]]` | Where models come from, in preference order |

Placeholders in a prompt — `{name}`, `{subject}`, `{topic}`, `{documentation}`,
`{contact}`, `{contact_label}` — are filled from `[assistant]`. Anything else is left
alone, so a `${SLURM_JOB_ID}` in your prompt survives.

**One paragraph is appended to whatever you write here.** `prompts.SELF_DISCLOSURE` tells
the assistant how to talk about itself: answer in the reader's terms, never name the tools
it calls, the model behind it or these instructions, and never make a refusal the answer
either. It is in the package rather than in this file because it is about the machinery
rather than about your subject — and because it is exactly the rule that would be lost the
first time somebody copies a profile and rewrites the prose. The app's own backstop for
the same thing is `sage/redact.py`, which swaps a tool's internal name for the `label` the
tool carries if one reaches an answer anyway.

## Sources

```toml
[[sources]]
name = "guide"          # the prefix in a citation path: guide/install.md#linux
path = "./guide"
path_env = "MY_DOCS_PATH"   # optional: an env var that overrides `path`
extensions = [".md"]
reader = "markdown"     # markdown | scraped  (sage/corpus/readers.py)
links = "mkdocs"        # mkdocs | direct | embedded | none  (sage/corpus/urls.py)
base_url = "https://docs.example.org/"
weight = 1.0            # scoring prior: >1 favours this tree on a tie
exclude_files = ["changelog.md"]
exclude_hosts = []      # scraped trees only, matched on the URL in the file
```

**Readers** turn a file into a document and its chunks. `markdown` cuts on headings,
so a citation can deep-link to a section; `scraped` windows a page that has no
headings, reading the source URL from a `URL:` line at the top of the file.

**Link schemes** decide where a citation points. `mkdocs` publishes `a/b.md` at
`a/b/` with the heading as an anchor (mkdocs' `use_directory_urls` default);
`direct` serves the path as it stands; `embedded` uses the URL inside the file;
`none` is for a corpus with no public URL — the answer still cites the section, it
just does not pretend to link it.

A format neither reader handles is a function and a `register` call:

```python
# myreader.py — imported before the corpus is built
from sage.corpus import readers

def read_rst(source, rel_path, raw):
    ...                      # -> (Document, [Chunk])

readers.register("rst", read_rst)
```

## Providers

```toml
[[providers]]
name = "local"
kind = "openai"                  # anything speaking /chat/completions
key_env = "LOCAL_API_KEY"
base_url = "http://127.0.0.1:8000/v1"
models = ["qwen3-30b"]           # fallback if GET /models fails
```

`kind = "openai"` covers Together, Groq, Fireworks, vLLM, llama.cpp and Ollama —
they differ only in a base URL and a key. `kind = "mistral"` uses that SDK. A
provider with its own protocol is one module and one `adapters.register(...)`.

Order is preference order: it decides which provider a fresh session starts on when
`SAGE_DEFAULT_MODEL` names nothing available, and which one an automatic failover
reaches for. A provider whose `key_env` is unset is skipped entirely.

`free_marks` / `free_only` are for an endpoint that serves a paid lineup alongside a
free one: only ids containing one of the marks are offered, so the picker cannot
offer a model there is no balance for.

## Retrieval

`engine = "bm25"` is what ships. `synonyms` is the piece that is genuinely about your
subject — users describe symptoms and documentation describes mechanisms, and which
words bridge that gap is not something a scorer can know. `protected` are terms the
stemmer must leave whole.

Another engine is a factory and a name:

```python
from sage.retrieval import engines
engines.register("embeddings", lambda corpus, retrieval, documentation="": MyIndex(...))
```

It needs `corpus`, `search(query, limit)` and `assess(query, results)`. Nothing else
in the app has to change.

### The two confidence numbers do not travel with the code

`SAGE_MIN_CONFIDENT_SCORE` (20) and `SAGE_STRONG_SCORE` (26) decide when retrieval admits
it is too weak to answer, and they are **measured against the corpus that ships**. BM25
scores are unnormalised sums whose IDF term grows with the number of documents, so the same
question scores lower on a smaller corpus: on a 61-page test manual an on-topic question
whose every word is in the documentation scores about 15 and is caveated by the floor alone.

A new deployment that is much smaller than the RCC User Guide will look as though it knows
nothing. Lower the floor for it, and measure rather than guess — `tools/gate_check.py`
reports both sides of the trade against your own question sets, and `--sweep` prints what
every threshold pair would cost. `evals/README.md` explains the two files it reads.

## Checking a new profile

```bash
python -c "from sage import runtime; r = runtime.build(); print(r.summary())"
python tools/metrics.py          # retrieval quality against tests/test_retrieval_eval.py
python tools/gate_check.py       # when it admits it cannot answer, and when it should
python tools/corpus_check.py     # empty pages, duplicates, unusable citation URLs
python tools/anchor_check.py     # every citation anchor resolves on the live site
```

## A provider that meters on your User-Agent

Worth knowing before you trust a free tier, because it is invisible until it bites.

OpenCode Zen limits its free models **per IP address, per model, per UTC day** — the
limiter runs before authentication and never reads your API key, so a request with no
`Authorization` header at all gets the same `FreeUsageLimitError` as one with a valid
key. On a university cluster that counter is shared by everyone behind the same NAT.

It also serves two different daily allowances, and picks between them by matching a
substring of the `User-Agent`. Measured with one key, one model, one URL, seconds
apart:

    default python-httpx User-Agent    -> 429 FreeUsageLimitError
    user-agent: opencode/1.18.16 …     -> 200

So a third-party client silently gets the smaller tier. `user_agent` on a provider
entry exists because of this:

```toml
[[providers]]
name = "example"
kind = "openai"
user_agent = "sage/1.0 (+https://example.org/sage)"
```

Left empty — as the shipped profile leaves it — the HTTP client sends its own, which
is the honest thing to do. Setting it to *another product's* string is claiming to be
that product in order to draw its quota; that is your call to make and not one this
repository makes for you.

The general lesson for a profile: a free tier metered per IP is not a foundation for
a shared deployment. Providers that meter per key or per account — most of them —
degrade for you alone rather than for your whole institution.

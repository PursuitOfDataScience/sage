"""The citations a model emits: point them at real URLs, drop the duplicate list.

The previous version sent *every* `web/` citation to the user-guide root on the
stated grounds that "website pages have no stable per-page docs URL". They do —
each scraped file records it on line 1 — and they span five different hosts, so a
Skyway or Beagle3 answer was being cited to the Midway user guide.
"""

from __future__ import annotations

import re

from .corpus import Corpus

# One level of nesting inside the label, because `[Batch jobs [beta]](docs/…)` is a
# link a model writes and `[^\]]+` could not match it: the target was neither resolved
# nor unlinked, so it shipped as a live relative href, which the browser resolves
# against the Streamlit app's own host and 404s — the exact confident-wrong-citation
# this module exists to prevent, and `unresolved()` could not see it either.
_MARKDOWN_LINK = re.compile(
    r"\[((?:[^\[\]]|\[[^\[\]]*\])+)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)"
)
_ATTR_LIST = re.compile(r"\{:[^}]*\}")
_EXTERNAL = ("http://", "https://", "mailto:", "tel:", "#")

# A markdown image, with the mkdocs-material size attribute that usually follows one.
# Eighteen indexed sections carry these — the SDE3 connection tutorial is nothing but
# screenshots — so a model quoting one echoes the syntax into its answer. The link
# rules below see `[alt](images/avd_login.png)`, cannot resolve an image path in a
# corpus of documents, and unlink it: what the reader got was `!Screenshot showing AVD
# login{ width="1000" }`, a stray exclamation mark and a stray attribute list.
#
# `[figure: alt]` instead, which is the wording `normalize._replace_img` already gives
# an HTML image at index time — the same thing said the same way, and honest about
# there being a picture here that this transcript is not showing.
_MARKDOWN_IMAGE = re.compile(
    r"!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)(?:\{[^}\n]*\})?"
)


def _as_figure(match: re.Match[str]) -> str:
    """A relative image reference as text. An absolute one is left to render.

    Only the relative form is broken: there is no image in a corpus of documents for
    it to resolve against, so it reached the reader as `!alt{ width="1000" }`. An
    `https://` image is a picture the browser can actually fetch — the geocoding
    tutorial has four — and replacing those with a caption would take a working
    figure away, which every other rule in this module is careful not to do.
    """
    if match.group(2).startswith(_EXTERNAL):
        return match.group(0)
    alt = match.group(1).strip()
    return f"[figure: {alt}]" if alt else "[figure]"


def resolve(target: str, corpus: Corpus) -> str | None:
    """Best URL for an internal doc reference, or None if it cannot be resolved."""
    target = target.strip()
    if not target:
        return None

    chunk = corpus.chunk(target)
    if chunk is not None:
        return chunk.url

    base, _, anchor = target.partition("#")
    base = base.strip().lstrip("./")

    document = corpus.document(base)
    if document is None:
        # Declaration order is the preference, which is what the two literals that used
        # to be here — `("docs", "web")` — were really saying: prefer the maintained user
        # guide to the scraped site when a bare `guide.md` could be either. Written as
        # the RCC's own tree names, that preference belonged to one deployment. Two
        # sources named anything else got no preference and no link: `resolve` returned
        # None, `fix_links` did the honest thing and unlinked the citation, and a second
        # deployment quietly lost working links that this one gets. The docstring six
        # lines down already complains about this pattern in six other places.
        for source in corpus.sources:
            document = corpus.document(f"{source.name}/{base}")
            if document is not None:
                break

    if document is None:
        # A bare or relative filename: match on path suffix.
        candidates = [
            item
            for item in corpus.documents.values()
            if item.path == base or item.path.endswith(f"/{base}")
        ]
        document = candidates[0] if len(candidates) == 1 else None

    if document is None:
        return None
    # The document's own source knows how to place an anchor — or that it cannot,
    # which is the right answer for a scraped page with no headings to point at.
    # This used to be `if document.source == "web"`, one of six places the corpus's
    # two tree names were spelled out in code that had no other business knowing them.
    return corpus.url_for(document, anchor)


def unresolved(text: str, corpus: Corpus) -> list[str]:
    """Internal link targets in `text` that resolve to nothing.

    Worth counting rather than only hiding: a model inventing a path is a generation
    defect, and a turn that produces one should be visible in the log rather than
    silently tidied away by the renderer.
    """
    missing = []
    # Images first, and for the same reason `fix_links` does it: an image path is not
    # a citation, and counting one as an invented section put a warning in the log
    # every time a model quoted the SDE3 screenshots.
    text = _MARKDOWN_IMAGE.sub(_as_figure, _ATTR_LIST.sub("", text))
    for match in _MARKDOWN_LINK.finditer(text):
        target = match.group(2)
        if target.startswith(_EXTERNAL):
            continue
        if resolve(target, corpus) is None:
            missing.append(target)
    return missing


def cited_pages(text: str, corpus: Corpus) -> set[str]:
    """Every page an internal link in `text` resolves to — the inverse of `unresolved`.

    What the *reader* can click, which is not the same as what the turn read: the Sources
    strip is built from `read_doc` calls only, so a model that searches, cites a page from
    the snippet and never reads it delivers a working inline link under an empty strip.
    Measured over 157 recorded answers with a gold page, that is six turns — and the
    benchmark scored every one of them as not having cited the right page, under a column
    labelled `cited_gold`.
    """
    pages: set[str] = set()
    text = _MARKDOWN_IMAGE.sub(_as_figure, _ATTR_LIST.sub("", text))
    for match in _MARKDOWN_LINK.finditer(text):
        target = match.group(2)
        if target.startswith(_EXTERNAL) or resolve(target, corpus) is None:
            continue
        chunk = corpus.chunk(target)
        if chunk is not None:
            pages.add(chunk.path)
            continue
        document = corpus.document(target.split("#", 1)[0])
        if document is not None:
            pages.add(document.path)
    return pages


def fix_links(text: str, corpus: Corpus) -> str:
    """Point internal links at published URLs; unlink what cannot be resolved.

    That second clause is what this docstring promised while the code did the
    opposite: an unresolvable target became a live link to `DOCS_BASE_URL`, so a
    reader clicking a citation landed on the front page of the user guide believing
    they had reached the cited section. A confident wrong citation is worse than no
    citation — it spends the trust the Sources strip exists to earn, and nothing about
    it looks different from a citation that works.

    The label now survives as plain text: a section named but not linked, which is
    honest about exactly what happened.
    """
    text = _MARKDOWN_IMAGE.sub(_as_figure, _ATTR_LIST.sub("", text))

    def replace(match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2)
        if target.startswith(_EXTERNAL):
            # A bare in-page anchor has nowhere to go in a chat transcript.
            return label if target.startswith("#") else match.group(0)
        url = resolve(target, corpus)
        label = _titled(label, target, corpus)
        return f"[{label}]({url})" if url else label

    return _MARKDOWN_LINK.sub(replace, text)


# The prompt asks for citations "as [Section title](path)", and a model that copies the
# instruction rather than following it emits that phrase verbatim as the visible label.
# Observed in a live answer: "The same table in the docs explains each field. Section
# title" — the reader is shown a fragment of this app's own prompt, and the one thing a
# citation has to say, which page it is, is the thing missing.
_PLACEHOLDER_LABELS = frozenset({
    "section title", "page title", "title", "section", "page", "doc title",
    "document title", "section name", "link text",
})


def _titled(label: str, target: str, corpus: Corpus) -> str:
    """The label, unless it is the prompt's own placeholder — then the real title."""
    if label.strip().lower().strip("*_`") not in _PLACEHOLDER_LABELS:
        return label
    chunk = corpus.chunk(target.strip())
    if chunk is not None:
        return chunk.label
    base = target.strip().partition("#")[0].lstrip("./")
    document = corpus.document(base)
    if document is None:
        for source in corpus.sources:
            document = corpus.document(f"{source.name}/{base}")
            if document is not None:
                break
    return document.title if document is not None and document.title else label


# `Sources:`, `**References:**`, `**Citations**:`, `## Sources` — every decoration a
# model puts round the word, matched by treating `*_#` and space as noise either side
# of it. Both spellings of the bold form turn up, which is why the colon is allowed to
# fall on either side of the markup rather than in one fixed place.
_LABEL = r"(?:sources?|references?|citations?)"
_MARKUP = r"[*_#\s]*"
_LABEL_LINE = re.compile(
    rf"^\s{{0,3}}{_MARKUP}{_LABEL}{_MARKUP}(?P<colon>:?){_MARKUP}(?P<rest>.*)$",
    re.IGNORECASE,
)
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_FENCE = re.compile(r"^\s*(?:`{3,}|~{3,})")
_RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")

# Links and nothing else: no words outside the brackets, separators only between them.
# This is the shape a model falls back on when told not to write the word "Sources" —
# it drops the label and leaves the list. Prose that happens to contain a link ("see
# [Batch jobs](docs/slurm/sbatch.md) for flags") has words outside the brackets and
# does not match, which is the whole distinction.
_LINK_PART = r"\[[^\]]+\]\(\s*[^)\s]+(?:\s+\"[^\"]*\")?\s*\)"
_ONLY_LINKS = re.compile(
    rf"^\s*(?:[-*+]\s+|\d+[.)]\s+)?{_LINK_PART}(?:[\s,;·|]*{_LINK_PART})*[\s,;.·]*$"
)

# The third shape, and the one a model reaches for when told not to write the word
# "Sources": a *sentence* of citations. "Cited from [A] and [B]." is a footer with
# grammar, so neither the label rule nor the bare-links rule sees it.
#
# Split into scaffolding — words a citation sentence is built from — and the signal
# words that say it IS one. Both are required: without a signal, "See [Batch jobs](…)
# and [Partitions](…)." is a pointer inside an answer and stays. With any word outside
# the set, it is prose: "For full details, see [GPU jobs](…) and [PyTorch](…)." keeps
# `details`, so it stays too.
_CITE_SIGNAL = frozenset({
    "cited", "citing", "citation", "citations", "source", "sources", "sourced",
    "reference", "references", "referenced", "per", "based", "according", "drawn",
    "taken",
})
_CITE_SCAFFOLD = _CITE_SIGNAL | frozenset({
    "and", "from", "on", "to", "of", "in", "the", "this", "these", "those", "above",
    "see", "i", "my", "we", "you", "it", "is", "are", "was", "were", "all", "both",
    "they", "them", "information", "info", "answer",
})
_WORDS = re.compile(r"[A-Za-z']+")


def _footer_label(line: str) -> str | None:
    """The text after a `Sources:`-style label, `None` if this is not such a line.

    A payload without a colon is prose — "Sources of variation include …" opens with
    the word and is a sentence, not a footer — so the colon is what licenses cutting
    anything that sits on the same line.
    """
    match = _LABEL_LINE.match(line)
    if not match:
        return None
    rest = match.group("rest").strip()
    if rest and not match.group("colon"):
        return None
    return rest


# How long a reference may be before it is a sentence, by how it ends.
#
# A question mark buys the most room, because RCC section headings run to whole
# questions: "How do I check how many service units I have remaining on my
# allocation?" is fourteen words and is a heading, not prose. A phrase that stops
# like a sentence gets the least, because that is the one ending where a short title
# and a short sentence look the same. Everything else sits in between — eight words
# is longer than any chip label in the corpus and shorter than "This work was
# completed in part with resources provided by the", which is what a citation
# paragraph looks like when it wraps.
_MAX_TITLE_WORDS = 14
_MAX_PLAIN_TITLE_WORDS = 8


# A title that closes like a sentence has to be short to still read as a title.
# `Sources: Storage.` and `Sources: Midway3 partitions.` are footers a model really
# writes; `The University of Chicago's Research Computing Center is acknowledged.` is
# an answer, and the only thing separating them by shape is length.
_MAX_STOPPED_TITLE_WORDS = 6


def _looks_like_a_title(text: str) -> bool:
    """A reference in a citation list, as opposed to a sentence in an answer.

    The rule this replaces was "shorter than 120 characters", and under a `Citation:`
    label that ate the answer: asked how to acknowledge RCC in a paper, the model
    printed the wording to copy and the strip deleted it, from the transcript and from
    the history sent upstream. "This work was completed in part with resources
    provided by the" is 61 characters.

    A title is a noun phrase — it starts on a capital, a digit or a bracket, and it is
    short. A trailing `?` costs nothing, because this corpus is full of headings that
    are questions; a trailing full stop halves the length allowed, because that is the
    one mark that makes a short phrase and a sentence look alike.
    """
    if len(text) > 120:
        return False
    words = text.split()
    if not words:
        return False
    # A bare path is a reference whatever its case: `Sources: docs/slurm/sbatch.md`
    # is the same footer as the linked form, and one token with a slash in it and no
    # spaces cannot be a sentence.
    if len(words) == 1 and "/" in text:
        return True
    if text.endswith((";", ":")):
        return False
    if text.endswith("?"):
        limit = _MAX_TITLE_WORDS
    elif text.endswith((".", "!")):
        limit = _MAX_STOPPED_TITLE_WORDS
    else:
        limit = _MAX_PLAIN_TITLE_WORDS
    if len(words) > limit:
        return False
    head = words[0].lstrip("*_“\"'(")
    return bool(head) and (head[0].isupper() or head[0].isdigit() or head[0] == "[")


def _is_citation_payload(text: str, names: set[str]) -> bool:
    """Is what sits after a `Sources:` label a list of references, or a sentence?

    The label alone used to be enough, and for a list of links or titles it is. It is
    not enough for `Citation: please reference the University of Chicago's Research
    Computing Center.` — which is not a footer, it is the answer, and the whole line
    went.

    A markdown link settles it: that is the citation shape whatever else is on the
    line. Otherwise every comma-separated part has to be a name the strip is already
    showing — proof, so punctuation cannot get in the way — or read as a title.
    """
    if "](" in text:
        return True
    # The whole payload first, before it is split. A comma is the separator between
    # citations and also a character inside a heading — "Service units, allocations,
    # and accounts" is one section of the RCC guide — so splitting first turns a name
    # the strip is showing into three fragments that match nothing.
    if names and _norm_title(text) in names:
        return True
    parts = [part.strip() for part in re.split(r"[,;]", text) if part.strip()]
    if not parts:
        return False
    if names and all(_norm_title(part) in names for part in parts):
        return True
    return all(_looks_like_a_title(part) for part in parts)


def _is_citation_line(line: str, names: set[str]) -> bool:
    """A line that could only be part of a citation list, never of an answer.

    Deliberately narrow. `- Run \\`sbatch job.sh\\`` is a step, not a citation, so a
    code span disqualifies a line; so does the shape of a real sentence. What is
    left is bullets of titles and bare links, which is what the footer is made of.
    """
    if _FENCE.match(line) or "`" in line:
        return False
    stripped = line.strip()
    if not stripped:
        return True          # blank lines inside a block belong to it
    if stripped.startswith("#"):
        return False
    if _ONLY_LINKS.match(line) or _LIST_ITEM.match(line):
        return True
    return _norm_title(stripped) in names or _looks_like_a_title(stripped)


def _pages(line: str, corpus: Corpus) -> set[str] | None:
    """The published pages every link on this line points at, or None if any is a
    reference this repository cannot resolve — in which case it is not provably a
    duplicate of anything and must be left where it is.

    Compared at page granularity, not per anchor: a strip chip linking
    `…/faq/#how-do-i-review` already gives the reader that page, whatever section of
    it the model chose to point at.
    """
    found = _MARKDOWN_LINK.findall(line)
    if not found:
        return None
    pages = set()
    for _label, target in found:
        if target.startswith(_EXTERNAL):
            return None
        url = resolve(target, corpus)
        if not url:
            return None
        pages.add(url.split("#", 1)[0])
    return pages


# The fourth shape, and the one that survives every rule above: a parenthetical of
# bare section titles dropped into a sentence — "…used on a cluster (Allocations and
# Service Units FAQ, Running jobs on RCC clusters)." It is not a trailing line, so the
# line-oriented rules never see it; it holds no links, so `_pages` cannot judge it; and
# it names the very sections the strip lists three lines below.
#
# Judged against what the strip is actually showing rather than by shape, because shape
# alone cannot tell a citation from prose: the same sentence also contains
# "(CPUs/GPUs/time)", which has to stay. Every comma-separated part must name a
# retrieved section, so one ordinary aside anywhere inside the brackets keeps the whole
# parenthetical.
_PAREN = re.compile(r"[ \t]*\(([^()]*)\)")
# Tried in order, widest first, because "and" is both a separator between citations
# ("Batch jobs and Partitions") and a word inside one ("Allocations and Service Units
# FAQ"). Splitting on it up front cuts that title in half and the match is lost, so the
# unsplit string and the comma-only split both get a turn before it is used.
_PAREN_SPLITS = (None, re.compile(r"[,;]"), re.compile(r"[,;&]|\band\b"))
# A citation the model introduces rather than states bare: "(see Batch jobs)".
_CITE_LEAD = frozenset({
    "see", "from", "per", "source", "sources", "cited", "citing", "citation",
    "citations", "reference", "references", "based", "on", "according", "to", "in",
    "the", "also", "further", "more", "detail", "details",
})


def _norm_title(text: str) -> str:
    """A section title reduced to what two spellings of it have in common."""
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = re.sub(r"[`*_]+", "", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text.strip(" .,;:!?—–-")


def _source_names(sources: list[dict], *, floor: int = 2) -> set[str]:
    """Every name the Sources strip is already showing a reader.

    A chip reads `Doc title — Section heading`, and a model citing it in prose picks
    one end or the other, so both halves count as the same reference.

    `floor` is why this takes an argument. Single-word names are left out for the
    inline rule: `Storage` or `Python` is a title *and* an ordinary word, and
    "(Python)" after a package name is an aside, not a citation. A footer is a
    different question — `Sources: Storage.` is a whole line whose entire content is
    that one word — so the footer rules ask for `floor=1`, where an exact match
    against a chip is proof rather than a guess.
    """
    names: set[str] = set()
    for item in sources:
        label = str(item.get("label", ""))
        head, sep, tail = label.partition(" — ")
        for candidate in (label, head, tail) if sep else (label,):
            name = _norm_title(candidate)
            if name and len(name.split()) >= floor:
                names.add(name)
    return names


# A reference the reader cannot use: the index's own name for a section, printed as
# prose. The loose shape is deliberate — anything that could be a path gets *offered*,
# and `resolve()` against the corpus is what decides. That way this cannot invent a rule
# about file extensions that a second deployment's corpus breaks.
_REFERENCE_TOKEN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._/-]*\.[A-Za-z0-9]{1,6}(?:#[A-Za-z0-9._-]+)?"
)

# Wrappers a model puts around one of those when it thinks it is citing. The last two
# are not decoration: `【…】` and `{…}` both turned up in real answers, and a wrapper
# missing from here is left behind empty, so the reader is shown `documentation 【】:`
# instead of the identifier — a worse leak than the one being removed.
_WRAPPED = {"[": "]", "(": ")", "`": "`", "<": ">", "{": "}", "\u3010": "\u3011"}


def strip_bare_references(text: str, corpus: Corpus) -> str:
    """Remove index identifiers the model printed instead of linking them.

    `search_docs` hands the model strings like `web/about-rcc_our-team.txt#5` and the
    system prompt asks for them back inside `[Title](path)`, where `fix_links` turns
    them into URLs. A model that instead writes the identifier as text —

        Source: "Our Team" page on the RCC website [web/about-rcc_our-team.txt#5].

    — has published this app's internal filing system to the reader. It is not a broken
    link, which is why nothing else here caught it: `unresolved()` is quiet because the
    id resolves perfectly, `strip_inline_citations` only reads *parenthesised* asides
    naming a section *title*, and `strip_source_footer` judges the shape of a footer
    rather than its contents. So the string sails through every existing guard and lands
    in the answer, where it reads as machine output leaking into prose.

    Only references that RESOLVE are removed, so ordinary text that merely looks like a
    filename is left alone. Markdown link targets are skipped — `](path)` is the citation
    the prompt asked for and the one thing here that must survive — as is anything inside
    code, where a filename is usually the reader's own file and not ours.

    **What models actually write, measured over the 662 recorded answers in
    `report/transcripts*.jsonl`: this pass fires on 10 of them, and every one is a
    TRAILING BRACKETED ASIDE** — `…is the hard limit 【docs/storage/main.md#quotas】.` or
    the same in square brackets after a working link. `_with_wrapper` takes the brackets
    with the id and the sentence closes cleanly; all ten read correctly afterwards.

    The shape that would NOT read correctly is a bare id used as a sentence constituent,
    with no wrapper around it: `See docs/accounts.md#apply for the details` becomes `See
    for the details`, and `docs/x.md#y covers this` becomes `covers this`. Zero of 662
    answers do that, which is why removal is the right move and why this is recorded
    rather than fixed — the cure would be to replace the id with `[Title](path)` and let
    `fix_links` render it, which is more code, a new failure mode (a link the model did
    not ask for) and, on the evidence, a fix for nothing. If it ever shows up, that is
    the fix, and this paragraph is the measurement it should be re-taken against.
    """
    if not text or not corpus:
        return text

    out: list[str] = []
    fenced = False
    for line in text.split("\n"):
        if _FENCE.match(line):
            fenced = not fenced
            out.append(line)
            continue
        if fenced:
            out.append(line)
            continue
        cleaned, removed = _clean_line(line, corpus)
        # A citation line whose only citation has just been taken out of it is a label
        # with nothing under it — "Source: the RCC website ." — and keeping it would
        # replace one leak with a sentence pointing at nothing. Dropped only when this
        # function is what emptied it; a `Sources:` line it never touched belongs to
        # `strip_source_footer`, which has its own rules for judging one.
        if removed and "](" not in cleaned:
            label = _LABEL_LINE.match(cleaned)
            if label or not re.search(r"[A-Za-z0-9]", cleaned):
                continue
        out.append(cleaned)

    return "\n".join(out)


def _clean_line(line: str, corpus: Corpus) -> tuple[str, bool]:
    """One line with its resolvable bare references removed, and whether any were.

    Cuts are collected first and applied last, right to left, so each one is spliced
    against the offsets it was measured at. Every judgement below is about markdown
    *structure* rather than text, because the first version of this read the line as
    prose and took a working link apart: `[docs/x.md#y](docs/x.md#y)` lost its label and
    left the reader `(docs/x.md#y)`, bare, in the middle of a sentence.
    """
    spans = _spans(_CODE_SPAN, line)
    cuts: list[tuple[int, int]] = []

    for match in _REFERENCE_TOKEN.finditer(line):
        start, end = match.span()
        if _inside(start, spans):
            continue
        if resolve(match.group(0), corpus) is None:
            continue
        # `](path)` — the target half of a working citation, and the one thing here that
        # must survive untouched.
        if line[:start].endswith("]("):
            continue

        group = _enclosing_brackets(line, start, end)
        if group is None:
            cuts.append(_with_wrapper(line, start, end))
            continue

        opened, closed = group
        if line[closed : closed + 1] == "(":
            # A link *label*. Strip the identifier out of it — `[FAQs (web/faqs.txt#1)]`
            # should read `[FAQs]` — but never empty it, because a label with nothing in
            # it is a link the reader cannot see or click. When the label is *only* the
            # identifier there is nothing to keep, so the link is left as it stands and
            # `fix_links` gets to render it.
            cut = _with_wrapper(line, start, end)
            remainder = line[opened + 1 : cut[0]] + line[cut[1] : closed - 1]
            if re.search(r"[A-Za-z0-9]", remainder):
                cuts.append(cut)
            continue

        # A bracketed group that is not a link and contains an identifier: a citation
        # the model got wrong, whole. Removing only the identifier is what produced
        # `[Python #Distributions]` out of `[Python (docs/…/python.md)#Distributions]` —
        # the title kept, the link never made, the fragment stranded.
        cuts.append((opened, closed))

    if not cuts:
        return line, False

    cleaned = line
    for begin, finish in sorted(set(cuts), reverse=True):
        cleaned = _cut(cleaned, begin, finish)
    return cleaned, True


def _with_wrapper(line: str, start: int, end: int) -> tuple[int, int]:
    """The span to cut, widened over a wrapping pair that holds this and nothing else."""
    opener = line[start - 1] if start else ""
    if opener in _WRAPPED and line[end : end + 1] == _WRAPPED[opener]:
        return start - 1, end + 1
    return start, end


def _enclosing_brackets(line: str, start: int, end: int) -> tuple[int, int] | None:
    """The `[…]` this span sits inside, if any. Flat, which is what models write."""
    opened = line.rfind("[", 0, start)
    if opened == -1:
        return None
    closed = line.find("]", end)
    if closed == -1:
        return None
    if "]" in line[opened:start] or "[" in line[end:closed]:
        return None
    return opened, closed + 1


def _cut(line: str, start: int, end: int) -> str:
    r"""Remove `line[start:end]` and close the hole, touching nothing else on the line.

    This replaces a `_tidy` that ran line-wide regular expressions over the result, and
    the difference is the whole point. `\s+([,.;:!?])` does not know which comma the
    removal was near, so it closed a gap three clauses away and turned `Submitting a
    .sbatch script` into `Submitting a.sbatch script`; `[ \t]{2,}` flattened a
    three-space markdown indent on any line that happened to contain a citation. Both
    were edits nobody asked for, in answers the reader was about to read.
    """
    before, after = line[:start], line[end:]
    # A wrapper the cut has just emptied — `()`, `[]`, `{}`, `【】`.
    if before and after and _WRAPPED.get(before[-1]) == after[:1]:
        before, after = before[:-1], after[1:]
    # Leading indentation is structure in markdown, so a hole at the start of a line
    # closes up to it and no further.
    left = before if not before.strip() else before.rstrip()
    right = after.lstrip()
    spaced = bool(re.match(r"\s", before[-1:] or "x") or re.match(r"\s", after[:1] or "x"))
    if not left or not right or right[0] in ",.;:!?)]}":
        joiner = ""
    else:
        joiner = " " if spaced else ""
    return left + joiner + right


def strip_inline_citations(text: str, sources: list[dict] | None = None) -> str:
    """Drop parenthetical asides that only name sections the strip already lists.

    Left alone when the brackets contain a real markdown link: `([Batch jobs](path))`
    is the citation form the system prompt asks for, it gives the reader something to
    click, and removing it would delete the only pointer at the claim's source.
    """
    if not text or not sources:
        return text
    names = _source_names(sources)
    if not names:
        return text

    def cited(part: str) -> bool:
        name = _norm_title(part)
        # "see Batch jobs" cites the same section "Batch jobs" does.
        while name:
            first, _, rest = name.partition(" ")
            if first in _CITE_LEAD and rest:
                name = rest
                continue
            break
        return name in names

    def replace(match: re.Match[str]) -> str:
        inner = match.group(1)
        if "](" in inner:
            return match.group(0)
        for pattern in _PAREN_SPLITS:
            parts = (
                [inner] if pattern is None
                else [part for part in pattern.split(inner) if part.strip()]
            )
            if parts and all(cited(part) for part in parts):
                return ""
        return match.group(0)

    return _PAREN.sub(replace, text)


def _interior_footer(
    lines: list[str], corpus: Corpus, sources: list[dict], names: set[str]
) -> tuple[int, int] | None:
    """A labelled citation list with the answer continuing underneath it.

    Everything above judges a *trailing* footer, and a model that carries on afterwards
    escapes all of it. Measured across 98 live turns, two answers ended with a
    `**Citations:**` block and then one more sentence, and one of them listed the same two
    sections the Sources strip printed three lines below — the duplicate list this module
    exists to prevent, arriving in a position it could not see.

    Cutting inside an answer is more dangerous than cutting off its end, so the bar is the
    strongest evidence available rather than the shape rules: **every line of the block
    must carry a link, and every one of those links must resolve to a page the strip is
    already showing.** No proof, no cut. That is deliberately narrower than the trailing
    rules — the other surviving case is a `**Citations**` heading over two prose sentences
    summarising what each source says, which is content, and it is left exactly where it
    is.

    Returns the half-open span to remove, including a `---` the model fenced the block off
    with, or None.
    """
    shown = {
        str(item.get("url", "")).split("#", 1)[0]
        for item in sources
        if item.get("url")
    }
    if not shown:
        return None

    for index, line in enumerate(lines):
        payload = _footer_label(line)
        if payload is None:
            continue
        if payload and not _is_citation_payload(payload, names):
            continue
        stop = index
        proven = False
        for position in range(index + 1, len(lines)):
            if not lines[position].strip():
                break        # the block ends at the blank line
            pages = _pages(lines[position], corpus)
            if not pages or not pages <= shown:
                proven = False
                break
            proven = True
            stop = position
        if not proven or stop == index:
            continue
        # Nothing but blank lines after it means this is the trailing shape, which the
        # rules above own; leaving it to them keeps one decision in one place.
        if not any(item.strip() for item in lines[stop + 1:]):
            continue
        start = index
        while start - 1 >= 0 and (
            not lines[start - 1].strip() or _RULE.match(lines[start - 1])
        ):
            start -= 1
        return start, stop
    return None


def strip_source_footer(
    text: str, corpus: Corpus | None = None, sources: list[dict] | None = None
) -> str:
    """Remove a trailing citation list the model wrote for itself.

    Every answer already gets a Sources strip built from the chunks that were
    actually retrieved, so a model that also signs off with `Sources: A, B` prints
    the same citations twice, three lines apart. The system prompt asks for inline
    links and no footer; across nine models that holds on most turns and not all of
    them, so the footer comes off here too.

    Two shapes, deliberately judged by different evidence:

    * **Labelled** — `Sources:`, `**References:**`, `## Citations`. The label is the
      model declaring what the block is, and what follows it has to read as a list of
      references — or be, provably, names the strip is already showing. The label
      alone was evidence enough until `Citation: please reference the University of
      Chicago's Research Computing Center.` turned up, which is not a footer, it is
      the answer to "how do I acknowledge RCC in a paper".
    * **Unlabelled** — a bare paragraph of nothing but links. This is what asking for
      no "Sources" list actually produced: the label went and the links stayed, which
      is the same duplication with no word to match on. Shape alone is too thin here —
      an answer could legitimately end on a list of links — so this one comes off only
      when `sources` proves every link is a page the strip below already shows.

    Passing no `corpus`/`sources` leaves the unlabelled shape alone, since nothing can
    be proven about it. Passing an empty `sources` list means the app is drawing no
    strip at all, and then the footer is the only citation there is and stays put.
    """
    if not text or not text.strip():
        return text
    if sources is not None and not sources:
        return text

    lines = text.splitlines()
    last = len(lines) - 1
    while last >= 0 and not lines[last].strip():
        last -= 1

    # What the strip is showing, when the caller told us. A part of a footer that
    # matches one of these is provably a duplicate, whatever its punctuation — which
    # is what recovers `Sources: Storage.`, a real footer the shape rules decline to
    # judge because one capitalised word and a full stop is also how a sentence looks.
    names = _source_names(sources or [], floor=1)

    cut = None
    payload = _footer_label(lines[last])
    if payload is not None:
        # The label is on the last line, so whatever sits after it is the whole
        # footer and the decision is about that payload alone. An empty one — `##
        # Sources` with nothing under it — is a label the model left dangling.
        if payload == "" or _is_citation_payload(payload, names):
            cut = last
    else:
        # Otherwise the list is underneath a label of its own. Only the last such
        # label is considered — scanning further back to find a block that happens
        # to look like citations is how a strip like this eats half an answer.
        for idx in range(last, -1, -1):
            found = _footer_label(lines[idx])
            if found is None:
                continue
            if (found == "" or _is_citation_payload(found, names)) and all(
                _is_citation_line(line, names) for line in lines[idx + 1 : last + 1]
            ):
                cut = idx
            break

    if cut is None and corpus is not None and sources:
        shown = {
            str(item.get("url", "")).split("#", 1)[0]
            for item in sources
            if item.get("url")
        }

        def citation_sentence(line: str) -> bool:
            """A sentence whose only content is "these came from here".

            Every word outside the links has to be scaffolding, and at least one has to
            say the line is a citation. That is what separates `Cited from A and B.`
            from `For full details, see A and B.`, which is an answer pointing somewhere
            and keeps its `details`.
            """
            without_links = _MARKDOWN_LINK.sub(" ", line)
            words = [word.lower() for word in _WORDS.findall(without_links)]
            if not words or not any(word in _CITE_SIGNAL for word in words):
                return False
            return all(word in _CITE_SCAFFOLD for word in words)

        def duplicate(line: str) -> bool:
            """Links the strip is already showing, and nothing else worth keeping."""
            if not (_ONLY_LINKS.match(line) or citation_sentence(line)):
                return False
            pages = _pages(line, corpus)
            return bool(pages) and pages <= shown

        # The whole run, not just the last line of it. Taking one line off the end of
        # a bulleted list leaves a half-eaten list, which is worse than the duplicate.
        begin = last + 1
        while begin - 1 >= 0 and duplicate(lines[begin - 1]):
            begin -= 1
        if begin <= last and begin > 0:
            # Unless a sentence introduces it. "Here is what the docs cover:" followed
            # by links is an answer *made* of links, and cutting them leaves the colon
            # pointing at nothing; a footer is never introduced, it is just appended.
            above = next(
                (line for line in reversed(lines[:begin]) if line.strip()), ""
            )
            if not above.rstrip().endswith(":"):
                cut = begin

    if cut is None and corpus is not None and sources:
        interior = _interior_footer(lines, corpus, sources, names)
        if interior is not None:
            start, stop = interior
            kept = lines[:start] + lines[stop + 1 :]
            if any(line.strip() for line in kept):
                return "\n".join(kept)

    if cut is None:
        return text

    kept = lines[:cut] + lines[last + 1 :]
    # Models fence the footer off with a rule; without the footer it leads nowhere.
    while kept and (not kept[-1].strip() or _RULE.match(kept[-1])):
        kept.pop()
    # An answer that was *only* a footer is a failure of the model, not something to
    # blank out: a duplicate Sources strip beats an empty bubble.
    if not any(line.strip() for line in kept):
        return text
    return "\n".join(kept)


# --- inline markers ---------------------------------------------------------

# The marker a sentence gets when it rests on a retrieved section: that section's
# number in the strip below, small and dimmed, linked where the strip links.
#
# Streamlit's own `:small[]` and `:gray[]` directives rather than a span of HTML.
# Rendering an answer with `unsafe_allow_html` would let anything the model emits —
# or anything an uploaded file talked it into emitting — reach the page as markup,
# and escaping the answer first would break every code sample containing a `<`, which
# in this corpus is most of them.
_MARKER = ":small[:gray[[{number}]({url})]]"

# A sentence ends at one of these followed by space or nothing. Any closing quote or
# bracket goes with it, so a marker lands outside the quotation rather than inside.
_SENTENCE_END = re.compile(r"[.!?][\"'’”)\]]*(?=\s|$)")
_CODE_SPAN = re.compile(r"`[^`]*`")


def _numbering(sources: list[dict]) -> dict[str, int]:
    """URL -> its position in the strip, by exact link and by page.

    Both, because the two come apart: the strip shows one entry per destination, and
    a model may cite `…/faq/#one-section` where the strip lists `…/faq/#another`. The
    page is the same page and the number is the same number, so an exact match wins
    and the page is the fallback.
    """
    numbers: dict[str, int] = {}
    for index, source in enumerate(sources, start=1):
        url = str(source.get("url", ""))
        if not url:
            continue
        numbers.setdefault(url, index)
        numbers.setdefault(url.split("#", 1)[0], index)
    return numbers


def _number_for(url: str, numbers: dict[str, int]) -> int | None:
    return numbers.get(url) or numbers.get(url.split("#", 1)[0])


def _spans(pattern, line: str) -> list[tuple[int, int]]:
    return [match.span() for match in pattern.finditer(line)]


def _inside(position: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in spans)


def _mark_line(line: str, numbers: dict[str, int]) -> str:
    """Unlink the citations in one line and mark the sentences they belong to."""
    code = _spans(_CODE_SPAN, line)
    out: list[str] = []
    pending: list[tuple[int, int]] = []   # (position in `out` text, number)
    cursor = 0
    length = 0

    for match in _MARKDOWN_LINK.finditer(line):
        if _inside(match.start(), code):
            continue
        number = _number_for(match.group(2), numbers)
        if number is None:
            continue                      # not a retrieved section: leave it linked
        label = match.group(1)
        out.append(line[cursor : match.start()])
        length += match.start() - cursor
        out.append(label)
        length += len(label)
        pending.append((length, number))
        cursor = match.end()

    if not pending:
        return line
    out.append(line[cursor:])
    plain = "".join(out)

    # Each citation attaches to the end of the sentence it sits in, which is where a
    # reader looks for one — not mid-clause, where the model happened to put the link.
    # Sentences are found in the unlinked text, so a URL's own full stops cannot be
    # mistaken for one.
    plain_code = _spans(_CODE_SPAN, plain)
    placed: dict[int, list[int]] = {}
    for position, number in pending:
        end = len(plain)
        for match in _SENTENCE_END.finditer(plain):
            if match.end() >= position and not _inside(match.start(), plain_code):
                end = match.end()
                break
        placed.setdefault(end, [])
        if number not in placed[end]:
            placed[end].append(number)

    result: list[str] = []
    last = 0
    for at in sorted(placed):
        result.append(plain[last:at])
        result.append(
            "".join(
                _MARKER.format(number=number, url=_url_of(number, numbers))
                for number in placed[at]
            )
        )
        last = at
    result.append(plain[last:])
    return "".join(result)


def _url_of(number: int, numbers: dict[str, int]) -> str:
    """The longest URL recorded for a number — the one with its anchor still on."""
    found = [url for url, value in numbers.items() if value == number]
    return max(found, key=len) if found else ""



# --- attributing a sentence the model did not link -------------------------
#
# Markers built from the model's own links are exact, and they are also occasional:
# asked the same question twice, `nemotron-3.5-lightning` linked two sections on one
# run and none on the next. An answer's citations should not depend on which way a
# free model felt on a Tuesday.
#
# So a sentence the model left unlinked is attributed from what the turn actually
# read — but only when the turn read ONE section, and that restriction is the whole
# of the design.
#
# With one section there is no wrong answer available: the answer was built from it
# and nothing else, so a sentence that draws on the documentation draws on that. With
# two, picking between them is a guess, and measured on the real corpus it is a
# biased one — asked how to submit a batch job, the turn read a 422-character section
# on submitting and a 4151-character section on script contents, and simple word
# overlap handed almost every sentence to the longer one because a longer section
# owns more words. That is a plausible wrong citation, which spends exactly the trust
# the Sources strip exists to earn.
#
# For the multi-section case the citation has to come from the model, which knows
# what it used. `prompts` asks for it; where it arrives, `_mark_line` above is exact.

_WORD_TOKEN = re.compile(r"[a-z0-9][a-z0-9_.:/=+-]{2,}")
# Words that discriminate nothing: they are in every section of any corpus.
_STOPWORDS = frozenset({
    "the", "and", "for", "you", "your", "with", "that", "this", "from", "are", "can",
    "will", "not", "use", "used", "using", "run", "runs", "have", "has", "was", "all",
    "any", "its", "it's", "each", "when", "then", "than", "how", "what", "which",
    "want", "need", "must", "should", "also", "see", "one", "two", "more", "most",
    "some", "our", "out", "get", "set", "add", "may", "but", "there", "their", "them",
    "these", "those", "into", "onto", "over", "under", "before", "after", "here",
})
# How many distinctive words a sentence has to share with a section before it is
# marked as resting on it. One is a coincidence — every answer about Slurm says
# "sbatch" — and three is so strict that only a quotation clears it.
_MIN_EVIDENCE = 2


def _words(text: str) -> set[str]:
    return {
        word for word in _WORD_TOKEN.findall(text.lower())
        if word not in _STOPWORDS
    }


def _distinctive(evidence: dict[str, str], sources: list[dict]) -> dict[int, set]:
    """The words that belong to one read section and to none of the others.

    Sections read in the same turn are about the same question and share most of
    their vocabulary; what is left after the overlap is removed is the part that can
    tell them apart. With only one section read there is nothing to be told apart
    from, and every word of it counts — there is no wrong answer to pick.
    """
    # Keyed by the chunk id the strip carries, not by URL: two sections of one page
    # share a URL and are one entry, and their text is the same entry's evidence.
    of_id = {str(source.get("id", "")): index
             for index, source in enumerate(sources, start=1)}
    by_number: dict[int, set[str]] = {}
    for identifier, body in evidence.items():
        number = of_id.get(identifier)
        if number is None:
            continue
        by_number.setdefault(number, set()).update(_words(body))
    if len(by_number) < 2:
        return by_number
    return {
        number: words - set().union(*(
            other for key, other in by_number.items() if key != number
        ))
        for number, words in by_number.items()
    }


def _attribute(sentence: str, distinctive: dict[int, set]) -> int | None:
    """The one section this sentence is about, or None if that is not clear."""
    words = _words(sentence)
    scores = sorted(
        ((len(words & terms), number) for number, terms in distinctive.items()),
        reverse=True,
    )
    return scores[0][1] if scores and scores[0][0] >= _MIN_EVIDENCE else None


def _attribute_line(line: str, distinctive: dict[int, set],
                    numbers: dict[str, int]) -> str:
    """Mark the last sentence of a paragraph that rests on one section.

    One marker per paragraph rather than per sentence: a paragraph drawn from a
    single section would otherwise carry the same number on every line of it, which
    is not attribution, it is decoration.
    """
    ends = [match.end() for match in _SENTENCE_END.finditer(line)]
    if not ends:
        return line
    start = 0
    best: tuple[int, int] | None = None
    for end in ends:
        number = _attribute(line[start:end], distinctive)
        if number is not None:
            best = (end, number)
        start = end
    if best is None:
        return line
    at, number = best
    return line[:at] + _MARKER.format(number=number, url=_url_of(number, numbers)) + line[at:]


def mark_sources(
    text: str,
    sources: list[dict] | None,
    evidence: dict[str, str] | None = None,
) -> str:
    """Put a small numbered marker at the end of every sentence that cites a source.

    The Sources strip under an answer says what the whole answer rests on. It cannot
    say which sentence rests on which, and that is the question a reader asks of any
    particular claim. A marker where the claim is answers it, and clicking it opens
    the same page the strip's entry opens.

    Two ways a marker arrives, in that order of confidence.

    **The model linked it.** The system prompt asks for `[Section title](path)`
    inline; where one is there, the citation is the model's own and exact. A link the
    strip does not list is left exactly as it is: it resolved to something real, it is
    just not one of the numbered sections, and inventing a number for it would make
    the strip and the answer disagree.

    **The model did not, and `evidence` says what was read.** Asked the same question
    twice, `nemotron-3.5-lightning` linked two sections on one run and none on the
    next, so an answer's citations cannot depend on that. A paragraph with no link of
    its own is attributed to the read section whose distinctive words it uses — and
    to nothing at all when that does not discriminate. See `_attribute`.

    Render-time only. The stored answer keeps its links, because that text goes back
    upstream as history, and a transcript full of `:small[:gray[[1](…)]]` teaches the
    model to write markers instead of citations.
    """
    if not text or not sources:
        return text
    numbers = _numbering(sources)
    if not numbers:
        return text

    # What the one read section is made of, for the sentences the model left
    # unlinked. Empty for a turn that read several: see the note above `_words`.
    distinctive = _distinctive(evidence or {}, sources)
    if len(distinctive) != 1:
        distinctive = {}

    out: list[str] = []
    fenced = False
    for line in text.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
            out.append(line)
            continue
        if fenced:
            out.append(line)
            continue
        marked = _mark_line(line, numbers)
        if distinctive and marked == line and not _skip(line):
            marked = _attribute_line(line, distinctive, numbers)
        out.append(marked)
    return "\n".join(out)


# Lines that are not prose making a claim: a heading names a section, a list bullet
# of one fragment is not a sentence, and a table row is a grid.
_SKIP_LINE = re.compile(r"^\s{0,3}(?:#{1,6}\s|>|\||\s*$)")


def _skip(line: str) -> bool:
    return bool(_SKIP_LINE.match(line))

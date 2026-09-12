"""Turning one file into one document and its indexable chunks.

A reader is `(source, rel_path, raw) -> (Document, [Chunk])`, registered under the
name a source declares. Two ship here — `markdown`, which cuts on headings, and
`scraped`, which windows a page that has none — and a corpus in a third format is a
third function plus a line of TOML.

Chunks are heading-sized rather than file-sized. That is what removes the old
15k-character truncation (which cut 62% of `docs/slurm/sbatch.md`) and what lets a
citation deep-link to the exact section an answer came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .. import config
from ..normalize import (
    collapse_blank_lines,
    normalize_markdown,
    parse_scraped,
    plain_heading,
    pretty_title,
    slugify,
)
from ..profile import Source
from ..registry import Registry
from . import urls
from .model import Chunk, Document

_HEADING = re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<text>\S.*?)[ \t]*#*$")
_FENCE = re.compile(r"^[ \t]*(?P<ticks>`{3,}|~{3,})")

# (source, rel_path, raw) -> (Document, [Chunk])
readers: Registry = Registry("reader")


# --- markdown --------------------------------------------------------------


@dataclass
class _Section:
    level: int
    heading: str
    trail: list[str]
    #: The heading line exactly as the file wrote it, before `plain_heading` tidied it.
    #:
    #: Kept because one thing in a heading is not decoration: an attr_list id,
    #: `## Using renv {#using-the-renv}`, which mkdocs publishes verbatim. `slugify`
    #: reads it and `plain_heading` strips it, so handing the cleaned title to `slugify`
    #: — which is what happened — meant the marker was gone before anything could act on
    #: it and the citation pointed at a derived anchor the page does not have.
    raw_heading: str = ""
    lines: list[str] = field(default_factory=list)

    @property
    def body(self) -> str:
        return collapse_blank_lines("\n".join(self.lines))


def _split_sections(text: str) -> list[_Section]:
    """Break normalized markdown at headings, tracking the ancestor trail."""
    sections = [_Section(level=0, heading="", trail=[])]
    stack: list[tuple[int, str]] = []
    fence: str | None = None

    for line in text.splitlines():
        match = _FENCE.match(line)
        if fence:
            if match and match.group("ticks")[0] == fence:
                fence = None
            sections[-1].lines.append(line)
            continue
        if match:
            fence = match.group("ticks")[0]
            sections[-1].lines.append(line)
            continue

        heading = _HEADING.match(line)
        if not heading:
            sections[-1].lines.append(line)
            continue

        level = len(heading.group("hashes"))
        title = plain_heading(heading.group("text"))
        while stack and stack[-1][0] >= level:
            stack.pop()
        sections.append(
            _Section(level=level, heading=title, raw_heading=heading.group("text"),
                     trail=[name for _, name in stack])
        )
        stack.append((level, title))

    return sections


def _document_title(sections: list[_Section]) -> str:
    """The page's H1, which is the title mkdocs publishes it under.

    Any heading used to do, taken from a 40-line window. Five pages in the guide have no
    H1, so each was named after whichever subsection came first: the R page was cited as
    "Table of Contents", `software/index.md` as "Private Software", and
    `tutorials/sde3/data-transfer.md` as "Step 1. From Data Provider to SDE Virtual
    Desktop" — a name that page also carries as a real section, so its citation and its
    own Related entry read identically while linking to two different places.

    The window was what kept a code comment out of the title, not a rule: the R page has
    five `# Install renv …` lines inside an R fence, 274 lines down. Reading the split
    sections rather than raw lines is fence-aware for free, so the H1 looked for here is
    always a real one wherever it sits, and a page without one falls back to its path.
    """
    return next(
        (item.heading for item in sections if item.level == 1 and item.heading), ""
    )


def _split_oversized(body: str, limit: int) -> list[str]:
    """Break a long section on paragraph boundaries, never inside a fence."""
    if len(body) <= limit:
        return [body]

    blocks: list[str] = []
    current: list[str] = []
    fence: str | None = None

    for line in body.splitlines():
        match = _FENCE.match(line)
        if fence:
            current.append(line)
            if match and match.group("ticks")[0] == fence:
                fence = None
            continue
        if match:
            fence = match.group("ticks")[0]
            current.append(line)
            continue
        if not line.strip() and not fence:
            blocks.append("\n".join(current))
            current = []
            continue
        current.append(line)
    blocks.append("\n".join(current))

    parts: list[str] = []
    buffer = ""
    for block in blocks:
        candidate = f"{buffer}\n\n{block}" if buffer else block
        if len(candidate) > limit and buffer:
            parts.append(buffer)
            buffer = block
        else:
            buffer = candidate
    if buffer.strip():
        parts.append(buffer)
    kept = [part for part in parts if part.strip()]
    return [piece for part in kept for piece in _hard_split(part, limit)]


def _hard_split(part: str, limit: int) -> list[str]:
    """The last resort: a block with no blank line anywhere in it.

    Splitting on paragraphs cannot bound a block that contains no paragraph break, and
    such a block was returned whole however long it was — one unbroken 100 KB line became
    one 100 KB chunk against a 6 000 limit. No page in the bundled corpus does that, so
    this never fires here; a scrape is one HTML-to-text pass away from doing it, and
    `gather_context` puts whole chunk texts in a system message that `history.build` has
    already finished trimming, so nothing downstream would have caught it.

    A line break is preferred, then a space, then the limit itself. The docstring above
    promises never to cut inside a fence and this may have to — an unbalanced fence in a
    retrieval chunk is text the model reads, where an unbounded one is a request that
    cannot be sent at all.
    """
    if len(part) <= limit:
        return [part]
    pieces: list[str] = []
    while len(part) > limit:
        cut = part.rfind("\n", 0, limit)
        if cut <= limit // 2:
            cut = part.rfind(" ", 0, limit)
        if cut <= limit // 2:
            cut = limit
        pieces.append(part[:cut])
        part = part[cut:].lstrip("\n")
    if part.strip():
        pieces.append(part)
    return pieces


def read_markdown(
    source: Source, rel_path: str, raw: str
) -> tuple[Document, list[Chunk]]:
    text = normalize_markdown(raw)
    sections = _split_sections(text)
    doc_title = _document_title(sections) or pretty_title(rel_path)
    document = Document(
        source=source.name,
        path=rel_path,
        title=doc_title,
        url=urls.build(source, rel_path),
        text=text,
    )

    chunks: list[Chunk] = []
    seen_anchors: dict[str, int] = {}
    # Occurrences of each heading SLUG, which is not what `seen_anchors` counts: that
    # one numbers chunk ids and so also counts the parts an oversized section is split
    # into. This counts headings, because it is reproducing what the site does to them.
    #
    # mkdocs runs Python-Markdown's `toc.unique`, so a heading repeated on one page
    # publishes at `slug`, `slug_1`, `slug_2` — and every chunk here used to cite the
    # bare slug. Measured on `software/apps-and-envs/alphafold.md`, which carries
    # `AlphaFold 2` and `AlphaFold 3` three times each: six chunks pointing at two
    # anchors, so FOUR sections of that page were unreachable from any citation and two
    # citations landed the reader at the first occurrence of the right name. Invisible
    # to an anchor check that only asks whether the anchor exists, because it does.
    heading_anchors: dict[str, int] = {}

    for section in sections:
        body = section.body
        if section.heading:
            indent = "  " * max(section.level - 1, 0)
            document.outline.append(f"{indent}- {section.heading}")
        if not body.strip():
            continue
        if not section.heading and len(body) < config.MIN_CHUNK_CHARS:
            continue

        # From the RAW heading, so an explicit `{#id}` is still there to be read.
        anchor = slugify(section.raw_heading or section.heading) if section.heading else ""
        # The anchor as the SITE publishes it. Counted per heading rather than per
        # chunk, so every part of one oversized section cites the one heading it is
        # under — which is what the reader wants from a citation and what the page
        # actually offers.
        if anchor:
            nth = heading_anchors.get(anchor, 0)
            heading_anchors[anchor] = nth + 1
            published = anchor if nth == 0 else f"{anchor}_{nth}"
        else:
            published = ""
        trail: list[str] = []
        for part in (doc_title, *section.trail, section.heading):
            # The page H1 usually repeats as the first section heading.
            if part and (not trail or trail[-1] != part):
                trail.append(part)
        breadcrumb = " › ".join(trail)

        for index, part in enumerate(_split_oversized(body, config.MAX_CHUNK_CHARS)):
            base = anchor or "intro"
            seen = seen_anchors.get(base, 0)
            seen_anchors[base] = seen + 1
            suffix = base if seen == 0 and index == 0 else f"{base}-{seen}"
            heading_text = section.heading or doc_title
            chunks.append(
                Chunk(
                    id=f"{source.name}/{rel_path}#{suffix}",
                    source=source.name,
                    path=rel_path,
                    doc_title=doc_title,
                    heading=heading_text,
                    breadcrumb=breadcrumb or doc_title,
                    text=part,
                    url=urls.build(source, rel_path, published),
                )
            )

    return document, chunks


# --- scraped pages ---------------------------------------------------------


def read_scraped(
    source: Source, rel_path: str, raw: str
) -> tuple[Document, list[Chunk]]:
    """Scraped pages have no heading structure, so window them by paragraph."""
    page_url, title, body = parse_scraped(raw)
    doc_title = title or pretty_title(rel_path)
    document = Document(
        source=source.name,
        path=rel_path,
        title=doc_title,
        url=urls.build(source, rel_path, page_url=page_url),
        text=body,
    )

    paragraphs = [line.strip() for line in body.splitlines() if line.strip()]
    windows: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        candidate = f"{buffer}\n\n{paragraph}" if buffer else paragraph
        if len(candidate) > config.WEB_CHUNK_CHARS and buffer:
            windows.append(buffer)
            tail = buffer[-config.WEB_CHUNK_OVERLAP :]
            buffer = f"{tail}\n\n{paragraph}" if config.WEB_CHUNK_OVERLAP else paragraph
        else:
            buffer = candidate
    if buffer.strip():
        windows.append(buffer)

    # The same bound the heading-split reader needs, for the same reason and by the same
    # helper: a paragraph longer than the window is never cut by the loop above, because
    # the `and buffer` guard means an oversized paragraph arriving on an empty buffer is
    # simply kept. One unbroken line became one 100 KB window against a 2 400 cap.
    #
    # It matters more here than there. This source is machine-generated: `refresh-docs.sh`
    # re-scrapes the site, and one HTML-to-text pass that emits a page without paragraph
    # breaks — a flattened table, a minified block — produces exactly that page. Nothing
    # downstream would bound it either, since `gather_context` puts whole chunk texts into
    # a system message that `history.build` has already finished trimming.
    #
    # Inert on the bundled scrape: 83 windows, the largest 2 399 characters.
    windows = [
        piece
        for window in windows
        for piece in _hard_split(window, config.WEB_CHUNK_CHARS)
    ]

    chunks = [
        Chunk(
            id=f"{source.name}/{rel_path}#{index + 1}",
            source=source.name,
            path=rel_path,
            doc_title=doc_title,
            # The page title, for every window. `(part 3)` used to go here, and it was
            # the index's private arithmetic wearing a section heading's clothes: a
            # scraped page has no headings to cut on, so window 3 is not a section
            # called "part 3", it is the same page cut at 2400 characters — and it
            # carries the same URL, because there is no anchor to deep-link to either.
            # The reader saw the cut and could not act on it, since `Our Team — Our
            # Team (part 3)` in the Sources strip and `Our Team (part 3)` under Related
            # both land exactly where plain `Our Team` lands. The window number is kept
            # where it is needed and nowhere else: in the id, which is what `read_doc`
            # takes to fetch one window in full.
            heading=doc_title,
            breadcrumb=doc_title,
            text=window,
            url=document.url,
        )
        for index, window in enumerate(windows)
        if len(window) >= config.MIN_CHUNK_CHARS or index == 0
    ]
    return document, chunks


readers.register("markdown", read_markdown)
readers.register("scraped", read_scraped)


def probe_url(source: Source, raw: str) -> str:
    """The URL a file claims for itself, before it is worth chunking it.

    Only the scraped reader records one, and the host-exclusion rule needs it before
    the reader runs. Asking the reader for it would mean parsing every excluded page
    in full to find out it should be skipped.
    """
    if source.reader != "scraped":
        return ""
    url, _title, _body = parse_scraped(raw)
    return url


def read(source: Source, rel_path: str, raw: str) -> tuple[Document, list[Chunk]]:
    return readers.get(source.reader)(source, rel_path, raw)

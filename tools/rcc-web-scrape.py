#!/usr/bin/env python3
"""Refresh Sage's scraped `web/` corpus from the RCC websites, one listed page at a time.

    python tools/rcc-web-scrape.py web                      # update web/ in place
    python tools/rcc-web-scrape.py web --summary run.json   # and record what happened

`refresh-docs.sh --scrape` runs this, and `.github/workflows/refresh-corpus.yml` runs
that every week. The output is what `sage/corpus/readers.py` (`read_scraped`) reads: a
`URL:` line, a `Title:` line, a rule of 80 `=`, then the page's text.

This used to be a crawler: start at the home page, follow every link, keep whatever
looked useful, with TLS verification switched off. Now nothing is fetched that
`web_pages.toml` does not name and no link is ever followed, so a redirect loop or a
crawler trap cannot happen by construction, and the corpus cannot grow by itself.
Sitemap pages that are not on the list are reported as "available, not included".

A listed page is fetched when its sitemap `<lastmod>` changed, when it has none (the
four subdomains publish no sitemap at all, so their pages are fetched every run), when
it is new to the list, when it failed last run, or when its file is missing or no
longer matches the hash recorded for it. Everything else is left alone. That state
lives in `web_manifest.json`, outside `web/`, so the corpus reader never sees it; with
no manifest yet, every listed page is new.

What a fetch can come to:

* A 404 or 410, or a soft 404 (a 200 whose title or opening line says the page was not
  found, or whose text is under 200 characters where the copy held had more, or is
  new, or is blank): a failure. The file is kept, and removed on the second failed run
  in a row. A page that has always been that short stays a page when it changes.
* A timeout or a 5xx: retried twice with growing waits, then a failure. The file is
  kept however long that lasts, because a server having a bad week is not a page gone.
* A redirect: followed by hand, at most five hops, so robots.txt and the crawl delay
  apply to every hop and the final URL can be recorded. Two listed URLs that land on
  one page keep one file. A redirect off the listed hosts is a failure, not content.

A page that leaves the sitemap is removed, and so is any file in `web/` whose URL is
not on the list or is denied in it.

The circuit breaker: if more than 10% of this run's fetches fail, or the total text in
`web/` would shrink by more than 20%, nothing is written (neither `web/` nor the
manifest) and the exit status is 3, with the reason printed. So does a sitemap that
cannot be read, and a run that outlives its time budget. A site outage or a redesign
must never replace a good snapshot. A page that already failed last run is not counted
again, or the breaker would block the second run the two-run rule needs.

Polite by construction: robots.txt is read for each host and obeyed, Disallow and
Crawl-delay both (rcc.uchicago.edu asks for 10 seconds, and a host that names no delay
gets the same), and every request carries a User-Agent that says who is asking.

Exit status: 0 done, with or without changes; 1 the configuration or the manifest
cannot be used; 3 refused to write.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import unquote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
import tomllib
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

USER_AGENT = "Sage-corpus-refresh/1.0 (+https://github.com/PursuitOfDataScience/sage)"
TIMEOUT = 20                 # seconds, per request
RETRY_WAITS = (10.0, 30.0)   # two retries on a timeout or a 5xx, each waiting longer
MAX_REDIRECTS = 5
MIN_DELAY = 10.0             # seconds between two requests to one host, at the least
MIN_TEXT = 200               # characters of text under which a 200 is a soft 404
DEAD_RUNS = 2                # failed runs in a row before a dead page's file goes
MAX_FAILED = 0.10            # the breaker: the share of this run's fetches that may fail
MAX_SHRINK = 0.20            # and the share of web/'s text a run may take away
BUDGET = 20 * 60             # seconds; the workflow's job has 30 minutes in all
MAX_SITEMAPS = 20            # documents, counting the children of a sitemap index

RULE = "=" * 80
BLOCKED = "disallowed by robots.txt"
OFF_SITE = "redirected off the listed hosts"
FAILED_KINDS = ("dead", "transient")
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_RETRY_ERRORS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
)


# --- text extraction ---------------------------------------------------------------
#
# Built so that a page fetched again comes out byte for byte as the bundled file it
# replaces, which keeps a refresh's diff to real content changes. That meant matching
# the files, not the crawler they were thought to come from.
#
# The crawler at /home/youzhi/LLM-API/rcc-web-scrape.py (2025-12-26 15:31) is not the
# version that wrote the bundle (copied in at 15:05 the same day): run over the 55
# pages as served on 2026-10-05, its extraction reproduced 2 of the 55 files. These
# rules were recovered from the bundle itself, each one kept only because removing it
# loses matches, and together they reproduce 44 of the 55. The other 11 differ in
# their words, because those pages changed (one, the excluded publication list, by a
# single line break as well). Departures from that crawler:
#
#   * the title keeps its site suffix, and each line of a two-line title is stripped;
#   * an em dash becomes "--", a bullet "*", and a minus sign "-";
#   * menus that are not <nav> (role="navigation") are dropped, and their labels count
#     as already seen, so a menu label repeated in the text is dropped too;
#   * the Drupal page title (#page-title) is dropped;
#   * a line is a duplicate only if it matches before Unicode is normalized;
#   * a lowercase continuation is joined with a space, a line starting "http" can be
#     joined, and after the crawler's rules a second pass joins any line of 80 or more
#     characters that ends in a letter to the line after it, with a space;
#   * `render` writes no blank line after the rule and no newline at the end.
#
# Two of these keep flaws the bundle has, on purpose: a menu label inside a sentence
# goes ("support for and data sharing"), and a line that starts with a capitalized
# acronym is joined without a space ("TheRCC"). Fixing either is a deliberate rewrite
# of most of web/, not something a weekly refresh should do on its own.

# Navigation and boilerplate patterns to remove (exact line matches)
REMOVE_LINES = {
    "Skip to main content",
    "Skip to internal navigation",
    "Request Account",
    "User Guide",
    "Contact Us",
    "Accounts & Allocations",
    "Resources",
    "Grants & Publications",
    "Support & Services",
    "About RCC",
    "Section Navigation",
    "navigateright",
    "Get an Account",
    "Get Support",
    "Primary tabs",
    "View",
    "(active tab)",
    "What links here",
    "previous",
    "next",
    # Common navigation items
    "Director's Welcome",
    "Our Team",
    "Vision & Mission",
    "News & Features",
    "Calendar",
    "Committees",
    "Location & Directions",
    "RCC User Policy",
    "Job Opportunities",
    # Support & Services section nav
    "Cluster Partnership Program",
    "Consultant Partnership Program",
    "New Faculty Program",
    "Workshops and Training",
    "Data Sharing Services",
    "Data Management",
    "Consulting and Technical Support",
    "Outreach",
    # Resources section nav
    "Storage and Backup",
    "Software",
    "Visualization",
    "Networking",
    "Hosted Data",
    "Secure Research Environment",
    "Cloud",
    "Quantum",
    "GIS",
    # Grants section nav
    "Acknowledging the RCC",
    "Facilities and Resources Documents",
    "For PI Proposals",
    "Grant Support",
    "Hardware Quotes",
    "List of Publications",
    "Publications",
    "Support Letters",
    # About section nav
    "Advisory Committees",
    "Research Computing Oversight Committee",
}

# Written as code points so this file stays ASCII. The crawler's table, except where
# the bundle shows otherwise: the em dash, the bullet and the minus sign. The crawler
# removed the zero-width space and the bundle kept it; it is removed here, because a
# zero-width space glued to a word makes it a different word to the search index, and
# both bundled pages that held one have changed upstream since.
_UNICODE = {
    chr(0x2018): "'",    # left single quote
    chr(0x2019): "'",    # right single quote
    chr(0x201C): '"',    # left double quote
    chr(0x201D): '"',    # right double quote
    chr(0x2013): "-",    # en dash
    chr(0x2014): "--",   # em dash
    chr(0x2026): "...",  # ellipsis
    chr(0x00A0): " ",    # non-breaking space
    chr(0x200B): "",     # zero-width space
    chr(0x00B7): "-",    # middle dot
    chr(0x2022): "*",    # bullet
    chr(0x2212): "-",    # minus sign
    chr(0x25CF): "-",    # black circle bullet
    chr(0x25CB): "-",    # white circle bullet
    chr(0x25AA): "-",    # small black square
    chr(0x25AB): "-",    # small white square
    chr(0xFEFF): "",     # BOM
}
# A line starting with one of these is never joined to the line before it.
_BULLETS = (chr(0x2022), "-", "*", chr(0x2013), "URL:", "Title:")
LONG_LINE = 80   # the second wrapping pass joins a line at least this long


def normalize_unicode(text: str) -> str:
    """Normalize unicode characters to their ASCII equivalents."""
    for old, new in _UNICODE.items():
        text = text.replace(old, new)
    return text


def is_navigation_line(line: str) -> bool:
    """Check if a line is purely navigation/boilerplate."""
    stripped = line.strip()

    # Check exact matches
    if stripped in REMOVE_LINES:
        return True

    # Check regex patterns
    nav_patterns = [
        r'^navigateright$',
        r'^\(active tab\)$',
        r'^View$',
        r'^next$',
        r'^previous$',
    ]
    return any(re.match(pattern, stripped) for pattern in nav_patterns)


def fix_line_wrapping(text: str) -> str:
    """Fix lines that were incorrectly wrapped mid-word or mid-sentence."""
    lines = text.split('\n')
    result = []
    i = 0

    while i < len(lines):
        current = lines[i].rstrip()

        # Skip empty lines
        if not current:
            result.append('')
            i += 1
            continue

        # Check if we should merge with next line
        while i + 1 < len(lines):
            next_line = lines[i + 1].strip()

            # Don't merge if next line is empty
            if not next_line:
                break

            # Don't merge if current line ends with sentence-ending punctuation
            if current.rstrip().endswith(('.', '!', '?', ':', ';')):
                break

            # Don't merge if next line starts with bullet or special chars
            if next_line.startswith(_BULLETS):
                break

            # Don't merge separator lines
            if next_line.startswith('=' * 10):
                break

            # Merge if current line ends mid-word (ends with letter/number)
            # and next starts with lowercase letter
            if current and current[-1].isalnum() and next_line and next_line[0].islower():
                current = current + ' ' + next_line
                i += 1
                continue

            # Merge if current line ends with incomplete word (long line ending with
            # letter) and the next line looks like a continuation (starts with lowercase
            # or continues a word). This handles the column-width wrapping issue.
            if (len(current) >= 60 and current and current[-1].isalpha()
                    and next_line
                    and (next_line[0].islower()
                         or (next_line[0].isupper()
                             and not next_line.split()[0].istitle()))):
                current = current + next_line
                i += 1
                continue

            break

        result.append(current)
        i += 1

    return '\n'.join(result)


def join_long_lines(text: str) -> str:
    """The second pass: a line of LONG_LINE or more characters that ends in a letter
    takes the next line, with a space, under the same guards as `fix_line_wrapping`.

    A separate pass and not one more rule in the first, because the first judges
    lines before they are joined: "The IRI Marketing dataset" is too short there to
    be glued to "Consumer-level data...", and in a single pass it would already be
    the tail of a long line."""
    lines = text.split('\n')
    result = []
    i = 0
    while i < len(lines):
        current = lines[i].rstrip()
        if not current:
            result.append('')
            i += 1
            continue
        while i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if (not next_line or current.endswith(('.', '!', '?', ':', ';'))
                    or next_line.startswith(_BULLETS) or next_line.startswith('=' * 10)):
                break
            if len(current) >= LONG_LINE and current[-1].isalpha():
                current = current + ' ' + next_line
                i += 1
                continue
            break
        result.append(current)
        i += 1
    return '\n'.join(result)


def _squeeze(line: str) -> str:
    return re.sub(r' +', ' ', line.replace('\t', ' ')).strip()


def get_filename(url):
    parsed = urlparse(url)
    path = unquote(parsed.path)
    name = 'index' if not path or path == '/' else path.strip('/').replace('/', '_')
    name = re.sub(r'[<>:"/\\|?*%]', '_', name)
    return name[:200] + '.txt'


def get_text(html):
    """Extract and clean text from HTML content."""
    soup = BeautifulSoup(html, 'html.parser')

    # The title as the page gives it, site suffix included (the crawler stripped
    # " | Research Computing Center"; `parse_scraped` drops everything after the first
    # "|" anyway). The learning site's titles run over two lines; each is stripped.
    title = ''
    if soup.title:
        title = soup.title.get_text(strip=True)
        title = '\n'.join(part.strip() for part in title.split('\n'))

    # Remove junk elements
    for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'form', 'noscript', 'iframe']):
        tag.decompose()

    # Menus that are not <nav> elements: Drupal's top bar and section menu. Their
    # labels are not written, and they count as seen, so the same words later in the
    # page are dropped as duplicates. Then the page title, which Drupal prints as an
    # <h2 id="page-title"> above the content.
    seen = set()
    for tag in soup.find_all(attrs={'role': 'navigation'}):
        for piece in tag.get_text(separator='\n', strip=True).split('\n'):
            if _squeeze(piece):
                seen.add(_squeeze(piece).lower())
        tag.decompose()
    for tag in soup.find_all(id='page-title'):
        tag.decompose()

    # Get body text
    body = soup.find('body')
    raw = (body or soup).get_text(separator='\n', strip=True)

    # Normalize unicode characters. Duplicates are still judged on the text as it
    # was, which is what keeps a spec line written once with a non-breaking space and
    # once without from losing its second copy.
    text = normalize_unicode(raw)
    title = normalize_unicode(title)
    raw_lines = raw.split('\n')

    # Clean up lines: remove duplicates, navigation, and very short lines
    lines = []

    for number, line in enumerate(text.split('\n')):
        line = _squeeze(line)

        # Skip empty or very short lines
        if not line or len(line) < 3:
            continue

        # Skip navigation/boilerplate lines
        if is_navigation_line(line):
            continue

        # Skip duplicates (case-insensitive)
        key = _squeeze(raw_lines[number]).lower()
        if key in seen:
            continue
        seen.add(key)

        lines.append(line)

    # Join and fix line wrapping issues
    text = '\n'.join(lines)
    text = fix_line_wrapping(text)
    text = join_long_lines(text)

    # Remove excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return title, text.strip()


def render(url: str, title: str, text: str) -> str:
    """A page as `web/` holds it: URL, title, the rule, the text, no final newline."""
    return "\n".join([f"URL: {url}", f"Title: {title}", RULE] + ([text] if text else []))


def body_of(content: str) -> str:
    """The text of a `web/` file, after its header."""
    _head, rule, body = content.partition("\n" + RULE)
    return body.lstrip("\n") if rule else content


def url_of(content: str) -> str:
    first = content.split("\n", 1)[0]
    return first[4:].strip() if first.startswith("URL:") else ""


_NOT_FOUND = re.compile(r"(?:error\s*)?(?:404\b|page not found\b|not found\b)", re.IGNORECASE)


def soft_404(title: str, text: str) -> str:
    """Why a 200 is a missing page in disguise, or "" if it is a page.

    Judged on the title (before the site suffix) and the first lines of the text, not
    on the whole text, so a FAQ that mentions an error page is not one. Length is the
    caller's to judge, because a page that has always been short is not a soft 404.
    """
    name = title.split("|")[0].strip()
    if _NOT_FOUND.match(name):
        return f"soft 404: titled {name!r}"
    for line in text.split("\n")[:3]:
        if _NOT_FOUND.match(line.strip()):
            return f"soft 404: the page opens with {line.strip()[:60]!r}"
    return ""


def digest(content: str | None) -> str | None:
    if content is None:
        return None
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# --- the list ----------------------------------------------------------------------


class ConfigError(Exception):
    """`web_pages.toml` or `web_manifest.json` cannot be used as written."""


def page_key(url: str) -> str:
    """What two spellings of one address share: https, lower-case host, decoded path,
    no trailing slash and no fragment. Used to match the list against the sitemap and
    to tell whether two URLs landed on the same page, never to fetch."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    path = unquote(parsed.path).rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"https://{host}{path}{query}"


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


@dataclass(frozen=True)
class Page:
    url: str    # as the list writes it, which is what the file's URL: line says
    key: str    # page_key(url)
    file: str   # get_filename(url), the name the bundled file already has
    host: str


@dataclass
class Pages:
    """`web_pages.toml`, checked."""

    sitemaps: list[str]
    listed: list[Page]   # allowed and not denied, in the order the file lists them
    allowed: set[str]    # keys of every allowed URL, denied ones included
    denied: set[str]     # keys

    @property
    def hosts(self) -> set[str]:
        return {page.host for page in self.listed} | {host_of(url) for url in self.sitemaps}


def load_pages(path: str) -> Pages:
    try:
        with open(path, "rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc

    def section(name: str) -> list[str]:
        table = raw.get(name, {})
        urls = table.get("urls", []) if isinstance(table, dict) else None
        if not isinstance(urls, list) or not all(isinstance(url, str) for url in urls):
            raise ConfigError(f"{path}: [{name}] urls must be a list of strings")
        for url in urls:
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ConfigError(f"{path}: [{name}] {url!r} is not an https:// URL")
        return urls

    sitemaps, allow, deny = section("sitemaps"), section("allow"), section("deny")
    if not allow:
        raise ConfigError(f"{path}: [allow] lists no pages")
    denied = {page_key(url) for url in deny}
    listed: list[Page] = []
    keys: dict[str, str] = {}
    files: dict[str, str] = {}
    for url in allow:
        key = page_key(url)
        if key in keys:
            raise ConfigError(f"{path}: {url} is listed twice (also as {keys[key]})")
        keys[key] = url
        if key in denied:
            continue
        name = get_filename(url)
        if name in files:
            raise ConfigError(f"{path}: {url} and {files[name]} would both be {name}")
        files[name] = url
        listed.append(Page(url=url, key=key, file=name, host=host_of(url)))
    return Pages(sitemaps=sitemaps, listed=listed, allowed=set(keys), denied=denied)


def load_manifest(path: str) -> dict[str, dict]:
    """Per-page state from the last run, by URL. No file yet: every page is new."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    pages = data.get("pages") if isinstance(data, dict) else None
    if not isinstance(pages, dict) or not all(isinstance(row, dict) for row in pages.values()):
        raise ConfigError(f'{path}: expected {{"pages": {{url: {{...}}}}}}')
    return pages


def dump_manifest(pages: dict[str, dict]) -> str:
    about = ("Per-page state for tools/rcc-web-scrape.py: the sitemap lastmod and the "
             "sha256 of the file each page was last written as, its consecutive failed "
             "runs, and where its URL landed. Written by the weekly refresh.")
    return json.dumps({"about": about, "pages": pages}, indent=2, sort_keys=True) + "\n"


# --- fetching ----------------------------------------------------------------------


class Fetcher:
    """Every request this script makes goes through here.

    Per host: robots.txt first, then its Crawl-delay (at least MIN_DELAY) between any
    two requests, counted from the end of the last one. Redirects are followed by hand
    so that robots.txt and the delay apply to each hop, and only to listed hosts.
    """

    def __init__(self, session, hosts: Iterable[str], *,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 min_delay: float = MIN_DELAY,
                 retry_waits: tuple[float, ...] = RETRY_WAITS):
        self.session = session
        self.hosts = set(hosts)
        self.sleep = sleep
        self.clock = clock
        self.min_delay = min_delay
        self.retry_waits = retry_waits
        self.robots: dict[str, RobotFileParser | str] = {}  # a parser, or why there is none
        self.delays: dict[str, float] = {}
        self.last: dict[str, float] = {}
        self.holds: dict[str, float] = {}
        self.requests = 0

    def _pace(self, host: str) -> None:
        if host in self.last:
            gap = max(self.delays.get(host, self.min_delay), self.holds.pop(host, 0.0))
            wait = self.last[host] + gap - self.clock()
            if wait > 0:
                self.sleep(wait)

    def _request(self, url: str):
        """One GET with no redirect followed: (response, error). Retried on a timeout,
        a dropped connection or a 5xx, never on a 4xx or a certificate that fails."""
        host = host_of(url)
        response, error = None, ""
        for attempt in range(len(self.retry_waits) + 1):
            self._pace(host)
            self.requests += 1
            retry = False
            try:
                response = self.session.get(url, timeout=TIMEOUT, allow_redirects=False)
            except requests.exceptions.SSLError as exc:
                self.last[host] = self.clock()
                return None, f"TLS verification failed: {exc}"
            except _RETRY_ERRORS as exc:
                response, error, retry = None, f"{type(exc).__name__}: {exc}", True
            except requests.RequestException as exc:
                self.last[host] = self.clock()
                return None, f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code >= 500:
                    error, retry = f"HTTP {response.status_code}", True
            self.last[host] = self.clock()
            if not retry:
                return response, ""
            if attempt < len(self.retry_waits):
                self.holds[host] = self.retry_waits[attempt]
        return response, error

    def _rules(self, host: str) -> RobotFileParser | str:
        if host in self.robots:
            return self.robots[host]
        response, error, _final = self.get(f"https://{host}/robots.txt", robots=False)
        rules: RobotFileParser | str
        if error or response is None:
            rules = f"robots.txt unreachable ({error})"
        elif response.status_code == 200:
            rules = RobotFileParser()
            rules.parse(response.text.splitlines())
        elif response.status_code in (401, 403):
            rules = RobotFileParser()
            rules.disallow_all = True
        elif 400 <= response.status_code < 500:
            rules = RobotFileParser()   # no robots.txt: nothing is disallowed
            rules.allow_all = True
        else:
            rules = f"robots.txt unreachable (HTTP {response.status_code})"
        if isinstance(rules, RobotFileParser):
            # None for a parser that never read a file, as with the two cases above.
            delay = rules.crawl_delay(USER_AGENT)
            self.delays[host] = max(self.min_delay, float(delay or 0))
        self.robots[host] = rules
        return rules

    def get(self, url: str, *, robots: bool = True):
        """(response, error, final URL). `error` is "" when a response came back that
        was not a redirect; the caller judges its status."""
        current = url
        for _hop in range(MAX_REDIRECTS + 1):
            if urlparse(current).scheme != "https":
                return None, f"redirected to a URL that is not https: {current}", current
            host = host_of(current)
            if robots:
                if host not in self.hosts:
                    return None, f"{OFF_SITE}, to {current}", current
                rules = self._rules(host)
                if isinstance(rules, str):
                    return None, rules, current
                if not rules.can_fetch(USER_AGENT, current):
                    return None, BLOCKED, current
            response, error = self._request(current)
            if error or response is None:
                return response, error, current
            if response.status_code not in _REDIRECT_CODES:
                return response, "", current
            location = response.headers.get("Location", "")
            if not location:
                return response, f"HTTP {response.status_code} with no Location", current
            current = urljoin(current, location)
        return None, f"more than {MAX_REDIRECTS} redirects", current


def decode(response) -> str:
    """The body as text: in the charset the server names, else UTF-8 if it is UTF-8.

    requests reads an unnamed charset on text/html as ISO-8859-1, which is right by the
    old HTTP rule and wrong for a UTF-8 page that leaves it out. Every listed page names
    its charset today (2026-10-05), so this is for the day one stops."""
    if "charset=" in response.headers.get("Content-Type", "").lower():
        return response.text
    try:
        return response.content.decode("utf-8")
    except UnicodeDecodeError:
        return response.text


@dataclass
class Outcome:
    """What one page's fetch came to."""

    kind: str                 # "ok", "dead", "transient" or "blocked"
    error: str = ""
    status: int | None = None
    final_url: str = ""
    title: str = ""
    text: str = ""
    content: str = ""         # the file to write, when kind is "ok"


def fetch_page(fetcher: Fetcher, page: Page, existing: str | None = None,
               start: str = "") -> Outcome:
    """Fetch one listed page and judge it. `existing` is the file `web/` holds now.

    `start` is where the last run found the page, when that is the same page by
    `page_key`: the WordPress hosts answer every listed URL with a redirect to its
    trailing-slash form, and asking for that form directly saves a request a page."""
    response, error, final = fetcher.get(start or page.url)
    status = getattr(response, "status_code", None)
    if error == BLOCKED:
        return Outcome("blocked", error, status, final)
    if error:
        return Outcome("dead" if error.startswith(OFF_SITE) else "transient", error, status, final)
    if status in (404, 410):
        return Outcome("dead", f"HTTP {status}", status, final)
    if status != 200:
        return Outcome("transient", f"HTTP {status}", status, final)
    content_type = response.headers.get("Content-Type", "")
    if "html" not in content_type.lower():
        return Outcome("dead", f"not an HTML page ({content_type or 'no Content-Type'})",
                       status, final)
    title, text = get_text(decode(response))
    why = soft_404(title, text)
    content = render(page.url, title, text)
    # Short text is a soft 404 when it is news: a page that had more and now has a
    # stub, a new page, or a page gone blank. Three bundled pages have always been
    # under the floor (the Mind Bytes 2018 teaser, Skyway's news listing, the course
    # page), and a short page that changes but stays short is a page, not a failure:
    # counting it as one would delete Skyway's news page two weeks after its next
    # listing, which is a removal nobody decided on.
    held = len(body_of(existing)) if existing is not None else None
    if (not why and len(text) < MIN_TEXT and content != existing
            and (held is None or held >= MIN_TEXT or not text)):
        why = f"soft 404: {len(text)} characters of text, under {MIN_TEXT}"
    if why:
        return Outcome("dead", why, status, final, title, text)
    return Outcome("ok", "", status, final, title, text, content)


# --- the sitemap -------------------------------------------------------------------


class SitemapError(Exception):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_sitemap(data: bytes) -> tuple[dict[str, str | None], list[str]]:
    """One sitemap document: ({loc: lastmod or None}, [child sitemaps of an index])."""
    if b"<!ENTITY" in data:
        raise ValueError("it declares XML entities, which are not expanded here")
    root = ET.fromstring(data)
    kind = _local(root.tag)
    if kind not in ("urlset", "sitemapindex"):
        raise ValueError(f"its root element is <{kind}>, not <urlset> or <sitemapindex>")
    entries: dict[str, str | None] = {}
    children: list[str] = []
    for item in root:
        fields = {_local(child.tag): (child.text or "").strip() for child in item}
        loc = fields.get("loc", "")
        if not loc:
            continue
        if kind == "sitemapindex" and _local(item.tag) == "sitemap":
            children.append(loc)
        elif kind == "urlset" and _local(item.tag) == "url":
            entries[loc] = fields.get("lastmod") or None
    return entries, children


def read_sitemaps(fetcher: Fetcher, urls: list[str]) -> dict[str, tuple[str, str | None]]:
    """Every page the sitemaps list, by page_key: (loc as written, lastmod or None)."""
    found: dict[str, tuple[str, str | None]] = {}
    queue, seen = list(urls), set()
    while queue:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        if len(seen) > MAX_SITEMAPS:
            raise SitemapError(f"more than {MAX_SITEMAPS} sitemap documents")
        response, error, _final = fetcher.get(url)
        if error or response is None:
            raise SitemapError(f"{url}: {error}")
        if response.status_code != 200:
            raise SitemapError(f"{url}: HTTP {response.status_code}")
        try:
            entries, children = parse_sitemap(response.content)
        except (ET.ParseError, ValueError) as exc:
            raise SitemapError(f"{url} is not a usable sitemap: {exc}") from exc
        if not entries and not children:
            raise SitemapError(f"{url} lists no pages")
        for loc, lastmod in entries.items():
            found[page_key(loc)] = (loc, lastmod)
        queue.extend(children)
    return found


# --- one run -----------------------------------------------------------------------


@dataclass
class Result:
    code: int
    summary: dict
    writes: dict[str, str] = field(default_factory=dict)    # file -> content
    removals: dict[str, str] = field(default_factory=dict)  # file -> why
    manifest: dict[str, dict] = field(default_factory=dict)


def read_tree(out: str) -> dict[str, str]:
    """Every `.txt` file in `out`, by name. A tree that does not exist yet is empty."""
    if not os.path.isdir(out):
        return {}
    tree = {}
    for name in sorted(os.listdir(out)):
        path = os.path.join(out, name)
        if name.endswith(".txt") and os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as handle:
                tree[name] = handle.read()
    return tree


def interleave(due: list[tuple[Page, str]]) -> list[tuple[Page, str]]:
    """Round-robin across hosts, so one host's crawl delay is spent on the others."""
    lanes: dict[str, list[tuple[Page, str]]] = {}
    for item in due:
        lanes.setdefault(item[0].host, []).append(item)
    order = []
    for index in range(max((len(lane) for lane in lanes.values()), default=0)):
        order.extend(lane[index] for lane in lanes.values() if index < len(lane))
    return order


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(message: str) -> None:
    print(message, flush=True)


def plan(pages: Pages, manifest: dict[str, dict], sitemap: dict, current: dict[str, str]):
    """Which pages are due, which files go without a fetch, and each page's entry."""
    entries: dict[str, dict] = {}
    due: list[tuple[Page, str]] = []
    removals: dict[str, str] = {}
    stale: list[str] = []
    for page in pages.listed:
        old = manifest.get(page.url) or {}
        listed = sitemap.get(page.key)
        lastmod = listed[1] if listed else None
        existing = current.get(page.file)
        was_listed = bool(old.get("in_sitemap"))
        entry = {
            "file": page.file,
            "in_sitemap": listed is not None,
            "lastmod": old.get("lastmod"),
            "sha256": old.get("sha256") if old else digest(existing),
            "failures": int(old.get("failures") or 0),
            "error": old.get("error") or "",
            "final_url": old.get("final_url") or page.url,
            "removed": old.get("removed") or "",
        }
        entries[page.url] = entry
        reason = ""
        if not old:
            reason = "new to the list"
        elif entry["removed"]:
            if listed and (not was_listed or lastmod != entry["lastmod"]):
                reason = "changed in the sitemap since it was removed"
            else:
                stale.append(page.url)
        elif was_listed and not listed:
            entry.update(removed="left the sitemap", sha256=None)
            if existing is not None:
                removals[page.file] = "left the sitemap"
        elif entry["failures"]:
            reason = "failed last run"
        elif lastmod is None:
            reason = "no lastmod"
        elif lastmod != entry["lastmod"]:
            reason = "lastmod changed"
        elif existing is None:
            reason = "its file is missing"
        elif digest(existing) != entry["sha256"]:
            reason = "its file does not match the manifest"
        if reason:
            due.append((page, reason))
    return entries, due, removals, stale


def refresh(pages: Pages, manifest: dict[str, dict], out: str, fetcher: Fetcher, *,
            budget: float = BUDGET) -> Result:
    """Work out one run without writing anything. `apply` writes it."""
    started = fetcher.clock()
    summary: dict = {
        "started_at": _now(), "refused": "", "listed": len(pages.listed),
        "sitemap_urls": 0, "fetched": 0, "unchanged": 0, "not_due": 0,
        "added": [], "changed": [], "removed": [], "failed": [], "blocked": [],
        "redirected": [], "available_not_included": [], "stale_listing": [],
        "manifest_changed": False, "requests": 0, "seconds": 0.0,
    }

    def refuse(why: str) -> Result:
        summary.update(refused=why, requests=fetcher.requests,
                       seconds=round(fetcher.clock() - started, 1))
        return Result(3, summary)

    try:
        sitemap = read_sitemaps(fetcher, pages.sitemaps)
    except SitemapError as exc:
        return refuse(f"could not read the sitemap: {exc}")
    summary["sitemap_urls"] = len(sitemap)
    summary["available_not_included"] = sorted(
        loc for key, (loc, _lastmod) in sitemap.items()
        if key not in pages.allowed and key not in pages.denied
    )

    current = read_tree(out)
    entries, due, removals, stale = plan(pages, manifest, sitemap, current)
    summary["stale_listing"] = stale
    summary["not_due"] = len(pages.listed) - len(due)

    order = interleave(due)
    outcomes: dict[str, Outcome] = {}
    failing: list[dict] = []
    for number, (page, reason) in enumerate(order, 1):
        if fetcher.clock() - started > budget:
            summary.update(fetched=number - 1, failed=failing)
            return refuse(f"ran out of time: {number - 1} of {len(order)} pages fetched "
                          f"in {budget:.0f}s")
        landed = entries[page.url]["final_url"]
        start = landed if landed != page.url and page_key(landed) == page.key else ""
        outcome = fetch_page(fetcher, page, current.get(page.file), start)
        outcomes[page.url] = outcome
        verdict = outcome.kind if outcome.kind != "ok" else (
            "unchanged" if outcome.content == current.get(page.file) else "new text")
        _log(f"[{number}/{len(order)}] {page.url} ({reason}): {verdict}"
             + (f", {outcome.error}" if outcome.error else ""))
        # The breaker counts NEW failures. A page failing again after failing last run
        # is the second look the two-run rule is waiting for, not news of an outage;
        # counting it would let the breaker veto the very run that removes a dead page,
        # every week, whenever little else is due. An outage still trips it every
        # week: a refused run records nothing, so its failures stay new.
        if outcome.kind in FAILED_KINDS and not entries[page.url]["failures"]:
            failing.append({"url": page.url, "error": outcome.error})
        # Past this many the breaker trips whatever the rest do, so a site that is down
        # costs a few timeouts rather than the whole list's worth.
        if len(failing) > MAX_FAILED * len(order):
            summary.update(fetched=number, failed=failing)
            return refuse(f"{len(failing)} of the {len(order)} fetches due have failed, "
                          f"more than {MAX_FAILED:.0%}; stopped after {number}")

    writes: dict[str, str] = {}
    for page, _reason in order:
        outcome, entry = outcomes[page.url], entries[page.url]
        existing = current.get(page.file)
        listed = sitemap.get(page.key)
        if outcome.final_url and page_key(outcome.final_url) != page.key:
            summary["redirected"].append({"url": page.url, "final_url": outcome.final_url})
        if outcome.kind == "ok":
            entry.update(failures=0, error="", removed="", final_url=outcome.final_url,
                         lastmod=listed[1] if listed else None,
                         sha256=digest(outcome.content))
            if outcome.content == existing:
                summary["unchanged"] += 1
            else:
                writes[page.file] = outcome.content
        elif outcome.kind == "blocked":
            entry["error"] = BLOCKED
            summary["blocked"].append(page.url)
        else:
            entry.update(failures=entry["failures"] + 1, error=outcome.error)
            gone = outcome.kind == "dead" and entry["failures"] >= DEAD_RUNS
            if gone:
                entry.update(removed=f"dead: {outcome.error}", sha256=None)
                if existing is not None:
                    removals[page.file] = (f"{outcome.error}, on {entry['failures']} runs "
                                           "in a row")
            summary["failed"].append({
                "url": page.url, "error": outcome.error, "runs": entry["failures"],
                "file": "removed" if gone and existing is not None
                        else "kept" if existing is not None else "none",
            })

    projected = {name: content for name, content in current.items() if name not in removals}
    projected.update(writes)

    # Two listed URLs that land on one page keep one file: the URL that IS that page if
    # one of them is, else whichever the list names first.
    landing: dict[str, list[Page]] = {}
    for page in pages.listed:
        entry = entries[page.url]
        if not entry["removed"] and page.file in projected:
            landing.setdefault(page_key(entry["final_url"]), []).append(page)
    for target, group in landing.items():
        keep = next((page for page in group if page.key == target), group[0])
        for page in group:
            if page is keep:
                continue
            why = f"lands on the same page as {keep.url}"
            entries[page.url].update(removed=why, sha256=None)
            writes.pop(page.file, None)
            projected.pop(page.file, None)
            if page.file in current:
                removals[page.file] = why

    # Files the list does not account for: denied, or never listed at all.
    ours = {page.file for page in pages.listed}
    for name, content in current.items():
        if name not in ours:
            denied = page_key(url_of(content)) in pages.denied
            removals[name] = "denied in web_pages.toml" if denied else "not on the list"
            projected.pop(name, None)

    # The failure half of the breaker ran during the fetches; this is the other half.
    summary["fetched"] = len(order)
    before = sum(len(body_of(content)) for content in current.values())
    after = sum(len(body_of(content)) for content in projected.values())
    if before and after < (1 - MAX_SHRINK) * before:
        return refuse(f"web/ text would shrink by {1 - after / before:.0%} ({before} to "
                      f"{after} characters), more than {MAX_SHRINK:.0%}")

    by_file = {page.file: page.url for page in pages.listed}
    summary["added"] = sorted(by_file[name] for name in writes if name not in current)
    summary["changed"] = sorted(by_file[name] for name in writes if name in current)
    summary["removed"] = [
        {"file": name, "url": by_file.get(name) or url_of(current[name]), "reason": why}
        for name, why in sorted(removals.items()) if name in current
    ]
    summary.update(requests=fetcher.requests, seconds=round(fetcher.clock() - started, 1))
    new_manifest = {page.url: entries[page.url] for page in pages.listed}
    return Result(0, summary, writes, {k: v for k, v in removals.items() if k in current},
                  new_manifest)


def _write(path: str, text: str) -> None:
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temporary, path)


def apply(result: Result, out: str, manifest_path: str) -> None:
    """Write what `refresh` worked out. Never called for a refused run."""
    os.makedirs(out, exist_ok=True)
    for name, content in result.writes.items():
        _write(os.path.join(out, name), content)
    for name in result.removals:
        os.remove(os.path.join(out, name))
    text = dump_manifest(result.manifest)
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            unchanged = handle.read() == text
    except OSError:
        unchanged = False
    if not unchanged:
        _write(manifest_path, text)
    result.summary["manifest_changed"] = not unchanged


def run(pages: Pages, manifest: dict[str, dict], out: str, manifest_path: str,
        fetcher: Fetcher, *, budget: float = BUDGET) -> Result:
    result = refresh(pages, manifest, out, fetcher, budget=budget)
    if result.code == 0:
        apply(result, out, manifest_path)
    result.summary["finished_at"] = _now()
    return result


def report(summary: dict) -> str:
    lines = [
        f"web/: {summary['listed']} pages listed, {summary['sitemap_urls']} in the sitemap, "
        f"{summary['fetched']} fetched, {summary['not_due']} not due",
        f"   added {len(summary['added'])}   changed {len(summary['changed'])}   "
        f"removed {len(summary['removed'])}   failed {len(summary['failed'])}   "
        f"unchanged {summary['unchanged']}   blocked {len(summary['blocked'])}",
    ]
    lines += [f"   added      {url}" for url in summary["added"]]
    lines += [f"   changed    {url}" for url in summary["changed"]]
    lines += [f"   removed    {row['file']}: {row['reason']}" for row in summary["removed"]]
    lines += [f"   FAILED     {row['url']}: {row['error']}"
              + (f" (run {row['runs']}, file {row['file']})" if "runs" in row else "")
              for row in summary["failed"]]
    lines += [f"   blocked    {url}" for url in summary["blocked"]]
    lines += [f"   redirected {row['url']} -> {row['final_url']}" for row in summary["redirected"]]
    lines += [f"   stale      {url} is listed and its file is gone" for url in summary["stale_listing"]]
    if summary["available_not_included"]:
        lines.append(f"available, not included ({len(summary['available_not_included'])}): "
                     "add them to web_pages.toml to fetch them, or deny them to stop this")
        lines += [f"   {url}" for url in summary["available_not_included"]]
    lines.append(f"{summary['requests']} requests in {summary['seconds']:.0f}s")
    if summary["refused"]:
        lines.append(f"REFUSED, nothing written: {summary['refused']}")
    return "\n".join(lines)


def make_session() -> requests.Session:
    """The one HTTP client: TLS verified (requests' default, left alone), and a
    User-Agent that says what is asking and where to complain."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", help="the web/ directory to update in place")
    parser.add_argument("--pages", default=os.path.join(ROOT, "web_pages.toml"),
                        help="the allow and deny lists (default: web_pages.toml)")
    parser.add_argument("--manifest", default=os.path.join(ROOT, "web_manifest.json"),
                        help="per-page state between runs (default: web_manifest.json)")
    parser.add_argument("--summary", help="also write the run summary here, as JSON")
    parser.add_argument("--budget", type=float, default=BUDGET,
                        help=f"seconds before the run gives up (default: {BUDGET})")
    args = parser.parse_args(argv)

    try:
        pages = load_pages(args.pages)
        manifest = load_manifest(args.manifest)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    fetcher = Fetcher(make_session(), pages.hosts)
    result = run(pages, manifest, args.out, args.manifest, fetcher, budget=args.budget)
    print(report(result.summary), flush=True)
    if args.summary:
        os.makedirs(os.path.dirname(os.path.abspath(args.summary)), exist_ok=True)
        with open(args.summary, "w", encoding="utf-8") as handle:
            json.dump(result.summary, handle, indent=2)
            handle.write("\n")
    return result.code


if __name__ == "__main__":
    raise SystemExit(main())

"""`tools/rcc-web-scrape.py` with the network faked: what it fetches, what it writes, and
when it refuses to write anything.

Nothing here touches the network. A fake session answers from a table of routes and a
fake clock stands in for the crawl delay, so the delay is measured rather than waited
out. The scraper is loaded by path because its file name is not a module name.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from itertools import pairwise

import pytest
import requests

from sage.normalize import parse_scraped
from tools import metrics
from tools import refresh_report as report

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "rcc_web_scrape", os.path.join(ROOT, "tools", "rcc-web-scrape.py"))
scrape = importlib.util.module_from_spec(_SPEC)
sys.modules["rcc_web_scrape"] = scrape
_SPEC.loader.exec_module(scrape)

HOST = "https://rcc.uchicago.edu"
SITEMAP = f"{HOST}/sitemap.xml"
ROBOTS = "User-agent: *\nCrawl-delay: 10\nDisallow: /admin/\n"
TEXT = "Midway3 is the shared cluster every RCC account can use. " * 6   # > 200 chars
A, B = f"{HOST}/resources", f"{HOST}/resources/software"
# Ten healthy pages with no lastmod, due on every run the way the subdomain pages are, so
# that one failing page is one failure in eleven rather than the whole run.
FILLER = [f"{HOST}/p{n}" for n in range(10)]


# --- a fake web ----------------------------------------------------------------------


class Response:
    def __init__(self, status=200, body="", headers=None):
        self.status_code = status
        self.content = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = {"Content-Type": "text/html; charset=utf-8", **(headers or {})}

    @property
    def text(self):
        return self.content.decode("utf-8")


def page(title, *paragraphs):
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return Response(200, f"<html><head><title>{title} | Research Computing Center</title>"
                         f"</head><body><nav>Home</nav><main>{body}</main></body></html>")


def moved(to):
    return Response(301, "", {"Location": to})


def sitemap(*entries):
    rows = "".join(f"<url><loc>{loc}</loc>" + (f"<lastmod>{mod}</lastmod>" if mod else "")
                   + "</url>" for loc, mod in entries)
    return Response(200, '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns='
                         f'"http://www.sitemaps.org/schemas/sitemap/0.9">{rows}</urlset>',
                    {"Content-Type": "text/xml"})


def site(entries, routes, filler=True):
    """A sitemap of `entries` and the routes, plus the FILLER pages when asked for."""
    rows = list(entries) + ([(url, None) for url in FILLER] if filler else [])
    table = {SITEMAP: sitemap(*rows), **routes}
    if filler:
        table.update({url: page(f"Page {n}", TEXT) for n, url in enumerate(FILLER)})
    return table


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Site:
    """Stands in for requests.Session. A route is a Response, an exception to raise, or
    a list of them used in turn, the last one repeating."""

    def __init__(self, routes, clock):
        self.routes, self.clock, self.calls = dict(routes), clock, []

    def get(self, url, timeout=None, allow_redirects=True):
        assert allow_redirects is False, "redirects are followed by hand, hop by hop"
        assert timeout == scrape.TIMEOUT
        self.calls.append((self.clock(), url))
        self.clock.now += 0.1
        route = self.routes.get(url, Response(404, "<title>Page not found</title>"))
        if isinstance(route, list):
            route = route.pop(0) if len(route) > 1 else route[0]
        if isinstance(route, BaseException):
            raise route
        return route

    def count(self, url):
        return sum(1 for _when, called in self.calls if called == url)


class World:
    """A scratch repository: a page list, a web/ tree and a manifest, run against a
    fake site."""

    def __init__(self, tmp_path):
        self.web = tmp_path / "web"
        self.web.mkdir()
        self.manifest = tmp_path / "web_manifest.json"
        self.listing = tmp_path / "web_pages.toml"

    def list_pages(self, allow, deny=(), sitemaps=(SITEMAP,)):
        def urls(items):
            return "[" + ", ".join(f'"{url}"' for url in items) + "]"
        self.listing.write_text(f"[sitemaps]\nurls = {urls(sitemaps)}\n[allow]\n"
                                f"urls = {urls(allow)}\n[deny]\nurls = {urls(deny)}\n")

    def hold(self, url, title, text=TEXT):
        """Put a file in web/ as an earlier run would have written it."""
        name = scrape.get_filename(url)
        (self.web / name).write_text(
            scrape.render(url, f"{title} | Research Computing Center", text), encoding="utf-8")
        return name

    def run(self, routes, robots=ROBOTS):
        clock = Clock()
        table = {f"{HOST}/robots.txt": Response(200, robots, {"Content-Type": "text/plain"})}
        table.update(routes)
        fake = Site(table, clock)
        pages = scrape.load_pages(str(self.listing))
        fetcher = scrape.Fetcher(fake, pages.hosts, sleep=clock.sleep, clock=clock)
        result = scrape.run(pages, scrape.load_manifest(str(self.manifest)), str(self.web),
                            str(self.manifest), fetcher)
        return result, fake

    def files(self):
        return {path.name: path.read_text(encoding="utf-8") for path in self.web.glob("*.txt")}

    def entry(self, url):
        return json.loads(self.manifest.read_text())["pages"][url]


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


# --- the sitemap ---------------------------------------------------------------------


class TestTheSitemap:
    def test_lastmod_is_read_and_an_absent_one_is_none(self):
        entries, children = scrape.parse_sitemap(
            sitemap((A, "2026-10-02T20:20Z"), (B, None)).content)
        assert entries == {A: "2026-10-02T20:20Z", B: None}
        assert children == []

    def test_a_sitemap_without_the_namespace_still_parses(self):
        data = f"<urlset><url><loc>{A}</loc><lastmod>2024-01-01</lastmod></url></urlset>"
        assert scrape.parse_sitemap(data.encode()) == ({A: "2024-01-01"}, [])

    def test_a_sitemap_index_is_followed_to_its_children(self, world):
        index = Response(200, '<sitemapindex xmlns="http://www.sitemaps.org/schemas/'
                              f'sitemap/0.9"><sitemap><loc>{HOST}/sitemap-1.xml</loc>'
                              "</sitemap></sitemapindex>", {"Content-Type": "text/xml"})
        world.list_pages([A])
        result, fake = world.run({SITEMAP: index, f"{HOST}/sitemap-1.xml":
                                  sitemap((A, "2024-01-01")), A: page("Resources", TEXT)})
        assert result.code == 0
        assert result.summary["sitemap_urls"] == 1
        assert fake.count(f"{HOST}/sitemap-1.xml") == 1

    def test_xml_entities_are_refused_rather_than_expanded(self):
        bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><urlset/>'
        with pytest.raises(ValueError, match="entities"):
            scrape.parse_sitemap(bomb)

    def test_a_sitemap_that_cannot_be_read_writes_nothing(self, world):
        world.hold(A, "Resources")
        before = world.files()
        world.list_pages([A])
        result, _fake = world.run({SITEMAP: Response(503, "busy")})
        assert result.code == 3
        assert "sitemap" in result.summary["refused"]
        assert world.files() == before
        assert not world.manifest.exists()

    def test_a_sitemap_that_lists_nothing_writes_nothing(self, world):
        world.list_pages([A])
        result, _fake = world.run({SITEMAP: sitemap()})
        assert result.code == 3
        assert "lists no pages" in result.summary["refused"]


# --- the list ------------------------------------------------------------------------


class TestTheList:
    def test_the_shipped_list_accounts_for_every_bundled_file(self):
        """Every file in web/ is a listed page under its own name, and every listed page
        has a file or a manifest entry that says why it has none."""
        pages = scrape.load_pages(os.path.join(ROOT, "web_pages.toml"))
        by_url = {page.url: page for page in pages.listed}
        manifest = scrape.load_manifest(os.path.join(ROOT, "web_manifest.json"))
        tree = scrape.read_tree(os.path.join(ROOT, "web"))
        for name, content in tree.items():
            url = scrape.url_of(content)
            assert url in by_url, f"web/{name} claims {url}, which web_pages.toml does not list"
            assert by_url[url].file == name, f"web/{name} should be {by_url[url].file}"
        for listed in pages.listed:
            if listed.file not in tree:
                entry = manifest.get(listed.url, {})
                assert entry.get("removed") or entry.get("failures"), (
                    f"{listed.url} is listed, has no file, and the manifest does not say why")

    @pytest.mark.parametrize("allow, problem", [
        (["http://rcc.uchicago.edu/resources"], "not an https"),
        ([A, A + "/"], "listed twice"),
        ([f"{HOST}/a/b", f"{HOST}/a_b"], "would both be"),
        ([], "lists no pages"),
    ])
    def test_a_list_that_cannot_be_right_is_refused(self, world, allow, problem):
        world.list_pages(allow)
        with pytest.raises(scrape.ConfigError, match=problem):
            scrape.load_pages(str(world.listing))

    def test_sitemap_pages_off_the_list_are_reported_and_never_fetched(self, world):
        form = f"{HOST}/accounts-allocations/request-account"
        world.list_pages([A])
        result, fake = world.run(site([(A, "2024"), (form, "2024")],
                                      {A: page("Resources", TEXT), form: page("Form", TEXT)},
                                      filler=False))
        assert result.summary["available_not_included"] == [form]
        assert fake.count(form) == 0

    def test_a_denied_page_is_not_fetched_and_its_file_goes(self, world):
        name = world.hold(B, "Software")
        world.list_pages([A, B], deny=[B])
        result, fake = world.run(site([(A, "2024"), (B, "2024")],
                                      {A: page("Resources", TEXT), B: page("Software", TEXT)},
                                      filler=False))
        assert result.code == 0
        assert fake.count(B) == 0
        assert name not in world.files()
        assert result.summary["removed"] == [
            {"file": name, "url": B, "reason": "denied in web_pages.toml"}]
        assert result.summary["available_not_included"] == []

    def test_a_file_the_list_does_not_name_is_removed(self, world):
        stray = world.hold(f"{HOST}/somewhere-else", "Elsewhere")
        world.list_pages([A])
        result, _fake = world.run(site([(A, "2024")], {A: page("Resources", TEXT)},
                                       filler=False))
        assert stray not in world.files()
        assert result.summary["removed"][0]["reason"] == "not on the list"


# --- what is fetched -----------------------------------------------------------------


class TestWhatIsFetched:
    def routes(self, lastmod_a="2024-01-01", text_a=TEXT):
        return site([(A, lastmod_a), (B, "2024-01-01")],
                    {A: page("Resources", text_a), B: page("Software", TEXT)}, filler=False)

    def test_with_no_manifest_every_listed_page_is_new(self, world):
        world.list_pages([A, B])
        result, fake = world.run(self.routes())
        assert result.code == 0
        assert (fake.count(A), fake.count(B)) == (1, 1)
        assert set(result.summary["added"]) == {A, B}
        files = world.files()
        for url in (A, B):
            entry = world.entry(url)
            assert entry["sha256"] == scrape.digest(files[entry["file"]])
            assert entry["failures"] == 0 and entry["lastmod"] == "2024-01-01"

    def test_an_unchanged_lastmod_is_not_fetched_again(self, world):
        world.list_pages([A, B])
        world.run(self.routes())
        result, fake = world.run(self.routes())
        assert (fake.count(A), fake.count(B)) == (0, 0)
        assert result.summary["not_due"] == 2

    def test_a_changed_lastmod_is_fetched_and_the_new_text_written(self, world):
        world.list_pages([A, B])
        world.run(self.routes())
        newer = TEXT + " Midway3 now has H100 nodes."
        result, fake = world.run(self.routes(lastmod_a="2026-10-02", text_a=newer))
        assert (fake.count(A), fake.count(B)) == (1, 0)
        assert result.summary["changed"] == [A]
        assert "H100" in world.files()[scrape.get_filename(A)]
        assert world.entry(A)["lastmod"] == "2026-10-02"

    def test_a_page_with_no_lastmod_is_fetched_every_run(self, world):
        world.list_pages([A, B])
        routes = site([(A, None), (B, "2024")],
                      {A: page("Resources", TEXT), B: page("Software", TEXT)}, filler=False)
        world.run(routes)
        _result, fake = world.run(routes)
        assert (fake.count(A), fake.count(B)) == (1, 0)

    def test_a_quiet_run_leaves_the_manifest_byte_for_byte(self, world):
        world.list_pages([A, B])
        world.run(self.routes())
        before = world.manifest.read_bytes()
        result, _fake = world.run(self.routes())
        assert result.summary["manifest_changed"] is False
        assert world.manifest.read_bytes() == before

    def test_a_file_that_went_missing_is_fetched_again(self, world):
        world.list_pages([A, B])
        world.run(self.routes())
        (world.web / scrape.get_filename(A)).unlink()
        _result, fake = world.run(self.routes())
        assert fake.count(A) == 1
        assert scrape.get_filename(A) in world.files()


# --- dead pages ----------------------------------------------------------------------


class TestDeadPages:
    def test_a_404_keeps_the_file_once_and_removes_it_on_the_second_run(self, world):
        name = world.hold(B, "Software")
        world.list_pages([B] + FILLER)
        routes = site([(B, None)], {B: Response(404, "<title>Page not found</title>")})
        first, _fake = world.run(routes)
        assert first.code == 0
        assert name in world.files()
        assert world.entry(B)["failures"] == 1
        assert first.summary["failed"][0]["file"] == "kept"
        second, _fake = world.run(routes)
        assert name not in world.files()
        assert second.summary["removed"][0]["file"] == name
        assert world.entry(B)["removed"].startswith("dead: HTTP 404")

    def test_the_second_strike_is_not_vetoed_when_it_is_all_that_is_due(self, world):
        """A page that failed last run is due on its own. Counted by the breaker, its
        second failure would be one in one, over 10%, and the run that should remove it
        would refuse every week."""
        name = world.hold(B, "Software")
        world.list_pages([B] + [f"{HOST}/q{n}" for n in range(10)])
        dated = [(f"{HOST}/q{n}", "2024") for n in range(10)]
        routes = site([(B, "2024"), *dated], {B: Response(410, "gone"),
                      **{url: page("Q", TEXT) for url, _mod in dated}}, filler=False)
        world.run(routes)
        second, fake = world.run(routes)
        assert sum(fake.count(url) for url, _mod in dated) == 0   # only B was due
        assert second.code == 0
        assert name not in world.files()

    def test_a_success_in_between_starts_the_count_again(self, world):
        name = world.hold(B, "Software")
        world.list_pages([B] + FILLER)
        world.run(site([(B, None)], {B: Response(410, "gone")}))
        world.run(site([(B, None)], {B: page("Software", TEXT)}))
        assert world.entry(B)["failures"] == 0
        world.run(site([(B, None)], {B: Response(410, "gone")}))
        assert name in world.files()
        assert world.entry(B)["failures"] == 1

    def test_a_page_that_leaves_the_sitemap_is_removed_without_a_fetch(self, world):
        world.list_pages([A, B] + FILLER)
        world.run(site([(A, "2024"), (B, "2024")],
                       {A: page("Resources", TEXT), B: page("Software", TEXT)}))
        result, fake = world.run(site([(A, "2024")], {A: page("Resources", TEXT)}))
        assert result.code == 0
        assert fake.count(B) == 0
        assert scrape.get_filename(B) not in world.files()
        assert result.summary["removed"][0]["reason"] == "left the sitemap"

    def test_a_5xx_is_retried_twice_with_growing_waits(self, world):
        world.list_pages([B] + FILLER)
        _result, fake = world.run(site([(B, None)], {B: Response(503, "busy")}))
        times = [when for when, url in fake.calls if url == B]
        assert len(times) == 1 + len(scrape.RETRY_WAITS)
        assert times[2] - times[1] > times[1] - times[0] >= scrape.MIN_DELAY

    def test_a_server_error_never_removes_a_file(self, world):
        name = world.hold(B, "Software")
        world.list_pages([B] + FILLER)
        for _week in range(3):
            result, _fake = world.run(site([(B, None)], {B: Response(500, "oops")}))
            assert result.code == 0
        assert name in world.files()
        assert world.entry(B)["failures"] == 3

    def test_a_4xx_other_than_404_is_not_retried(self, world):
        world.list_pages([A] + FILLER)
        result, fake = world.run(site([(A, None)], {A: Response(403, "forbidden")}))
        assert fake.count(A) == 1
        assert result.summary["failed"][0]["error"] == "HTTP 403"


# --- soft 404s -----------------------------------------------------------------------


class TestSoft404:
    def fetch(self, response, existing=None, url=A):
        clock = Clock()
        fake = Site({f"{HOST}/robots.txt": Response(200, ROBOTS), url: response}, clock)
        fetcher = scrape.Fetcher(fake, {"rcc.uchicago.edu"}, sleep=clock.sleep, clock=clock)
        target = scrape.Page(url, scrape.page_key(url), scrape.get_filename(url),
                             "rcc.uchicago.edu")
        return scrape.fetch_page(fetcher, target, existing)

    def held(self, text, title="News"):
        return scrape.render(A, f"{title} | Research Computing Center", text)

    def test_a_200_titled_page_not_found_is_a_failure(self):
        outcome = self.fetch(page("Page not found", TEXT))
        assert outcome.kind == "dead" and "soft 404" in outcome.error

    def test_a_200_that_opens_with_not_found_is_a_failure(self):
        assert self.fetch(page("Resources", "Page not found", TEXT)).kind == "dead"

    def test_a_page_that_mentions_an_error_further_down_is_a_page(self):
        outcome = self.fetch(page("FAQ", TEXT, TEXT, "If you see Page not found, log in."))
        assert outcome.kind == "ok"

    def test_short_text_is_a_failure_for_a_page_that_had_more(self):
        outcome = self.fetch(page("Resources", "Coming soon."), self.held(TEXT, "Resources"))
        assert outcome.kind == "dead" and "under 200" in outcome.error

    def test_short_text_is_a_failure_for_a_page_never_seen(self):
        assert self.fetch(page("Resources", "Coming soon.")).kind == "dead"

    def test_a_page_that_was_always_short_is_a_page_when_it_changes(self):
        outcome = self.fetch(page("News", "News", "Cloud Forum, May 19-21"),
                             self.held("News\nCloud Days"))
        assert outcome.kind == "ok"

    def test_a_short_page_that_went_blank_is_a_failure(self):
        assert self.fetch(page("News"), self.held("News\nCloud Days")).kind == "dead"

    def test_a_short_page_unchanged_is_a_page(self):
        response = page("News", "News")
        title, text = scrape.get_text(response.text)
        assert self.fetch(response, scrape.render(A, title, text)).kind == "ok"


# --- the circuit breaker -------------------------------------------------------------


class TestTheCircuitBreaker:
    URLS = [f"{HOST}/p{n}" for n in range(10)]

    def prepared(self, world, text=TEXT):
        for url in self.URLS:
            world.hold(url, "Page", text)
        world.list_pages(self.URLS)
        return world.files()

    def routes(self, failing=(), text=TEXT):
        table = {SITEMAP: sitemap(*[(url, None) for url in self.URLS])}
        for url in self.URLS:
            table[url] = Response(404, "gone") if url in failing else page("Page", text)
        return table

    def test_more_than_a_tenth_failing_writes_nothing(self, world):
        before = self.prepared(world)
        result, _fake = world.run(self.routes(failing=self.URLS[:2],
                                              text=TEXT + " Updated today."))
        assert result.code == 3
        assert "2 of the 10 fetches" in result.summary["refused"]
        assert [row["url"] for row in result.summary["failed"]] == self.URLS[:2]
        assert world.files() == before
        assert not world.manifest.exists()

    def test_exactly_a_tenth_failing_is_allowed(self, world):
        self.prepared(world)
        result, _fake = world.run(self.routes(failing=self.URLS[:1]))
        assert result.code == 0
        assert len(result.summary["failed"]) == 1

    def test_shrinking_web_by_more_than_a_fifth_writes_nothing(self, world):
        before = self.prepared(world, text=TEXT * 4)
        result, _fake = world.run(self.routes(text=TEXT))
        assert result.code == 3
        assert "shrink" in result.summary["refused"]
        assert world.files() == before

    def test_an_outage_stops_early_instead_of_timing_out_every_page(self, world):
        self.prepared(world)
        routes = self.routes()
        for url in self.URLS:
            routes[url] = requests.exceptions.ConnectTimeout("timed out")
        result, fake = world.run(routes)
        assert result.code == 3
        tries = 1 + len(scrape.RETRY_WAITS)
        assert sum(fake.count(url) for url in self.URLS) == 2 * tries   # then it stops


# --- politeness ----------------------------------------------------------------------


class TestPoliteness:
    def test_a_disallowed_page_is_never_requested(self, world):
        secret = f"{HOST}/admin/settings"
        world.list_pages([A, secret])
        result, fake = world.run(site([(A, "2024"), (secret, "2024")],
                                      {A: page("Resources", TEXT), secret: page("Admin", TEXT)},
                                      filler=False))
        assert fake.count(secret) == 0
        assert result.summary["blocked"] == [secret]

    def test_the_crawl_delay_spaces_every_request_to_a_host(self, world):
        world.list_pages(FILLER[:4])
        result, fake = world.run({SITEMAP: sitemap(*[(url, None) for url in FILLER[:4]]),
                                  **{url: page("P", TEXT) for url in FILLER[:4]}},
                                 robots="User-agent: *\nCrawl-delay: 30\n")
        times = [when for when, _url in fake.calls]
        assert len(times) == 6                       # robots.txt, the sitemap, four pages
        assert all(later - earlier >= 30 for earlier, later in pairwise(times))
        assert result.code == 0

    def test_a_host_that_names_no_delay_still_gets_the_minimum(self, world):
        world.list_pages(FILLER[:3])
        _result, fake = world.run({SITEMAP: sitemap(*[(url, None) for url in FILLER[:3]]),
                                   **{url: page("P", TEXT) for url in FILLER[:3]}},
                                  robots="User-agent: *\nDisallow: /admin/\n")
        times = [when for when, _url in fake.calls]
        assert all(later - earlier >= scrape.MIN_DELAY for earlier, later in pairwise(times))

    def test_the_user_agent_names_sage_and_links_this_repository(self):
        agent = scrape.make_session().headers["User-Agent"]
        assert "Sage" in agent and "github.com/PursuitOfDataScience/sage" in agent

    def test_tls_verification_is_on_and_nothing_silences_it(self):
        assert scrape.make_session().verify is True
        with open(os.path.join(ROOT, "tools", "rcc-web-scrape.py"), encoding="utf-8") as handle:
            source = handle.read()
        assert "verify=False" not in source
        assert "disable_warnings" not in source


# --- redirects -----------------------------------------------------------------------


class TestRedirects:
    def chain(self, hops):
        urls = [f"{HOST}/hop{n}" for n in range(hops)]
        table = {A: moved(urls[0])}
        for here, there in pairwise(urls):
            table[here] = moved(there)
        table[urls[-1]] = page("Resources", TEXT)
        return table, urls[-1]

    def test_five_redirects_are_followed_and_the_final_url_recorded(self, world):
        world.list_pages([A])
        table, final = self.chain(5)
        result, _fake = world.run(site([(A, "2024")], table, filler=False))
        assert result.code == 0
        assert world.entry(A)["final_url"] == final
        assert result.summary["redirected"] == [{"url": A, "final_url": final}]
        # The file still cites the listed URL, which is the one the corpus links to.
        assert scrape.url_of(world.files()[scrape.get_filename(A)]) == A

    def test_a_sixth_redirect_is_a_failure(self, world):
        world.list_pages([A] + FILLER)
        table, _final = self.chain(6)
        result, _fake = world.run(site([(A, "2024")], table))
        assert result.summary["failed"][0]["error"] == "more than 5 redirects"

    def test_two_listed_urls_that_land_on_one_page_keep_one_file(self, world):
        alias, canonical = f"{HOST}/midway2", f"{HOST}/support-and-services/midway2"
        alias_file = world.hold(alias, "Midway2")
        world.hold(canonical, "Midway2")
        world.list_pages([alias, canonical] + FILLER)
        result, _fake = world.run(site([(canonical, "2022")], {
            alias: moved(canonical), canonical: page("Midway2", TEXT)}))
        assert result.code == 0
        files = world.files()
        assert alias_file not in files and scrape.get_filename(canonical) in files
        assert result.summary["removed"][0]["reason"] == f"lands on the same page as {canonical}"

    def test_a_redirect_off_the_listed_hosts_is_a_failure_not_content(self, world):
        world.list_pages([A] + FILLER)
        result, fake = world.run(site([(A, "2024")], {A: moved("https://docs.rcc.uchicago.edu/")}))
        assert fake.count("https://docs.rcc.uchicago.edu/") == 0
        assert result.summary["failed"][0]["error"].startswith(scrape.OFF_SITE)

    def test_a_redirect_to_the_same_page_is_asked_for_directly_next_time(self, world):
        slash = A + "/"
        world.list_pages([A])
        routes = site([(A, None)], {A: moved(slash), slash: page("Resources", TEXT)},
                      filler=False)
        world.run(routes)
        _result, fake = world.run(routes)
        assert (fake.count(A), fake.count(slash)) == (0, 1)


# --- what is written -----------------------------------------------------------------


class TestWhatIsWritten:
    def test_a_file_reads_back_through_the_corpus_reader(self):
        content = scrape.render(A, "Resources | Research Computing Center", "First.\nSecond.")
        assert content.split("\n")[2:4] == ["=" * 80, "First."]
        assert not content.endswith("\n")
        assert parse_scraped(content) == (A, "Resources", "First.\nSecond.")

    def test_a_page_with_no_text_is_its_header_alone(self):
        assert scrape.render(A, "T", "").split("\n") == [f"URL: {A}", "Title: T", "=" * 80]

    def test_the_extraction_is_the_one_the_bundled_files_were_written_with(self):
        """The rules recovered from the bundle, in one page: a two-line title with its
        suffix, a menu that is dropped and counts as seen (so "data management" goes
        mid-sentence), the page-title heading dropped, a lowercase continuation joined
        with a space, an em dash as "--" and a bullet as "*"."""
        html = (
            "<html><head><title>Data Sharing Services\n | Research Computing Center</title>"
            "</head><body><div role='navigation'><a>Data Management</a></div>"
            "<h2 id='page-title'>Data Sharing Services</h2>"
            f"<p>Learn about RCC{chr(0x2019)}s <a>storage</a> and <a>data management</a> "
            f"plans{chr(0x2014)}today.</p><p>{chr(0x2022)} Point</p></body></html>")
        title, text = scrape.get_text(html)
        assert title == "Data Sharing Services\n| Research Computing Center"
        assert text == "Learn about RCC's storage and plans--today.\n* Point"

    def test_a_long_line_takes_the_next_with_a_space_and_an_acronym_with_none(self):
        long = ("The full Corpus of Contemporary American English (COCA) and Corpus of "
                "Historical American English (COHA) datasets")
        assert scrape.join_long_lines(scrape.fix_line_wrapping(
            f"{long}\nTo request a dataset")) == f"{long} To request a dataset"
        segregated = "and tests are being performed to ensure that traffic is segregated. The"
        assert scrape.fix_line_wrapping(f"{segregated}\nRCC has seen transfers") == (
            f"{segregated}RCC has seen transfers")


# --- refresh-docs.sh -----------------------------------------------------------------


class TestTheRefreshScript:
    @pytest.fixture
    def script(self, tmp_path):
        """A copy in a scratch directory, so nothing it does can reach this checkout."""
        copy = tmp_path / "refresh-docs.sh"
        shutil.copy(os.path.join(ROOT, "refresh-docs.sh"), copy)
        return copy

    def run(self, script, *args, **env):
        return subprocess.run(["bash", str(script), *args], capture_output=True, text=True,
                              env={**os.environ, **env}, timeout=60)

    def test_help_does_nothing_and_succeeds(self, script, tmp_path):
        done = self.run(script, "--help")
        assert done.returncode == 0 and "--scrape" in done.stdout
        assert sorted(os.listdir(tmp_path)) == ["refresh-docs.sh"]

    def test_an_unknown_flag_is_refused(self, script):
        assert self.run(script, "--scrap").returncode == 2

    def test_a_directory_that_is_not_a_checkout_fails_before_anything_is_touched(
            self, script, tmp_path):
        stray = tmp_path / "not-a-checkout"
        stray.mkdir()
        done = self.run(script, RCC_USER_GUIDE_REPO=str(stray))
        assert done.returncode != 0
        assert "not a git checkout" in done.stderr
        assert sorted(os.listdir(tmp_path)) == ["not-a-checkout", "refresh-docs.sh"]


# --- the workflow's other two tools --------------------------------------------------


class TestTheMergeGate:
    """`tools/metrics.py --fail-on-recall-drop`: the refresh merges itself only if this
    finds nothing."""

    def test_a_recall_that_fell_is_reported(self):
        before = {"recall@5": 1.0, "recall@3": 1.0, "p@1": 0.9}
        now = {"recall@5": 1.0, "recall@3": 35 / 36, "p@1": 0.9}
        assert metrics.recall_drops(now, before) == ["recall@3 100.0% -> 97.2%"]

    def test_recall_that_held_or_rose_is_not(self):
        before = {"recall@5": 0.97, "recall@3": 0.9}
        assert metrics.recall_drops({"recall@5": 0.97, "recall@3": 0.95}, before) == []

    def test_p_at_1_is_printed_not_gated(self):
        before = {"recall@5": 1.0, "recall@3": 1.0, "p@1": 0.9}
        assert metrics.recall_drops({"recall@5": 1.0, "recall@3": 1.0, "p@1": 0.5}, before) == []


class TestThePullRequest:
    def write(self, directory, guards):
        (directory / "web-summary.json").write_text(json.dumps({
            "listed": 55, "fetched": 55, "added": [], "changed": [A],
            "removed": [{"file": "midway2.txt", "url": f"{HOST}/midway2",
                         "reason": f"lands on the same page as {HOST}/support-and-services/midway2"}],
            "failed": [], "available_not_included": [f"{HOST}/accounts-allocations/pi-account-request"],
            "redirected": [], "blocked": [], "stale_listing": []}))
        (directory / "stamp-before.json").write_text('{"user_guide_commit": "f5676ad"}')
        (directory / "docs-changes.txt").write_text("M\tdocs/slurm/sbatch.md\nA\tdocs/new.md\n")
        (directory / "guards.txt").write_text(guards)
        stamp = directory / "docs_snapshot.json"
        stamp.write_text('{"user_guide_commit": "1a2b3c4"}')
        return str(stamp)

    def test_a_failed_guard_says_why_the_pull_request_was_left_open(self, tmp_path):
        stamp = self.write(tmp_path, "ruff success\npytest failure\nmetrics success\n")
        title, message, body = report.build(str(tmp_path), stamp, "2026-10-10")
        assert title == ("Corpus refresh 2026-10-10: User Guide f5676ad..1a2b3c4, "
                         "web 0 added, 1 changed, 1 removed, 0 failed")
        assert message.startswith(title + "\n\nUser Guide f5676ad..1a2b3c4: ")
        assert "**Left open for review**: pytest -q did not pass" in body
        assert "| `pytest -q` | **FAILED** |" in body
        assert "`midway2.txt`: lands on the same page as" in body
        assert "docs/: 1 added, 1 changed, 0 removed" in body
        assert f"{HOST}/accounts-allocations/pi-account-request" in body

    def test_every_guard_passing_says_it_merges(self, tmp_path):
        stamp = self.write(tmp_path, "ruff success\npytest success\n")
        _title, _message, body = report.build(str(tmp_path), stamp, "2026-10-10")
        assert "**Merging**" in body

    def test_nothing_it_writes_carries_an_em_dash_even_when_pasted_output_does(self, tmp_path):
        stamp = self.write(tmp_path, "ruff success\n")
        em = chr(0x2014)
        (tmp_path / "corpus.txt").write_text(f"empty documents (1) {em} topics\nStep 1{em}Go\n")
        texts = report.build(str(tmp_path), stamp, "d")
        assert all(em not in text for text in texts)
        assert "empty documents (1): topics" in texts[2] and "Step 1, Go" in texts[2]

    def test_what_the_documents_moved_is_listed_and_does_not_hold_the_merge(self, tmp_path):
        stamp = self.write(tmp_path, "corpus_check success\nruff success\npytest success\n")
        (tmp_path / "baseline.json").write_text(json.dumps({
            "shared_boilerplate": {"appeared": [["docs/a.md#x", "docs/b.md#x"]],
                                   "went": []},
            "unfindable_by_title": {"appeared": ["docs/tutorials/sde3/software.md"],
                                    "went": ["docs/old.md"]},
        }))
        _title, message, body = report.build(str(tmp_path), stamp, "2026-10-10")
        assert "**Merging**" in body
        assert "### What the documents moved" in body
        assert "- new: `docs/a.md#x`, `docs/b.md#x`" in body
        assert "- new: `docs/tutorials/sde3/software.md`" in body
        assert "- gone: `docs/old.md`" in body
        assert ("Re-measured into evals/corpus_baseline.json: shared_boilerplate +1 -0; "
                "unfindable_by_title +1 -1.") in message

    def test_a_refresh_that_moved_nothing_says_so(self, tmp_path):
        stamp = self.write(tmp_path, "ruff success\n")
        _title, message, body = report.build(str(tmp_path), stamp, "2026-10-10")
        assert "Nothing recorded in `evals/corpus_baseline.json` moved." in body
        assert "Re-measured" not in message

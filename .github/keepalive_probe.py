"""Visit the deployed app the way a reader does, wake it if it is asleep, prove it renders.

Streamlit Community Cloud discards an app's container after roughly twelve hours without
traffic. It does not suspend it: waking means rescheduling a container, re-cloning the
deployed repository and reinstalling the dependencies before a line of the app runs.
Measured on this account's other deployment on 2026-08-17, that took fourteen minutes,
against an app whose own startup is about a second. A reader who arrives during it is
shown "check back in a minute or two", so a wake that is merely slow is indistinguishable
from one that has failed, and they give up.

The probe is layered, cheapest first, and only the last layer is authoritative:

1. `GET /~/+/_stcore/health` returns plain `ok` from the app's own container, with no
   redirects and no cookies. That is the honest liveness test. Do NOT substitute the app
   root for it: `/` is served by Community Cloud's *proxy* and answers 200 with ~9 kB of
   React shell whether or not the container is running, so it can never report sleep.
   (`/~/+/` is where the app is mounted. `/_stcore/health` at the root is the proxy
   again.) A keepalive built on the root URL ran green for eight days on the sibling
   deployment while readers met a sleeping app every morning; that is what this avoids.

2. `GET /api/v2/app/status` is readable anonymously and reports the platform's own view.
   Measured values of its `status` field so far: 5 while running, 12 while asleep.

3. `POST /api/v2/app/resume` is what the shell's own "Yes, get this app back up!" button
   calls: `resumeAppFromSubdomain()` in its bundle, a POST with no body and no auth. It
   returns 403 against an app that is already running. Whether an anonymous caller may
   resume a *sleeping* one is the open question, so this is attempted and its result
   logged, and nothing depends on the answer. If it works, the schedule can move off
   GitHub Actions, which disables scheduled workflows after sixty days without a commit.

4. A real browser, which is the guarantee, because a session is the one thing a reader
   cannot be distinguished from.

Then it asserts the app view rendered and the composer exists, so an app that comes up
empty is a red run rather than a pass. Nothing here swallows a failure.

The browser is the Chrome every GitHub Ubuntu image already ships, and Playwright's own
Chromium is downloaded only on a machine without one. It is never
`playwright install --with-deps`, which is what the workflow used to run: that sends apt
to Ubuntu's mirrors for nine font packages the probe has no use for, and on 2026-11-11 a
runner could not resolve the mirror for ten minutes, so the run went red without the app
being looked at. Network steps are retried, and a red run says why in an annotation at
the top of the run page. One that could not start a browser names the runner, and one
whose page would not load says whether the app's own health check answered, so a missed
ping does not read as a sleeping app.

No question is asked, so no provider quota is spent.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

APP_URL = os.environ.get("APP_URL", "https://uchicago-rcc.streamlit.app").rstrip("/")

#: How long to wait for a cold start, generous on purpose: a budget shorter than a real
#: wake turns a slow success into a red run, and a check that misreports is worse than no
#: check at all.
WAKE_BUDGET = int(os.environ.get("WAKE_BUDGET", "900"))

HEALTH = f"{APP_URL}/~/+/_stcore/health"
STATUS = f"{APP_URL}/api/v2/app/status"
RESUME = f"{APP_URL}/api/v2/app/resume"

DASHBOARD = "https://share.streamlit.io"
STATUS_PAGE = "https://www.streamlitstatus.com"

#: Browsers already on the machine, tried in order before anything is downloaded. GitHub's
#: Ubuntu images ship Google Chrome, 24.04 and 26.04 alike, so a scheduled run fetches
#: nothing but the Python package and the app. `PROBE_CHROME` names another.
SYSTEM_BROWSERS = (
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/opt/google/chrome/chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
)

#: Downloads of Playwright's headless Chromium before giving up, on a machine with none of
#: the above. A blip on the runner's network is the usual reason one fails.
INSTALL_ATTEMPTS = 3

#: What a red run caused by the runner rather than the app should leave the reader with.
RUNNER_NOT_APP = (
    "That is the runner, not the app: the next scheduled run tries again, and one missed "
    "run still leaves eight hours before the app would sleep."
)

SLEEP_PAGE = re.compile(r"gone to sleep|Zzzz|get this app back up", re.I)
WAKE_SELECTORS = (
    '[data-testid="wakeup-button-viewer"]',
    '[data-testid="wakeup-button-owner"]',
    'text="Yes, get this app back up!"',
)
APP_VIEW = '[data-testid="stAppViewContainer"]'


def _get(url: str, timeout: int = 30) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "keepalive-probe"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(1024).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - unreachable is a result, not a crash
        return 0, f"{type(exc).__name__}: {exc}"


def _post(url: str, timeout: int = 45) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        data=b"",
        method="POST",
        headers={"User-Agent": "keepalive-probe", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(1024).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(1024).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def is_serving() -> bool:
    code, body = _get(HEALTH)
    return code == 200 and body.strip() == "ok"


def platform_status() -> str:
    """The platform's own status field, verbatim. For the log, not for a decision."""
    code, body = _get(STATUS)
    if code != 200:
        return f"http {code}"
    try:
        parsed = json.loads(body)
    except ValueError:
        return body[:200]
    keys = ("status", "platformStatus", "isCpuThrottled", "streamlitVersion")
    return json.dumps({key: parsed.get(key) for key in keys})


def _first_line(exc: BaseException) -> str:
    lines = str(exc).strip().splitlines()
    return (lines[0] if lines else type(exc).__name__)[:200]


def report(title: str, message: str) -> None:
    """One annotation at the top of the run page, and the same words in its summary."""
    flat = message.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print(f"::error title={title}::{flat}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"### {title}\n\n{message}\n")


def launch_browser(pw, at):
    """A browser to visit the app with, or None when this machine cannot provide one."""
    candidates = (os.environ.get("PROBE_CHROME", ""), *SYSTEM_BROWSERS)
    for path in dict.fromkeys(c for c in candidates if c):
        if not os.access(path, os.X_OK):
            continue
        try:
            browser = pw.chromium.launch(executable_path=path, args=["--no-sandbox"])
        except Exception as exc:  # noqa: BLE001 - the next candidate may start
            print(f"{at()} browser  {path} would not start: {_first_line(exc)}")
            continue
        print(f"{at()} browser  {path} {browser.version}")
        return browser

    fetched = False
    for attempt in range(INSTALL_ATTEMPTS + 1):
        try:
            browser = pw.chromium.launch(args=["--no-sandbox"])
        except Exception as exc:  # noqa: BLE001 - usually not downloaded yet
            print(f"{at()} browser  Playwright's Chromium would not start: {_first_line(exc)}")
        else:
            print(f"{at()} browser  Playwright's Chromium {browser.version}")
            return browser
        # Downloaded and still would not start: another download will not help.
        if fetched or attempt == INSTALL_ATTEMPTS:
            break
        if attempt:
            time.sleep(30 * attempt)
        print(f"{at()} browser  fetching it, attempt {attempt + 1} of {INSTALL_ATTEMPTS}")
        install = [sys.executable, "-m", "playwright", "install", "--only-shell", "chromium"]
        fetched = subprocess.run(install, check=False).returncode == 0
    return None


def open_app(page, at) -> str:
    """Load the app's page, a second time if the first does not arrive. Why, if neither did."""
    reason = ""
    for attempt in (1, 2):
        try:
            page.goto(f"{APP_URL}/", wait_until="domcontentloaded", timeout=120_000)
            return ""
        except Exception as exc:  # noqa: BLE001 - a dropped navigation is a result
            reason = _first_line(exc)
            print(f"{at()} GET      attempt {attempt} failed: {reason}")
        if attempt == 1:
            page.wait_for_timeout(30_000)
    return reason


def app_frame(page):
    """The frame the app is actually in.

    Community Cloud nests the app under `/~/+/` inside the shell, so the app view is
    never in the top-level document. Looking for it there finds nothing and reads exactly
    like an app that failed to start.
    """
    for frame in page.frames:
        try:
            if frame.query_selector(APP_VIEW):
                return frame
        except Exception:  # noqa: BLE001 - a frame can navigate mid-query
            continue
    return None


def main() -> int:
    # Line by line, so a wake can be watched live and a browser download's own output
    # lands where it happened rather than ahead of everything printed before it.
    sys.stdout.reconfigure(line_buffering=True)
    started = time.monotonic()

    def at() -> str:
        return f"[{time.monotonic() - started:6.1f}s]"

    serving = is_serving()
    print(f"{at()} health   {HEALTH} -> {'ok' if serving else 'NOT ok'}")
    print(f"{at()} status   {platform_status()}")

    if not serving:
        code, body = _post(RESUME)
        print(f"{at()} resume   POST -> http {code} {body[:160]!r}")
        print(f"{at()}          (logged only; the browser below is the guarantee)")

    health = "said ok" if serving else "did not say ok"

    with sync_playwright() as pw:
        browser = launch_browser(pw, at)
        if browser is None:
            print(f"{at()} FAILED: no browser would start, so the app was not visited")
            report("The runner could not start a browser",
                   "Neither a Chrome on the runner nor Playwright's Chromium would start, "
                   f"so the app was not visited. Its health check {health}. {RUNNER_NOT_APP}")
            return 1
        # The wait for a wake starts here, so time spent fetching a browser is not
        # taken out of it.
        waiting_since = time.monotonic()
        page = browser.new_page(viewport={"width": 1000, "height": 800})
        print(f"{at()} GET      {APP_URL}/")
        reason = open_app(page, at)
        if reason:
            print(f"{at()} FAILED: the page did not load")
            browser.close()
            if serving:
                verdict = ("Its health check said ok, so the runner's network is the likelier "
                           f"cause. {RUNNER_NOT_APP}")
            else:
                verdict = f"Its health check did not say ok either: check {STATUS_PAGE}."
            report("The app's page did not load",
                   f"{APP_URL}/ did not load in two attempts ({reason}). {verdict}")
            return 1
        page.wait_for_timeout(6_000)

        if SLEEP_PAGE.search(page.inner_text("body")[:2_000]):
            for selector in WAKE_SELECTORS:
                button = page.query_selector(selector)
                if button:
                    print(f"{at()} asleep;  clicking {selector}")
                    button.click()
                    break
            else:
                print(f"{at()} asleep but no wake control is offered")
        else:
            print(f"{at()} no sleep page")

        deadline = waiting_since + WAKE_BUDGET
        frame = None
        while time.monotonic() < deadline:
            frame = app_frame(page)
            if frame is not None:
                break
            page.wait_for_timeout(5_000)

        if frame is None:
            print(f"{at()} FAILED: no app view within {WAKE_BUDGET}s")
            print("  top-level text:", repr(page.inner_text("body")[:300]))
            browser.close()
            report("The app did not render",
                   f"No app view appeared within {WAKE_BUDGET}s of opening {APP_URL}/, and "
                   f"its health check {health} at the start of the run. Check {STATUS_PAGE} "
                   f"for an incident, then reboot the app from its menu on {DASHBOARD}.")
            return 1

        print(f"{at()} app view rendered in {frame.url[:100]}")

        # The composer, because an app view that renders empty is what a boot that died
        # halfway looks like, and that would otherwise pass as awake.
        composer = None
        while time.monotonic() < deadline:
            composer = frame.query_selector("textarea[placeholder]")
            if composer:
                break
            page.wait_for_timeout(2_000)

        if composer is None:
            print(f"{at()} FAILED: app view has no composer")
            print("  app frame text:", repr(frame.inner_text("body")[:300]))
            browser.close()
            report("The app rendered without its composer",
                   "The app view appeared but never drew the question box, which is what a "
                   f"boot that died halfway looks like. Read its logs under Manage app on "
                   f"{DASHBOARD}.")
            return 1

        print(f"{at()} composer {composer.get_attribute('placeholder')!r}")
        print(f"{at()} awake and serving")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

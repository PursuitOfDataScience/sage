#!/usr/bin/env python3
"""Every colour and design token this app declares, held against a baseline.

`tools/render_check.py` renders the app and measures it, and it is the right tool for
anything with a size: clipping, overlap, contrast, the gap between a question and its
answer. What it cannot do is notice that something is *a different colour than it was
yesterday* — a repaint is not a defect in any single render, so there is no bound for
it to fail. And it renders `static/app.css` against a replica of Streamlit's DOM,
which means it never reads `.streamlit/config.toml`: the file that decides what
Streamlit paints its own widgets with is invisible to the only UI check in CI.

Both gaps were one bug. #36 stated `[theme.dark] primaryColor` to stop a dark-mode
device getting the dark palette on Streamlit's white page, and picked the tint this
stylesheet uses for brand *text* on a near-black page. Streamlit spends `primaryColor`
on fills too, so the composer's send button — maroon since the app was written, asked
about by nobody — came out pale pink and shipped that way. Nothing was wrong with any
layout. Nothing failed. The reader found it.

So this is a different kind of check, and it does not measure anything. It reads every
colour-bearing declaration and every custom property out of `static/app.css`, every
value out of the `[theme]` tables in `.streamlit/config.toml`, and holds the lot
against `tools/palette_baseline.json`. Any drift fails, and the only way to accept a
repaint is `--update`, which puts the before and after in the commit where a reader
can see it. The point is not that changing a colour is wrong — it is that changing one
should never be silent.

    python tools/palette_check.py            # fail on any drift, and say what drifted
    python tools/palette_check.py --update   # accept the current values as the baseline

`tests/test_palette.py` runs the same comparison in-process, so `pytest -q` covers it
and no CI step has to be remembered. This file stays runnable on its own because
`--update` has to live somewhere.
"""

from __future__ import annotations

import json
import os
import re
import sys

import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CSS = os.path.join(ROOT, "static", "app.css")
JS = os.path.join(ROOT, "static", "app.js")
CONFIG = os.path.join(ROOT, ".streamlit", "config.toml")
BASELINE = os.path.join(HERE, "palette_baseline.json")

# Properties that put a colour on the page. Shorthands are in the list as well as the
# longhands, because `border: 1px solid var(--brand-line)` is where most of this
# stylesheet's borders get their colour and a rule that only knew `border-color` would
# not see any of them. A value with no colour in it (`border: none`, `box-shadow:
# none`) is still recorded: removing a border is as visible as recolouring one.
COLOUR_PROPERTIES = frozenset({
    "color", "background", "background-color", "background-image",
    "border", "border-color", "border-top", "border-right", "border-bottom",
    "border-left", "border-top-color", "border-right-color",
    "border-bottom-color", "border-left-color", "border-inline-start",
    "border-inline-end", "border-block-start", "border-block-end",
    "outline", "outline-color", "fill", "stroke", "box-shadow", "text-shadow",
    "caret-color", "accent-color", "text-decoration-color", "column-rule-color",
    "scrollbar-color", "-webkit-text-fill-color",
})


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _blocks(css: str):
    """Yield `(scope, selector, body)` for every declaration block in `css`.

    A hand-rolled brace walker rather than a CSS parser, because the alternative is a
    dependency in a repo whose test job installs four packages on purpose. `scope` is
    the enclosing at-rules joined by a space — `@media (prefers-color-scheme: dark)`
    for the dark palette — so the same selector under two schemes stays two entries.

    Quotes are tracked because a brace inside a string would otherwise unbalance the
    stack and silently swallow the rest of the file, which is exactly the sort of
    quiet failure this check exists to prevent.
    """
    stack: list[str] = []
    buf: list[str] = []
    quote = ""
    for ch in css:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == "{":
            stack.append("".join(buf).strip())
            buf = []
        elif ch == "}":
            body = "".join(buf)
            prelude = stack.pop() if stack else ""
            if body.strip():
                yield " ".join(stack), prelude, body
            buf = []
        else:
            buf.append(ch)


def _declarations(body: str):
    """Yield `(property, value)` pairs, whitespace collapsed."""
    for chunk in body.split(";"):
        if ":" not in chunk:
            continue
        prop, _, value = chunk.partition(":")
        prop = prop.strip().lower()
        value = " ".join(value.split())
        if prop and value:
            yield prop, value


def css_inventory(css: str) -> dict[str, str]:
    """Every custom property, and every declaration that paints something.

    Custom properties are taken whole rather than filtered down to the ones holding a
    colour: `:root` is this app's design system, and a radius or a transition changing
    under nobody's instruction is the same class of surprise as a hue changing.
    """
    found: dict[str, str] = {}
    seen: dict[str, int] = {}
    for scope, selector, body in _blocks(_strip_comments(css)):
        # Whitespace inside a selector list is normalised so that rewrapping a long
        # list of selectors does not read as a repaint.
        selector = " ".join(selector.split())
        for prop, value in _declarations(body):
            if not (prop.startswith("--") or prop in COLOUR_PROPERTIES):
                continue
            key = f"{scope} :: {selector} :: {prop}" if scope else f"{selector} :: {prop}"
            # The same property set twice under one selector is legal and used here
            # (fallbacks). Number the repeats so neither one hides the other.
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                key = f"{key} #{seen[key]}"
            found[key] = value
    return found


def config_inventory(settings: dict) -> dict[str, str]:
    """Every value in every `[theme]` table.

    All of it, not just the keys ending in `Color`. `font` is as visible as
    `primaryColor`, and `base` is the key whose absence put the dark palette on a
    white page in the first place — a check that only watched colours would have
    watched the wrong half of the file that broke.
    """
    theme = settings.get("theme", {})
    found: dict[str, str] = {}

    def walk(table: dict, path: str) -> None:
        for key, value in sorted(table.items()):
            if isinstance(value, dict):
                walk(value, f"{path}.{key}")
            else:
                found[f"{path} :: {key}"] = str(value)

    walk(theme, "theme")
    return found


# --- static/app.js, which the inventory above cannot see --------------------------
#
# `.claude/hooks/ui-guard.sh` fires on an edit to app.js and then runs this file.
# Measured: an app.js edit that repainted the page came back "271 declared colours
# and tokens, all unchanged" — the only check the hook has never opened the file that
# had just been edited, and said so in the words of a pass. Reassurance from a check
# that did not look is the thing this repo is written against.
#
# There is no colour literal in app.js to inventory. The appearance it decides travels
# in custom properties it measures and publishes, which app.css reads with a fallback:
# `right: var(--toggle-right, 16px)`. That is a contract across two files and nothing
# held it, and its failure mode is the quiet kind — rename or drop one side and the
# `var()` takes its fallback for ever, which renders, breaks no bound, fails no
# baseline, and is wrong at every width app.js was measuring for. CLAUDE.md records
# the half that went right (`--pick-right`/`--pick-bottom`, removed from both sides
# together) and app.css holds the near miss: `--strip-h` survives there only inside a
# comment, which is why the comments come out before anything is counted.
#
# So this is not an inventory and has no baseline: the two files are read and held
# against each other. There is nothing here for `--update` to accept, because a broken
# contract is a bug rather than a repaint.


def _strip_js_comments(js: str) -> str:
    """Block comments and whole-line comments out of app.js.

    Deliberately not a JavaScript parser: the only thing read out afterwards is token
    names inside string literals, and no comment in that file quotes one. Line
    comments are taken only where they start a line, so a `https://` inside a string
    is left alone.
    """
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.DOTALL)
    return re.sub(r"^[ \t]*//.*$", "", js, flags=re.MULTILINE)


def js_publishes(js: str) -> set[str]:
    """The custom properties app.js writes onto the page."""
    return set(re.findall(r"""['"](--[A-Za-z0-9-]+)['"]""", _strip_js_comments(js)))


def css_custom_properties(css: str) -> tuple[set[str], set[str]]:
    """`(declared, read)`: the properties app.css states, and the ones it reads."""
    css = _strip_comments(css)
    declared = {prop for _, _, body in _blocks(css)
                for prop, _ in _declarations(body) if prop.startswith("--")}
    read = set(re.findall(r"var\(\s*(--[A-Za-z0-9-]+)", css))
    return declared, read


#: A colour written as a value, in any of the notations CSS takes one in.
COLOUR_LITERAL = re.compile(
    r"#[0-9a-fA-F]{3,8}\b"
    r"|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color-mix|color)\s*\("
    r"|['\"](?:red|blue|green|yellow|orange|purple|white|black|maroon|pink|grey|gray"
    r"|silver|navy|teal|olive|lime|aqua|fuchsia|crimson|tomato)['\"]"
)


def js_colour_decisions(js: str) -> list[str]:
    """Lines where app.js decides a colour rather than measuring a position.

    The contract above catches a *name* going out of step. It cannot catch app.js
    setting a name that is in step to a colour of its own: measured, appending
    `setProperty('--brand', '#ff00ff')` to app.js and running this file reported
    everything unchanged, because `--brand` is declared in app.css and read there and
    nothing was asking where its value came from at runtime.

    So the rule is that colour is decided in `static/app.css` and
    `.streamlit/config.toml`, which the baseline above covers, and app.js measures
    geometry. That is already true of every line in the file — it holds no hex, no
    `rgb(`, no named colour and no write to a colour-bearing property, only `opacity`
    twice and `position` once — so this costs nothing today and fails the first time a
    colour is introduced where the baseline cannot see it. Deciding to paint from
    JavaScript is then a decision somebody makes here, out loud.
    """
    problems: list[str] = []
    for number, line in enumerate(_strip_js_comments(js).splitlines(), 1):
        if COLOUR_LITERAL.search(line):
            problems.append(
                f"  colour   static/app.js:{number} names a colour, which belongs in "
                f"app.css\n           or config.toml where the baseline can see it: "
                f"{line.strip()[:72]}")
            continue
        match = re.search(
            r"\.style\.([A-Za-z]+)\s*=|setProperty\(\s*['\"]([a-z-]+)['\"]", line)
        if not match:
            continue
        name = match.group(1) or match.group(2) or ""
        kebab = re.sub(r"([A-Z])", lambda m: "-" + m.group(1).lower(), name)
        if kebab in COLOUR_PROPERTIES:
            problems.append(
                f"  colour   static/app.js:{number} writes `{kebab}` from JavaScript, "
                f"which\n           puts a colour outside everything this check "
                f"reads: {line.strip()[:60]}")
    return problems


def token_contract() -> list[str]:
    """Every way static/app.css and static/app.js can disagree about appearance."""
    with open(CSS, encoding="utf-8") as handle:
        declared, read = css_custom_properties(handle.read())
    with open(JS, encoding="utf-8") as handle:
        js = handle.read()
    published = js_publishes(js)
    problems: list[str] = js_colour_decisions(js)
    for name in sorted(read - declared - published):
        problems.append(
            f"  orphan   static/app.css reads {name}, and neither app.css nor "
            f"app.js\n           ever sets it, so every use of it takes its "
            f"var() fallback")
    for name in sorted(published - read):
        problems.append(
            f"  unread   static/app.js publishes {name}, and static/app.css never "
            f"reads\n           it, so whatever it measures reaches nothing")
    return problems


CONTRACT_REMEDY = """
Nothing to accept here and no baseline to update: these are two files disagreeing, or
one of them deciding something the other owns. Either app.css is reading a property
nobody sets — in which case it has been silently drawing its fallback — or app.js is
measuring something no rule consumes, or app.js is naming a colour, which belongs in
app.css or .streamlit/config.toml where the baseline above can see it. Rename both
sides together, drop both sides together, or move the colour.
"""


def inventory() -> dict[str, dict[str, str]]:
    with open(CSS, encoding="utf-8") as handle:
        css = handle.read()
    with open(CONFIG, "rb") as handle:
        settings = tomllib.load(handle)
    return {
        "static/app.css": css_inventory(css),
        ".streamlit/config.toml": config_inventory(settings),
    }


def load_baseline() -> dict[str, dict[str, str]]:
    with open(BASELINE, encoding="utf-8") as handle:
        return json.load(handle)


def save_baseline(current: dict[str, dict[str, str]]) -> None:
    with open(BASELINE, "w", encoding="utf-8") as handle:
        json.dump(current, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")


def diff(baseline: dict, current: dict) -> list[str]:
    """Lines describing every drift, or an empty list."""
    lines: list[str] = []
    for source in sorted(set(baseline) | set(current)):
        was, now = baseline.get(source, {}), current.get(source, {})
        for key in sorted(set(was) | set(now)):
            if key not in now:
                lines.append(f"  gone     {source}\n    {key}\n      was  {was[key]}")
            elif key not in was:
                lines.append(f"  new      {source}\n    {key}\n      now  {now[key]}")
            elif was[key] != now[key]:
                lines.append(f"  changed  {source}\n    {key}\n"
                             f"      was  {was[key]}\n      now  {now[key]}")
    return lines


REMEDY = """
If you meant to change how the app looks, run

    python tools/palette_check.py --update

and commit tools/palette_baseline.json in the same change, so the diff says in one
place what was repainted and the reader can disagree with it.

If you did not mean to, you have just changed the appearance of something nobody
asked you to change — which is how a maroon send button became a pink one. Find out
which declaration did it before going any further.
"""


def main() -> int:
    # Before either mode and in both of them, because this is the only thing here that
    # reads static/app.js — which the hook fires on and the inventory cannot see — and
    # because a broken contract is a bug rather than a repaint, so `--update` is not
    # how it gets accepted.
    #
    # Reported and then fallen through rather than returned on: one edit can do both,
    # and the first version of this stopped at the contract. Deleting the whole
    # `#theme-toggle` rule breaks the contract (nothing reads `--toggle-right` any
    # more) AND removes three colours from the baseline, and the run that says only
    # the first of those has told you the smaller half of what you did.
    contract = token_contract()
    if contract:
        noun = "thing" if len(contract) == 1 else "things"
        print(f"palette_check: {len(contract)} {noun} static/app.css and "
              "static/app.js do not agree on:\n")
        print("\n".join(contract))
        print(CONTRACT_REMEDY)

    if "--update" in sys.argv[1:]:
        current = inventory()
        before = load_baseline() if os.path.exists(BASELINE) else {}
        drift = diff(before, current)
        save_baseline(current)
        counted = sum(len(v) for v in current.values())
        if drift:
            print(f"palette_check: baseline updated, {len(drift)} entries changed:")
            print("\n".join(drift))
        else:
            print("palette_check: baseline unchanged.")
        print(f"palette_check: {counted} declarations recorded.")
        return 1 if contract else 0

    if not os.path.exists(BASELINE):
        print("palette_check: no baseline. Run with --update to write the first one.")
        return 1

    drift = diff(load_baseline(), inventory())
    if not drift:
        counted = sum(len(v) for v in inventory().values())
        print(f"palette_check: {counted} declared colours and tokens, all unchanged.")
        return 1 if contract else 0

    plural = "declaration" if len(drift) == 1 else "declarations"
    print(f"palette_check: {len(drift)} {plural} changed the way this app looks, "
          "and the baseline was not told.\n")
    print("\n".join(drift))
    print(REMEDY)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

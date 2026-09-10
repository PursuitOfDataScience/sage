"""Nothing changes colour here without the change saying so.

`tools/render_check.py` measures the app and fails on bounds: clipping, overlap, a
control painted over, contrast under AA. A repaint breaks no bound. Something that
used to be maroon and is now pink renders perfectly at every width in both themes,
and every check this repo had said so — the send button was pale pink for a day
because there was no mechanism that could describe the problem, let alone catch it.

And the harness renders `static/app.css` against a replica of Streamlit's DOM, so it
never opens `.streamlit/config.toml`. That is the file the pink actually came from:
Streamlit paints its own widgets with `primaryColor`, and the send button is one of
them. The one UI check in CI was structurally blind to the source of the bug.

So `tools/palette_check.py` takes an inventory instead of a measurement — every
colour-bearing declaration and every custom property in the stylesheet, every value in
the config's theme tables — and this holds it against the checked-in baseline. Run
against the two commits either side of #36 it reports exactly three drifts, all three
of them the theme change, and nothing else in that large commit: the mechanism is
specific to the class of thing it is for.

Updating the baseline is how a deliberate repaint is declared. That is the whole
design: not that colours may not change, but that changing one is never silent.
"""

from __future__ import annotations

import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: The two ways into the dark palette, as `tools/palette_check.py` keys them. Written
#: out rather than discovered, so renaming or dropping either block fails here instead
#: of quietly leaving the comparison below with nothing to compare.
SYSTEM_DARK = (
    '@media (prefers-color-scheme: dark) :: '
    ':root:not([data-sage-theme="light"]) :: '
)
CHOSEN_DARK = ':root[data-sage-theme="dark"] :: '


def _palette_check():
    path = os.path.join(ROOT, "tools", "palette_check.py")
    spec = importlib.util.spec_from_file_location("palette_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestPalette:
    def test_nothing_was_repainted_without_the_baseline_saying_so(self):
        palette = _palette_check()
        drift = palette.diff(palette.load_baseline(), palette.inventory())
        assert not drift, (
            "the app's declared appearance has changed and tools/palette_baseline.json "
            "was not updated with it:\n\n" + "\n".join(drift) + "\n\n"
            "If the change was wanted, run `python tools/palette_check.py --update` and "
            "commit the baseline with it, so the diff records what was repainted. If it "
            "was not wanted, something has just restyled the app unasked."
        )

    def test_the_config_theme_is_covered(self):
        """The channel the pink came through, and the one the replica cannot see."""
        palette = _palette_check()
        config = palette.inventory()[".streamlit/config.toml"]
        assert "theme.dark :: primaryColor" in config
        assert "theme.light :: primaryColor" in config

    def test_the_send_button_fill_is_covered(self):
        """The control this check was built for. If the rule is ever renamed or
        dropped, the entry goes with it — and that is drift, which fails above."""
        palette = _palette_check()
        css = palette.inventory()["static/app.css"]
        fills = [key for key in css if "stChatInput button" in key and ":: background" in key]
        assert fills, "no send-button fill in the inventory"

    def test_both_schemes_are_inventoried_separately(self):
        """A dark-mode override must not collapse onto the light declaration.

        Keying on the selector alone would let a retint of the dark palette read as no
        change at all, which is most of what a palette can get wrong.
        """
        palette = _palette_check()
        css = palette.inventory()["static/app.css"]
        assert ":root :: --brand-text" in css
        assert SYSTEM_DARK + "--brand-text" in css
        assert css[":root :: --brand-text"] != css[SYSTEM_DARK + "--brand-text"]

    def test_chosen_dark_matches_system_dark(self):
        """The two dark palettes in app.css are the same palette.

        There are two because there have to be. One is reached when the browser asks
        for dark and the reader has not overridden it; the other when the reader picks
        dark from the toggle in the composer — a media query cannot be made to match on
        an attribute, and CSS has no way to give one declaration list to two
        conditions. (`light-dark()` and style queries each would, and both are recent
        enough that a reader's browser may not have them.)

        So the duplication is deliberate, and this is what makes it safe. A drifted
        copy does not break a layout or fail a bound: the reader picks dark and gets
        most of it, with one token still holding a light value on a near-black page.
        That is how a source link ends up at 1.9:1 and stays there — the exact failure
        `.streamlit/config.toml` already carries a paragraph about.
        """
        palette = _palette_check()
        css = palette.inventory()["static/app.css"]
        system = {
            key[len(SYSTEM_DARK):]: value
            for key, value in css.items() if key.startswith(SYSTEM_DARK)
        }
        chosen = {
            key[len(CHOSEN_DARK):]: value
            for key, value in css.items() if key.startswith(CHOSEN_DARK)
        }
        assert system, "no dark palette under prefers-color-scheme in app.css"
        missing = sorted(set(system) - set(chosen))
        extra = sorted(set(chosen) - set(system))
        assert not missing, (
            "the reader-chosen dark palette is missing tokens the browser-chosen one "
            f"has, so picking dark leaves these light: {missing}"
        )
        assert not extra, (
            "the reader-chosen dark palette declares tokens the browser-chosen one "
            f"does not, so a dark-mode device does not get them: {extra}"
        )
        differing = sorted(key for key in system if system[key] != chosen[key])
        assert not differing, (
            "the two dark palettes disagree on: "
            + ", ".join(f"{key} ({system[key]} vs {chosen[key]})" for key in differing)
        )

    def test_a_repaint_is_detected(self):
        """The check has to be able to fail, or it is decoration.

        Moving the dark primary is the actual regression, in the actual file: it is
        still #f0a8ac there, which is right for everything Streamlit tints that is
        text rather than a fill. What must never happen again is it moving quietly.
        """
        palette = _palette_check()
        current = palette.inventory()
        repainted = {source: dict(entries) for source, entries in current.items()}
        key = "theme.dark :: primaryColor"
        assert repainted[".streamlit/config.toml"][key] != "#ff00ff"
        repainted[".streamlit/config.toml"][key] = "#ff00ff"
        drift = palette.diff(current, repainted)
        assert len(drift) == 1
        assert key in drift[0] and "#ff00ff" in drift[0]

    def test_a_css_repaint_is_detected_under_the_right_scheme(self):
        """And the same for the stylesheet, in one scheme only.

        The send button is the case in hand: its fill is stated once and inherited by
        both themes, so a change to it has to surface as exactly one drift naming the
        rule — not as silence, and not as a wall of unrelated entries.
        """
        palette = _palette_check()
        css = palette.css_inventory(
            ":root { --brand: #800000; }\n"
            "@media (prefers-color-scheme: dark) { :root { --brand-text: #f0a8ac; } }"
        )
        pinker = dict(css, **{":root :: --brand": "#f0a8ac"})
        drift = palette.diff({"static/app.css": css}, {"static/app.css": pinker})
        assert len(drift) == 1
        assert "--brand" in drift[0]
        assert "was  #800000" in drift[0] and "now  #f0a8ac" in drift[0]

    def test_a_rewrapped_selector_list_is_not_a_repaint(self):
        """And it has to be able to pass, or it will be turned off.

        A check that cries at reformatting gets `--update`d reflexively, which is the
        same as not having it.
        """
        palette = _palette_check()
        one = palette.css_inventory(".a,\n.b {\n  color: red;\n}")
        two = palette.css_inventory(".a, .b { color: red }")
        assert one == two and one

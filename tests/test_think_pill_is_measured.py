"""The layout harness must render the marker that keeps the Think pill alive.

`tools/render_check.py` renders `<button id="think-btn">` inside the composer and then
runs the real `static/app.js` over it, which is the right way round: the pill is
injected in the app, so a replica that draws it by hand has to survive the injector
that owns it.

`addThinkButton` owns it by REMOVING it when `#think-state` is absent. That guard is
the `View.can_think` path — a failover onto a provider with no `reasoning` parameter
stops rendering the marker, and a pill left behind would be a control with no widget
under it. So a replica that renders the pill and not the marker is a replica where
app.js deletes the pill on its first pass, and every check keyed on `#think-btn`
measures a node that is not in the document:

    PICKER = "#think-btn"        # its collapsed width, that it is inside the box,
    STRIP  = "#think-btn"        # level with the others, clear of the send button,
                                 # below the text, its white-on-maroon "on" fill,
                                 # and both reachability checks

Every one of those is written `if element and ...`, so they do not fail — they pass
without looking. Measured 2026-09-12 against `SCENARIOS["think-on"]`: the pill is
`REMOVED BY app.js` in both the at-rest and the generating render, and a full run
reports "No layout or contrast problems found" across all 684. That is the failure
mode this repository has a standing rule about: a check that cannot fail reads as a
pass, which is worse than no check.

Adding the marker to `page()` — one hidden `<div>`, the same one `composer.py` emits —
is the whole fix, and it restores more than it looks like. app.js does not keep the
replica's pill: the node it finds is parented to Streamlit's inner wrapper, not to
`[data-testid="stChatInput"]`, so the repaint path declines it and the pill is rebuilt
where the app really puts it — the wrapper's SIBLING, which is the nesting app.css's
z-index comment turns on. With the marker in place the harness measures the pill in
the app's own shape, and its hit test starts reading the composer the way an audit
with `elementFromPoint` did.

This test is a string check on the markup and needs no browser, the same arrangement
`test_documented_numbers.py` uses to hold the render count against the loop that
produces it.
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def harness():
    """The layout harness as a module. Importing it launches no browser."""
    tools = os.path.join(ROOT, "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import render_check  # noqa: PLC0415

    return render_check


class TestTheReplicaKeepsThePill:
    """Held for both turn states, because the pill is checked in both."""

    @pytest.mark.parametrize("generating", [False, True], ids=["at-rest", "generating"])
    @pytest.mark.parametrize("think_on", [False, True], ids=["off", "on"])
    def test_a_rendered_pill_comes_with_its_marker(self, harness, generating, think_on):
        # The first scenario rather than one by name: the scenario list is the harness's
        # own and a test that pins a name there breaks on a rename that changes nothing.
        body = harness.SCENARIOS[next(iter(harness.SCENARIOS))]
        html = harness.page(
            body, "light", False, generating=generating, think_on=think_on
        )
        if 'id="think-btn"' not in html:
            pytest.skip("this render draws no pill, so there is nothing to keep alive")
        assert 'id="think-state"' in html, (
            "the replica renders #think-btn without #think-state, so app.js removes "
            "the pill on its first pass and every check keyed on it passes without "
            "looking — render `composer.render_think_toggle`'s marker too: "
            '<div id="think-state" data-on="1" data-label="…" data-hint="…" hidden>'
        )

    def test_the_marker_carries_what_app_js_reads_off_it(self, harness):
        """`data-label` decides whether the pill is rebuilt; `data-hint` names it.

        `addThinkButton` compares `existing.dataset.label` with the marker's
        `data-label` and rebuilds when they differ, and it takes the `title` and the
        `aria-label` from `data-hint`. A marker with neither would keep the pill on the
        page and leave the harness measuring a control with no accessible name.
        """
        body = harness.SCENARIOS[next(iter(harness.SCENARIOS))]
        html = harness.page(body, "light", False)
        if 'id="think-state"' not in html:
            pytest.skip("no marker to inspect yet — the test above is the one to read")
        marker = html[html.index('id="think-state"'):]
        marker = marker[: marker.index(">")]
        for attribute in ("data-label", "data-hint"):
            assert attribute in marker, (
                f"#think-state has no {attribute}; app.js reads it to label the pill "
                f"and to decide whether a profile's copy has changed under a session"
            )

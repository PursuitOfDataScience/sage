"""The lineup drift check, offline.

`tools/lineup_check.py` is the answer to "does this repository still describe the
models the provider actually serves". Every part of it that talks to the network is
injected here, because the one thing a check like this must not do is need the network
to be tested — and because a free tier's catalogue is precisely the input that cannot
be relied on to hold still for a test.

What is worth holding it to, in order of what it would cost to get wrong:

* **Free is decided by the profile's rule, not a copy of it.** Two definitions of
  "free" is the bug this whole mechanism exists to prevent, and a second one living in
  the checker would be the funniest possible place for it.
* **Nothing is reordered, and nothing is removed for being broken today.** The first
  entry of the profile's list is what every fresh session starts on and what an
  automatic failover lands on. Retirement is a separate thing from breakage and has to
  clear a threshold in days: `hy3-free` was gone from the catalogue for two days and
  came back, so one day's listing is not evidence.
* **A quiet day is quiet.** A daily report that always has something in it is a daily
  report nobody reads, so latency wobble is not news and a first run is not drift.
* **Account state does not reach the ledger**, which is committed to a public repo.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import types
from dataclasses import replace

import pytest

from sage import config, profile, providers
from tools import lineup_check

ZEN = profile.active().provider("opencode")


def zen(**overrides):
    return replace(ZEN, **overrides)


def options(**overrides) -> argparse.Namespace:
    base = {
        "provider": "opencode",
        "ledger": "",
        "probe": False,
        "probe_budget": 12,
        "update": False,
        "retire_after": 7,
        "summary_out": "",
        "fail_on_drift": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestFreeIsTheProfilesRule:
    def test_it_asks_the_adapter_rather_than_matching_its_own_pattern(self):
        """The point of `free_marks` is that there is one definition of free.

        `-contributor-free` is the case that makes this concrete: it is not the `-free`
        suffix the convention was written for, but the rule matches substrings, so the
        picker offered `muse-spark-1.2-contributor-free` before anything named it. A
        checker with its own endswith test would have called it paid and filed a bug
        against reality.
        """
        entry = zen()
        assert lineup_check.is_free(entry, "muse-spark-1.2-contributor-free")
        assert lineup_check.is_free(entry, "hy3-free")
        assert lineup_check.is_free(entry, "big-pickle")
        assert not lineup_check.is_free(entry, "claude-opus-5")
        assert not lineup_check.is_free(entry, "gpt-5.2-codex")

    def test_widening_the_rule_widens_the_check(self):
        entry = zen(free_marks=("-free", "big-pickle", "muse-"))
        assert lineup_check.is_free(entry, "muse-anything")
        assert not lineup_check.is_free(zen(), "muse-anything")


class TestATOolCallIsNotAnAnswer:
    """The gap that let a broken model stay in the picker for a day.

    `nemotron-3-ultra-free` was recorded `answered: true` with `tool_calls: 2` and
    `chars: 0` — two calls and not one word — while readers were being told "the model
    returned an empty answer". `probe` counts either as answering, `failing_since` never
    opened an entry, and the seven-day clock that would have denied it never started.

    The asymmetry is in the app: `turn.run` sends the last request of a turn with the
    tools withdrawn, because a model that answers every round with another tool call
    otherwise never reaches the round that writes prose. Whatever that request returns
    is the answer. So the probe has to ask that question too.
    """

    def replies(self, monkeypatch, *rounds):
        """Script `probe` by call order, and record how it was asked each time."""
        asked = []

        def fake(entry, key, model_id, *, tools=True):
            asked.append(tools)
            return {"model": model_id, **rounds[len(asked) - 1]}

        monkeypatch.setattr(lineup_check, "probe", fake)
        return asked

    def test_prose_on_the_first_ask_is_the_end_of_it(self, monkeypatch):
        """The common case must not cost a second request."""
        asked = self.replies(
            monkeypatch, {"status": 200, "chars": 40, "tool_calls": 1, "answered": True}
        )
        verdict = lineup_check.verdict_for(zen(), "", "m1")
        assert verdict["answered"] is True
        assert asked == [True], "a working model was probed twice"

    def test_a_tool_call_with_no_prose_is_asked_again_without_tools(self, monkeypatch):
        asked = self.replies(
            monkeypatch,
            {"status": 200, "chars": 0, "tool_calls": 2, "answered": True, "seconds": 21},
            {"status": 200, "chars": 180, "answered": True, "seconds": 2},
        )
        verdict = lineup_check.verdict_for(zen(), "", "m1")
        assert asked == [True, False], "the second ask must withdraw the tools"
        assert verdict["answered"] is True, (
            "it can write prose when nothing else is on offer, which is all the app "
            "needs of it"
        )
        assert verdict["prose_chars"] == 180

    def test_a_model_that_only_ever_calls_tools_is_failing(self, monkeypatch):
        """The verdict that was wrong. Two calls, no words, and nothing to say when
        the tools are taken away — which is every turn this app runs."""
        asked = self.replies(
            monkeypatch,
            {"status": 200, "chars": 0, "tool_calls": 2, "answered": True, "seconds": 21},
            {"status": 200, "chars": 0, "answered": False, "seconds": 19},
        )
        verdict = lineup_check.verdict_for(zen(), "", "m1")
        assert asked == [True, False]
        assert verdict["answered"] is False

    def test_the_first_request_is_still_what_the_verdict_describes(self, monkeypatch):
        """Only the judgement changes. Latency and tool calls stay the early rounds'
        numbers, because those are the requests the app actually makes most of."""
        self.replies(
            monkeypatch,
            {"status": 200, "chars": 0, "tool_calls": 2, "answered": True,
             "seconds": 21, "tier": "free"},
            {"status": 200, "chars": 0, "answered": False, "seconds": 19},
        )
        verdict = lineup_check.verdict_for(zen(), "", "m1")
        assert verdict["seconds"] == 21
        assert verdict["tool_calls"] == 2
        assert verdict["tier"] == "free"

    def test_a_refusal_is_not_asked_twice(self, monkeypatch):
        """A 4xx or 5xx already said everything. Spending a second request on it is
        the one direction this change must not add cost in."""
        asked = self.replies(
            monkeypatch,
            {"status": 500, "error": "Internal server error", "answered": False},
        )
        assert lineup_check.verdict_for(zen(), "", "m1")["answered"] is False
        assert asked == [True]

    def test_the_report_says_which_of_the_two_shapes_it_is(self, monkeypatch):
        """A model that is up and cannot finish a turn reads the same to a reader as a
        dead endpoint — both are the error card — so the report has to tell them
        apart or nobody can act on either."""
        self.replies(
            monkeypatch,
            {"status": 200, "chars": 0, "tool_calls": 2, "answered": True, "seconds": 21},
            {"status": 200, "chars": 0, "answered": False, "seconds": 19},
        )
        note = lineup_check._verdict_note(lineup_check.verdict_for(zen(), "", "m1"))
        assert "tool call" in note
        assert "no prose" in note
        assert "tools withdrawn" in note

    def test_a_stream_that_carried_nothing_at_all_still_reads_that_way(self):
        """The other shape, unchanged: no calls and no text is a dead endpoint."""
        note = lineup_check._verdict_note(
            {"status": 200, "chars": 0, "tool_calls": 0, "answered": False,
             "seconds": 300.23}
        )
        assert "empty completion" in note
        assert "tool call" not in note


class TestReview:
    def test_it_separates_appeared_from_vanished_from_unclassified(self):
        entry = zen(models=("a-free", "gone-free"))
        got = lineup_check.review(
            entry, ["a-free", "new-free", "claude-opus-5"], {"providers": {}}
        )
        assert got["appeared"] == ["new-free"]
        assert got["vanished"] == ["gone-free"]
        # The only candidate for the next `big-pickle`, and the only name a probe is
        # worth spending on.
        assert got["unclassified"] == ["claude-opus-5"]
        assert got["free"] == ["a-free", "new-free"]

    def test_a_name_the_ledger_has_already_priced_is_not_probed_again(self):
        """This is what keeps a daily run at nearly zero requests.

        Fifty-five of Zen's sixty-three models are paid. Re-probing them every morning
        would be fifty-five requests a day to re-learn a fact that does not change.
        """
        ledger = {"providers": {"opencode": {"paid": ["claude-opus-5"]}}}
        got = lineup_check.review(
            zen(models=()), ["claude-opus-5", "gpt-5.2"], ledger
        )
        assert got["unclassified"] == ["gpt-5.2"]

    def test_missing_since_accrues_instead_of_being_recomputed(self):
        """The profile keeps a model that is broken today, on the grounds that a free
        tier's outages end. What it could not say is how long a given one has run."""
        ledger = {
            "providers": {
                "opencode": {"missing_since": {"gone-free": "2026-01-01"}, "paid": []}
            }
        }
        got = lineup_check.review(zen(models=("gone-free", "also-free")), [], ledger)
        assert got["missing_since"]["gone-free"] == "2026-01-01"
        assert got["missing_since"]["also-free"] == lineup_check.today()

    def test_a_returning_model_stops_being_missing(self):
        ledger = {
            "providers": {
                "opencode": {"missing_since": {"hy3-free": "2026-01-01"}, "paid": []}
            }
        }
        got = lineup_check.review(zen(models=("hy3-free",)), ["hy3-free"], ledger)
        assert got["missing_since"] == {}

    def test_it_notices_the_configured_default_is_not_served(self, monkeypatch):
        """Not an outage — `app.current_model` falls through to the first discovered
        model — but `SAGE_DEFAULT_MODEL` is a fiction until somebody changes it."""
        monkeypatch.setattr(config, "DEFAULT_MODEL", "opencode:vanished-free")
        got = lineup_check.review(zen(models=()), ["hy3-free"], {"providers": {}})
        assert got["default_missing"] is True

    def test_it_notices_the_rule_matching_nothing(self):
        """With `free_only` set this is the state where the picker offers the entire
        paid lineup as if it worked. The adapter logs it; nobody reads those logs."""
        got = lineup_check.review(
            zen(models=()), ["claude-opus-5", "gpt-5.2"], {"providers": {}}
        )
        assert got["rule_matched_nothing"] is True


class TestMaterialChange:
    def test_a_first_run_is_not_drift(self):
        """An empty ledger listed all eight free models as news, which is the report a
        reader learns to skim past."""
        after = lineup_check.review(zen(), ["hy3-free"], {"providers": {}})
        reasons = lineup_check.material({"free": None, "verdicts": {}}, after)
        assert len(reasons) == 1
        assert "first record" in reasons[0]

    def test_latency_alone_is_not_news(self, monkeypatch):
        monkeypatch.setattr(config, "DEFAULT_MODEL", "opencode:hy3-free")
        after = lineup_check.review(
            zen(models=("hy3-free",)), ["hy3-free"], {"providers": {}}
        )
        after["verdicts"] = {"hy3-free": {"answered": True, "seconds": 9.9}}
        after["candidates"] = []
        before = {
            "free": ["hy3-free"],
            "verdicts": {"hy3-free": {"answered": True, "seconds": 0.4}},
        }
        assert lineup_check.material(before, after) == []

    def test_a_verdict_flipping_is_news_in_both_directions(self):
        after = lineup_check.review(
            zen(models=("hy3-free",)), ["hy3-free"], {"providers": {}}
        )
        after["candidates"] = []
        after["verdicts"] = {"hy3-free": {"answered": False}}
        before = {"free": ["hy3-free"], "verdicts": {"hy3-free": {"answered": True}}}
        assert any("stopped answering" in reason
                   for reason in lineup_check.material(before, after))

        after["verdicts"] = {"hy3-free": {"answered": True}}
        before = {"free": ["hy3-free"], "verdicts": {"hy3-free": {"answered": False}}}
        assert any("answers again" in reason
                   for reason in lineup_check.material(before, after))

    def test_a_new_free_model_is_news(self):
        after = lineup_check.review(
            zen(models=("hy3-free",)), ["hy3-free", "new-free"], {"providers": {}}
        )
        after["candidates"] = []
        before = {"free": ["hy3-free"], "verdicts": {}}
        reasons = lineup_check.material(before, after)
        assert any("`new-free` is now served free" in reason for reason in reasons)

    def test_a_stealth_candidate_is_news(self):
        after = lineup_check.review(zen(), ["hy3-free"], {"providers": {}})
        after["candidates"] = ["big-cucumber"]
        after["verdicts"] = {}
        reasons = lineup_check.material({"free": ["hy3-free"], "verdicts": {}}, after)
        assert any("without matching `free_marks`" in reason for reason in reasons)


class TestAppendModels:
    PROFILE = '''\
[[providers]]
name = "opencode"
kind = "openai"
# A comment that has to survive.
models = [
    # Why this one is first.
    "first-free",
    "second-free",
]
free_marks = ["-free"]

[[providers]]
name = "other"
models = ["untouched"]
'''

    def test_it_appends_at_the_end_and_keeps_every_comment(self):
        got = lineup_check.append_models(self.PROFILE, "opencode", ["new-free"])
        assert "# Why this one is first." in got
        assert "# A comment that has to survive." in got
        lines = [line.strip() for line in got.splitlines()]
        assert lines.index('"new-free",') > lines.index('"second-free",')

    def test_it_never_reorders_or_removes(self):
        """The first entry decides what every fresh session starts on and what a
        failover lands on. A daily job that reordered it would be choosing, once a day,
        which model every reader gets — from a catalogue listing that says nothing about
        whether the model is any good."""
        got = lineup_check.append_models(self.PROFILE, "opencode", ["new-free"])
        kept = [line for line in got.splitlines() if line.strip().startswith('"')]
        assert [line.strip() for line in kept][:3] == [
            '"first-free",', '"second-free",', '"new-free",'
        ]

    def test_it_leaves_other_providers_alone(self):
        got = lineup_check.append_models(self.PROFILE, "opencode", ["new-free"])
        assert 'models = ["untouched"]' in got

    def test_it_handles_a_single_line_list(self):
        text = '[[providers]]\nname = "p"\nmodels = ["a", "b"]\n'
        got = lineup_check.append_models(text, "p", ["c"])
        assert got == '[[providers]]\nname = "p"\nmodels = ["a", "b", "c"]\n'

    def test_nothing_to_add_changes_nothing(self):
        assert lineup_check.append_models(self.PROFILE, "opencode", []) == self.PROFILE

    def test_an_unknown_provider_raises_rather_than_writing_the_wrong_block(self):
        with pytest.raises(ValueError):
            lineup_check.append_models(self.PROFILE, "absent", ["x"])

    def test_the_result_still_parses_as_the_profile_it_was(self, tmp_path):
        """The check that matters: an edit that produced valid-looking text but an
        unparseable profile would take the app down, and this runs unattended."""
        source = profile.active().origin
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        target = tmp_path / "rcc.toml"
        target.write_text(lineup_check.append_models(text, "opencode", ["probe-free"]))
        loaded = profile.load(str(target))
        entry = loaded.provider("opencode")
        assert entry.models[-1] == "probe-free"
        assert entry.models[0] == ZEN.models[0], "the failover target moved"
        assert loaded.identity.name == profile.active().identity.name


class TestRetireModels:
    """Taking a model off the list, which this check used only to report.

    Four models sat in the profile for three days, absent from the catalogue, reported
    to an issue every morning and removed by nobody. So the retirement is an edit now.
    What these hold is the two ways that edit could do damage: a threshold short enough
    to act on an outage, and a removal that guts the comments around it.
    """

    PROFILE = '''\
[[providers]]
name = "opencode"
kind = "openai"
# A comment that has to survive.
models = [
    # Why this one is first, compared with second-free.
    "first-free",
    # All about the second one, and nothing else.
    "second-free",
    "third-free",
]
free_marks = ["-free"]

[[providers]]
name = "other"
models = ["untouched"]
'''

    def test_it_removes_the_entry(self):
        got = lineup_check.retire_models(self.PROFILE, "opencode", ["third-free"])
        assert '"third-free",' not in got
        assert '"first-free",' in got and '"second-free",' in got

    def test_a_removed_entry_takes_its_own_comment_with_it(self):
        """An orphaned comment is worse than no comment: it reads as documentation of
        whichever entry it ends up above."""
        got = lineup_check.retire_models(self.PROFILE, "opencode", ["second-free"])
        assert "# All about the second one" not in got
        assert "# A comment that has to survive." in got

    def test_a_comment_naming_another_model_stays(self):
        """The first entry's note explains its rank by comparison with another entry in
        the list, so it is not a note about the line it happens to sit on."""
        got = lineup_check.retire_models(self.PROFILE, "opencode", ["first-free"])
        assert '"first-free",' not in got
        assert "# Why this one is first, compared with second-free." in got

    def test_it_leaves_other_providers_alone(self):
        got = lineup_check.retire_models(self.PROFILE, "opencode", ["first-free"])
        assert 'models = ["untouched"]' in got

    def test_it_handles_a_single_line_list(self):
        text = '[[providers]]\nname = "p"\nmodels = ["a", "b", "c"]\n'
        got = lineup_check.retire_models(text, "p", ["b"])
        assert got == '[[providers]]\nname = "p"\nmodels = ["a", "c"]\n'

    def test_nothing_to_remove_changes_nothing(self):
        assert lineup_check.retire_models(self.PROFILE, "opencode", []) == self.PROFILE

    def test_an_unknown_provider_raises_rather_than_writing_the_wrong_block(self):
        with pytest.raises(ValueError):
            lineup_check.retire_models(self.PROFILE, "absent", ["x"])

    def test_the_result_still_parses_as_the_profile_it_was(self, tmp_path):
        """The one that matters: this runs unattended, and an edit that produced
        valid-looking text but an unparseable profile would take the app down."""
        source = profile.active().origin
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        going = ZEN.models[-1]
        target = tmp_path / "rcc.toml"
        target.write_text(lineup_check.retire_models(text, "opencode", [going]))
        loaded = profile.load(str(target))
        entry = loaded.provider("opencode")
        assert going not in entry.models
        assert entry.models[0] == ZEN.models[0], "the failover target moved"
        assert loaded.identity.name == profile.active().identity.name


class TestRetirementThreshold:
    """When an absence becomes a retirement.

    `hy3-free` is the case this is calibrated against: absent from the catalogue,
    answering 401, and served again two days later with nothing about this deployment
    changed. A check that acted on one day's listing would have removed a working
    model and then had to put it back.
    """

    @staticmethod
    def report(days_ago: int, names=("gone-free",)):
        stamp = (dt.date.today() - dt.timedelta(days=days_ago)).isoformat()
        return {
            "vanished": list(names),
            "missing_since": dict.fromkeys(names, stamp),
        }

    def test_a_two_day_absence_is_not_a_retirement(self):
        assert lineup_check.retiring(self.report(2), 7) == []

    def test_a_long_absence_is(self):
        assert lineup_check.retiring(self.report(9), 7) == ["gone-free"]

    def test_the_threshold_is_inclusive_on_the_day_it_falls_due(self):
        assert lineup_check.retiring(self.report(7), 7) == ["gone-free"]

    def test_zero_retires_nothing(self):
        """The behaviour this file had before the threshold existed, kept reachable so
        a deployment that wants report-only can have it."""
        assert lineup_check.retiring(self.report(400), 0) == []

    def test_an_absence_with_no_recorded_date_is_not_retired(self):
        """A lost ledger must not read as "gone for ever". The Actions cache is
        evictable, and the first run after an eviction knows nothing about history."""
        report = {"vanished": ["gone-free"], "missing_since": {}}
        assert lineup_check.retiring(report, 7) == []


class TestTierFromARefusal:
    """What a 4xx says about the tier, which is most of what a keyless probe learns.

    Measured against Zen, with no `Authorization` header: a paid model answers
    `AuthError: Missing API key.`, a rate-limited free one answers
    `FreeUsageLimitError`, and a free one answers 200 with a whole completion. With a
    *wrong* key the message is `Invalid API key.` instead — a broken key, not a paid
    model, and the difference between those two strings is the only thing stopping one
    typo from filing every model Zen serves as paid.
    """

    def test_a_missing_key_prices_the_model(self):
        body = '{"error":{"type":"AuthError","message":"Missing API key."}}'
        assert lineup_check._tier_of(body) == "paid"

    def test_an_invalid_key_prices_nothing(self):
        """The one that would do damage. This is a fact about the key."""
        body = '{"error":{"type":"AuthError","message":"Invalid API key."}}'
        assert lineup_check._tier_of(body) == "unknown"

    def test_a_free_usage_limit_is_evidence_of_the_free_tier(self):
        """`big-pickle` keyless. A free-usage limit is a thing only a free model has,
        so the refusal itself is the classification."""
        body = ('{"error":{"type":"FreeUsageLimitError","message":"Rate limit '
                'exceeded. Please try again later."}}')
        assert lineup_check._tier_of(body) == "free"

    def test_an_empty_balance_still_prices_the_model(self):
        """The keyed case, unchanged."""
        assert lineup_check._tier_of("CreditsError: insufficient balance") == "paid"

    def test_anything_else_stays_unknown(self):
        assert lineup_check._tier_of("502 Bad Gateway") == "unknown"
        assert lineup_check._tier_of("") == "unknown"


class TestProbingNeedsNoKey:
    """The probe used to be skipped entirely without a key, and the workflow has none.

    So the two findings that require a completion — a stealth codename, and a model
    that is served but answers nothing — were only ever checked by a deployment that
    had a secret, which is to say never. Zen serves its free models to a request
    carrying no `Authorization` header at all, so the key is an option.
    """

    class FakeResponse:
        status_code = 200

        def __init__(self, sent):
            self.sent = sent

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def iter_lines(self):
            return iter(["data: [DONE]"])

    class FakeClient:
        def __init__(self, sent, **_kwargs):
            self.sent = sent

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def stream(self, _method, _url, json=None, headers=None):
            self.sent.append(headers or {})
            return TestProbingNeedsNoKey.FakeResponse(self.sent)

    def fake_httpx(self, sent):
        module = types.ModuleType("httpx")
        module.Client = lambda **kwargs: TestProbingNeedsNoKey.FakeClient(sent, **kwargs)
        module.Timeout = lambda *args, **kwargs: None
        return module

    def test_no_key_means_no_authorization_header(self, monkeypatch):
        """Not an empty one. `Authorization: Bearer ` is an illegal header value and
        httpx refuses it locally, so the probe raised before it sent anything —
        recorded as a verdict of "unknown", which reads as a model that could not be
        reached rather than a bug here."""
        sent: list[dict] = []
        monkeypatch.setitem(sys.modules, "httpx", self.fake_httpx(sent))
        lineup_check.probe(ZEN, "", "some-free")
        assert sent and "Authorization" not in sent[0]

    def test_a_key_is_still_sent_when_there_is_one(self):
        sent: list[dict] = []
        with pytest.MonkeyPatch.context() as patch:
            patch.setitem(sys.modules, "httpx", self.fake_httpx(sent))
            lineup_check.probe(ZEN, "sk-zen-real", "some-free")
        assert sent[0]["Authorization"] == "Bearer sk-zen-real"

class TestAModelThatIsServedAndCannotAnswer:
    """The other way a model stops existing, and the one nothing here used to see.

    `muse-spark-1.2-contributor-free` returned `500 Internal server error` to every
    request while `GET /models` went on listing it and the picker went on offering it.
    Every daily run called that lineup healthy, because the probe queue was
    `appeared + unclassified` — and a model both named in the profile and free by the
    rule is in neither. The one finding that needed a completion was the one the queue
    could not reach.
    """

    @staticmethod
    def run_with(monkeypatch, tmp_path, verdicts, ledger=None, **opts):
        target = tmp_path / "rcc.toml"
        target.write_text(
            '[[providers]]\nname = "opencode"\nkind = "openai"\n'
            'base_url = "http://x/v1"\nkey_env = "OPENCODE_API_KEY"\n'
            'models = [\n    "good-free",\n    "sick-free",\n]\n'
            'free_marks = ["-free"]\nfree_only = true\n'
        )
        loaded = profile.load(str(target))
        monkeypatch.setattr(lineup_check, "_active", lambda: loaded)
        monkeypatch.setattr(lineup_check, "discoverable", lambda: list(loaded.providers))
        monkeypatch.setattr(
            lineup_check, "served", lambda entry, key="": ["good-free", "sick-free"]
        )
        monkeypatch.setattr(lineup_check.providers, "api_key", lambda name: "")
        monkeypatch.setattr(
            lineup_check, "probe",
            lambda entry, key, model_id, tools=True: dict(
                verdicts[model_id], model=model_id
            ),
        )
        path = tmp_path / "l.json"
        if ledger is not None:
            path.write_text(json.dumps(ledger))
        return target, lineup_check.run(
            options(ledger=str(path), probe=True, **opts)
        )

    HEALTHY = {"status": 200, "tier": "free", "answered": True, "chars": 40}
    DEAD = {"status": 500, "tier": "unknown", "answered": False,
            "error": "Internal server error"}
    LIMITED = {"status": 429, "tier": "free", "answered": False,
               "error": "FreeUsageLimitError: Rate limit exceeded"}

    def test_a_listed_free_model_is_probed_at_all(self, monkeypatch, tmp_path):
        seen = []
        target = tmp_path / "rcc.toml"
        target.write_text(
            '[[providers]]\nname = "opencode"\nkind = "openai"\n'
            'base_url = "http://x/v1"\nmodels = [\n    "good-free",\n]\n'
            'free_marks = ["-free"]\nfree_only = true\n'
        )
        loaded = profile.load(str(target))
        monkeypatch.setattr(lineup_check, "_active", lambda: loaded)
        monkeypatch.setattr(lineup_check, "discoverable", lambda: list(loaded.providers))
        monkeypatch.setattr(lineup_check, "served", lambda entry, key="": ["good-free"])
        monkeypatch.setattr(lineup_check.providers, "api_key", lambda name: "")
        monkeypatch.setattr(
            lineup_check, "probe",
            lambda entry, key, model_id, tools=True: seen.append(model_id) or {
                "model": model_id, "status": 200, "tier": "free", "answered": True},
        )
        lineup_check.run(options(ledger=str(tmp_path / "l.json"), probe=True))
        assert seen == ["good-free"], "the lineup a reader can pick went unchecked"

    def test_a_failure_is_reported_and_dated(self, monkeypatch, tmp_path):
        _, (_code, body, _changed) = self.run_with(
            monkeypatch, tmp_path,
            {"good-free": self.HEALTHY, "sick-free": self.DEAD},
        )
        assert "Served, and could not answer" in body
        assert "sick-free" in body and "failing since" in body

    def test_a_rate_limit_is_not_a_failure(self, monkeypatch, tmp_path):
        """A keyless probe is limited per address, so a popular model gets a 429 for
        being popular. Reading that as "broken" would retire a working model."""
        _, (_code, body, _changed) = self.run_with(
            monkeypatch, tmp_path,
            {"good-free": self.HEALTHY, "sick-free": self.LIMITED},
        )
        assert "Served, and could not answer" not in body

    def test_answering_again_clears_the_clock(self, monkeypatch, tmp_path):
        """`hy3-free` did exactly this. A model that recovers starts from nothing."""
        old = (dt.date.today() - dt.timedelta(days=4)).isoformat()
        ledger = {"providers": {"opencode": {
            "free": ["good-free", "sick-free"], "listed": ["good-free", "sick-free"],
            "paid": [], "missing_since": {}, "failing_since": {"sick-free": old},
            "verdicts": {}, "candidates": [],
        }}}
        _, (_code, body, _changed) = self.run_with(
            monkeypatch, tmp_path,
            {"good-free": self.HEALTHY, "sick-free": self.HEALTHY}, ledger=ledger,
        )
        assert "Served, and could not answer" not in body
        assert "answering again" in body

    @staticmethod
    def offered(target):
        """What the picker would actually show, which is the only thing that counts.

        Asserted through the adapter rather than off the profile field, because the
        two came apart and that gap is what the reader met as an error card: the
        picker's membership comes from discovery, so a name removed from `models` is
        still offered for as long as the provider serves it.
        """
        entry = profile.load(str(target)).provider("opencode")
        adapter = providers.adapters.get(entry.kind)(entry, "k")
        return [model.id for model in adapter.models()]

    def test_a_week_of_failing_takes_it_out_of_the_picker(self, monkeypatch, tmp_path):
        old = (dt.date.today() - dt.timedelta(days=9)).isoformat()
        ledger = {"providers": {"opencode": {
            "free": ["good-free", "sick-free"], "listed": ["good-free", "sick-free"],
            "paid": [], "missing_since": {}, "failing_since": {"sick-free": old},
            "verdicts": {}, "candidates": [],
        }}}
        target, (_code, body, _changed) = self.run_with(
            monkeypatch, tmp_path,
            {"good-free": self.HEALTHY, "sick-free": self.DEAD},
            ledger=ledger, update=True,
        )
        entry = profile.load(str(target)).provider("opencode")
        assert "sick-free" in entry.deny
        assert "sick-free" in entry.models, (
            "denying is not delisting: the record of what the provider is expected to "
            "serve is a different statement from what works today"
        )
        assert "Taken out of the picker" in body

    COMMENTED = (
        '[[providers]]\nname = "opencode"\nkind = "openai"\n'
        'models = ["good-free"]\n'
        "deny = [\n"
        '    "a-free",\n'
        "    # Added by hand, and how it got here is the point: the router returned an\n"
        "    # empty answer on 9 of 13 real turns and every failover to this one\n"
        "    # answered HTTP 500.\n"
        '    "b-free",\n'
        "]\n"
        'free_marks = ["-free"]\n'
    )

    def test_rewriting_the_denylist_keeps_the_reasoning(self):
        """The only thing that makes a denylist reviewable is why each name is on it.

        This rewrote the array to one line, and on the profile as it stands that deleted
        fourteen lines explaining the difference between "cannot be paid for" and "does
        not answer" — written by hand the same day. A list of names nobody can argue
        with is a list nobody can take off.
        """
        out = lineup_check.set_deny(self.COMMENTED, "opencode",
                                    ["a-free", "b-free", "c-free"])
        assert "answered HTTP 500" in out
        # Still attached to the name it explains, not floated to the top.
        lines = [line.strip() for line in out.splitlines()]
        assert lines.index("# answered HTTP 500.") < lines.index('"b-free",')
        first_comment = next(i for i, line in enumerate(lines)
                             if line.startswith("# Added by hand"))
        assert lines.index('"a-free",') < first_comment

    def test_a_name_removed_takes_its_reasoning_with_it(self):
        out = lineup_check.set_deny(self.COMMENTED, "opencode", ["a-free"])
        assert "answered HTTP 500" not in out
        assert '"a-free"' in out

    def test_a_denylist_with_no_comments_keeps_its_one_line_form(self):
        """A day with no change has to produce no diff, or the pull request stops being
        a signal — which is why the flat form survives where there is nothing to keep."""
        plain = ('[[providers]]\nname = "opencode"\n'
                 'deny = ["a-free"]\nfree_marks = ["-free"]\n')
        out = lineup_check.set_deny(plain, "opencode", ["b-free", "a-free"])
        assert 'deny = ["a-free", "b-free"]' in out

    def test_the_shipped_profile_round_trips_unchanged(self):
        """Sorted output against a hand-sorted file: a dispatch that changes nothing
        must leave the profile byte-identical, comments and all."""
        import os  # noqa: PLC0415

        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "profiles", "rcc.toml"), encoding="utf-8") as fh:
            text = fh.read()
        current = list(profile.active().provider("opencode").deny)
        assert lineup_check.set_deny(text, "opencode", current) == text

    def test_a_denied_model_is_put_back_when_it_answers(self, monkeypatch, tmp_path):
        """The property that makes a blocklist safe to have at all. `hy3-free` was
        down for two days and came back; a list that could not let go would have kept
        it out of the picker for ever."""
        target = tmp_path / "rcc.toml"
        target.write_text(
            '[[providers]]\nname = "opencode"\nkind = "openai"\n'
            'base_url = "http://x/v1"\nkey_env = "OPENCODE_API_KEY"\n'
            'models = [\n    "good-free",\n    "sick-free",\n]\n'
            'deny = ["sick-free"]\nfree_marks = ["-free"]\nfree_only = true\n'
        )
        loaded = profile.load(str(target))
        assert "sick-free" in loaded.provider("opencode").deny
        monkeypatch.setattr(lineup_check, "_active", lambda: loaded)
        monkeypatch.setattr(lineup_check, "discoverable", lambda: list(loaded.providers))
        monkeypatch.setattr(
            lineup_check, "served", lambda entry, key="": ["good-free", "sick-free"]
        )
        monkeypatch.setattr(lineup_check.providers, "api_key", lambda name: "")
        monkeypatch.setattr(
            lineup_check, "probe",
            lambda entry, key, model_id, tools=True: dict(self.HEALTHY, model=model_id),
        )
        _, body, _ = lineup_check.run(
            options(ledger=str(tmp_path / "l.json"), probe=True, update=True)
        )
        assert profile.load(str(target)).provider("opencode").deny == ()
        assert "Put back in the picker" in body

    def test_one_bad_day_retires_nothing(self, monkeypatch, tmp_path):
        target, (_code, body, _changed) = self.run_with(
            monkeypatch, tmp_path,
            {"good-free": self.HEALTHY, "sick-free": self.DEAD}, update=True,
        )
        assert "sick-free" in profile.load(str(target)).provider("opencode").models
        assert "Removed from" not in body

class TestScrub:
    def test_it_takes_the_billing_url_out_of_a_credits_error(self):
        """Zen's `CreditsError` carries the workspace id in a billing link. That is
        account state, it is not a fact about the model, and this ledger is committed
        to a public repository. Found by reading the first one this wrote."""
        body = (
            '{"error":{"type":"CreditsError","message":"Insufficient balance. Manage '
            'your billing here: https://opencode.ai/workspace/wrk_01KQ5KVT0SG152WC5'
            'TMF735F2F/billing"}}'
        )
        got = lineup_check.scrub(body)
        assert "wrk_01" not in got
        assert "opencode.ai" not in got
        # Still says the thing the classification depends on.
        assert "CreditsError" in got
        assert lineup_check._looks_paid(got)

    def test_it_takes_a_bare_opaque_id_too(self):
        assert "sk_" not in lineup_check.scrub("key sk_0123456789abcdefghij rejected")

    def test_it_collapses_whitespace_and_truncates(self):
        assert lineup_check.scrub("a\n\n  b") == "a b"
        assert len(lineup_check.scrub("x" * 400)) == 200


class TestRun:
    """The whole script, with `served` stubbed. Nothing here touches the network."""

    def stub(self, monkeypatch, catalogue):
        monkeypatch.setattr(lineup_check, "served", lambda entry, key="": catalogue)
        monkeypatch.setattr(lineup_check, "discoverable", lambda: [zen()])

    def test_a_quiet_day_exits_zero_and_reports_no_change(self, monkeypatch, tmp_path):
        self.stub(monkeypatch, list(ZEN.models))
        ledger = tmp_path / "lineup.json"
        # First run seeds; second is the quiet one.
        lineup_check.run(options(ledger=str(ledger)))
        code, body, changed = lineup_check.run(options(ledger=str(ledger)))
        assert code == 0
        assert changed is False
        assert "**Changed:**" not in body

    def test_it_writes_a_ledger_that_round_trips(self, monkeypatch, tmp_path):
        self.stub(monkeypatch, ["hy3-free", "claude-opus-5"])
        ledger = tmp_path / "nested" / "lineup.json"
        lineup_check.run(options(ledger=str(ledger)))
        found = json.loads(ledger.read_text())
        assert found["providers"]["opencode"]["free"] == ["hy3-free"]
        assert found["checked"]

    def test_fail_on_drift_is_opt_in(self, monkeypatch, tmp_path):
        """A free tier rotating its lineup is not this repository's fault, so the
        default is a report rather than a red build — the same reasoning `EVAL.md`
        gives for Axis B never being gated."""
        self.stub(monkeypatch, ["brand-new-free"])
        ledger = tmp_path / "lineup.json"
        lineup_check.run(options(ledger=str(ledger)))
        self.stub(monkeypatch, ["brand-new-free", "newer-free"])
        assert lineup_check.run(options(ledger=str(ledger)))[0] == 0
        code, _, changed = lineup_check.run(
            options(ledger=str(ledger), fail_on_drift=True)
        )
        assert changed is True
        assert code == 1

    def test_an_unreachable_endpoint_is_a_finding_not_a_crash(
        self, monkeypatch, tmp_path
    ):
        def boom(entry, key=""):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(lineup_check, "served", boom)
        monkeypatch.setattr(lineup_check, "discoverable", lambda: [zen()])
        code, body, _ = lineup_check.run(options(ledger=str(tmp_path / "l.json")))
        assert code == 2
        assert "Could not list models" in body

    def test_update_holds_back_a_model_whose_probe_got_nothing(
        self, monkeypatch, tmp_path
    ):
        """Served is not working. `north-mini-code-free` was in the profile's list and
        answering 401 from Zen's own upstream, and a list-only check called that
        lineup healthy."""
        target = tmp_path / "rcc.toml"
        target.write_text(
            '[[providers]]\nname = "opencode"\nkind = "openai"\n'
            'base_url = "http://x/v1"\nmodels = [\n    "known-free",\n]\n'
            'free_marks = ["-free"]\nfree_only = true\n'
        )
        loaded = profile.load(str(target))
        monkeypatch.setattr(profile, "active", lambda: loaded)
        monkeypatch.setattr(lineup_check, "_active", lambda: loaded)
        monkeypatch.setattr(lineup_check, "discoverable", lambda: list(loaded.providers))
        monkeypatch.setattr(
            lineup_check, "served", lambda entry, key="": ["known-free", "dud-free"]
        )
        monkeypatch.setattr(lineup_check.providers, "api_key", lambda name: "k")
        monkeypatch.setattr(
            lineup_check,
            "probe",
            lambda entry, key, model_id, tools=True: {
                "model": model_id, "status": 200, "answered": False, "tier": "free",
                "seconds": 1.0, "chars": 0,
            },
        )
        code, body, _ = lineup_check.run(
            options(ledger=str(tmp_path / "l.json"), probe=True, update=True)
        )
        assert code == 0
        assert "Held back" in body
        assert "dud-free" not in target.read_text()

    def test_update_appends_a_model_whose_probe_answered(self, monkeypatch, tmp_path):
        target = tmp_path / "rcc.toml"
        target.write_text(
            '[[providers]]\nname = "opencode"\nkind = "openai"\n'
            'base_url = "http://x/v1"\nmodels = [\n    "known-free",\n]\n'
            'free_marks = ["-free"]\nfree_only = true\n'
        )
        loaded = profile.load(str(target))
        monkeypatch.setattr(lineup_check, "_active", lambda: loaded)
        monkeypatch.setattr(lineup_check, "discoverable", lambda: list(loaded.providers))
        monkeypatch.setattr(
            lineup_check, "served", lambda entry, key="": ["known-free", "good-free"]
        )
        monkeypatch.setattr(lineup_check.providers, "api_key", lambda name: "k")
        monkeypatch.setattr(
            lineup_check,
            "probe",
            lambda entry, key, model_id, tools=True: {
                "model": model_id, "status": 200, "answered": True, "tier": "free",
                "seconds": 0.8, "chars": 40, "tool_calls": 1,
            },
        )
        lineup_check.run(
            options(ledger=str(tmp_path / "l.json"), probe=True, update=True)
        )
        assert profile.load(str(target)).provider("opencode").models == (
            "known-free", "good-free",
        )

    @staticmethod
    def profile_with(tmp_path, names, ledger_dates=None):
        """A one-provider profile plus a ledger that already knows how long each
        missing model has been gone. The dates are the whole input: without a ledger
        every absence is new today, and nothing is ever old enough to retire."""
        target = tmp_path / "rcc.toml"
        listed = "".join(f'    "{name}",\n' for name in names)
        target.write_text(
            '[[providers]]\nname = "opencode"\nkind = "openai"\n'
            f'base_url = "http://x/v1"\nmodels = [\n{listed}]\n'
            'free_marks = ["-free"]\nfree_only = true\n'
        )
        ledger = tmp_path / "l.json"
        if ledger_dates:
            stamps = {
                name: (dt.date.today() - dt.timedelta(days=days)).isoformat()
                for name, days in ledger_dates.items()
            }
            ledger.write_text(json.dumps({
                "providers": {"opencode": {
                    "free": list(names), "listed": list(names), "paid": [],
                    "missing_since": stamps, "verdicts": {}, "candidates": [],
                }}
            }))
        return target, ledger

    def test_update_retires_a_model_the_catalogue_has_not_served_for_a_week(
        self, monkeypatch, tmp_path
    ):
        """The gap this closes. Four models sat in the profile for three days, absent
        from the catalogue and reported daily to an issue, because the only thing this
        check would edit was an addition."""
        target, ledger = self.profile_with(
            tmp_path, ["stays-free", "long-gone-free"], {"long-gone-free": 9}
        )
        loaded = profile.load(str(target))
        monkeypatch.setattr(lineup_check, "_active", lambda: loaded)
        monkeypatch.setattr(lineup_check, "discoverable", lambda: list(loaded.providers))
        monkeypatch.setattr(lineup_check, "served", lambda entry, key="": ["stays-free"])
        monkeypatch.setattr(lineup_check.providers, "api_key", lambda name: "")

        _, body, _ = lineup_check.run(options(ledger=str(ledger), update=True))

        assert profile.load(str(target)).provider("opencode").models == ("stays-free",)
        assert "Removed from" in body and "long-gone-free" in body

    def test_a_two_day_absence_is_reported_and_not_edited(self, monkeypatch, tmp_path):
        """`hy3-free` came back after two. An edit here would have removed a working
        model, and the next run would have had to put it back."""
        target, ledger = self.profile_with(
            tmp_path, ["stays-free", "blipping-free"], {"blipping-free": 2}
        )
        loaded = profile.load(str(target))
        monkeypatch.setattr(lineup_check, "_active", lambda: loaded)
        monkeypatch.setattr(lineup_check, "discoverable", lambda: list(loaded.providers))
        monkeypatch.setattr(lineup_check, "served", lambda entry, key="": ["stays-free"])
        monkeypatch.setattr(lineup_check.providers, "api_key", lambda name: "")

        _, body, _ = lineup_check.run(options(ledger=str(ledger), update=True))

        assert "blipping-free" in profile.load(str(target)).provider("opencode").models
        assert "Removed from" not in body
        assert "blipping-free" in body, "still reported, just not acted on"

    def test_a_catalogue_that_lost_everything_is_an_outage_not_a_retirement(
        self, monkeypatch, tmp_path
    ):
        """The guard that matters most. An empty fallback list is what the app falls
        back *to* when discovery fails, so a provider that stopped serving every
        listed model must not leave the profile with nothing in it."""
        target, ledger = self.profile_with(
            tmp_path, ["one-free", "two-free"], {"one-free": 30, "two-free": 30}
        )
        loaded = profile.load(str(target))
        monkeypatch.setattr(lineup_check, "_active", lambda: loaded)
        monkeypatch.setattr(lineup_check, "discoverable", lambda: list(loaded.providers))
        monkeypatch.setattr(lineup_check, "served", lambda entry, key="": [])
        monkeypatch.setattr(lineup_check.providers, "api_key", lambda name: "")

        _, body, _ = lineup_check.run(options(ledger=str(ledger), update=True))

        assert profile.load(str(target)).provider("opencode").models == (
            "one-free", "two-free",
        )
        assert "Nothing was removed" in body

    def test_retiring_the_first_entry_says_where_the_default_moved(
        self, monkeypatch, tmp_path
    ):
        """It is the right edit — a dead model is a bad thing to fail over to — but the
        replacement is a judgement, so the diff has to say it made one."""
        target, ledger = self.profile_with(
            tmp_path, ["anchor-free", "next-free"], {"anchor-free": 30}
        )
        loaded = profile.load(str(target))
        monkeypatch.setattr(lineup_check, "_active", lambda: loaded)
        monkeypatch.setattr(lineup_check, "discoverable", lambda: list(loaded.providers))
        monkeypatch.setattr(lineup_check, "served", lambda entry, key="": ["next-free"])
        monkeypatch.setattr(lineup_check.providers, "api_key", lambda name: "")

        _, body, _ = lineup_check.run(options(ledger=str(ledger), update=True))

        assert profile.load(str(target)).provider("opencode").models == ("next-free",)
        assert "was the first entry" in body and "next-free" in body

    def test_retire_after_zero_leaves_the_list_alone(self, monkeypatch, tmp_path):
        target, ledger = self.profile_with(
            tmp_path, ["stays-free", "long-gone-free"], {"long-gone-free": 400}
        )
        loaded = profile.load(str(target))
        monkeypatch.setattr(lineup_check, "_active", lambda: loaded)
        monkeypatch.setattr(lineup_check, "discoverable", lambda: list(loaded.providers))
        monkeypatch.setattr(lineup_check, "served", lambda entry, key="": ["stays-free"])
        monkeypatch.setattr(lineup_check.providers, "api_key", lambda name: "")

        lineup_check.run(options(ledger=str(ledger), update=True, retire_after=0))

        assert "long-gone-free" in profile.load(str(target)).provider("opencode").models

    def test_the_probe_budget_says_what_it_dropped(self, monkeypatch, tmp_path):
        """A cap nobody is told about reads as "everything was covered"."""
        self.stub(monkeypatch, ["a-paid", "b-paid", "c-paid"])
        monkeypatch.setattr(lineup_check.providers, "api_key", lambda name: "k")
        monkeypatch.setattr(
            lineup_check,
            "probe",
            lambda entry, key, model_id, tools=True: {
                "model": model_id, "status": 401, "tier": "paid", "answered": False,
            },
        )
        _, body, _ = lineup_check.run(
            options(ledger=str(tmp_path / "l.json"), probe=True, probe_budget=1)
        )
        assert "2 unclassified name(s) went unprobed" in body

    def test_probing_without_a_key_probes_and_says_which_evidence_it_is(
        self, monkeypatch, tmp_path
    ):
        """This used to assert the opposite — that a keyless run probed nothing — and
        that assertion was the bug, held in place by a test. The workflow has no
        secret, so it was the only path that ever ran, and the two findings needing a
        completion were checked by nobody.

        `probe` is stubbed, and has to be: with the gate gone, a keyless run reaches
        the network, and this suite must not.
        """
        self.stub(monkeypatch, ["hy3-free", "claude-opus-5"])
        monkeypatch.setattr(lineup_check.providers, "api_key", lambda name: "")
        seen: list[tuple[str, str]] = []

        def spy(entry, key, model_id, tools=True):
            seen.append((model_id, key))
            return {"model": model_id, "status": 401, "tier": "paid", "answered": False}

        monkeypatch.setattr(lineup_check, "probe", spy)
        _, body, _ = lineup_check.run(
            options(ledger=str(tmp_path / "l.json"), probe=True)
        )
        assert [key for _name, key in seen] == ["", ""], "no run may invent a key"
        assert {name for name, _key in seen} == {"hy3-free", "claude-opus-5"}, (
            "the served free model is probed too, not just the unclassified one"
        )
        assert "carried no `Authorization` header" in body
        assert "nothing was probed" not in body


class TestProbeCost:
    def test_a_probe_asks_for_the_budget_the_app_would(self, monkeypatch):
        """The reasoning-model trap. `muse-spark-1.2-contributor-free` at
        `max_tokens=200` returns `completion_tokens: 200` and an empty completion,
        three times out of three — its thinking is not emitted and it never reaches the
        answer. A cheap probe would report a working model as a dead endpoint, and
        `--update` would hold it back on that evidence.
        """
        sent = {}

        class Response:
            status_code = 200

            def iter_lines(self):
                return iter(['data: [DONE]'])

            def read(self):
                return b""

        class Client:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def stream(self, method, url, json=None, headers=None):
                sent.update(json or {})
                return Response()

        class Stub:
            Client = staticmethod(lambda **kwargs: Client())
            Timeout = staticmethod(lambda *a, **k: None)

        monkeypatch.setitem(__import__("sys").modules, "httpx", Stub)
        Response.__enter__ = lambda self: self
        Response.__exit__ = lambda self, *exc: False
        lineup_check.probe(zen(), "k", "muse-spark-1.2-contributor-free")
        assert sent["max_tokens"] == config.MAX_TOKENS
        assert sent["max_tokens"] >= 4000, "a reasoning model needs room to think"
        # Offered a real tool, so the verdict can say whether it can call one.
        assert sent["tools"][0]["function"]["name"] == "search_docs"

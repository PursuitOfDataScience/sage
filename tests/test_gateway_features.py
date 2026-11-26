"""What the OpenAI-compatible adapter sends for the features a profile entry declares.

Every one of these is opt-in per provider entry, for the reason `stream_usage` is: an
endpoint that has never heard of a field or a header is entitled to answer it with a
400. So each feature is tested twice: it is sent where declared, and it is absent where
not, which is the guarantee that a deployment that declares nothing new sends exactly
what it sent before.
"""

from __future__ import annotations

import logging
import re
import sys
from types import ModuleType

import pytest

import stub_streamlit
from sage import alignment, config
from sage.profile import ProviderEntry, from_mapping
from sage.providers import openai_compat
from sage.providers.base import CallTag, tagged
from sage.providers.openai_compat import OpenAICompatProvider


class Wire:
    """A stand-in for httpx: keeps what was sent, and answers GETs from a table."""

    def __init__(self, monkeypatch, gets=None) -> None:
        self.json: dict = {}
        self.headers: dict = {}
        self.got: list[str] = []
        wire = self
        table = gets or {}

        class Streamed:
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def iter_lines(self):
                return iter(['data: {"choices":[{"delta":{"content":"ok"}}]}',
                             "data: [DONE]"])

        class Client:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def stream(self, _method, _url, json=None, headers=None, **_kwargs):
                wire.json = dict(json or {})
                wire.headers = dict(headers or {})
                return Streamed()

        class Got:
            def __init__(self, payload, status=200):
                self._payload = payload
                self.status_code = status

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(f"HTTP {self.status_code}")

            def json(self):
                if isinstance(self._payload, Exception):
                    raise self._payload
                return self._payload

        def get(url, headers=None, timeout=None):
            wire.got.append(url)
            for suffix, answer in table.items():
                if url.endswith(suffix):
                    payload, status = answer if isinstance(answer, tuple) else (answer, 200)
                    return Got(payload, status)
            return Got({}, 404)

        fake = ModuleType("httpx")
        fake.Client = Client
        fake.Timeout = lambda *_args, **_kwargs: None
        fake.get = get
        monkeypatch.setitem(sys.modules, "httpx", fake)


def entry(**declared) -> ProviderEntry:
    return ProviderEntry(name="gw", kind="openai", base_url="https://gw.test/api/v1",
                         **declared)


def send(monkeypatch, provider_entry, model="vendor/model", thinking=False,
         catalogue=None, tag=None):
    wire = Wire(monkeypatch, gets={"/models": {"data": catalogue or []}})
    adapter = OpenAICompatProvider(provider_entry, "k")
    if catalogue is not None:
        adapter.models()
    with tagged(tag):
        list(adapter.stream(model, [{"role": "user", "content": "hi"}], None, thinking))
    return wire


class TestRouteMetadata:
    def test_asked_for_only_where_declared(self, monkeypatch):
        assert "X-OpenRouter-Metadata" not in send(monkeypatch, entry()).headers
        wire = send(monkeypatch, entry(route_metadata=True))
        assert wire.headers["X-OpenRouter-Metadata"] == "enabled"

    def test_the_profile_reads_only_a_real_true(self):
        def read(value):
            return from_mapping({"providers": [
                {"name": "x", "route_metadata": value}]}).provider("x").route_metadata
        assert read(True) is True
        assert read("yes") is False and read(1) is False


class TestRoutingPreferences:
    def test_nothing_is_sent_by_default(self, monkeypatch):
        assert "provider" not in send(monkeypatch, entry()).json

    def test_a_models_own_preferences_are_sent_for_that_model_only(self, monkeypatch):
        declared = from_mapping({"providers": [{
            "name": "gw", "base_url": "https://gw.test/api/v1",
            "routing": {"paid/model": {"data_collection": "deny"}},
        }]}).provider("gw")
        assert send(monkeypatch, declared, model="paid/model").json["provider"] == {
            "data_collection": "deny"
        }
        assert "provider" not in send(monkeypatch, declared, model="openrouter/free").json

    def test_a_star_applies_to_every_model_and_a_named_one_replaces_it(self):
        declared = from_mapping({"providers": [{
            "name": "gw", "routing": {"*": {"sort": "price"},
                                      "m": {"data_collection": "deny"}},
        }]}).provider("gw")
        assert declared.routing_for("other") == {"sort": "price"}
        assert declared.routing_for("m") == {"data_collection": "deny"}

    @pytest.mark.parametrize("routing", ["deny", {"m": "deny"}, {"m": {}}, {" ": {"a": 1}}, 7])
    def test_a_shape_that_is_not_a_table_of_tables_is_dropped(self, routing):
        declared = from_mapping({"providers": [{"name": "gw", "routing": routing}]})
        assert declared.provider("gw").routing == ()
        assert declared.provider("gw").routing_for("m") is None


class TestThinkOff:
    """OFF sends `effort: none` only where the catalogue says the model will take it."""

    OPTIONAL = {"mandatory": False, "supported_efforts": ["high", "low", "none"]}

    def catalogue(self, **reasoning):
        return [{"id": model, "reasoning": caps} for model, caps in reasoning.items()]

    def sent(self, monkeypatch, model, caps, thinking=False, **declared):
        declared.setdefault("think_off", "none")
        wire = send(monkeypatch, entry(**declared), model=model, thinking=thinking,
                    catalogue=[{"id": model, "reasoning": caps}] if caps else [])
        return wire.json.get("reasoning")

    def test_an_optional_model_is_switched_off(self, monkeypatch):
        assert self.sent(monkeypatch, "m", self.OPTIONAL) == {"effort": "none"}

    def test_nothing_changes_where_the_profile_does_not_ask(self, monkeypatch):
        assert self.sent(monkeypatch, "m", self.OPTIONAL, think_off="") is None

    def test_a_mandatory_model_is_left_alone(self, monkeypatch):
        caps = {"mandatory": True, "supported_efforts": ["high", "none"]}
        assert self.sent(monkeypatch, "m", caps) is None

    def test_an_unstated_mandatory_is_not_assumed_optional(self, monkeypatch):
        assert self.sent(monkeypatch, "m", {"supported_efforts": ["none"]}) is None

    def test_a_model_without_the_value_is_left_alone(self, monkeypatch):
        caps = {"mandatory": False, "supported_efforts": ["high", "medium"]}
        assert self.sent(monkeypatch, "m", caps) is None

    def test_a_model_with_no_effort_control_is_left_alone(self, monkeypatch):
        assert self.sent(monkeypatch, "m", {"mandatory": False}) is None

    def test_null_efforts_means_every_value(self, monkeypatch):
        caps = {"mandatory": False, "supported_efforts": None}
        assert self.sent(monkeypatch, "m", caps) == {"effort": "none"}

    def test_a_router_is_never_switched_off(self, monkeypatch):
        assert self.sent(monkeypatch, "r", self.OPTIONAL, routers=("r",)) is None

    def test_an_undescribed_model_is_left_alone(self, monkeypatch):
        """Discovery that has not run, or a model the catalogue does not list."""
        wire = send(monkeypatch, entry(think_off="none"), model="m")
        assert "reasoning" not in wire.json

    def test_think_on_is_exactly_what_it_was(self, monkeypatch):
        assert self.sent(monkeypatch, "m", self.OPTIONAL, thinking=True,
                         reasoning=True) == {"enabled": True, "exclude": True}

    def test_an_environment_variable_can_switch_it_off_again(self, monkeypatch):
        monkeypatch.setenv("SAGE_TEST_THINK_OFF", "")
        declared = from_mapping({"providers": [{
            "name": "x", "think_off": "none", "think_off_env": "SAGE_TEST_THINK_OFF",
        }]}).provider("x")
        assert declared.think_off == ""


class TestTheAudit:
    def test_sent_only_where_declared(self, monkeypatch):
        assert "plugins" not in send(monkeypatch, entry()).json
        wire = send(monkeypatch, entry(alignment=True))
        assert wire.json["plugins"] == [alignment.plugin()]

    def test_it_measures_and_changes_nothing(self):
        """Audit mode delivers every message; `instruct` off keeps the rules out of the
        conversation, so the model answers the request it would have answered."""
        plugin = alignment.plugin()
        assert plugin["mode"] == "audit" and plugin["instruct"] is False

    def test_every_rule_fits_the_plugins_limit(self):
        assert all(1 <= len(rule) <= 200 for rule in alignment.RULES)

    def test_an_environment_variable_turns_it_on_or_off(self, monkeypatch):
        monkeypatch.setenv("SAGE_TEST_AUDIT", "1")
        declared = from_mapping({"providers": [{
            "name": "x", "alignment": False, "alignment_env": "SAGE_TEST_AUDIT",
        }]}).provider("x")
        assert declared.alignment is True

    def test_the_rules_name_no_subject(self, profile):
        """Machinery, not subject: nothing here may name the deployment."""
        text = " ".join(alignment.RULES)
        for word in (profile.identity.topic, profile.identity.name):
            assert not re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE), word


class TestKeyStatus:
    DOCUMENTED = {"data": {
        "limit": 5, "limit_reset": "weekly", "limit_remaining": 4.5, "usage_daily": 0.25,
        "free_model_daily_requests": {"used": 778, "limit": 1000, "remaining": 222},
    }}

    def test_read_from_the_declared_path(self, monkeypatch):
        wire = Wire(monkeypatch, gets={"/key": self.DOCUMENTED})
        status = OpenAICompatProvider(entry(status_path="/key"), "k").status()
        assert wire.got == ["https://gw.test/api/v1/key"]
        assert status == {
            "free_used": 778, "free_limit": 1000, "free_remaining": 222,
            "limit_usd": 5, "limit_remaining_usd": 4.5, "limit_reset": "weekly",
            "spent_today_usd": 0.25,
        }

    def test_no_path_means_no_request(self, monkeypatch):
        wire = Wire(monkeypatch, gets={"/key": self.DOCUMENTED})
        assert OpenAICompatProvider(entry(), "k").status() is None
        assert wire.got == []

    @pytest.mark.parametrize("answer", [({}, 500), ({"data": "x"}, 200),
                                        (ValueError("not json"), 200)])
    def test_a_broken_endpoint_is_no_status_and_no_exception(self, monkeypatch, answer):
        Wire(monkeypatch, gets={"/key": answer})
        assert OpenAICompatProvider(entry(status_path="key"), "k").status() is None

    def test_what_was_not_reported_is_none(self, monkeypatch):
        Wire(monkeypatch, gets={"/key": {"data": {"limit": None}}})
        status = OpenAICompatProvider(entry(status_path="/key"), "k").status()
        assert status["free_remaining"] is None and status["limit_usd"] is None


class TestRetirementWarnings:
    def test_a_dated_model_in_the_lineup_is_warned_about_once(self, monkeypatch, caplog):
        monkeypatch.setattr(openai_compat, "_RETIREMENTS_SEEN", set())
        catalogue = [
            {"id": "~vendor/family-latest", "alias_target": {"slug": "vendor/family-0731"}},
            {"id": "vendor/family", "canonical_slug": "vendor/family-0731",
             "expiration_date": "2026-12-31"},
            {"id": "vendor/unlisted", "expiration_date": "2026-12-01"},
        ]
        Wire(monkeypatch, gets={"/models": {"data": catalogue}})
        adapter = OpenAICompatProvider(entry(models=("~vendor/family-latest",)), "k")
        with caplog.at_level(logging.WARNING, logger="sage.providers.openai_compat"):
            adapter.models()
            adapter.models()
        warned = [record.getMessage() for record in caplog.records
                  if "may be removed" in record.getMessage()]
        assert len(warned) == 1, warned
        assert "vendor/family-0731" in warned[0] and "2026-12-31" in warned[0]

    def test_an_undated_lineup_is_silent(self, monkeypatch, caplog):
        monkeypatch.setattr(openai_compat, "_RETIREMENTS_SEEN", set())
        Wire(monkeypatch, gets={"/models": {"data": [{"id": "m"}]}})
        with caplog.at_level(logging.WARNING, logger="sage.providers.openai_compat"):
            OpenAICompatProvider(entry(models=("m",)), "k").models()
        assert not [r for r in caplog.records if "may be removed" in r.getMessage()]


class TestNothingNewIsSentUndeclared:
    """The guarantee the whole file exists for, in one request."""

    def test_an_entry_declaring_nothing_sends_what_it_always_sent(self, monkeypatch):
        monkeypatch.setattr(config, "DEPLOYMENT", "cloudrun")
        wire = send(monkeypatch, entry(), tag=CallTag(session="s", turn_id="t", round=1,
                                                      prompt="p", corpus="c"))
        assert set(wire.json) == {"model", "messages", "stream", "max_tokens",
                                  "temperature"}
        assert set(wire.headers) == {"Content-Type", "Authorization"}


def _access():
    """`sage.ui.access` under the Streamlit stub, which is all CI has."""
    stub_streamlit.install()
    from sage.ui import access  # noqa: PLC0415

    return access


class TestLimitWarnings:
    """`sage.quota`: a WARNING before a provider-side limit refuses a reader."""

    @pytest.fixture(autouse=True)
    def _clean_modules(self):
        yield
        stub_streamlit.forget_importers()

    def test_a_nearly_spent_free_counter_is_a_warning(self):
        from sage import quota

        lines = quota.warnings("gw", {"free_used": 950, "free_limit": 1000,
                                      "free_remaining": 50}, 0.1)
        assert len(lines) == 1 and "950 of 1000 free-model requests" in lines[0]

    def test_a_healthy_counter_is_silent(self):
        from sage import quota

        assert quota.warnings("gw", {"free_used": 10, "free_limit": 1000,
                                     "free_remaining": 990}, 0.1) == []

    def test_a_nearly_spent_key_limit_is_a_warning(self):
        from sage import quota

        lines = quota.warnings("gw", {"limit_usd": 5, "limit_remaining_usd": 0.3,
                                      "limit_reset": "weekly"}, 0.1)
        assert lines == ["gw: $0.30 of this key's $5.00 weekly spending limit is left. "
                         "Requests on the key are refused once it is spent."]

    @pytest.mark.parametrize("status", [None, {}, {"free_limit": 0, "free_remaining": 0},
                                        {"limit_usd": None, "limit_remaining_usd": 0},
                                        {"free_limit": True, "free_remaining": 0}])
    def test_what_was_not_reported_is_never_guessed_at(self, status):
        from sage import quota

        assert quota.warnings("gw", status, 0.1) == []

    def test_a_fraction_of_zero_switches_it_off(self):
        from sage import quota

        assert quota.warnings("gw", {"free_limit": 1000, "free_remaining": 0}, 0) == []

    def test_the_hourly_check_runs_off_the_page_and_logs(self, monkeypatch, caplog):
        from sage import profile as profile_module
        access = _access()

        declared = from_mapping({"providers": [{"name": "gw", "status_path": "/key"}]})
        monkeypatch.setattr(profile_module, "_active", declared)

        class Reporting:
            def status(self):
                return {"free_used": 999, "free_limit": 1000, "free_remaining": 1}

        with caplog.at_level(logging.WARNING, logger="sage.ui.access"):
            thread = access.watch_limits("gw", Reporting())
            thread.join(timeout=5)
        assert any("999 of 1000" in record.getMessage() for record in caplog.records)

    def test_an_entry_without_a_status_path_is_never_asked(self, monkeypatch):
        from sage import profile as profile_module
        access = _access()

        declared = from_mapping({"providers": [{"name": "gw"}]})
        monkeypatch.setattr(profile_module, "_active", declared)

        class Raising:
            def status(self):
                raise AssertionError("asked without a status_path")

        assert access.watch_limits("gw", Raising()) is None

    def test_a_status_that_raises_never_reaches_the_page(self, monkeypatch, caplog):
        from sage import profile as profile_module
        access = _access()

        declared = from_mapping({"providers": [{"name": "gw", "status_path": "/key"}]})
        monkeypatch.setattr(profile_module, "_active", declared)

        class Broken:
            def status(self):
                raise RuntimeError("boom")

        thread = access.watch_limits("gw", Broken())
        thread.join(timeout=5)
        assert not thread.is_alive()

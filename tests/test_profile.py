"""The seam that makes this app a *documentation* assistant rather than the RCC's.

Two things are worth holding here, and neither is visible from any other test:

* a second profile really does produce a second assistant — different prompt,
  different tool descriptions, different copy — without touching code;
* and nothing under `sage/` says "RCC", so there is nowhere for the subject to hide
  when someone swaps the profile and wonders why an answer still mentions Midway.
"""

from __future__ import annotations

import ast
import os
import pathlib

import pytest

from sage import corpus as corpus_mod
from sage import profile as profile_mod
from sage import prompts, retrieval, runtime, tools
from sage.profile import Profile, from_mapping

SAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sage")

OTHER = {
    "assistant": {
        "name": "Atlas",
        "icon": "🗺️",
        "page_title": "Atlas — Maps Handbook",
        "subject": "the Cartography Department's handbook",
        "topic": "mapping",
        "corpus_name": "the Maps Handbook",
        "contact": "maps@example.org",
        "contact_label": "the Maps desk",
        "operator": "the maps team",
        "topics": "projections, datums or tiling",
        "path_example": "handbook/projections.md#utm",
    },
    "copy": {
        "welcome_title": "Ask about maps",
        "placeholder": "Ask any question about mapping…",
    },
    "prompt": {"system": "You are {name}. You answer about {subject}. Ask {contact}."},
    "examples": [{"icon": "🗺️", "label": "Pick a projection"}],
    "sources": [
        {
            "name": "handbook",
            "path": "./handbook",
            "extensions": [".md"],
            "reader": "markdown",
            "links": "direct",
            "base_url": "https://maps.example.org/",
            "weight": 1.5,
        }
    ],
    "retrieval": {"engine": "bm25", "synonyms": [["utm", "grid"]], "protected": ["wgs84"]},
    "providers": [
        {"name": "local", "kind": "openai", "key_env": "LOCAL_KEY",
         "base_url": "http://127.0.0.1:8000/v1", "models": ["qwen3"]}
    ],
}


@pytest.fixture
def atlas():
    """A wholly different deployment, installed for the duration of one test."""
    built = from_mapping(OTHER, origin="profiles/atlas.toml")
    profile_mod.use(built)
    yield built
    profile_mod.use(None)


class TestTheProfileIsTheDeployment:
    def test_the_shipped_profile_loads_from_its_file(self, profile):
        assert profile.origin.endswith("rcc.toml")
        assert profile.identity.name == "Sage"
        assert [source.name for source in profile.sources] == ["docs", "web"]
        assert [entry.name for entry in profile.providers] == [
            "openrouter", "mistral", "opencode",
        ]
        assert profile.prompt, "the prompt file beside the profile was not read"

    def test_a_second_profile_changes_who_the_assistant_is(self, atlas):
        assert prompts.system_prompt(atlas).startswith(
            "You are Atlas. You answer about the Cartography Department's handbook. "
            "Ask maps@example.org."
        )
        assert atlas.identity.documentation == "the mapping documentation"

    def test_a_second_profile_changes_what_the_tools_say(self, atlas):
        index = retrieval.Index(corpus_mod.Corpus())
        schemas = {
            schema["function"]["name"]: schema["function"]["description"]
            for schema in tools.build(index, atlas.identity).schemas
        }
        assert "the Maps Handbook" in schemas[tools.SEARCH_DOCS]
        assert "projections, datums or tiling" in schemas[tools.SEARCH_DOCS]
        assert "handbook/projections.md#utm" in schemas[tools.READ_DOC]
        assert "RCC" not in "".join(schemas.values())

    def test_a_second_profile_changes_where_citations_point(self, atlas):
        source = atlas.source("handbook")
        assert corpus_mod.url_for(source, "projections.md", "utm") == (
            "https://maps.example.org/projections.md#utm"
        )

    def test_a_second_profile_changes_the_vocabulary(self, atlas):
        words = retrieval.vocabulary(atlas)
        assert "grid" in words.expand("utm")
        # The RCC groups are not inherited: "killed" no longer reaches "memory".
        assert words.stem("memory") not in words.expand("my job was killed")

    def test_an_absent_source_tree_is_a_warning_not_a_crash(self, atlas):
        built = runtime.build(atlas)
        assert built.corpus.chunks == []
        assert built.identity.name == "Atlas"
        assert built.toolset.schemas


class TestAProviderThatNeedsNoLineupMaintenance:
    """One provider is a router, and the rule that offers it is the whole mechanism.

    Zen needs `.github/workflows/lineup.yml`: its free lineup rotates without notice,
    the fallback list goes stale, and a model that stops answering has to be noticed by
    something. OpenRouter's entry is one id — `openrouter/free`, a router that picks a
    working free model per request — so all three of those jobs happen on the provider's
    side and there is no list here to keep true.

    That only holds while the entry cannot admit anything it does not NAME. These tests
    are what stops it quietly becoming a discovered list: widen `free_marks` to `:free`
    and eighteen models nothing is checking become selectable, which is exactly the
    state the workflow exists to prevent for the other provider.

    The entry held exactly one id until 2026-09-12, and these tests said so. It holds
    two now — the router plus one pinned PAID model, added because the whole free
    lineup stopped answering on the same afternoon (see the note on `models` in the
    profile). That is a widening of the list and not of the RULE: both ids are written
    out, `free_marks` still matches the list exactly, and discovery is still a no-op. So
    the count is no longer the thing to assert, and the two properties that made the
    count worth asserting are.
    """

    ROUTER = "openrouter/free"

    def router(self, profile):
        """The provider whose rule names its own models: no discovery can widen it."""
        return next(
            (entry for entry in profile.providers
             if entry.free_only and set(entry.free_marks) == set(entry.models)),
            None,
        )

    def test_one_provider_selects_itself(self, profile):
        assert self.router(profile) is not None, (
            "no provider whose free rule names exactly its own model list; if the "
            "router entry was widened, lineup.yml has to start checking it"
        )

    def test_every_id_it_offers_is_one_the_profile_writes_out(self, profile):
        """Not "exactly one" any more — "exactly these". A mark that is a substring
        rather than a whole id is what lets discovery add a model nothing checked."""
        entry = self.router(profile)
        assert entry.models, "the router entry offers nothing at all"
        assert set(entry.free_marks) == set(entry.models), (
            "a mark that is not one of the named ids means discovery can widen this "
            "entry, and nothing is checking what it would admit"
        )
        assert self.ROUTER in entry.models, "the free router is no longer offered"

    def test_its_rule_cannot_admit_anything_the_list_does_not_name(self, profile):
        """`free_only` plus a mark that *is* the id is what makes discovery a
        no-op — the adapter filters 387 served models down to this one."""
        entry = self.router(profile)
        assert entry.free_only is True
        # Sets, not tuples: `models` is ordered — its first entry is the model a fresh
        # session starts on — and `free_marks` is a filter, which has no order to it.
        assert set(entry.free_marks) == set(entry.models)

    def test_it_has_no_denylist_because_it_has_nothing_to_deny(self, profile):
        """A denylist is for a name the provider serves and cannot run. With one id,
        and that id being the thing that routes around a broken model, there is no
        such name — and a stale entry here would empty the provider instead."""
        assert self.router(profile).deny == ()

    def test_the_lineup_workflow_checks_the_other_provider_and_not_this_one(self):
        """The workflow's `--provider` is the other half of this arrangement. Left
        unscoped, the 386 models OpenRouter fronts and the rule does not match land in
        the stealth-codename queue, and every run spends its probe budget asking paid
        models whether they are secretly free."""
        workflow = pathlib.Path(__file__).resolve().parents[1] / (
            ".github/workflows/lineup.yml"
        )
        text = workflow.read_text(encoding="utf-8")
        assert "--provider" in text, (
            "lineup_check.py runs over every discoverable provider by default, which "
            "now includes one that needs no checking"
        )

    def test_the_router_is_shown_under_a_name_the_profile_chose(self, profile):
        """A served id is sometimes an implementation detail wearing a name.

        `openrouter/free` describes which free tier the request draws on. A reader
        choosing a row in a picker is not choosing a billing arrangement, and the row is
        a different model every turn, so no specific model name would be right either.
        """
        from sage.providers import Model

        entry = self.router(profile)
        # The ROUTER's id, named rather than taken as `models[0]` — that was a shortcut
        # from when the entry held one id, and the first entry is now whichever model
        # the deployment starts on.
        served = self.ROUTER
        assert served in entry.models
        shown = Model(entry.name, served).label
        assert shown, "the router has no label at all"
        assert shown != served
        assert "free" not in shown.lower(), (
            "the tier is the one thing the label exists to stop saying"
        )
        assert "/" not in shown, "a vendor path is an id, not a name"

    def test_renaming_it_changes_nothing_that_is_measured(self, profile):
        """The label is the only thing that moves. Everything that identifies a model
        to the provider, to the feedback log, to `tools/agent_bench.py` or to the
        error card's technical-details panel is built from the id — so a nickname
        cannot end up standing in for a model in a measurement."""
        from sage.providers import Model

        entry = self.router(profile)
        served = entry.models[0]
        model = Model(entry.name, served)
        assert model.id == served
        assert model.key == f"{entry.name}:{served}"

    def test_a_provider_that_names_nothing_still_gets_a_label(self, profile):
        """The mechanism has to be optional, because two of the three providers here
        use none of it and a deployment may use none at all."""
        from sage.providers import Model

        for entry in profile.providers:
            if entry.labels:
                continue
            for served in entry.models:
                assert Model(entry.name, served).label, served

    def test_the_name_lives_in_the_profile_and_not_in_the_package(self, profile):
        """The standing rule for this repository, applied to one more word. A label is
        copy, and `sage/` holds no copy — so the check is that the shown name appears
        nowhere under the package, which is what would happen if a lookup table were
        added to `sage/providers/base.py` instead of to the profile."""
        from sage.providers import Model

        entry = self.router(profile)
        shown = Model(entry.name, entry.models[0]).label
        for path in pathlib.Path(SAGE).rglob("*.py"):
            assert shown not in path.read_text(encoding="utf-8"), (
                f"{path.name} names the deployment's word for a model"
            )

    def test_the_default_model_names_a_provider_this_profile_has(self, profile):
        """`SAGE_DEFAULT_MODEL` naming a provider the profile dropped is a session
        that starts on nothing. Checked here rather than trusted, because the default
        and the profile are edited in different files."""
        from sage import config

        provider, _, model_id = config.DEFAULT_MODEL.partition(":")
        assert model_id, f"DEFAULT_MODEL is not `provider:model-id`: {config.DEFAULT_MODEL!r}"
        entry = profile.provider(provider)
        assert entry is not None, f"no `{provider}` provider in the profile"
        assert model_id in entry.models, (
            f"`{model_id}` is not in {provider}'s list, so a fresh session falls "
            f"through to whatever discovery happens to return first"
        )


class TestEveryDeploymentIsToldNotToNameItsMachinery:
    """`prompts.SELF_DISCLOSURE` is appended to whatever prompt a profile supplies.

    Which is the whole reason it lives in the package rather than in
    `profiles/rcc.prompt.md`. A deployment writes its own prompt — Atlas here does, and it
    is three sentences long — and the rule that the tools, the model and the instructions
    are nobody's business is exactly the one nobody would think to copy across. Without
    these two assertions the clause could be deleted from `system_prompt` and the only
    thing that would notice is `tools/agent_bench.py --meta`, which is never a gate.
    """

    def test_a_profile_with_its_own_prompt_still_gets_it(self, atlas):
        prompt = prompts.system_prompt(atlas)
        assert "Atlas" in prompt
        assert "Never name the machinery" in prompt
        assert "you look things up in the mapping documentation" in prompt

    def test_a_profile_with_no_prompt_at_all_gets_it(self):
        assert "Never name the machinery" in prompts.system_prompt(Profile())

    def test_it_also_forbids_making_the_refusal_the_answer(self):
        """Half the clause, and the half a leak-only fix leaves out.

        Told only to keep quiet, a model answers "I'm not able to discuss my
        configuration" — which confirms there is something hidden and leaves the reader's
        actual doubt where it was. `evals/checks.stonewalled` measures it.
        """
        # Whitespace collapsed, because the clause is wrapped prose and where the lines
        # break is not something a test should hold still.
        clause = " ".join(prompts.SELF_DISCLOSURE.split())
        assert "Never say you are not allowed to discuss it" in clause
        assert "you cannot run commands" in clause
        assert "outside this conversation" in clause

    def test_the_clause_is_about_the_machinery_and_names_no_subject(self):
        lowered = prompts.SELF_DISCLOSURE.lower()
        for word in ("rcc", "uchicago", "midway", "slurm"):
            assert word not in lowered
        # The one hole in it is filled from the profile, so it reads as English in a
        # deployment about anything.
        assert "{documentation}" in prompts.SELF_DISCLOSURE


class TestNothingUnderSageNamesTheSubject:
    """A string a reader or a model can see must come from the profile.

    Scanned as string *literals*, with docstrings excluded: the comments and
    docstrings in this package are full of the RCC, because that is where the
    evidence for every decision came from and deleting it would cost more than it
    buys. What must not survive is a sentence the app can actually emit.
    """

    BRANDED = ("rcc", "uchicago", "midway", "beagle", "skyway", "cnetid")

    def literals(self, path: str) -> list[str]:
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            ):
                body = getattr(node, "body", None)
                if body and isinstance(body[0], ast.Expr) and isinstance(
                    body[0].value, ast.Constant
                ) and isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))
        return [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ]

    def modules(self) -> list[str]:
        found = []
        for root, _dirs, names in os.walk(SAGE):
            found += [
                os.path.join(root, name) for name in names if name.endswith(".py")
            ]
        return sorted(found)

    def test_the_package_is_not_about_anything_in_particular(self):
        assert self.modules(), "no modules were scanned"
        offences = [
            (os.path.relpath(path, SAGE), text)
            for path in self.modules()
            for text in self.literals(path)
            if any(word in text.lower() for word in self.BRANDED)
            # The one exception, and it is the mechanism rather than a leak: the
            # default value of `SAGE_PROFILE` has to name a file, and the file this
            # repository ships is the RCC's. A path is not a sentence the app emits.
            and not text.endswith(".toml")
        ]
        assert not offences, (
            "these strings name this deployment and belong in a profile: "
            f"{offences[:5]}"
        )

    def test_no_module_names_a_tree_or_a_provider_this_profile_invented(self, profile):
        """The leak the branded-word list above cannot see.

        `BRANDED` catches a string that *looks* like this deployment. It cannot catch one
        that is deployment-specific only because the profile says so: `links.resolve`
        carried `for source in ("docs", "web")` — two ordinary English words that mean the
        RCC's user guide and the RCC's scraped site, and nothing anywhere else. A second
        deployment naming its trees anything else silently lost every bare-path citation.

        Registry keys are excluded rather than exempted by name: `reader = "markdown"`,
        `links = "mkdocs"`, `kind = "mistral"` are all profile values that *must* appear in
        `sage/`, because that is where the implementation registers itself. What must not
        appear is a name the deployment chose freely — a tree's name, a provider's name.
        (`mistral` is both here, which is why the exclusion is a set difference and not a
        list of pardons.)
        """
        chosen = {source.name for source in profile.sources}
        chosen |= {entry.name for entry in profile.providers}
        registered = {source.reader for source in profile.sources}
        registered |= {source.links for source in profile.sources}
        registered |= {entry.kind for entry in profile.providers}
        registered.add(profile.retrieval.engine)
        arbitrary = chosen - registered
        assert arbitrary, "the profile declares no name of its own to check for"
        offences = sorted(
            {
                (os.path.relpath(path, SAGE), text)
                for path in self.modules()
                for text in self.literals(path)
                if text in arbitrary
            }
        )
        assert not offences, (
            "these are names this profile chose, hardcoded in the package: "
            f"{offences[:5]}"
        )

    def test_the_shipped_profile_is_where_it_all_lives(self, profile):
        """…and the counterpart: the profile really does say all of it."""
        text = "\n".join(
            [profile.identity.subject, profile.identity.corpus_name, profile.prompt]
            + [source.base_url for source in profile.sources]
        ).lower()
        for word in ("rcc", "uchicago", "midway"):
            assert word in text


def test_the_default_profile_is_a_working_assistant():
    """No file at all: unbranded copy, no documents, and no sentence with a hole in it.

    The topic is an adjective, so leaving it unset has to read as English rather than
    as a template that was never filled — "any question", not "any  question", and no
    dangling "point the user at the maintainers ()".
    """
    empty = Profile()
    prompt = prompts.system_prompt(empty)
    assert prompt and "{" not in prompt
    assert empty.identity.documentation == "the documentation"

    search = next(
        schema["function"]["description"]
        for schema in tools.build(
            retrieval.Index(corpus_mod.Corpus()), empty.identity
        ).schemas
        if schema["function"]["name"] == tools.SEARCH_DOCS
    )
    assert "for any question, then read" in search
    assert "  " not in search

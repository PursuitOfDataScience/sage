import pytest

from sage import config, retrieval
from sage.corpus import Chunk, Corpus
from sage.retrieval import bm25, text

# The shipped profile's vocabulary: its protected terms and its synonym groups. That
# split is the seam under test here — the stemming rules are about English and live in
# code, while which words are technical terms, and which stand in for each other, is
# about the subject and arrives from `profiles/rcc.toml`.
words = retrieval.vocabulary()


def make_corpus(*bodies: tuple[str, str, str]) -> Corpus:
    chunks = [
        Chunk(
            id=f"docs/{path}#{index}",
            source="docs",
            path=path,
            doc_title=title,
            heading=title,
            breadcrumb=title,
            text=text,
            url=f"https://example.test/{path}",
        )
        for index, (path, title, text) in enumerate(bodies)
    ]
    return Corpus(chunks=chunks, documents={})


class TestTokenize:
    def test_stems_plurals_consistently(self):
        assert words.tokenize("quotas") == words.tokenize("quota")
        assert words.tokenize("nodes") == words.tokenize("node")
        assert words.tokenize("processes") == words.tokenize("process")
        assert words.tokenize("directories") == words.tokenize("directory")

    def test_double_s_words_are_not_mangled(self):
        assert "clas" not in words.tokenize("class")

    def test_technical_terms_are_protected(self):
        assert "gres" in words.tokenize("--gres=gpu:1")
        assert "globus" in words.tokenize("Globus")

    def test_cluster_names_emit_both_forms(self):
        tokens = words.tokenize("midway3")
        assert "midway3" in tokens
        assert "midway" in tokens
        assert "3" in tokens

    def test_single_characters_are_kept_so_r_is_searchable(self):
        """`R` is a language users ask about; IDF handles the noisy letters."""
        assert words.tokenize("use R") == ["use", "r"]

    def test_single_letter_language_is_retrievable(self, real_index):
        pages = {result.chunk.path for result in real_index.search("use R on midway", 5)}
        assert "software/apps-and-envs/r.md" in pages


class TestExpandQuery:
    def test_exact_terms_outweigh_synonyms(self):
        weights = words.expand("scavenge")
        assert weights[words.stem("scavenge")] == 1.0
        assert weights[words.stem("preemptible")] == config.SYNONYM_WEIGHT

    def test_symptom_language_reaches_mechanism_language(self):
        weights = words.expand("my job was killed")
        assert words.stem("memory") in weights

    def test_empty_query_expands_to_nothing(self):
        assert words.expand("   ") == {}


class TestRanking:
    def test_shorter_focused_pages_beat_long_dumps(self):
        """BM25 length normalization is what the old `min(count, 5)` scorer lacked."""
        filler = " ".join(f"unrelated sentence {n}" for n in range(4000))
        corpus = make_corpus(
            ("focused.md", "Storage quota", "Your storage quota is 25 GB on /home."),
            ("dump.md", "Publications", f"quota {filler}"),
        )
        results = retrieval.Index(corpus).search("storage quota")
        assert results[0].chunk.path == "focused.md"

    def test_rare_terms_outrank_common_ones(self):
        corpus = make_corpus(
            ("a.md", "A", "the the the the sbatch"),
            ("b.md", "B", "the the the the the the the the"),
            ("c.md", "C", "the the the the the"),
        )
        results = retrieval.Index(corpus).search("the sbatch")
        assert results[0].chunk.path == "a.md"

    def test_title_matches_are_boosted(self):
        corpus = make_corpus(
            ("a.md", "Unrelated heading", "globus appears once here"),
            ("b.md", "Globus transfers", "some other body text entirely"),
        )
        results = retrieval.Index(corpus).search("globus")
        assert results[0].chunk.path == "b.md"

    def test_the_user_guide_outranks_the_scraped_site_on_a_tie(self, profile):
        """The prior travels with the corpus, not with the scorer.

        `Corpus.weight` is what applies it, and it reads the source records the
        corpus was built with — so a corpus assembled without them scores every tree
        the same, which is the right answer for a corpus that never said otherwise.
        """
        text = "Storage quotas are enforced per directory."
        chunks = [
            Chunk("web/p.txt#1", "web", "p.txt", "Storage", "Storage", "Storage", text, "u"),
            Chunk("docs/p.md#1", "docs", "p.md", "Storage", "Storage", "Storage", text, "u"),
        ]
        corpus = Corpus(chunks=chunks, sources=profile.sources)
        assert corpus.weight("docs") > corpus.weight("web")
        results = retrieval.Index(corpus).search("storage quotas")
        assert results[0].source == "docs"
        assert results[0].score > results[1].score

    def test_no_match_returns_nothing(self):
        corpus = make_corpus(("a.md", "A", "storage quota information"))
        assert retrieval.Index(corpus).search("xylophone unicorn") == []

    def test_empty_index_is_safe(self):
        assert retrieval.Index(Corpus()).search("anything") == []

    def test_limit_is_respected(self, real_index):
        assert len(real_index.search("storage", limit=3)) == 3


class TestTheTitleFieldIsLengthNormalised:
    """A title that IS the query beats a heading trail that merely contains it.

    The body field was length-normalised and the title field was not, so the title
    boost was a flat `+idf * TITLE_BOOST` per matching term however long the title
    was. A `breadcrumb` is the whole path of headings, so a page with fifteen words
    of heading trail collected exactly the credit of a page whose entire title is
    the reader's word — and then won on its body.

    Measured on the shipped corpus, that was seven of 114 pages not retrievable by
    their own title: three of the four pages titled `Software`, the page titled
    `FAQs` (beaten by four sections of three other FAQ pages tied at an identical
    19.769), `Accessing RCC clusters` and the section-wise misses behind them.
    """

    #: Neither path carries the word, so the two chunks are separated by the title
    #: field and the body field alone — which is the comparison under test. The long
    #: title is the real shape of the breadcrumb that won: `docs/slurm/faq.md`'s.
    def corpus(self):
        return make_corpus(
            ("a.txt", "FAQs", "Frequently asked questions about cloud bursting."),
            (
                "b.md",
                "Running Jobs FAQ › Set-up and general questions › Are there any "
                "limits to running jobs on Midway?",
                "This FAQ covers limits on how many jobs one account may run.",
            ),
        )

    def test_the_page_whose_whole_title_is_the_query_wins(self):
        results = retrieval.Index(self.corpus()).search("FAQs")
        assert [result.chunk.path for result in results][0] == "a.txt"

    def test_and_it_lost_while_the_boost_was_flat(self, monkeypatch):
        """The defect itself, held somewhere it can fail.

        A floor above every achievable `1 / norm` makes the factor one constant for
        every chunk, which is arithmetically the old flat boost with a larger
        `TITLE_BOOST` — same ranking, and it is the ranking that was wrong. Without
        this the fix has no witness: a check that cannot fail reads as a pass.
        """
        monkeypatch.setattr(bm25, "TITLE_LENGTH_FLOOR", 50.0)
        results = retrieval.Index(self.corpus()).search("FAQs")
        assert [result.chunk.path for result in results][0] == "b.md"

    def test_the_floor_bounds_what_normalisation_may_take_away(self):
        """Load-bearing, and not for ranking: `MIN_CONFIDENT_SCORE` is a flat 20.

        Deflating a long title's boost lowers the top score of queries that have
        nothing to do with findability, and the confidence gate compares that score
        against an absolute threshold. Unclamped, "why did job 41235567 fail" fell
        from just above 20 to just below it and the app began refusing a question
        the corpus answers. The floor is what keeps the gate's calibration intact.
        """
        index = retrieval.Index(self.corpus())
        endless = index._title_weight(10_000)
        assert endless == pytest.approx(bm25.TITLE_LENGTH_FLOOR)
        assert index._title_weight(1) > 1.0


class TestSnippet:
    def test_original_casing_is_preserved(self):
        """The old snippet sliced a lowercased copy, mangling Midway3 and CNetID."""
        text = "Connect to Midway3 with your CNetID and run sbatch --gres=gpu:1 now."
        out = retrieval.snippet(text, words.expand("cnetid"), config.SNIPPET_CHARS)
        assert "CNetID" in out
        assert "--gres=gpu:1" in out

    def test_window_centres_on_the_match(self):
        text = "filler " * 60 + "QUOTA MARKER" + " tail" * 60
        out = retrieval.snippet(text, words.expand("quota"), 80)
        assert "QUOTA MARKER" in out
        assert out.startswith("…")

    def test_short_text_is_returned_whole(self):
        out = retrieval.snippet("Short body.", words.expand("short"), config.SNIPPET_CHARS)
        assert out == "Short body."


def test_index_builds_over_the_real_corpus(real_index):
    assert real_index.total > 300
    assert real_index.average_length > 0


class TestStemming:
    """The stemmer claimed to be "Porter-ish" and stripped plurals only."""

    @pytest.mark.parametrize(
        ("inflected", "base"),
        [
            # The group ("scavenge", "preemptible", "preempt") was written for this
            # query and could never fire, because `preempted` reached the index as
            # itself and matched no member of it.
            ("preempted", "preempt"),
            ("purged", "purge"),
            ("exceeded", "exceed"),
            ("submitting", "submit"),
            ("installed", "install"),
            ("cancelled", "cancel"),
        ],
    )
    def test_a_verb_and_its_inflection_share_a_key(self, inflected, base):
        assert words.stem(inflected) == words.stem(base)

    @pytest.mark.parametrize("word", ["running", "getting", "making"])
    def test_generic_verbs_are_left_apart(self, word):
        """`running` onto `run` hands that key the frequency of both, and the golden
        set charged 2.9pp of recall for it: `ecosystems.md` stopped being the best
        answer to "what clusters does RCC run" because every page mentions running
        something. A three-letter stem is scaffolding, not a topic."""
        assert words.stem(word) != words.stem(word[:3])

    @pytest.mark.parametrize("word", ["scoring", "sharing"])
    def test_gerunds_do_not_collapse_onto_four_letter_fragments(self, word):
        """`scoring` → `scor` matched a GIS page titled "Match Score" and scored a
        radiology question the corpus cannot answer at 28.7, on a title boost."""
        assert words.stem(word) == word

    def test_the_synonym_group_written_for_preemption_now_fires(self, real_index):
        weights = words.expand("my job was preempted")
        assert words.stem("scavenge") in weights


class TestAssessment:
    """Whether retrieval admits it is weak. Both thresholds are pinned here, on the
    labelled queries their values were measured from — the previous version of this
    idea shipped a threshold that passed the whole suite at any value from 0 to 20."""

    OUT_OF_SCOPE = [
        "how do I install OpenFOAM",
        "PI-RADS prostate MRI scoring",
        "mpMRI prostate imaging protocol",
        "what is the weather in Chicago",
        "who won the world cup",
        "how do I bake sourdough bread",
    ]
    # In scope, and each carrying a word the documentation has never seen: a daemon
    # named in an error message, a job ID, a CNetID, an error token.
    WITH_IDENTIFIERS = [
        "my job was killed by slurmstepd oom-kill event",
        "why did job 41235567 fail",
        "my CNetID is jsmith and I cannot log in",
        "srun: error: task 0 launch failed: Unspecified error",
    ]

    @pytest.mark.parametrize("question", OUT_OF_SCOPE)
    def test_out_of_scope_questions_are_not_confident(self, real_index, question):
        assessment = real_index.assess(question)
        assert not assessment.confident, f"{question!r} scored {assessment.top_score:.1f}"
        assert assessment.caveat()

    @pytest.mark.parametrize("question", WITH_IDENTIFIERS)
    def test_an_unseen_word_does_not_veto_strong_evidence(self, real_index, question):
        """This is what made the idea unusable before: every one of these was told the
        documentation does not cover it, and every one of them is answered by it."""
        assessment = real_index.assess(question)
        assert assessment.confident, (
            f"{question!r} scored {assessment.top_score:.1f} and was refused over "
            f"{assessment.unknown_terms}"
        )
        assert assessment.caveat() == ""

    def test_a_job_number_is_never_an_unseen_topic(self, real_index):
        assert real_index.assess("why did job 41235567 fail").unknown_terms == ()

    def test_the_caveat_quotes_the_readers_words_not_stems(self, real_index):
        """It said "No section contains: prostat, unspecifi, instal"."""
        assessment = real_index.assess("how do I bake sourdough bread")
        assert "sourdough" in assessment.caveat()
        # `bake` stems to `bak`, and the stem is what used to be quoted.
        assert "bake" in assessment.unknown_terms
        assert "bak" not in assessment.unknown_terms

    def test_a_caveat_is_not_a_percentage(self, real_index):
        assessment = real_index.assess("how do I install OpenFOAM")
        assert "%" not in assessment.caveat()
        assert assessment.margin >= 0


class TestNamingAnUnknownThing:
    """Telling a word that names something from a word that carries a value.

    This is what took the refusal gate from caveating 14 of 38 labelled unanswerable
    questions to 40 of 46, without moving either threshold — `tools/gate_check.py
    --sweep` had shown that no pair could, because the two sides occupy the same score
    range. Every case below is the shape of a real question, and the second half of the
    class is the half that must never regress: each one is answerable, and each one was
    refused by the first version of the weak-retrieval idea.
    """

    def test_a_cluster_that_does_not_exist(self, real_index):
        """`midway4` — the corpus knows `midway`, and the digit rule made this invisible."""
        assessment = real_index.assess("how many GPUs per node does Midway4 have")
        assert not assessment.confident
        assert "midway4" in assessment.named_topics

    def test_named_topics_is_a_subset_of_the_unknown_terms(self, real_index):
        """Same words, same spelling, so the two can be compared."""
        for question in (
            "how do I submit a job on Frontera",
            "how many GPUs per node does Midway4 have",
            "how do I submit a job with qsub",
        ):
            assessment = real_index.assess(question)
            assert set(assessment.named_topics) <= set(assessment.unknown_terms)

    def test_a_partition_that_does_not_exist(self, real_index):
        assert not real_index.assess(
            "what is the memory limit on the bigmem3 partition"
        ).confident

    def test_a_cluster_that_does_exist(self, real_index):
        """The same rule must not fire on the real one."""
        assessment = real_index.assess("how many GPUs per node does Midway3 have")
        assert assessment.named_topics == ()
        assert assessment.confident

    def test_another_sites_machine_by_its_capital_letter(self, real_index):
        assessment = real_index.assess("how do I submit a job on Frontera")
        assert not assessment.confident
        assert "frontera" in assessment.named_topics
        # Scores well above STRONG_SCORE: every word but the machine's name matches
        # sbatch.md, which is exactly why `strong` used to walk straight past it.
        assert assessment.strong

    def test_a_scheduler_this_centre_does_not_run(self, real_index):
        """Lower case, so it is the naming preposition that catches `with qsub`."""
        assessment = real_index.assess("how do I submit a job with qsub")
        assert not assessment.confident
        assert "qsub" in assessment.named_topics

    def test_a_package_that_is_not_installed(self, real_index):
        assert not real_index.assess("is Abaqus available on Midway").confident

    def test_an_undocumented_partition_named_in_prose(self, real_index):
        """`turbo` is neither capitalised nor versioned: the report rule catches it.

        "How do I submit to the turbo partition" is a question *about* the unknown word,
        not a report of something that happened, so evidence does not outweigh it.
        """
        assert not real_index.assess("how do I submit to the turbo partition").confident

    # --- and the other side, which must not move -------------------------------

    def test_a_daemon_in_a_message(self, real_index):
        assessment = real_index.assess("my job was killed by slurmstepd oom-kill event")
        assert assessment.confident
        assert assessment.named_topics == ()
        assert assessment.reporting

    def test_a_pasted_log_line(self, real_index):
        assert real_index.assess(
            "srun: error: task 0 launch failed: Unspecified error"
        ).confident

    def test_a_capital_letter_after_a_colon_is_not_a_name(self, real_index):
        """`Unspecified` is capitalised because a colon precedes it, not because it names
        anything. Without the boundary rule this was an over-refusal."""
        assessment = real_index.assess(
            "sbatch: error: Batch job submission failed: Invalid account"
        )
        assert assessment.named_topics == ()

    def test_a_username_the_reader_supplied(self, real_index):
        assert real_index.assess("my CNetID is jsmith and I cannot log in").confident

    def test_shouting_is_not_a_proper_noun(self, real_index):
        """Readers paste error messages in caps, and in caps everything is capitalised.

        Both of these answer in ordinary case; without the shouting guard the capital
        letters alone made `slurmstepd` and `jsmith` read as names of systems the
        documentation has never heard of, and the same question was refused for being
        typed loudly.
        """
        for question in (
            "MY JOB WAS KILLED BY SLURMSTEPD OOM-KILL EVENT",
            "MY CNETID IS JSMITH AND I CANNOT LOG IN",
        ):
            assessment = real_index.assess(question)
            assert assessment.named_topics == (), question
            assert assessment.confident, question

    def test_shouting_does_not_rescue_a_thing_that_is_named(self, real_index):
        """The other signals do not depend on case, so caps cannot smuggle one past."""
        assert not real_index.assess("HOW DO I SUBMIT A JOB ON FRONTERA").confident
        assert not real_index.assess("HOW MANY GPUS DOES MIDWAY4 HAVE").confident

    def test_an_all_caps_name_inside_an_ordinary_question_still_counts(self, real_index):
        """`ANSYS` is a name in caps; the guard is about the *query*, not the word."""
        assessment = real_index.assess("how do I load the ANSYS Fluent module")
        assert "ansys" in assessment.named_topics

    def test_a_regional_spelling_of_a_word_the_corpus_uses(self, real_index):
        """`favourite` is one edit from `favorite`, which is the FAQ heading's spelling."""
        assessment = real_index.assess("why is my favourite command not available")
        assert assessment.confident
        assert "favourite" not in assessment.unknown_terms

    def test_a_short_word_is_not_treated_as_a_misspelling(self, real_index):
        """`book` is one edit from `boot`, which the corpus uses 27 times."""
        assert not real_index.assess(
            "how do I book a study room in the library"
        ).confident

    def test_vocabulary_the_profile_declares_is_known(self, real_index):
        """`scavenge` is in the RCC profile's synonym groups and in none of its pages.

        The documentation calls the same thing preemptible. Refusing over a word the
        deployment's own configuration supplies would be the app contradicting itself.
        """
        assessment = real_index.assess("what does the scavenge partition do")
        assert assessment.unknown_terms == ()
        assert assessment.confident


class TestAnAddressIsMadeOfNames:
    """Inside a URL, both signals that decide "does this word name a thing?" are blind.

    A hostname's labels are lower case, so capitalisation says nothing, and no preposition
    introduces them — so `how do I use https://frontera.tacc.utexas.edu` scored 27.4 with
    `frontera`, `tacc` and `utexas` all unknown to the corpus and the gate stayed
    confident. Pasting an address is how a reader asks about a *page* rather than a topic,
    which makes it an ordinary query rather than an exotic one.

    Scheme-anchored deliberately: a bare dotted host is the same shape as a filename, and
    reading `job.sh` or `python3.11` as a name would refuse the answerable questions the
    second half of `TestNamingAnUnknownThing` exists to protect.
    """

    def shapes(self, query: str) -> dict[str, bool]:
        return {
            mention.word.lower(): mention.in_address
            for mention in text.mentions(query)
        }

    def test_a_word_inside_a_url_is_marked(self):
        found = self.shapes("how do I use https://frontera.tacc.utexas.edu today")
        assert found["frontera"] and found["tacc"] and found["utexas"]
        assert not found["how"] and not found["use"] and not found["today"]

    def test_www_counts_as_an_address(self):
        assert self.shapes("see www.tacc.utexas.edu/frontera")["frontera"]

    @pytest.mark.parametrize("query", [
        "my job wrote job.sh and job.out",
        "how do I load python3.11",
        "quota exceeded writing to /project2/pi-jsmith",
        "srun: error: task 0 launch failed",
    ])
    def test_a_dotted_filename_is_not_an_address(self, query):
        assert not any(self.shapes(query).values()), query

    def test_it_names_a_thing_without_a_capital_or_a_preposition(self):
        mention = next(
            item for item in text.mentions("see https://frontera.tacc.utexas.edu")
            if item.word.lower() == "frontera"
        )
        assert not mention.capitalized
        assert mention.previous not in text.NAMING_PREPOSITIONS
        assert text.names_a_thing(mention, versioned=False)

    def test_the_gate_caveats_a_foreign_url_and_not_an_rcc_one(self, real_index):
        foreign = real_index.assess("how do I use https://frontera.tacc.utexas.edu")
        ours = real_index.assess(
            "what does https://docs.rcc.uchicago.edu/slurm/sbatch/ say about the account flag"
        )
        assert not foreign.confident, "another centre's machine, named only in a URL"
        assert ours.confident, "our own documentation URL must still be answered"

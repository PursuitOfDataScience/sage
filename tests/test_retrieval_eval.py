"""Golden-set retrieval eval.

Without this there is no way to tell whether a ranking change made answers better
or worse — every tweak to scoring, synonyms or chunking is otherwise a guess. Each
case is a question a real RCC user would ask, paired with the page(s) that should
be retrieved for it. Some questions have more than one defensible answer page;
those list all of them.

Add a case whenever a bad answer is reported. A failure here means retrieval
regressed — fix the ranking, don't loosen the case.

Measured, not remembered: this line said "recall@5 97%, recall@3 94%,
precision@1 79%" for a configuration that scored 97/97/79 — the recall@3 figure was
never true of the committed code, and a hand-written number nobody re-derives is worse
than none. Print them with `tools/metrics.py` rather than trusting this paragraph:

    recall@5 100%, recall@3 100%, precision@1 85% over the 33 cases below.

The ratchets are one case below each of those, so a single regression fails and the
slack is stated rather than hidden.
"""

import pytest

# (question, pages any one of which is an acceptable top hit)
CASES: list[tuple[str, tuple[str, ...]]] = [
    # --- Slurm ---
    ("how do I submit a batch job with sbatch", ("slurm/sbatch.md",)),
    ("submit a job script to the queue", ("slurm/sbatch.md",)),
    ("how do I request a GPU in my job", ("slurm/sbatch.md", "slurm/partitions.md")),
    ("run a large memory job", ("slurm/sbatch.md",)),
    ("how do I check the status of my job", ("slurm/sbatch.md",)),
    ("cancel a running job", ("slurm/sbatch.md",)),
    ("my job failed because it exceeded the memory limit", ("slurm/faq.md",)),
    ("why is my job stuck in the queue", ("slurm/faq.md", "slurm/sbatch.md")),
    ("what partitions can I use", ("slurm/partitions.md",)),
    ("start an interactive session on a compute node", ("slurm/sinteractive.md",)),
    ("what is a service unit", ("allocations.md",)),
    ("how do I check my allocation balance", ("allocations.md",)),
    # --- Storage ---
    ("what are the storage quotas", ("storage/main.md", "storage/faq.md")),
    ("difference between home project and scratch", ("storage/main.md",)),
    ("is scratch space backed up or purged", ("storage/main.md",)),
    ("how do I see how much disk space I have left", ("storage/faq.md",)),
    ("how do I request more storage", ("storage/faq.md",)),
    # --- Connecting ---
    ("how do I connect to midway with ssh", ("connection/ssh/main.md",)),
    ("set up a remote desktop session", ("connection/thinlinc/main.md",)),
    (
        "thinlinc will not connect",
        ("connection/thinlinc/troubleshooting.md", "connection/thinlinc/main.md"),
    ),
    # --- Data transfer and sharing ---
    ("transfer files with globus", ("data_transfer/globus/transfer-files.md",)),
    (
        "mount my project directory as a network drive",
        ("data_transfer/persistent_mapping/samba.md",),
    ),
    # NB: docs/data_transfer/cloud/rclone.md is a 0-byte file upstream, so no
    # rclone-specific question is answerable until the User Guide fills it in.
    ("sync data to cloud storage", ("data_transfer/cloud/cloud-sync.md",)),
    (
        "share files with a collaborator outside the university",
        ("data_sharing/globus_sharing.md", "data_sharing/access_control.md"),
    ),
    # --- Software ---
    ("how do I set up a python environment", ("software/apps-and-envs/python.md",)),
    ("install a package with conda", ("software/apps-and-envs/python.md",)),
    ("how do I run pytorch on a gpu", ("software/apps-and-envs/tf-and-torch.md",)),
    ("run matlab on the cluster", ("software/apps-and-envs/matlab.md",)),
    ("use R on midway", ("software/apps-and-envs/r.md",)),
    ("run gromacs simulations", ("software/apps-and-envs/gromacs.md",)),
    (
        "use a container image",
        ("software/apps-and-envs/charliecloud.md", "software/apps-and-envs/singularity.md"),
    ),
    # --- Accounts and systems ---
    ("how do I get an RCC account", ("accounts.md",)),
    ("what clusters does RCC run", ("ecosystems.md",)),
]

# Questions lexical search cannot reach today, kept visible rather than deleted.
# "which queue should I submit to" is hard because slurm/partitions.md never uses the
# word "queue" — a genuine BM25 limitation that embeddings would close. It now reaches
# rank 5 (so this xfails-not-strictly and reports an xpass) because capping sections
# per page stopped slurm/sbatch.md taking the whole result set. Kept here rather than
# promoted: at exactly rank 5 it is one ranking wobble from failing, and a case that
# flaps in CI teaches nothing.
KNOWN_GAPS: list[tuple[str, tuple[str, ...]]] = [
    ("which queue should I submit to", ("slurm/partitions.md", "slurm/main.md")),
]

RECALL_AT = 5
# Ratchet. Raise it when retrieval improves; never lower it to make CI pass.
MINIMUM_RECALL_AT_5 = 0.96      # measured 1.00; one of 33 cases is 3.0pp
MINIMUM_RECALL_AT_3 = 0.96      # measured 1.00
MINIMUM_PRECISION_AT_1 = 0.87   # measured 0.91 (was 0.85, before the title field
                                # was length-normalised)


def pages(index, question, limit):
    return {result.chunk.path for result in index.search(question, limit)}


def hit(index, question, expected, limit):
    return bool(set(expected) & pages(index, question, limit))


@pytest.mark.parametrize(("question", "expected"), CASES, ids=[c[0] for c in CASES])
def test_case(real_index, question, expected):
    found = pages(real_index, question, RECALL_AT)
    assert set(expected) & found, f"wanted one of {expected}, got {sorted(found)}"


@pytest.mark.parametrize(
    ("question", "expected"), KNOWN_GAPS, ids=[c[0] for c in KNOWN_GAPS]
)
@pytest.mark.xfail(reason="known lexical-search gap", strict=False)
def test_known_gap(real_index, question, expected):
    found = pages(real_index, question, RECALL_AT)
    assert set(expected) & found, f"wanted one of {expected}, got {sorted(found)}"


def test_recall_at_5(real_index):
    score = sum(hit(real_index, q, e, 5) for q, e in CASES) / len(CASES)
    assert score >= MINIMUM_RECALL_AT_5, f"recall@5 fell to {score:.0%}"


def test_recall_at_3(real_index):
    score = sum(hit(real_index, q, e, 3) for q, e in CASES) / len(CASES)
    assert score >= MINIMUM_RECALL_AT_3, f"recall@3 fell to {score:.0%}"


def test_precision_at_1(real_index):
    """Matters most: the model usually reads the first result."""
    score = sum(hit(real_index, q, e, 1) for q, e in CASES) / len(CASES)
    assert score >= MINIMUM_PRECISION_AT_1, f"precision@1 fell to {score:.0%}"


def test_every_answerable_question_is_reported_as_confident(real_index):
    """The other half of the weak-retrieval caveat, and the half that decides whether
    it is usable: a warning that fires on questions the documentation answers teaches
    the model to ignore it. Every case in the golden set must come back clean."""
    noisy = [
        (question, real_index.assess(question))
        for question, _ in CASES + KNOWN_GAPS
    ]
    wrong = [
        f"{question!r} (top {a.top_score:.1f}, unseen {a.unknown_terms})"
        for question, a in noisy
        if not a.confident
    ]
    assert not wrong, "caveated an answerable question: " + "; ".join(wrong)


def test_out_of_scope_questions_are_caveated(real_index):
    """And the first half: something the corpus cannot answer must say so. These are
    scored above the excluded-content pair below — "install OpenFOAM" reaches 23.9 on
    the strength of "how do I install" alone — so a score floor alone cannot catch
    them and the unseen-word rule has to."""
    for question in ("how do I install OpenFOAM", "how do I bake sourdough bread"):
        assessment = real_index.assess(question)
        assert not assessment.confident, f"{question!r} passed as answerable"
        assert "documentation does not appear to cover it" in assessment.caveat()


def test_excluded_content_never_scores_confidently(real_index):
    """The radiology scrape is out of the index; these must stay weak, not vanish."""
    for question in (
        "PI-RADS prostate MRI scoring",
        "mpMRI prostate imaging protocol",
    ):
        results = real_index.search(question, limit=1)
        top = results[0].score if results else 0.0
        assert top < 20, f"{question!r} scored {top:.1f}"


def test_every_advertised_path_can_be_read_back(real_index):
    """A path search_docs returns must always resolve in read_doc."""
    from sage.tools import READ_DOC, build

    runner = build(real_index).runner()
    for question, _expected in CASES[:12]:
        for result in real_index.search(question, limit=3):
            out = runner.run(READ_DOC, {"path": result.id})
            assert not out.startswith("Error:"), f"{result.id} -> {out[:80]}"


class TestTheCardAndTheRatchetMeasureTheSameThing:
    """`tools/metrics.py` computes recall@5; this file ratchets it. Two computations.

    They are not written the same way: the tests search with `limit=RECALL_AT` and ask
    whether a gold page is among the results, while `metrics.measure` searches with
    `limit=6` and slices the first five. With `MAX_PER_PAGE` capping sections per page,
    those need not be the same five pages — and if they ever stop being, the card quotes
    one number while CI gates on another, with nothing saying so.

    The same gap was real in `evals/gate.py`: its threshold sweep never evaluated the pair
    the app runs at, so the front was a set of alternatives to a point that was not on it.
    """

    @pytest.fixture(scope="class")
    def metrics(self):
        from tools import metrics as tool

        return tool

    def test_the_case_list_read_with_ast_is_the_one_defined_here(self, metrics):
        """`metrics.py` parses this file rather than importing it, to run without pytest."""
        known, gaps = metrics.cases()
        assert [tuple(case) for case in known] == [
            (question, tuple(pages)) for question, pages in CASES
        ]
        assert [tuple(case) for case in gaps] == [
            (question, tuple(pages)) for question, pages in KNOWN_GAPS
        ]

    def test_slicing_six_results_gives_the_same_five_pages(self, real_index, metrics):
        known, gaps = metrics.cases()
        differ = [
            question
            for question, _expected in known + gaps
            if [result.chunk.path for result in real_index.search(question, RECALL_AT)]
            != [result.chunk.path for result in real_index.search(question, 6)][:RECALL_AT]
        ]
        assert not differ, (
            "searching for six and slicing five no longer matches searching for five, so "
            "the card and the ratchet are measuring different sets: " + "; ".join(differ[:3])
        )

    def test_the_two_recall_figures_agree(self, real_index, metrics):
        known, _gaps = metrics.cases()
        ratcheted = sum(
            hit(real_index, question, expected, RECALL_AT) for question, expected in CASES
        ) / len(CASES)
        assert metrics.measure(real_index, known)["recall@5"] == pytest.approx(ratcheted)

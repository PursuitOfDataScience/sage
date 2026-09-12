import pytest

from sage import normalize


def test_content_tabs_become_labelled_blocks():
    """The bug this fixes: read raw, nothing said which cluster owned which command."""
    source = """## What Partitions I Can Use?

=== "Midway2"
    ```
    sacctmgr list assoc account=$ACCOUNT
    ```
===+ "Midway3, Beagle3"
    ```
    scontrol show partition
    ```
"""
    out = normalize.normalize_markdown(source)
    assert "**Midway2**" in out
    assert "**Midway3, Beagle3**" in out
    assert out.index("**Midway2**") < out.index("sacctmgr")
    assert out.index("sacctmgr") < out.index("**Midway3, Beagle3**")
    assert out.index("**Midway3, Beagle3**") < out.index("scontrol")


def test_setext_underline_is_not_a_content_tab():
    out = normalize.normalize_markdown("Title\n=====\n\nBody text here.")
    assert "**" not in out
    assert "=====" in out


def test_admonition_variants():
    source = """!!! tip "Advanced tip"
    Configure SACCT_FORMAT.

!!! Note: `0:00` jobs
    Still queued.

??? warning
    Careful.

!!! Notes
    Bare label.
"""
    out = normalize.normalize_markdown(source)
    assert "**Advanced tip**" in out
    assert "**Note: `0:00` jobs**" in out
    assert "**Warning**" in out
    assert "**Notes**" in out
    assert "Configure SACCT_FORMAT." in out
    assert "Still queued." in out


def test_admonition_body_is_dedented():
    out = normalize.normalize_markdown('!!! note "T"\n    line one\n    line two\n')
    assert "\nline one\nline two" in out


def test_kramdown_attribute_lists_are_removed():
    out = normalize.normalize_markdown(
        "See [the guide](https://x.example){:target='_blank'} today.\n"
    )
    assert "{:target" not in out
    assert "[the guide](https://x.example)" in out


def test_html_is_stripped_but_prose_comparisons_survive():
    out = normalize.normalize_markdown(
        "<p align='center'>Centred</p>\n\nUse when a < b and b > c.\n"
    )
    assert "Centred" in out
    assert "<p" not in out
    assert "a < b and b > c" in out


def test_images_keep_their_alt_text():
    out = normalize.normalize_markdown("<img src='img/x.png' alt='Globus login screen'/>")
    assert out == "[figure: Globus login screen]"


def test_html_comments_are_dropped():
    assert "secret" not in normalize.normalize_markdown("a <!-- secret --> b")


def test_code_fences_are_untouched():
    source = "```bash\n!!! not an admonition\n=== \"not a tab\"\n<div>kept</div>\n```\n"
    out = normalize.normalize_markdown(source)
    assert "!!! not an admonition" in out
    assert '=== "not a tab"' in out
    assert "<div>kept</div>" in out


def test_indented_fence_inside_a_tab_survives_dedent():
    source = '=== "Midway3"\n    ```bash\n    module load python\n    ```\n'
    out = normalize.normalize_markdown(source)
    assert "```bash\nmodule load python\n```" in out


def test_parse_scraped_extracts_the_real_url():
    raw = (
        "URL: https://cloud-skyway.rcc.uchicago.edu/faqs\n"
        "Title: FAQs | Skyway - RCC Cloud Solution\n"
        "==============================================\n"
        "Frequently Asked Questions\n"
    )
    url, title, body = normalize.parse_scraped(raw)
    assert url == "https://cloud-skyway.rcc.uchicago.edu/faqs"
    assert title == "FAQs"  # site suffix dropped
    assert body == "Frequently Asked Questions"


def test_parse_scraped_tolerates_a_missing_header():
    url, title, body = normalize.parse_scraped("Just some text\n")
    assert (url, title) == ("", "")
    assert body == "Just some text"


def test_collapse_blank_lines():
    assert normalize.collapse_blank_lines("\n\na\n\n\n\nb\n\n") == "a\n\nb"


class TestSlugify:
    """Anchors must match what mkdocs-material generates or citations 404."""

    def test_punctuation_and_case(self):
        assert (
            normalize.slugify("How Do I Get a Full List of Partitions?")
            == "how-do-i-get-a-full-list-of-partitions"
        )

    def test_inline_code(self):
        assert normalize.slugify("`squeue` status and reason codes") == (
            "squeue-status-and-reason-codes"
        )

    def test_markdown_link_is_unwrapped(self):
        assert normalize.slugify("[GM4](https://gm4.rcc.uchicago.edu)") == "gm4"

    def test_slash(self):
        assert normalize.slugify("How much space do I have left/used?") == (
            "how-much-space-do-i-have-leftused"
        )


def test_plain_heading_drops_emphasis():
    assert normalize.plain_heading("Configuring Python for **`scode`**") == (
        "Configuring Python for scode"
    )


def test_plain_heading_unescapes_what_markdown_would_have_rendered():
    r"""`## 1\. Formatting Data` escapes the period so mkdocs does not read the line as
    an ordered list. mkdocs renders `1.`; the citation strip showed `1\.`, backslash and
    all, on all four headings of the geocoding tutorial. The published anchor is
    slugified from the rendered text, and this leaves it alone — the backslash was
    already being dropped there as punctuation."""
    assert normalize.plain_heading(r"1\. Formatting Data for Processing") == (
        "1. Formatting Data for Processing"
    )
    assert normalize.slugify(r"1\. Formatting Data for Processing") == (
        "1-formatting-data-for-processing"
    )
    # Only punctuation is escapable in markdown, so a backslash in front of a letter
    # is a literal one and stays — `\n` in a heading about escape sequences.
    assert normalize.plain_heading(r"What \n means") == r"What \n means"


def test_pretty_title():
    assert normalize.pretty_title("a/b/data-management.md") == "Data management"


def test_pretty_title_of_an_index_page_names_its_directory():
    """the mkdocs URL scheme publishes `software/index.md` at `software/`; "Index" is not a page
    name a reader can place in a citation."""
    assert normalize.pretty_title("software/index.md") == "Software"
    assert normalize.pretty_title("tutorials/gis/index.md") == "Gis"
    # Nothing above it to borrow a name from.
    assert normalize.pretty_title("index.md") == "Index"


class TestAnExplicitHeadingId:
    """attr_list writes the anchor outright, and mkdocs publishes it verbatim.

    `## Using renv {#using-the-renv}` is not a heading with decoration on the end — the
    braces ARE the anchor, and a slug derived from the text beside them is a different
    one. `tools/anchor_check.py` caught it as the site's `#using-the-renv` against our
    `#using-the-renv-r-package-for-project-environments`: a link that resolves, looks
    right, and lands the reader at the top of the page.

    Zero chunks in today's snapshot carry one; upstream added this one after the
    snapshot was taken, so the check is against the next `refresh-docs.sh`.
    """

    HEADING = "Using the renv R Package for Project Environments {#using-the-renv}"

    def test_the_stated_id_is_the_anchor(self):
        assert normalize.slugify(self.HEADING) == "using-the-renv"

    def test_the_label_does_not_carry_the_marker(self):
        assert normalize.plain_heading(self.HEADING) == (
            "Using the renv R Package for Project Environments"
        )

    @pytest.mark.parametrize("heading", [
        # Not an id: a kramdown attribute list, which `_clean_prose` already drops, and
        # a brace that is part of the prose.
        "Formatting {: .note }",
        "Using ${SLURM_JOB_ID} in a script",
        "A heading with {braces} in it",
        "Plain heading",
    ])
    def test_an_ordinary_heading_is_slugified_as_before(self, heading):
        assert normalize.slugify(heading) == normalize.slugify(
            normalize.plain_heading(heading)
        )


class TestTheUrlAScrapeClaims:
    """That string becomes the `href` of every citation to the page.

    Whatever followed `URL:` was taken verbatim, so a scrape that wrote a relative path
    produced citations pointing at something that is not a page, and `javascript:` would
    have gone into a markdown link inside an answer. All 55 bundled scrapes carry an
    `https://` URL, so this changes nothing today — it is about the day the scraper's
    output shifts.
    """

    def page(self, url_line: str) -> str:
        return f"{url_line}\nTitle: Midway2 | RCC\n{'=' * 40}\nbody text here"

    def test_an_https_url_is_kept(self):
        url, title, body = normalize.parse_scraped(
            self.page("URL: https://rcc.uchicago.edu/midway2")
        )
        assert url == "https://rcc.uchicago.edu/midway2"
        assert title == "Midway2"
        assert "body text here" in body

    def test_http_is_kept_too(self):
        url, _title, _body = normalize.parse_scraped(
            self.page("URL: http://rcc.uchicago.edu/midway2")
        )
        assert url == "http://rcc.uchicago.edu/midway2"

    @pytest.mark.parametrize(
        "claimed",
        ["javascript:alert(1)", "data:text/html,<script>x</script>",
         "file:///etc/passwd", "/relative/path", "rcc.uchicago.edu/no-scheme", ""],
    )
    def test_anything_else_is_treated_as_absent(self, claimed):
        """Absent falls back to the source's base_url — a link to the site root is a
        worse citation than a deep one and a better one than a broken href."""
        url, _title, body = normalize.parse_scraped(self.page(f"URL: {claimed}"))
        assert url == ""
        assert "body text here" in body

    def test_the_body_still_starts_after_the_rule(self):
        """Rejecting the URL must not move where the body begins."""
        _url, _title, body = normalize.parse_scraped(self.page("URL: /relative"))
        assert body.strip() == "body text here"

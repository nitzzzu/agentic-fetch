"""Behavioral tests for markdown helpers: grep output format, pagination
boundaries, link absolutization, and readability extraction fallbacks."""

import pytest

from agentic_fetch.markdown import (
    MarkdownExtractor,
    extract_toc,
    grep_markdown,
    paginate,
)

TEN_LINES = "\n".join(f"line number {i}" for i in range(1, 11))


class TestGrepMarkdown:
    def test_match_line_is_starred_with_context_unstarred(self):
        out = grep_markdown(TEN_LINES, "number 5", context_lines=1)
        assert "   4  line number 4" in out
        assert "   5* line number 5" in out
        assert "   6  line number 6" in out
        assert "line number 3" not in out

    def test_header_reports_match_and_line_counts(self):
        out = grep_markdown(TEN_LINES, "number", context_lines=0)
        assert out.startswith("10 matches for 'number' in 10 lines")

    def test_single_match_uses_singular_wording(self):
        out = grep_markdown(TEN_LINES, "number 7", context_lines=0)
        assert out.startswith("1 match for 'number 7' in 10 lines")

    def test_no_matches_message(self):
        out = grep_markdown(TEN_LINES, "absent")
        assert out == "no matches for 'absent' in 10 lines\n"

    def test_disjoint_match_blocks_are_separated(self):
        out = grep_markdown(TEN_LINES, "number (2|9)", context_lines=1)
        assert "\n--\n" in out

    def test_adjacent_context_windows_are_not_separated_or_duplicated(self):
        out = grep_markdown(TEN_LINES, "number (4|6)", context_lines=1)
        assert "--" not in out.replace("number", "")
        assert out.count("line number 5") == 1

    def test_max_matches_truncates_with_remainder_note(self):
        out = grep_markdown(TEN_LINES, "number", context_lines=0, max_matches=3)
        assert "(showing first 3)" in out
        assert "[7 more matches" in out
        assert "number 4" not in out.split("[")[0].splitlines()[-1]

    def test_ignore_case_flag(self):
        assert "no matches" in grep_markdown("Alpha", "alpha")
        assert "1 match" in grep_markdown("Alpha", "alpha", ignore_case=True)

    def test_invalid_regex_reports_error_instead_of_raising(self):
        out = grep_markdown(TEN_LINES, "[unclosed")
        assert out.startswith("Invalid pattern:")


class TestPaginate:
    def test_no_budget_returns_everything(self):
        text = "abc" * 100
        chunk, truncated, next_offset = paginate(text, 0, None)
        assert (chunk, truncated, next_offset) == (text, False, len(text))

    def test_text_within_budget_is_not_truncated(self):
        chunk, truncated, next_offset = paginate("short", 0, 1000)
        assert (chunk, truncated, next_offset) == ("short", False, 5)

    def test_oversize_text_is_cut_at_a_newline(self):
        # budget of 10 tokens = 40 chars; newline at char 30 is past the halfway
        # point, so the cut happens there
        text = "a" * 30 + "\n" + "b" * 50
        chunk, truncated, next_offset = paginate(text, 0, 10)
        assert chunk == "a" * 30
        assert truncated is True
        assert next_offset == 30

    def test_early_newline_is_ignored_for_the_cut(self):
        # newline at char 5 is before half the 40-char budget → hard cut at 40
        text = "a" * 5 + "\n" + "b" * 100
        chunk, truncated, next_offset = paginate(text, 0, 10)
        assert len(chunk) == 40
        assert next_offset == 40

    def test_offset_resumes_where_previous_page_ended(self):
        text = "x" * 100
        first, truncated, offset = paginate(text, 0, 10)
        assert truncated is True
        second, truncated2, end = paginate(text, offset, 100)
        assert first + second == text
        assert truncated2 is False

    def test_offset_at_end_returns_empty_tail(self):
        chunk, truncated, end = paginate("abcdef", 6, 10)
        assert (chunk, truncated, end) == ("", False, 6)


class TestLinkAbsolutization:
    def test_relative_links_resolve_against_base_url(self):
        html = '<html><body><p>See <a href="/docs/page">the docs</a></p></body></html>'
        md = MarkdownExtractor(html, base_url="https://site.test/root").to_markdown()
        assert "https://site.test/docs/page" in md

    def test_absolute_links_are_untouched(self):
        html = '<html><body><p><a href="https://other.test/x">link</a></p></body></html>'
        md = MarkdownExtractor(html, base_url="https://site.test/").to_markdown()
        assert "https://other.test/x" in md

    def test_without_base_url_relative_links_stay_relative(self):
        html = '<html><body><p><a href="/docs/page">docs</a></p></body></html>'
        md = MarkdownExtractor(html).to_markdown()
        assert "site.test" not in md
        assert "/docs/page" in md

    def test_relative_src_resolves_against_base_url(self):
        html = '<html><body><p><img src="pics/a.png"></p></body></html>'
        md = MarkdownExtractor(
            html, base_url="https://site.test/root/page"
        ).to_markdown(include_images=True)
        assert "https://site.test/root/pics/a.png" in md

    def test_relative_src_resolves_on_non_image_tags(self):
        html = '<html><body><p><iframe src="/embed/1"></iframe></p></body></html>'
        md = MarkdownExtractor(html, base_url="https://site.test/root/").to_markdown()
        assert "https://site.test/embed/1" in md

    def test_links_inside_readability_extracted_article_are_absolutized(self):
        paragraphs = "".join(
            f'<p>Article paragraph {i} with a <a href="/doc/{i}">reference link</a> '
            f"and enough words to count as real content.</p>"
            for i in range(8)
        )
        html = f"<html><body><article>{paragraphs}</article></body></html>"
        md = MarkdownExtractor(html, base_url="https://site.test/base/").to_markdown()
        assert "https://site.test/doc/3" in md


class TestReadabilityFallback:
    def test_script_only_page_falls_back_to_raw_html(self):
        html = (
            "<html><body><script>var x=1;</script><script>var y=2;</script>"
            "<p>tiny</p></body></html>"
        )
        md = MarkdownExtractor(html).to_markdown()
        assert "tiny" in md
        assert "var x" not in md  # scripts stripped either way

    def test_article_page_drops_boilerplate_navigation(self):
        paragraphs = "".join(
            f"<p>Meaningful article sentence number {i} that carries the actual "
            f"content of this page for readers.</p>"
            for i in range(10)
        )
        html = (
            "<html><body>"
            "<nav><a href='/a'>navigation-chrome-link</a></nav>"
            f"<article>{paragraphs}</article>"
            "</body></html>"
        )
        md = MarkdownExtractor(html).to_markdown()
        assert "Meaningful article sentence number 3" in md
        assert "navigation-chrome-link" not in md

    def test_explicit_selector_wins_over_readability(self):
        html = (
            "<html><body><div id='keep'><p>selected content</p></div>"
            "<div><p>other content</p></div></body></html>"
        )
        md = MarkdownExtractor(html).to_markdown(selector="#keep")
        assert "selected content" in md
        assert "other content" not in md

    def test_selector_matching_nothing_falls_back_to_whole_document(self):
        html = "<html><body><p>alpha</p><p>beta</p></body></html>"
        md = MarkdownExtractor(html).to_markdown(selector="#absent")
        assert "alpha" in md
        assert "beta" in md

    def test_page_keeping_under_a_tenth_of_its_text_falls_back_to_raw_html(self):
        # readability drops the #sidebar block as an unlikely candidate, keeping
        # only ~3% of the page's visible text — too little to trust, so the whole
        # document is converted instead.
        article = "".join(
            f"<p>Core article line {i} with enough words to count as meaningful "
            f"text.</p>"
            for i in range(6)
        )
        sidebar = "".join(
            f"<p>Sidebar prose paragraph {i} rambling on and on with plenty of "
            f"filler words.</p>"
            for i in range(200)
        )
        html = (
            f"<html><body><article>{article}</article>"
            f"<div id='sidebar'>{sidebar}</div></body></html>"
        )
        md = MarkdownExtractor(html).to_markdown()
        assert "Core article line 3" in md
        assert "Sidebar prose paragraph 7" in md

    def test_bulk_inline_script_does_not_trigger_the_ratio_fallback(self):
        # Script bytes dominate the markup but carry no visible text, so the
        # extracted article still clears the ratio and boilerplate stays stripped.
        article = "".join(
            f"<p>Core article line {i} with enough words to count as meaningful "
            f"text.</p>"
            for i in range(6)
        )
        html = (
            "<html><body><nav><a href='/a'>navigation-chrome-link</a></nav>"
            f"<article>{article}</article>"
            f"<script>var payload = '{'x' * 60000}';</script></body></html>"
        )
        md = MarkdownExtractor(html).to_markdown()
        assert "Core article line 3" in md
        assert "navigation-chrome-link" not in md
        assert "xxxxx" not in md

    def test_unparseable_html_yields_empty_markdown(self):
        assert MarkdownExtractor("").to_markdown() == ""


class TestExtractorReuse:
    def test_title_is_available_after_conversion(self):
        ext = MarkdownExtractor(
            "<html><head><title>Doc</title></head><body><p>body text</p></body></html>"
        )
        ext.to_markdown()
        assert ext.title == "Doc"

    def test_repeated_conversion_returns_the_same_markdown(self):
        html = (
            "<html><body><nav>chrome</nav><div id='main'><p>stable body</p></div>"
            "</body></html>"
        )
        ext = MarkdownExtractor(html, base_url="https://site.test/")
        assert ext.to_markdown(selector="#main") == ext.to_markdown(selector="#main")


class TestExtractToc:
    def test_heading_ranges_end_where_the_next_heading_starts(self):
        md = "# One\nbody\n## Two\nmore\n# Three\ntail"
        toc = extract_toc(md)
        assert [t["title"] for t in toc] == ["One", "Two", "Three"]
        assert [t["level"] for t in toc] == [1, 2, 1]
        assert toc[0]["start_line"] == 1
        assert toc[0]["end_line"] == 2
        assert toc[1]["end_line"] == 4
        assert toc[2]["end_line"] == 6  # last heading runs to EOF

    def test_no_headings_yields_empty_toc(self):
        assert extract_toc("plain text\nno headings") == []

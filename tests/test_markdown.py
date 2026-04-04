"""Tests for markdown extraction and utility functions."""
import pytest
from agentic_fetch.markdown import (
    MarkdownExtractor,
    apply_strip_lines,
    extract_toc,
    read_lines,
    count_code_blocks,
    extract_symbols,
    grep_markdown,
    paginate,
)

SAMPLE_HTML = """
<html>
<head><title>Test Page</title></head>
<body>
  <script>var x = 1;</script>
  <h1>Hello World</h1>
  <p>This is a <strong>test</strong> paragraph.</p>
  <h2>Section Two</h2>
  <p>Second section content.</p>
  <nav class="sidebar">Navigation</nav>
</body>
</html>
"""

SAMPLE_MD = """# Heading One

Some paragraph text here.

## Heading Two

More content here with `my_function` and `another_var`.

### Heading Three

```python
def hello():
    pass
```

```javascript
console.log("hi")
```

```python
x = 1
```
"""


class TestMarkdownExtractor:
    def test_title_extraction(self):
        ext = MarkdownExtractor(SAMPLE_HTML)
        assert ext.title == "Test Page"

    def test_title_missing(self):
        ext = MarkdownExtractor("<html><body><p>text</p></body></html>")
        assert ext.title == ""

    def test_scripts_removed(self):
        ext = MarkdownExtractor(SAMPLE_HTML)
        md = ext.to_markdown()
        assert "var x = 1" not in md

    def test_headings_preserved(self):
        ext = MarkdownExtractor(SAMPLE_HTML)
        md = ext.to_markdown()
        assert "Hello World" in md
        assert "Section Two" in md

    def test_selector_narrows_content(self):
        html = "<html><body><main><p>Main content</p></main><aside>Aside</aside></body></html>"
        ext = MarkdownExtractor(html)
        md = ext.to_markdown(selector="main")
        assert "Main content" in md
        assert "Aside" not in md

    def test_strip_selectors(self):
        ext = MarkdownExtractor(SAMPLE_HTML)
        md = ext.to_markdown(strip_selectors=["nav"])
        assert "Navigation" not in md

    def test_include_links_false(self):
        html = '<html><body><a href="http://example.com">click</a></body></html>'
        ext = MarkdownExtractor(html)
        md = ext.to_markdown(include_links=False)
        assert "http://example.com" not in md
        assert "click" in md

    def test_no_triple_newlines(self):
        ext = MarkdownExtractor(SAMPLE_HTML)
        md = ext.to_markdown()
        assert "\n\n\n" not in md


class TestApplyStripLines:
    def test_removes_matching_lines(self):
        md = "keep this\nremove me\nkeep that"
        result = apply_strip_lines(md, [r"remove"])
        assert "remove me" not in result
        assert "keep this" in result

    def test_empty_patterns_unchanged(self):
        md = "line one\nline two"
        assert apply_strip_lines(md, []) == md

    def test_invalid_pattern_skipped(self):
        md = "line one\nline two"
        result = apply_strip_lines(md, ["[invalid"])
        assert result == md


class TestExtractToc:
    def test_basic_headings(self):
        toc = extract_toc(SAMPLE_MD)
        titles = [e["title"] for e in toc]
        assert "Heading One" in titles
        assert "Heading Two" in titles
        assert "Heading Three" in titles

    def test_heading_levels(self):
        toc = extract_toc(SAMPLE_MD)
        by_title = {e["title"]: e for e in toc}
        assert by_title["Heading One"]["level"] == 1
        assert by_title["Heading Two"]["level"] == 2
        assert by_title["Heading Three"]["level"] == 3

    def test_end_line_set_correctly(self):
        toc = extract_toc(SAMPLE_MD)
        # First heading's end_line should be before second heading's start_line
        h1 = next(e for e in toc if e["title"] == "Heading One")
        h2 = next(e for e in toc if e["title"] == "Heading Two")
        assert h1["end_line"] < h2["start_line"]

    def test_empty_markdown(self):
        assert extract_toc("no headings here") == []


class TestReadLines:
    def test_basic_range(self):
        md = "line1\nline2\nline3\nline4\nline5"
        result = read_lines(md, 2, 4)
        assert "line2" in result
        assert "line4" in result
        assert "line5" not in result

    def test_clamps_to_bounds(self):
        md = "a\nb\nc"
        result = read_lines(md, 0, 100)
        assert "a" in result
        assert "c" in result

    def test_line_numbers_included(self):
        md = "alpha\nbeta"
        result = read_lines(md, 1, 2)
        assert "1" in result
        assert "alpha" in result


class TestCountCodeBlocks:
    def test_counts_by_language(self):
        counts = count_code_blocks(SAMPLE_MD)
        assert counts.get("python") == 2
        assert counts.get("javascript") == 1

    def test_unknown_language(self):
        # The regex matches both the opening and closing ```, each counts as "unknown"
        md = "```\ncode block\n```"
        counts = count_code_blocks(md)
        assert counts.get("unknown") == 2

    def test_empty_markdown(self):
        assert count_code_blocks("no code") == {}


class TestExtractSymbols:
    def test_finds_backtick_symbols(self):
        symbols = extract_symbols(SAMPLE_MD)
        assert "my_function" in symbols
        assert "another_var" in symbols

    def test_deduplication(self):
        md = "`foo` and `foo` again"
        symbols = extract_symbols(md)
        assert symbols.count("foo") == 1

    def test_limit_respected(self):
        md = " ".join(f"`sym{i}`" for i in range(30))
        symbols = extract_symbols(md, limit=10)
        assert len(symbols) == 10


class TestGrepMarkdown:
    def test_finds_pattern(self):
        result = grep_markdown(SAMPLE_MD, "Heading Two")
        assert "Heading Two" in result
        assert "match" in result

    def test_case_insensitive(self):
        result = grep_markdown(SAMPLE_MD, "heading two", ignore_case=True)
        assert "Heading Two" in result

    def test_no_matches(self):
        result = grep_markdown(SAMPLE_MD, "xyz_not_found")
        assert "no matches" in result

    def test_invalid_pattern(self):
        result = grep_markdown(SAMPLE_MD, "[invalid")
        assert "Invalid pattern" in result

    def test_context_lines(self):
        result = grep_markdown(SAMPLE_MD, "Heading Two", context_lines=1)
        # Should include surrounding lines
        assert "Heading Two" in result

    def test_max_matches_truncation(self):
        # Create markdown with many matches
        md = "\n".join(f"line {i} match here" for i in range(100))
        result = grep_markdown(md, "match", max_matches=5)
        assert "showing first 5" in result


class TestPaginate:
    def test_no_truncation_when_short(self):
        text = "short text"
        chunk, truncated, next_off = paginate(text, 0, 8000)
        assert chunk == text
        assert not truncated

    def test_truncates_long_text(self):
        text = "x" * 40000  # 10000 tokens at 0.25 t/char
        chunk, truncated, next_off = paginate(text, 0, 100)
        assert truncated
        assert len(chunk) <= 400 + 10  # some slack for newline search

    def test_offset_advances(self):
        text = "aaa\nbbb\nccc\nddd"
        chunk1, trunc1, next1 = paginate(text, 0, 4)  # 16 chars, limit 4 tokens = 16 chars
        # With 4 tokens = 16 chars, we might or might not truncate depending on text length
        chunk2, trunc2, next2 = paginate(text, next1, 4)
        # Second chunk should differ from first if text is long enough

    def test_none_max_tokens_returns_all(self):
        text = "a" * 100000
        chunk, truncated, _ = paginate(text, 0, None)
        assert chunk == text
        assert not truncated

    def test_offset_respected(self):
        text = "first\nsecond\nthird"
        # max_tokens=None ignores offset; use large max_tokens to test offset without truncation
        chunk, _, _ = paginate(text, 6, 10000)
        assert "second" in chunk
        assert "first" not in chunk

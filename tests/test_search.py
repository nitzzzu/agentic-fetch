"""Tests for SearchEngine parsing methods."""
import pytest
from agentic_fetch.search import SearchEngine

engine = SearchEngine()

GOOGLE_HTML = """
<html><body>
  <div class="g">
    <a href="https://example.com/page"><h3>Example Title</h3></a>
    <div class="VwiC3b">Example snippet text here.</div>
  </div>
  <div class="g">
    <a href="/url?q=https://another.com/article&sa=U"><h3>Another Title</h3></a>
    <div class="VwiC3b">Another snippet text.</div>
  </div>
  <div class="g">
    <a href="/relative/link"><h3>Relative Title</h3></a>
  </div>
</body></html>
"""

DDG_HTML = """
<html><body>
  <ol class="react-results--main">
    <li>
      <article data-testid="result">
        <h2><a href="https://example.com/page">DDG Result</a></h2>
        <div data-result="snippet">DDG snippet here.</div>
      </article>
    </li>
    <li>
      <article data-testid="result">
        <h2><a href="https://another.com/page">Second Result</a></h2>
      </article>
    </li>
    <li>
      <article data-testid="result">
        <h2><a href="/relative">Relative Link</a></h2>
      </article>
    </li>
  </ol>
</body></html>
"""


class TestParseGoogle:
    def test_parses_results(self):
        results = engine._parse_google(GOOGLE_HTML, 10)
        assert len(results) >= 1

    def test_extracts_title(self):
        results = engine._parse_google(GOOGLE_HTML, 10)
        titles = [r.title for r in results]
        assert "Example Title" in titles

    def test_extracts_snippet(self):
        results = engine._parse_google(GOOGLE_HTML, 10)
        snippets = [r.snippet for r in results]
        assert any("Example snippet" in s for s in snippets)

    def test_extracts_url(self):
        results = engine._parse_google(GOOGLE_HTML, 10)
        urls = [r.url for r in results]
        assert "https://example.com/page" in urls

    def test_resolves_redirect_url(self):
        results = engine._parse_google(GOOGLE_HTML, 10)
        urls = [r.url for r in results]
        assert "https://another.com/article" in urls

    def test_skips_relative_links(self):
        results = engine._parse_google(GOOGLE_HTML, 10)
        urls = [r.url for r in results]
        assert all(u.startswith("http") for u in urls)

    def test_limit_respected(self):
        results = engine._parse_google(GOOGLE_HTML, 1)
        assert len(results) <= 1

    def test_empty_html(self):
        results = engine._parse_google("<html><body></body></html>", 10)
        assert results == []


class TestParseDuckDuckGo:
    def test_parses_results(self):
        results = engine._parse_ddg(DDG_HTML, 10)
        assert len(results) >= 1

    def test_extracts_title(self):
        results = engine._parse_ddg(DDG_HTML, 10)
        titles = [r.title for r in results]
        assert "DDG Result" in titles

    def test_extracts_snippet(self):
        results = engine._parse_ddg(DDG_HTML, 10)
        snippets = [r.snippet for r in results]
        assert any("DDG snippet" in s for s in snippets)

    def test_extracts_url(self):
        results = engine._parse_ddg(DDG_HTML, 10)
        urls = [r.url for r in results]
        assert "https://example.com/page" in urls

    def test_skips_relative_links(self):
        results = engine._parse_ddg(DDG_HTML, 10)
        urls = [r.url for r in results]
        assert all(u.startswith("http") for u in urls)

    def test_limit_respected(self):
        results = engine._parse_ddg(DDG_HTML, 1)
        assert len(results) <= 1

    def test_empty_html(self):
        results = engine._parse_ddg("<html><body></body></html>", 10)
        assert results == []

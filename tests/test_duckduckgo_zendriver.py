"""
Tests for DuckDuckGo search using zendriver on duckduckgo.com (not html.duckduckgo.com).

Bugs fixed:
- _duckduckgo used httpx against html.duckduckgo.com — blocked by restrictions
- Should use browser_pool.get_html() on duckduckgo.com to get JS-rendered results
- Parser must handle the main DDG site HTML structure (article[data-testid="result"])
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agentic_fetch.search import SearchEngine
from agentic_fetch.models import SearchRequest

engine = SearchEngine()


# Simulates the JS-rendered HTML from duckduckgo.com (main site, not html subdomain)
DDG_MAIN_HTML = """
<html><body>
  <ol class="react-results--main">
    <li>
      <article data-testid="result">
        <h2><a href="https://example.com/page">Example Title</a></h2>
        <div data-result="snippet">Example snippet text here.</div>
      </article>
    </li>
    <li>
      <article data-testid="result">
        <h2><a href="https://another.com/article">Another Title</a></h2>
        <div data-result="snippet">Another snippet text.</div>
      </article>
    </li>
    <li>
      <article data-testid="result">
        <h2><a href="https://third.com/page">Third Title</a></h2>
      </article>
    </li>
  </ol>
</body></html>
"""

DDG_MAIN_HTML_EMPTY = "<html><body><div>No results found.</div></body></html>"


def make_req(query="test query", max_results=10):
    return SearchRequest(query=query, engine="duckduckgo", max_results=max_results)


# ---------------------------------------------------------------------------
# _duckduckgo should use browser_pool.get_html, not httpx
# ---------------------------------------------------------------------------

class TestDuckDuckGoUsesZendriver:
    @pytest.mark.asyncio
    async def test_uses_browser_pool_not_httpx(self):
        """_duckduckgo must call browser_pool.get_html, not httpx."""
        req = make_req()

        with patch("agentic_fetch.search.browser_pool") as mock_pool:
            mock_pool.get_html = AsyncMock(return_value=(DDG_MAIN_HTML, "https://duckduckgo.com", []))
            result = await engine._duckduckgo(req)

        mock_pool.get_html.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_duckduckgo_com_not_html_subdomain(self):
        """URL must be duckduckgo.com, not html.duckduckgo.com."""
        req = make_req("python asyncio")

        with patch("agentic_fetch.search.browser_pool") as mock_pool:
            mock_pool.get_html = AsyncMock(return_value=(DDG_MAIN_HTML, "https://duckduckgo.com", []))
            await engine._duckduckgo(req)

        called_url = mock_pool.get_html.call_args[0][0]
        assert "html.duckduckgo.com" not in called_url
        assert "duckduckgo.com" in called_url

    @pytest.mark.asyncio
    async def test_query_included_in_url(self):
        req = make_req("fastapi tutorial")

        with patch("agentic_fetch.search.browser_pool") as mock_pool:
            mock_pool.get_html = AsyncMock(return_value=(DDG_MAIN_HTML, "https://duckduckgo.com", []))
            await engine._duckduckgo(req)

        called_url = mock_pool.get_html.call_args[0][0]
        assert "fastapi" in called_url.lower() or "fastapi+tutorial" in called_url.lower() \
               or "fastapi%20tutorial" in called_url.lower()

    @pytest.mark.asyncio
    async def test_returns_search_response_with_results(self):
        req = make_req()

        with patch("agentic_fetch.search.browser_pool") as mock_pool:
            mock_pool.get_html = AsyncMock(return_value=(DDG_MAIN_HTML, "https://duckduckgo.com", []))
            result = await engine._duckduckgo(req)

        assert result.engine_used == "duckduckgo"
        assert result.query == "test query"
        assert len(result.results) > 0

    @pytest.mark.asyncio
    async def test_max_results_respected(self):
        req = make_req(max_results=1)

        with patch("agentic_fetch.search.browser_pool") as mock_pool:
            mock_pool.get_html = AsyncMock(return_value=(DDG_MAIN_HTML, "https://duckduckgo.com", []))
            result = await engine._duckduckgo(req)

        assert len(result.results) <= 1


# ---------------------------------------------------------------------------
# Parser for duckduckgo.com main site HTML
# ---------------------------------------------------------------------------

class TestParseDDGMain:
    def test_parses_results(self):
        results = engine._parse_ddg(DDG_MAIN_HTML, 10)
        assert len(results) >= 2

    def test_extracts_title(self):
        results = engine._parse_ddg(DDG_MAIN_HTML, 10)
        titles = [r.title for r in results]
        assert "Example Title" in titles

    def test_extracts_url(self):
        results = engine._parse_ddg(DDG_MAIN_HTML, 10)
        urls = [r.url for r in results]
        assert "https://example.com/page" in urls

    def test_extracts_snippet(self):
        results = engine._parse_ddg(DDG_MAIN_HTML, 10)
        snippets = [r.snippet for r in results]
        assert any("Example snippet" in s for s in snippets)

    def test_result_without_snippet_has_empty_string(self):
        results = engine._parse_ddg(DDG_MAIN_HTML, 10)
        urls = [r.url for r in results]
        third = next((r for r in results if r.url == "https://third.com/page"), None)
        assert third is not None
        assert third.snippet == ""

    def test_skips_non_http_urls(self):
        results = engine._parse_ddg(DDG_MAIN_HTML, 10)
        assert all(r.url.startswith("http") for r in results)

    def test_limit_respected(self):
        results = engine._parse_ddg(DDG_MAIN_HTML, 1)
        assert len(results) <= 1

    def test_empty_html_returns_empty_list(self):
        results = engine._parse_ddg(DDG_MAIN_HTML_EMPTY, 10)
        assert results == []

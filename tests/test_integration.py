"""
Real network integration tests.

Run all:      pytest tests/test_integration.py -v -s
Run search:   pytest tests/test_integration.py::TestSearchAiNews -v -s
Run medium:   pytest tests/test_integration.py::TestMediumArticle -v -s
Run digi24:   pytest tests/test_integration.py::TestDigi24Fetch -v -s

The digi24 tests start a real Chrome browser — Chrome must be installed.
"""
import pytest
from agentic_fetch.search import SearchEngine
from agentic_fetch.fetch import fetch_engine
from agentic_fetch.models import SearchRequest, FetchRequest
from agentic_fetch.plugins.medium import MediumPlugin
from agentic_fetch.browser import browser_pool

pytestmark = pytest.mark.asyncio

_search = SearchEngine()
_medium = MediumPlugin()

MEDIUM_URL = "https://realz.medium.com/running-android-on-kubernetes-be73b940833f"
DIGI24_URL = "https://www.digi24.ro"


# ---------------------------------------------------------------------------
# Browser fixture — starts Chrome once for the session, reused across tests.
# Tests that declare `browser` as a parameter will wait for it.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
async def browser():
    """Start Chrome once for all browser-dependent tests in this module.
    Skips the test if Chrome is not installed or fails to start within 20s."""
    import asyncio
    try:
        await asyncio.wait_for(browser_pool.start(), timeout=20.0)
    except (asyncio.TimeoutError, Exception) as e:
        pytest.skip(f"Browser unavailable: {e}")
    yield browser_pool
    try:
        await browser_pool.stop()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Shared DDG response — one real HTTP call reused across all search tests
# to avoid rate-limiting when tests fire in rapid succession.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
async def ddg_response():
    """Single DuckDuckGo request for 'ai news', shared across all search tests.
    Retries once after a short delay to handle transient rate-limiting."""
    import asyncio
    req = SearchRequest(query="ai news", engine="duckduckgo", max_results=5)
    for attempt in range(3):
        if attempt > 0:
            await asyncio.sleep(5 * attempt)
        resp = await _search._duckduckgo(req)
        if len(resp.results) > 0:
            return resp
    pytest.skip("DuckDuckGo returned no results after retries (rate limited / blocked)")


# ---------------------------------------------------------------------------
# Search: "ai news" via DuckDuckGo (httpx only — no browser required)
# ---------------------------------------------------------------------------

class TestSearchAiNews:
    async def test_returns_results(self, ddg_response):
        assert ddg_response.engine_used == "duckduckgo"
        assert ddg_response.query == "ai news"
        assert len(ddg_response.results) >= 3, (
            f"Expected ≥3 results, got {len(ddg_response.results)}"
        )

    async def test_all_results_have_valid_urls(self, ddg_response):
        for r in ddg_response.results:
            assert r.url.startswith("http"), f"Bad URL: {r.url!r}"
            assert len(r.title) > 0, "Empty title"

    async def test_results_are_ai_related(self, ddg_response):
        all_text = " ".join(
            r.title + " " + r.snippet for r in ddg_response.results
        ).lower()
        ai_terms = [
            "ai", "artificial intelligence", "llm", "gpt", "openai",
            "model", "machine learning", "deep learning", "neural",
        ]
        assert any(t in all_text for t in ai_terms), (
            f"No AI-related terms found in result text:\n{all_text[:400]}"
        )

    async def test_engine_via_search_method(self, ddg_response):
        """Verify SearchResponse model fields are properly populated."""
        assert ddg_response.error is None
        assert len(ddg_response.results) > 0
        first = ddg_response.results[0]
        assert first.title
        assert first.url.startswith("http")


# ---------------------------------------------------------------------------
# Medium article fetch (httpx via Freedium mirror — no browser required)
# ---------------------------------------------------------------------------

class TestMediumArticle:
    async def test_plugin_is_used(self):
        req = FetchRequest(url=MEDIUM_URL, max_tokens=None, no_cache=True)
        resp = await _medium.fetch(MEDIUM_URL, req)

        assert resp.plugin_used == "medium"
        assert resp.method_used == "plugin"

    async def test_article_has_content(self):
        req = FetchRequest(url=MEDIUM_URL, max_tokens=None, no_cache=True)
        resp = await _medium.fetch(MEDIUM_URL, req)

        assert len(resp.markdown) > 500, (
            f"Article too short ({len(resp.markdown)} chars)"
        )

    async def test_article_title_extracted(self):
        req = FetchRequest(url=MEDIUM_URL, max_tokens=None, no_cache=True)
        resp = await _medium.fetch(MEDIUM_URL, req)

        assert resp.title != "", "Title is empty"
        assert len(resp.title) > 5

    async def test_article_topic_matches(self):
        """The article is about running Android on Kubernetes."""
        req = FetchRequest(url=MEDIUM_URL, max_tokens=None, no_cache=True)
        resp = await _medium.fetch(MEDIUM_URL, req)

        md_lower = resp.markdown.lower()
        assert any(kw in md_lower for kw in ["android", "kubernetes", "k8s", "container"]), (
            f"Expected Android/Kubernetes keywords not found.\n"
            f"First 400 chars:\n{resp.markdown[:400]}"
        )

    async def test_no_freedium_noise_in_output(self):
        """The plugin should strip Freedium UI chrome from the output."""
        req = FetchRequest(url=MEDIUM_URL, max_tokens=None, no_cache=True)
        resp = await _medium.fetch(MEDIUM_URL, req)

        noise_terms = ["Freedium", "Ko-fi", "Patreon", "Sign up", "Open in app"]
        for term in noise_terms:
            assert term not in resp.markdown, (
                f"Freedium noise {term!r} leaked into output"
            )

    async def test_pagination_truncates(self):
        """max_tokens=500 should produce a shorter result with truncated=True."""
        req = FetchRequest(url=MEDIUM_URL, max_tokens=500, no_cache=True)
        resp = await _medium.fetch(MEDIUM_URL, req)

        assert resp.truncated is True
        assert resp.next_offset is not None and resp.next_offset > 0

    async def test_medium_plugin_matches_url(self):
        """Verify plugin URL matching works for realz.medium.com."""
        assert MediumPlugin.matches(MEDIUM_URL)
        assert not MediumPlugin.matches("https://example.com/article")

    async def test_fetch_engine_routes_to_medium_plugin(self):
        """FetchEngine should pick the MediumPlugin for this URL (no browser needed)."""
        req = FetchRequest(url=MEDIUM_URL, max_tokens=None, no_cache=True)
        resp = await fetch_engine.fetch(req)

        assert resp.plugin_used == "medium"
        assert len(resp.markdown) > 500


# ---------------------------------------------------------------------------
# digi24.ro news fetch (uses real Chrome for JS-rendered content)
# ---------------------------------------------------------------------------

class TestDigi24Fetch:
    async def test_homepage_fetched(self, browser):
        req = FetchRequest(url=DIGI24_URL, max_tokens=8000, no_cache=True)
        resp = await fetch_engine.fetch(req)

        assert resp.url.startswith("https"), f"Unexpected URL: {resp.url!r}"
        assert len(resp.markdown) > 200, (
            f"Homepage too short ({len(resp.markdown)} chars)"
        )
        assert resp.method_used in ("httpx", "httpx+browser", "zendriver"), (
            f"Unexpected method: {resp.method_used!r}"
        )

    async def test_homepage_has_romanian_news(self, browser):
        req = FetchRequest(url=DIGI24_URL, max_tokens=8000, no_cache=True)
        resp = await fetch_engine.fetch(req)

        md_lower = resp.markdown.lower()
        news_terms = [
            "digi24", "știri", "stiri", "news", "romania", "românia",
            "video", "live",
        ]
        assert any(t in md_lower for t in news_terms), (
            f"No news-related terms found.\nFirst 400 chars:\n{resp.markdown[:400]}"
        )

    async def test_homepage_has_toc_or_lines(self, browser):
        req = FetchRequest(url=DIGI24_URL, max_tokens=None, no_cache=True)
        resp = await fetch_engine.fetch(req)

        assert resp.total_lines > 20, (
            f"Expected >20 lines, got {resp.total_lines}"
        )

    async def test_ad_selectors_stripped(self, browser):
        """config.yaml strips .ad-wrapper and .ad-native from digi24.ro."""
        req = FetchRequest(url=DIGI24_URL, max_tokens=None, no_cache=True)
        resp = await fetch_engine.fetch(req)

        # Ad class names should not appear in clean markdown output
        assert ".ad-wrapper" not in resp.markdown
        assert ".ad-native" not in resp.markdown

    async def test_cache_populated_after_fetch(self, browser):
        """A second fetch of the same URL should return cached=True."""
        req_fresh = FetchRequest(url=DIGI24_URL, max_tokens=8000, no_cache=True)
        await fetch_engine.fetch(req_fresh)

        req_cached = FetchRequest(url=DIGI24_URL, max_tokens=8000, no_cache=False)
        resp = await fetch_engine.fetch(req_cached)

        assert resp.cached is True

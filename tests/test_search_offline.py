"""Offline SearchEngine tests — every backend exercised through the public
``search()`` interface with the HTTP layer mocked via respx and the browser
pool mocked at its boundary. No real network, no Chrome."""

import json
from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import Response

from agentic_fetch.models import SearchRequest
from agentic_fetch.search import SearchEngine

pytestmark = pytest.mark.asyncio

engine = SearchEngine()

JSON_HEADERS = {"content-type": "application/json"}


def reddit_payload(*titles: str) -> dict:
    return {
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "title": t,
                        "permalink": f"/r/python/comments/{i}/post/",
                        "subreddit": "python",
                        "author": "someone",
                        "score": 42,
                        "num_comments": 7,
                        "created_utc": 1700000000,
                        "selftext": "body text of the post",
                    },
                }
                for i, t in enumerate(titles)
            ]
        }
    }


GOOGLE_HTML = """
<html><body>
<div class="g"><div class="yuRUbf">
  <a href="https://example.com/one"><h3>First result</h3></a>
</div><div class="VwiC3b">First snippet</div></div>
<div class="g"><div class="yuRUbf">
  <a href="/url?q=https://example.com/two&sa=U"><h3>Second result</h3></a>
</div><div class="VwiC3b">Second snippet</div></div>
</body></html>
"""

DDG_LITE_HTML = """
<html><body>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&rut=abc">Wrapped result</a>
  <div class="result__snippet">A snippet about the page</div>
</div>
<div class="result">
  <a class="result__a" href="https://plain.example.com/">Plain result</a>
  <div class="result__snippet">Another snippet</div>
</div>
</body></html>
"""


class TestRedditSearch:
    @respx.mock
    async def test_returns_posts_with_metadata_snippet(self):
        respx.get("https://www.reddit.com/search.json").mock(
            return_value=Response(
                200, json=reddit_payload("Async tips", "Fetch patterns"),
                headers=JSON_HEADERS,
            )
        )
        resp = await engine.search(SearchRequest(query="async", engine="reddit"))
        assert resp.engine_used == "reddit"
        assert [r.title for r in resp.results] == ["Async tips", "Fetch patterns"]
        assert resp.results[0].url.startswith("https://www.reddit.com/r/python/")
        assert "42 pts" in resp.results[0].snippet
        assert resp.error is None

    @respx.mock
    async def test_subreddit_prefix_scopes_search(self):
        route = respx.get("https://www.reddit.com/r/python/search.json").mock(
            return_value=Response(
                200, json=reddit_payload("Scoped"), headers=JSON_HEADERS
            )
        )
        resp = await engine.search(
            SearchRequest(query="subreddit:python typing", engine="reddit")
        )
        assert route.called
        assert route.calls.last.request.url.params["restrict_sr"] == "1"
        assert resp.engine_used == "reddit/r/python"

    @respx.mock
    async def test_bare_subreddit_uses_listing_endpoint(self):
        respx.get("https://www.reddit.com/r/python/hot.json").mock(
            return_value=Response(
                200, json=reddit_payload("Listing post"), headers=JSON_HEADERS
            )
        )
        resp = await engine.search(
            SearchRequest(query="subreddit:python", engine="reddit")
        )
        assert resp.engine_used == "reddit/r/python"
        assert resp.results[0].title == "Listing post"

    @respx.mock
    async def test_rate_limit_reports_error_not_exception(self):
        respx.get("https://www.reddit.com/search.json").mock(
            return_value=Response(429, headers={"Retry-After": "0"})
        )
        resp = await engine.search(SearchRequest(query="q", engine="reddit"))
        assert resp.results == []
        assert "429" in (resp.error or "")

    @respx.mock
    async def test_html_block_page_reports_error(self):
        respx.get("https://www.reddit.com/search.json").mock(
            return_value=Response(
                200, text="<html>blocked</html>", headers={"content-type": "text/html"}
            )
        )
        resp = await engine.search(SearchRequest(query="q", engine="reddit"))
        assert resp.results == []
        assert "blocked" in (resp.error or "").lower()

    @respx.mock
    async def test_date_filters_are_reported_unsupported(self):
        respx.get("https://www.reddit.com/search.json").mock(
            return_value=Response(200, json=reddit_payload("x"), headers=JSON_HEADERS)
        )
        resp = await engine.search(
            SearchRequest(query="q", engine="reddit", date_from="2026-01-01")
        )
        assert "date_from" in (resp.error or "")


class TestHackerNewsSearch:
    @respx.mock
    async def test_returns_stories(self):
        respx.get("https://hn.algolia.com/api/v1/search").mock(
            return_value=Response(
                200,
                json={
                    "hits": [
                        {
                            "title": "Show HN: thing",
                            "objectID": "123",
                            "url": "https://thing.example.com",
                            "points": 250,
                            "num_comments": 90,
                            "author": "pg",
                            "created_at": "2026-05-01T12:00:00Z",
                        }
                    ]
                },
                headers=JSON_HEADERS,
            )
        )
        resp = await engine.search(SearchRequest(query="thing", engine="hackernews"))
        assert resp.engine_used == "hackernews"
        assert resp.results[0].title == "Show HN: thing"
        assert resp.results[0].url == "https://thing.example.com"
        assert "250" in resp.results[0].snippet

    @respx.mock
    async def test_numeric_filters_forwarded_to_algolia(self):
        route = respx.get("https://hn.algolia.com/api/v1/search").mock(
            return_value=Response(200, json={"hits": []}, headers=JSON_HEADERS)
        )
        await engine.search(
            SearchRequest(
                query="q", engine="hackernews", min_points=100, min_comments=10
            )
        )
        filters = route.calls.last.request.url.params["numericFilters"]
        assert "points>=100" in filters
        assert "num_comments>=10" in filters

    @respx.mock
    async def test_upstream_error_becomes_error_field(self):
        respx.get("https://hn.algolia.com/api/v1/search").mock(
            return_value=Response(500, text="boom")
        )
        resp = await engine.search(SearchRequest(query="q", engine="hackernews"))
        assert resp.results == []
        assert "500" in (resp.error or "")


class TestGitHubSearch:
    @respx.mock
    async def test_repo_search_returns_starred_titles(self):
        respx.get("https://api.github.com/search/repositories").mock(
            return_value=Response(
                200,
                json={
                    "items": [
                        {
                            "full_name": "octo/repo",
                            "html_url": "https://github.com/octo/repo",
                            "stargazers_count": 1234,
                            "forks_count": 56,
                            "language": "Python",
                            "description": "A repo",
                            "updated_at": "2026-06-01T00:00:00Z",
                        }
                    ]
                },
                headers=JSON_HEADERS,
            )
        )
        resp = await engine.search(SearchRequest(query="repo", engine="github"))
        assert resp.engine_used == "github"
        assert resp.results[0].title == "octo/repo ★1,234"
        assert resp.results[0].url == "https://github.com/octo/repo"

    @respx.mock
    async def test_code_search_titles_include_path_and_repo(self):
        respx.get("https://api.github.com/search/code").mock(
            return_value=Response(
                200,
                json={
                    "items": [
                        {
                            "path": "src/x.py",
                            "html_url": "https://github.com/octo/repo/blob/main/src/x.py",
                            "repository": {
                                "full_name": "octo/repo",
                                "description": "A repo",
                            },
                        }
                    ]
                },
                headers=JSON_HEADERS,
            )
        )
        resp = await engine.search(
            SearchRequest(query="def x", engine="github", search_type="code")
        )
        assert resp.engine_used == "github-code"
        assert resp.results[0].title == "src/x.py — octo/repo"

    @respx.mock
    async def test_trending_query_scrapes_trending_page(self):
        trending_html = """
        <article class="Box-row">
          <h2><a href="/octo/hot-repo">octo / hot-repo</a></h2>
          <p>Trending description</p>
          <span itemprop="programmingLanguage">Rust</span>
          <a href="/octo/hot-repo/stargazers">2,000</a>
          <span>150 stars today</span>
        </article>
        """
        respx.get("https://github.com/trending").mock(
            return_value=Response(200, html=trending_html)
        )
        resp = await engine.search(SearchRequest(query="trending", engine="github"))
        assert resp.engine_used.startswith("github trending")
        assert resp.results, "expected trending results"
        assert "octo/hot-repo" in resp.results[0].title

    @respx.mock
    async def test_rate_limit_suggests_token(self):
        respx.get("https://api.github.com/search/repositories").mock(
            return_value=Response(429, headers={"Retry-After": "0"})
        )
        resp = await engine.search(SearchRequest(query="q", engine="github"))
        assert resp.results == []
        assert "GITHUB_TOKEN" in (resp.error or "")


class TestGoogleSearch:
    async def test_requires_browser_pool(self):
        with patch("agentic_fetch.search.browser_pool") as pool:
            pool.is_running = False
            resp = await engine.search(SearchRequest(query="q", engine="google"))
        assert resp.results == []
        assert "browser" in (resp.error or "").lower()

    async def test_parses_direct_and_wrapped_urls(self):
        with patch("agentic_fetch.search.browser_pool") as pool:
            pool.is_running = True
            pool.get_html = AsyncMock(return_value=(GOOGLE_HTML, "", []))
            resp = await engine.search(SearchRequest(query="q", engine="google"))
        assert resp.engine_used == "google"
        urls = [r.url for r in resp.results]
        assert urls == ["https://example.com/one", "https://example.com/two"]
        assert resp.results[0].snippet == "First snippet"


class TestDuckDuckGoSearch:
    @respx.mock
    async def test_lite_endpoint_unwraps_redirect_urls(self):
        respx.post("https://html.duckduckgo.com/html/").mock(
            return_value=Response(200, html=DDG_LITE_HTML)
        )
        resp = await engine.search(SearchRequest(query="q", engine="duckduckgo"))
        assert resp.engine_used == "duckduckgo-lite"
        urls = [r.url for r in resp.results]
        assert "https://example.com/page" in urls
        assert "https://plain.example.com/" in urls

    @respx.mock
    async def test_lite_empty_and_no_browser_reports_error(self):
        respx.post("https://html.duckduckgo.com/html/").mock(
            return_value=Response(200, html="<html><body></body></html>")
        )
        with patch("agentic_fetch.search.browser_pool") as pool:
            pool.is_running = False
            resp = await engine.search(SearchRequest(query="q", engine="duckduckgo"))
        assert resp.results == []
        assert resp.error is not None

    @respx.mock
    async def test_auto_falls_back_to_ddg_when_google_unavailable(self):
        respx.post("https://html.duckduckgo.com/html/").mock(
            return_value=Response(200, html=DDG_LITE_HTML)
        )
        with patch("agentic_fetch.search.browser_pool") as pool:
            pool.is_running = True
            pool.get_html = AsyncMock(side_effect=RuntimeError("no browser"))
            resp = await engine.search(SearchRequest(query="q", engine="auto"))
        assert resp.engine_used == "duckduckgo-lite"
        assert len(resp.results) == 2


class TestCacheEngine:
    async def test_cache_engine_searches_cached_documents(self, tmp_path):
        from agentic_fetch.cache import FetchCache

        cache = FetchCache(cache_dir=str(tmp_path), ttl=300)
        cache.put(
            "https://kb.example.test/fastapi",
            "# FastAPI notes\n\nFastAPI uses pydantic models for validation.",
            "html",
        )
        with patch("agentic_fetch.cache.fetch_cache", cache):
            resp = await engine.search(SearchRequest(query="pydantic", engine="cache"))
        assert resp.engine_used == "cache"
        assert resp.results[0].url == "https://kb.example.test/fastapi"
        assert "score" in resp.results[0].snippet


class TestRetryBehavior:
    @respx.mock
    async def test_single_429_then_success_is_retried(self):
        route = respx.get("https://hn.algolia.com/api/v1/search")
        route.side_effect = [
            Response(429, headers={"Retry-After": "0"}),
            Response(200, json={"hits": []}, headers=JSON_HEADERS),
        ]
        resp = await engine.search(SearchRequest(query="q", engine="hackernews"))
        assert resp.error is None
        assert route.call_count == 2

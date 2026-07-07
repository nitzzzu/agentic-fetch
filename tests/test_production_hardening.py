"""Tests for production-hardening changes:

1. Plugin results are cached in FULL before pagination (the truncated-cache bug)
2. Plugin error responses are never cached
3. Request validation returns 422 (not 500 / silent garbage)
4. /grep returns 400 on an invalid regex pattern
5. /cache/write survives empty-ish input and rejects truly empty markdown
6. /fetch/batch dedupes URLs
7. /health exposes version, plugins and cache stats
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from agentic_fetch.fetch import FetchEngine
from agentic_fetch.models import FetchRequest, FetchResponse


@pytest.fixture
def client():
    with patch("agentic_fetch.main.browser_pool") as mock_pool:
        mock_pool.start = AsyncMock()
        mock_pool.stop = AsyncMock()
        mock_pool.is_running = True
        from agentic_fetch.main import app
        with TestClient(app) as c:
            yield c


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Point the module-level fetch_cache at a temp dir so tests don't share state."""
    from agentic_fetch import cache as cache_mod
    from pathlib import Path
    monkeypatch.setattr(cache_mod.fetch_cache, "cache_dir", Path(tmp_path / "cache"))
    monkeypatch.setattr(cache_mod.fetch_cache, "ttl", 300)
    cache_mod.fetch_cache.cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_mod.fetch_cache


class FakePlugin:
    """Minimal plugin returning a long document, as real plugins now do (full md)."""
    name = "fake"
    long_md = "# Big Doc\n\n" + "\n".join(f"line {i} with some words" for i in range(2000))

    async def fetch(self, url, req):
        return FetchResponse(
            url=url, title="Big Doc", markdown=self.long_md,
            plugin_used="fake", method_used="plugin",
        )


class FakeErrorPlugin:
    name = "fake-error"

    async def fetch(self, url, req):
        return FetchResponse(
            url=url, title="", markdown="**Error:** upstream 404\n",
            plugin_used="fake-error", method_used="plugin",
            error="upstream 404",
        )


class TestPluginPaginationCaching:
    async def test_full_markdown_cached_despite_truncated_response(self, isolated_cache):
        engine = FetchEngine()
        url = "https://plugin-test.example/doc"
        req = FetchRequest(url=url, max_tokens=100)

        with patch("agentic_fetch.fetch.get_plugin", return_value=FakePlugin):
            resp = await engine.fetch(req)

        assert resp.truncated is True
        assert resp.next_offset is not None
        assert len(resp.markdown) < len(FakePlugin.long_md)

        # The cache must hold the FULL document, not the paginated chunk.
        cached = isolated_cache.get(url)
        assert cached is not None
        assert cached[0] == FakePlugin.long_md

    async def test_offset_continues_past_first_chunk(self, isolated_cache):
        engine = FetchEngine()
        url = "https://plugin-test.example/doc2"

        with patch("agentic_fetch.fetch.get_plugin", return_value=FakePlugin):
            first = await engine.fetch(FetchRequest(url=url, max_tokens=100))
            second = await engine.fetch(
                FetchRequest(url=url, max_tokens=100, offset=first.next_offset)
            )

        assert second.markdown
        assert second.markdown != first.markdown
        # Second chunk comes from the cached full document.
        assert second.markdown in FakePlugin.long_md

    async def test_plugin_response_gets_toc_and_total_lines(self, isolated_cache):
        engine = FetchEngine()
        url = "https://plugin-test.example/doc3"
        with patch("agentic_fetch.fetch.get_plugin", return_value=FakePlugin):
            resp = await engine.fetch(FetchRequest(url=url, max_tokens=100))
        assert resp.total_lines > 1000
        assert resp.toc and resp.toc[0].title == "Big Doc"

    async def test_error_response_not_cached(self, isolated_cache):
        engine = FetchEngine()
        url = "https://plugin-test.example/missing"
        with patch("agentic_fetch.fetch.get_plugin", return_value=FakeErrorPlugin):
            resp = await engine.fetch(FetchRequest(url=url))
        assert resp.error == "upstream 404"
        assert isolated_cache.get(url) is None


class TestFetchValidation:
    def test_rejects_non_http_scheme(self, client):
        for bad in ("ftp://example.com/x", "file:///etc/passwd", "javascript:alert(1)", "example.com"):
            resp = client.post("/fetch", json={"url": bad})
            assert resp.status_code == 422, bad

    def test_rejects_negative_offset(self, client):
        resp = client.post("/fetch", json={"url": "https://example.com", "offset": -5})
        assert resp.status_code == 422

    def test_rejects_zero_max_tokens(self, client):
        resp = client.post("/fetch", json={"url": "https://example.com", "max_tokens": 0})
        assert resp.status_code == 422

    def test_null_max_tokens_allowed(self, client):
        with patch("agentic_fetch.main.fetch_engine") as mock_engine:
            mock_engine.fetch = AsyncMock(return_value=FetchResponse(
                url="https://example.com", title="t", markdown="m", method_used="httpx"))
            resp = client.post("/fetch", json={"url": "https://example.com", "max_tokens": None})
        assert resp.status_code == 200

    def test_batch_rejects_bad_url_in_list(self, client):
        resp = client.post("/fetch/batch", json={
            "urls": ["https://ok.example.com", "notaurl"],
        })
        assert resp.status_code == 422


class TestSearchValidation:
    def test_rejects_zero_max_results(self, client):
        resp = client.post("/search", json={"query": "x", "max_results": 0})
        assert resp.status_code == 422

    def test_rejects_huge_max_results(self, client):
        resp = client.post("/search", json={"query": "x", "max_results": 1000})
        assert resp.status_code == 422

    def test_rejects_malformed_date(self, client):
        resp = client.post("/search", json={"query": "x", "date_from": "June 2024"})
        assert resp.status_code == 422

    def test_accepts_iso_date(self, client):
        from agentic_fetch.models import SearchResponse
        with patch("agentic_fetch.main.search_engine") as mock_engine:
            mock_engine.search = AsyncMock(return_value=SearchResponse(
                query="x", engine_used="google", results=[]))
            resp = client.post("/search", json={"query": "x", "date_from": "2026-01-01"})
        assert resp.status_code == 200


class TestLinesAndGrepValidation:
    def test_lines_rejects_zero_start(self, client):
        resp = client.post("/fetch/lines", json={"url": "https://e.com", "start": 0, "end": 5})
        assert resp.status_code == 422

    def test_lines_rejects_end_before_start(self, client):
        resp = client.post("/fetch/lines", json={"url": "https://e.com", "start": 10, "end": 5})
        assert resp.status_code == 422

    def test_grep_invalid_regex_returns_400(self, client):
        resp = client.post("/grep", json={"url": "https://e.com", "pattern": "[unclosed"})
        assert resp.status_code == 400
        assert "pattern" in resp.json()["detail"].lower()

    def test_grep_empty_pattern_rejected(self, client):
        resp = client.post("/grep", json={"url": "https://e.com", "pattern": ""})
        assert resp.status_code == 422


class TestCacheWriteEndpoint:
    def test_empty_markdown_rejected(self, client):
        resp = client.post("/cache/write", json={"url": "synthesis://x", "markdown": ""})
        assert resp.status_code == 422

    def test_whitespace_only_markdown_does_not_crash(self, client, isolated_cache):
        resp = client.post("/cache/write", json={"url": "synthesis://x", "markdown": "\n\n\n"})
        assert resp.status_code == 200

    def test_writes_and_reports_word_count(self, client, isolated_cache):
        resp = client.post("/cache/write", json={
            "url": "synthesis://notes", "markdown": "# Notes\n\nhello world"})
        assert resp.status_code == 200
        assert resp.json()["word_count"] == 4


class TestBatchDedupe:
    def test_duplicate_urls_fetched_once(self, client):
        calls = []

        async def fake_fetch(req):
            calls.append(req.url)
            return FetchResponse(url=req.url, title="t", markdown="m", method_used="httpx")

        with patch("agentic_fetch.main.fetch_engine") as mock_engine:
            mock_engine.fetch = AsyncMock(side_effect=fake_fetch)
            resp = client.post("/fetch/batch", json={
                "urls": ["https://a.example.com", "https://a.example.com", "https://b.example.com"],
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert sorted(calls) == ["https://a.example.com", "https://b.example.com"]


class TestHealthEndpoint:
    def test_health_reports_plugins_and_cache(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "reddit" in data["plugins"]
        assert "total_entries" in data["cache"]

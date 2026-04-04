"""Tests for FastAPI endpoints."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from agentic_fetch.models import (
    FetchResponse, SearchResponse, SearchResult,
)


def make_fetch_response(**kwargs):
    defaults = dict(
        url="https://example.com",
        title="Example",
        markdown="# Hello\n\nContent here.",
        method_used="httpx",
        cached=False,
    )
    defaults.update(kwargs)
    return FetchResponse(**defaults)


def make_search_response(**kwargs):
    defaults = dict(
        query="test query",
        engine_used="duckduckgo",
        results=[
            SearchResult(title="Result", url="https://example.com", snippet="A snippet"),
        ],
    )
    defaults.update(kwargs)
    return SearchResponse(**defaults)


@pytest.fixture
def client():
    """TestClient with browser_pool mocked so no Chrome process starts."""
    with patch("agentic_fetch.main.browser_pool") as mock_pool:
        mock_pool.start = AsyncMock()
        mock_pool.stop = AsyncMock()
        mock_pool.is_running = True
        from agentic_fetch.main import app
        with TestClient(app) as c:
            yield c


class TestHealthEndpoint:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["browser_running"] is True


class TestFetchEndpoint:
    def test_fetch_success(self, client):
        mock_response = make_fetch_response()
        with patch("agentic_fetch.main.fetch_engine") as mock_engine:
            mock_engine.fetch = AsyncMock(return_value=mock_response)
            resp = client.post("/fetch", json={"url": "https://example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["url"] == "https://example.com"
        assert data["title"] == "Example"
        assert "Hello" in data["markdown"]

    def test_fetch_returns_method_used(self, client):
        with patch("agentic_fetch.main.fetch_engine") as mock_engine:
            mock_engine.fetch = AsyncMock(return_value=make_fetch_response(method_used="zendriver"))
            resp = client.post("/fetch", json={"url": "https://example.com"})
        assert resp.json()["method_used"] == "zendriver"

    def test_fetch_with_options(self, client):
        with patch("agentic_fetch.main.fetch_engine") as mock_engine:
            mock_engine.fetch = AsyncMock(return_value=make_fetch_response())
            resp = client.post("/fetch", json={
                "url": "https://example.com",
                "max_tokens": 1000,
                "force_browser": True,
                "no_cache": True,
            })
        assert resp.status_code == 200

    def test_fetch_engine_error_returns_500(self, client):
        with patch("agentic_fetch.main.fetch_engine") as mock_engine:
            mock_engine.fetch = AsyncMock(side_effect=RuntimeError("connection failed"))
            resp = client.post("/fetch", json={"url": "https://example.com"})
        assert resp.status_code == 500
        assert "connection failed" in resp.json()["detail"]

    def test_fetch_missing_url_returns_422(self, client):
        resp = client.post("/fetch", json={})
        assert resp.status_code == 422


class TestSearchEndpoint:
    def test_search_success(self, client):
        mock_response = make_search_response()
        with patch("agentic_fetch.main.search_engine") as mock_engine:
            mock_engine.search = AsyncMock(return_value=mock_response)
            resp = client.post("/search", json={"query": "test query"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "test query"
        assert len(data["results"]) >= 1
        assert data["results"][0]["title"] == "Result"

    def test_search_engine_used(self, client):
        with patch("agentic_fetch.main.search_engine") as mock_engine:
            mock_engine.search = AsyncMock(
                return_value=make_search_response(engine_used="google")
            )
            resp = client.post("/search", json={"query": "test"})
        assert resp.json()["engine_used"] == "google"

    def test_search_error_returns_500(self, client):
        with patch("agentic_fetch.main.search_engine") as mock_engine:
            mock_engine.search = AsyncMock(side_effect=RuntimeError("search failed"))
            resp = client.post("/search", json={"query": "test"})
        assert resp.status_code == 500

    def test_search_missing_query_returns_422(self, client):
        resp = client.post("/search", json={})
        assert resp.status_code == 422


class TestFetchLinesEndpoint:
    def test_returns_lines_when_cached(self, client, tmp_path):
        with patch("agentic_fetch.main.fetch_cache") as mock_cache:
            mock_cache.read_lines.return_value = "   1  # Title\n   2  Content"
            resp = client.post("/fetch/lines", json={
                "url": "https://example.com", "start": 1, "end": 2
            })
        assert resp.status_code == 200
        data = resp.json()
        assert "Title" in data["content"]
        assert data["start"] == 1
        assert data["end"] == 2

    def test_returns_404_when_not_cached(self, client):
        with patch("agentic_fetch.main.fetch_cache") as mock_cache:
            mock_cache.read_lines.return_value = None
            resp = client.post("/fetch/lines", json={
                "url": "https://example.com", "start": 1, "end": 5
            })
        assert resp.status_code == 404
        assert "cache" in resp.json()["detail"].lower()


class TestGrepEndpoint:
    def test_grep_success(self, client):
        grep_result = "1 match for 'Title' in 10 lines\n   1* # Title\n"
        with patch("agentic_fetch.main.fetch_cache") as mock_cache:
            mock_cache.grep.return_value = grep_result
            resp = client.post("/grep", json={
                "url": "https://example.com", "pattern": "Title"
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["pattern"] == "Title"
        assert "Title" in data["result"]

    def test_grep_not_cached_returns_404(self, client):
        with patch("agentic_fetch.main.fetch_cache") as mock_cache:
            mock_cache.grep.return_value = None
            resp = client.post("/grep", json={
                "url": "https://example.com", "pattern": "foo"
            })
        assert resp.status_code == 404

    def test_grep_with_options(self, client):
        with patch("agentic_fetch.main.fetch_cache") as mock_cache:
            mock_cache.grep.return_value = "no matches for 'foo' in 5 lines\n"
            resp = client.post("/grep", json={
                "url": "https://example.com",
                "pattern": "foo",
                "context_lines": 3,
                "ignore_case": True,
                "max_matches": 100,
            })
        assert resp.status_code == 200
        mock_cache.grep.assert_called_once_with(
            "https://example.com", "foo",
            context_lines=3, ignore_case=True, max_matches=100,
        )

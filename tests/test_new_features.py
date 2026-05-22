"""Tests for the features added in the cleanup pass:
- /fetch/batch parallel runner
- /cache/evict, /cache/prune, /cache/search endpoints
- Method-used replay from cache metadata
- DuckDuckGo Lite (no-browser) parser
- Cache metadata precomputed at write time
"""
import json
from unittest.mock import patch
from fastapi.testclient import TestClient

from agentic_fetch.cache import FetchCache
from agentic_fetch.search import SearchEngine
from agentic_fetch.models import FetchResponse


SAMPLE_MD = """# Title One

Some content about asyncio and `python` and `httpx`.

## Async basics

Body paragraph one.
Body paragraph two.

```python
async def f(): pass
```
"""


# ---------------------------------------------------------------------------
# Cache: metadata is precomputed and method is replayed
# ---------------------------------------------------------------------------

class TestCachePrecomputedMeta:
    def test_metadata_keys_present_after_put(self, tmp_path):
        c = FetchCache(cache_dir=str(tmp_path / "cache"), ttl=300)
        c.put("https://example.com/a", SAMPLE_MD, "html", method="zendriver")
        meta = c.metadata("https://example.com/a")
        assert meta is not None
        assert meta["title"] == "Title One"
        assert meta["method"] == "zendriver"
        assert meta["lines"] > 0
        assert any(e["title"] == "Title One" for e in meta["toc"])
        assert "python" in meta["code_blocks"]
        assert "python" in meta["symbols"] or "httpx" in meta["symbols"]

    def test_metadata_survives_round_trip(self, tmp_path):
        """meta.json is JSON-roundtrippable — no exotic types stored."""
        c = FetchCache(cache_dir=str(tmp_path / "cache"), ttl=300)
        c.put("https://example.com/a", SAMPLE_MD, "html", method="plugin")
        # Re-instantiate to force loading from disk
        c2 = FetchCache(cache_dir=str(tmp_path / "cache"), ttl=300)
        meta = c2.metadata("https://example.com/a")
        assert meta["method"] == "plugin"
        assert meta["title"] == "Title One"


# ---------------------------------------------------------------------------
# Cache: evict
# ---------------------------------------------------------------------------

class TestCacheEvict:
    def test_evict_existing_returns_true(self, tmp_path):
        c = FetchCache(cache_dir=str(tmp_path / "cache"), ttl=300)
        c.put("https://example.com/a", SAMPLE_MD, "html")
        assert c.evict("https://example.com/a") is True
        assert c.get("https://example.com/a") is None

    def test_evict_missing_returns_false(self, tmp_path):
        c = FetchCache(cache_dir=str(tmp_path / "cache"), ttl=300)
        assert c.evict("https://nope.com/x") is False


# ---------------------------------------------------------------------------
# Cache: prune
# ---------------------------------------------------------------------------

class TestCachePrune:
    def test_prune_removes_stale_entries(self, tmp_path):
        c = FetchCache(cache_dir=str(tmp_path / "cache"), ttl=10)
        c.put("https://example.com/old", SAMPLE_MD, "html")
        c.put("https://example.com/new", SAMPLE_MD, "html")

        # Backdate "old" entry far past ttl * 4
        import time
        key = c.cache_key("https://example.com/old")
        meta_path = c.cache_dir / f"{key}.meta.json"
        meta = json.loads(meta_path.read_text())
        meta["fetched_at"] = time.time() - 1000
        meta_path.write_text(json.dumps(meta))

        stats = c.prune(max_age_factor=4.0)
        assert stats["removed_age"] == 1
        assert c.get("https://example.com/new") is not None
        assert c.get("https://example.com/old") is None

    def test_prune_keeps_synthesis_entries(self, tmp_path):
        c = FetchCache(cache_dir=str(tmp_path / "cache"), ttl=10)
        c.write("https://forever.com", SAMPLE_MD)
        stats = c.prune(max_age_factor=0.0001)  # would prune everything
        assert stats["removed_age"] == 0
        assert c.get("https://forever.com") is not None


# ---------------------------------------------------------------------------
# DDG Lite parser
# ---------------------------------------------------------------------------

class TestDdgLiteParser:
    def test_parses_results_unwraps_uddg(self):
        engine = SearchEngine()
        html = """
        <html><body>
            <div class="result">
                <h2><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdoc">
                    Example Doc
                </a></h2>
                <a class="result__snippet">An example snippet.</a>
            </div>
            <div class="result">
                <a class="result__a" href="https://other.com/article">Other Article</a>
                <a class="result__snippet">Another snippet here.</a>
            </div>
        </body></html>
        """
        results = engine._parse_ddg_lite(html, limit=10)
        assert len(results) == 2
        assert results[0].url == "https://example.com/doc"
        assert "Example Doc" in results[0].title
        assert results[1].url == "https://other.com/article"

    def test_limit_respected(self):
        engine = SearchEngine()
        html = "".join(
            f'<div class="result"><a class="result__a" href="https://e{i}.com/">T{i}</a></div>'
            for i in range(20)
        )
        results = engine._parse_ddg_lite(html, limit=3)
        assert len(results) == 3

    def test_skips_relative_links(self):
        engine = SearchEngine()
        html = '<div class="result"><a class="result__a" href="/relative">Foo</a></div>'
        assert engine._parse_ddg_lite(html, limit=5) == []


# ---------------------------------------------------------------------------
# /fetch/batch endpoint
# ---------------------------------------------------------------------------

def _fr(url: str, **kwargs) -> FetchResponse:
    defaults = dict(url=url, title=f"T:{url}", markdown=f"md:{url}", method_used="httpx")
    defaults.update(kwargs)
    return FetchResponse(**defaults)


class TestBatchEndpoint:
    def test_batch_returns_per_url_results(self, mock_browser_pool):
        from agentic_fetch.main import app

        async def fake_fetch(req):
            return _fr(req.url)

        with patch("agentic_fetch.main.fetch_engine.fetch", side_effect=fake_fetch):
            with TestClient(app) as client:
                r = client.post("/fetch/batch", json={
                    "urls": ["https://a.com", "https://b.com", "https://c.com"],
                    "max_concurrency": 2,
                })
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 3
        assert data["succeeded"] == 3
        assert data["failed"] == 0
        urls = {res["url"] for res in data["results"]}
        assert urls == {"https://a.com", "https://b.com", "https://c.com"}

    def test_batch_partial_failure_is_isolated(self, mock_browser_pool):
        from agentic_fetch.main import app

        async def fake_fetch(req):
            if "bad" in req.url:
                raise RuntimeError("boom")
            return _fr(req.url)

        with patch("agentic_fetch.main.fetch_engine.fetch", side_effect=fake_fetch):
            with TestClient(app) as client:
                r = client.post("/fetch/batch", json={
                    "urls": ["https://ok.com", "https://bad.com"],
                })
        assert r.status_code == 200
        data = r.json()
        assert data["succeeded"] == 1
        assert data["failed"] == 1
        results = {res["url"]: res for res in data["results"]}
        assert results["https://bad.com"]["ok"] is False
        assert "boom" in results["https://bad.com"]["error"]

    def test_batch_return_markdown_false_strips_payload(self, mock_browser_pool):
        from agentic_fetch.main import app

        async def fake_fetch(req):
            return _fr(req.url, markdown="x" * 1000)

        with patch("agentic_fetch.main.fetch_engine.fetch", side_effect=fake_fetch):
            with TestClient(app) as client:
                r = client.post("/fetch/batch", json={
                    "urls": ["https://a.com"],
                    "return_markdown": False,
                })
        data = r.json()
        assert data["results"][0]["markdown"] == ""
        assert data["results"][0]["total_lines"] >= 0


# ---------------------------------------------------------------------------
# /cache/* endpoints
# ---------------------------------------------------------------------------

class TestCacheEndpoints:
    def test_evict_endpoint(self, mock_browser_pool, tmp_path):
        from agentic_fetch.main import app
        # Write to the real fetch_cache instance the endpoint uses
        with patch("agentic_fetch.main.fetch_cache") as mock_cache:
            mock_cache.evict.return_value = True
            with TestClient(app) as client:
                r = client.post("/cache/evict", json={"url": "https://x.com"})
        assert r.status_code == 200
        assert r.json() == {"url": "https://x.com", "removed": True}

    def test_prune_endpoint(self, mock_browser_pool):
        from agentic_fetch.main import app
        with patch("agentic_fetch.main.fetch_cache") as mock_cache:
            mock_cache.prune.return_value = {"removed_age": 2, "removed_lru": 0, "bytes_freed": 4096}
            with TestClient(app) as client:
                r = client.post("/cache/prune", json={"max_mb": 10.0})
        assert r.status_code == 200
        assert r.json()["removed_age"] == 2

    def test_search_endpoint(self, mock_browser_pool):
        from agentic_fetch.main import app
        with patch("agentic_fetch.main.fetch_cache") as mock_cache:
            mock_cache.search.return_value = [
                {"url": "https://x.com", "title": "X", "score": 3.0, "snippet": "..."}
            ]
            with TestClient(app) as client:
                r = client.post("/cache/search", json={"query": "asyncio", "limit": 5})
        assert r.status_code == 200
        results = r.json()
        assert len(results) == 1
        assert results[0]["title"] == "X"

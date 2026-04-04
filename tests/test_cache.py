"""Tests for FetchCache."""
import time
import pytest
from agentic_fetch.cache import FetchCache, TRACKING_PARAMS

SAMPLE_MD = """# Title

Some content here.

## Section

More content with `symbol_one` and `symbol_two`.

```python
print("hello")
```
"""


@pytest.fixture
def cache(tmp_path):
    return FetchCache(cache_dir=str(tmp_path / "cache"), ttl=300)


class TestCacheKey:
    def test_same_url_same_key(self, cache):
        k1 = cache.cache_key("https://example.com/page")
        k2 = cache.cache_key("https://example.com/page")
        assert k1 == k2

    def test_different_urls_different_keys(self, cache):
        k1 = cache.cache_key("https://example.com/a")
        k2 = cache.cache_key("https://example.com/b")
        assert k1 != k2

    def test_tracking_params_stripped(self, cache):
        url_clean = "https://example.com/page"
        url_tracked = "https://example.com/page?utm_source=newsletter&utm_medium=email"
        assert cache.cache_key(url_clean) == cache.cache_key(url_tracked)

    def test_non_tracking_params_preserved(self, cache):
        url_a = "https://example.com/page?q=foo"
        url_b = "https://example.com/page?q=bar"
        assert cache.cache_key(url_a) != cache.cache_key(url_b)

    def test_fragment_stripped(self, cache):
        url_a = "https://example.com/page"
        url_b = "https://example.com/page#section"
        assert cache.cache_key(url_a) == cache.cache_key(url_b)

    def test_key_length(self, cache):
        key = cache.cache_key("https://example.com")
        assert len(key) == 16


class TestPutAndGet:
    def test_put_and_get(self, cache):
        cache.put("https://example.com", SAMPLE_MD, "html")
        result = cache.get("https://example.com")
        assert result is not None
        md, meta = result
        assert "Title" in md
        assert meta.url == "https://example.com"
        assert meta.content_type == "html"

    def test_get_missing(self, cache):
        assert cache.get("https://notcached.com") is None

    def test_ttl_zero_disables_cache(self, tmp_path):
        c = FetchCache(cache_dir=str(tmp_path / "cache2"), ttl=0)
        c.put("https://example.com", SAMPLE_MD, "html")
        assert c.get("https://example.com") is None

    def test_expired_ttl(self, tmp_path):
        c = FetchCache(cache_dir=str(tmp_path / "cache3"), ttl=1)
        c.put("https://example.com", SAMPLE_MD, "html")
        # Manually expire by setting fetched_at in the past
        import json, time
        key = c.cache_key("https://example.com")
        meta_path = c.cache_dir / f"{key}.meta.json"
        meta = json.loads(meta_path.read_text())
        meta["fetched_at"] = time.time() - 10  # expired
        meta_path.write_text(json.dumps(meta))
        assert c.get("https://example.com") is None

    def test_etag_stored(self, cache):
        cache.put("https://example.com", SAMPLE_MD, "html", etag="abc123")
        etag = cache.get_etag("https://example.com")
        assert etag == "abc123"

    def test_get_etag_missing(self, cache):
        assert cache.get_etag("https://notcached.com") is None

    def test_get_etag_empty_string(self, cache):
        cache.put("https://example.com", SAMPLE_MD, "html", etag="")
        assert cache.get_etag("https://example.com") is None


class TestBumpTtl:
    def test_bump_ttl_refreshes_timestamp(self, cache):
        cache.put("https://example.com", SAMPLE_MD, "html")
        import json, time
        key = cache.cache_key("https://example.com")
        meta_path = cache.cache_dir / f"{key}.meta.json"
        old_ts = json.loads(meta_path.read_text())["fetched_at"]
        time.sleep(0.01)
        cache.bump_ttl("https://example.com")
        new_ts = json.loads(meta_path.read_text())["fetched_at"]
        assert new_ts > old_ts

    def test_bump_ttl_missing_is_noop(self, cache):
        # Should not raise
        cache.bump_ttl("https://notcached.com")


class TestReadLines:
    def test_read_lines_from_cache(self, cache):
        cache.put("https://example.com", SAMPLE_MD, "html")
        result = cache.read_lines("https://example.com", 1, 3)
        assert result is not None
        assert "Title" in result

    def test_read_lines_not_cached(self, cache):
        assert cache.read_lines("https://notcached.com", 1, 5) is None


class TestGrep:
    def test_grep_finds_pattern(self, cache):
        cache.put("https://example.com", SAMPLE_MD, "html")
        result = cache.grep("https://example.com", "Section")
        assert result is not None
        assert "Section" in result

    def test_grep_not_cached(self, cache):
        assert cache.grep("https://notcached.com", "pattern") is None


class TestMetadata:
    def test_metadata_structure(self, cache):
        cache.put("https://example.com", SAMPLE_MD, "html")
        meta = cache.metadata("https://example.com")
        assert meta is not None
        assert "lines" in meta
        assert "toc" in meta
        assert "code_blocks" in meta
        assert "symbols" in meta
        assert meta["lines"] > 0

    def test_metadata_toc_populated(self, cache):
        cache.put("https://example.com", SAMPLE_MD, "html")
        meta = cache.metadata("https://example.com")
        titles = [e["title"] for e in meta["toc"]]
        assert "Title" in titles
        assert "Section" in titles

    def test_metadata_not_cached(self, cache):
        assert cache.metadata("https://notcached.com") is None

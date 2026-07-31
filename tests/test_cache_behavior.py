"""Behavioral tests for FetchCache maintenance operations: health linting,
BM25 search, pruning, and the append-only fetch log."""

import json
import time

import pytest

from agentic_fetch.cache import FetchCache


@pytest.fixture
def cache(tmp_path):
    return FetchCache(cache_dir=str(tmp_path), ttl=300)


def age_entry(cache: FetchCache, url: str, seconds: float) -> None:
    """Rewrite an entry's meta so it looks `seconds` old."""
    _, meta_path = cache._paths(url)
    meta = json.loads(meta_path.read_text())
    meta["fetched_at"] = time.time() - seconds
    meta_path.write_text(json.dumps(meta))


class TestHealth:
    def test_empty_cache_reports_zero_entries(self, cache):
        h = cache.health()
        assert h["total_entries"] == 0
        assert h["fresh_entries"] == 0
        assert h["stale_entries"] == 0
        assert h["synthesis_entries"] == 0
        assert h["total_size_kb"] == 0
        assert h["oldest_entry"] is None
        assert h["newest_entry"] is None

    def test_fresh_stale_and_synthesis_are_counted_separately(self, cache):
        cache.put("https://a.test/", "# A\n\nfresh", "html")
        cache.put("https://b.test/", "# B\n\nstale", "html")
        age_entry(cache, "https://b.test/", 10_000)  # ttl=300 → stale
        cache.write("note://c", "# C\n\nsynthesis")

        h = cache.health()
        assert h["total_entries"] == 3
        assert h["fresh_entries"] == 1
        assert h["stale_entries"] == 1
        assert h["synthesis_entries"] == 1

    def test_size_is_reported_in_kb(self, cache):
        cache.put("https://a.test/", "x" * 2048, "html")
        assert cache.health()["total_size_kb"] == 2.0

    def test_oldest_and_newest_span_the_entries(self, cache):
        cache.put("https://old.test/", "old", "html")
        cache.put("https://new.test/", "new", "html")
        age_entry(cache, "https://old.test/", 5_000)
        h = cache.health()
        assert h["oldest_entry"] < h["newest_entry"]
        # ISO-8601 UTC format
        assert h["newest_entry"].endswith("Z") and "T" in h["newest_entry"]

    def test_stale_synthesis_is_not_counted_stale(self, cache):
        cache.write("note://x", "# X\n\npermanent")
        age_entry(cache, "note://x", 100_000)
        h = cache.health()
        assert h["stale_entries"] == 0
        assert h["synthesis_entries"] == 1


class TestBm25Search:
    def test_no_documents_returns_empty(self, cache):
        assert cache.search("anything") == []

    def test_query_with_no_tokens_returns_empty(self, cache):
        cache.put("https://a.test/", "content words here", "html")
        assert cache.search("!!! ...") == []

    def test_non_matching_query_returns_empty(self, cache):
        cache.put("https://a.test/", "alpha beta gamma", "html")
        assert cache.search("zeppelin") == []

    def test_matching_document_is_returned_with_metadata(self, cache):
        cache.put("https://a.test/", "# Title A\n\nzeppelin history", "html")
        hits = cache.search("zeppelin")
        assert len(hits) == 1
        assert hits[0]["url"] == "https://a.test/"
        assert hits[0]["title"] == "Title A"
        assert hits[0]["score"] > 0

    def test_higher_term_frequency_ranks_first(self, cache):
        filler = " ".join(["filler"] * 50)
        cache.put("https://often.test/", f"kubernetes kubernetes kubernetes {filler}", "html")
        cache.put("https://once.test/", f"kubernetes {filler}", "html")
        hits = cache.search("kubernetes")
        assert [h["url"] for h in hits] == ["https://often.test/", "https://once.test/"]
        assert hits[0]["score"] > hits[1]["score"]

    def test_limit_caps_results(self, cache):
        for i in range(5):
            cache.put(f"https://doc{i}.test/", f"shared term doc{i}", "html")
        assert len(cache.search("shared", limit=3)) == 3

    def test_snippet_is_centered_on_first_match(self, cache):
        words = [f"w{i}" for i in range(200)]
        words[100] = "needle"
        cache.put("https://a.test/", " ".join(words), "html")
        snippet = cache.search("needle")[0]["snippet"]
        assert "needle" in snippet
        assert snippet.startswith("…") and snippet.endswith("…")
        # window of ~40 words, not the whole 200-word doc
        assert len(snippet.split()) < 60

    def test_snippet_falls_back_to_document_start(self, cache):
        # Match is on a token inside punctuation the snippet scanner cleans up;
        # if no word matches, the snippet is the document head.
        cache.put("https://a.test/", "alpha beta gamma delta", "html")
        hits = cache.search("alpha")
        assert hits[0]["snippet"].startswith("…alpha")


class TestPrune:
    def test_entries_older_than_ttl_times_factor_are_evicted(self, cache):
        cache.put("https://old.test/", "old content", "html")
        cache.put("https://fresh.test/", "fresh content", "html")
        age_entry(cache, "https://old.test/", 300 * 4 + 100)

        stats = cache.prune()
        assert stats["removed_age"] == 1
        assert stats["bytes_freed"] > 0
        assert cache.get("https://old.test/") is None
        assert cache.get("https://fresh.test/") is not None

    def test_entries_within_age_budget_are_kept(self, cache):
        cache.put("https://a.test/", "content", "html")
        age_entry(cache, "https://a.test/", 300 * 2)  # stale but < ttl*4
        stats = cache.prune()
        assert stats["removed_age"] == 0

    def test_synthesis_entries_survive_age_pruning(self, cache):
        cache.write("note://keep", "# Keep\n\nforever")
        age_entry(cache, "note://keep", 10**7)
        stats = cache.prune()
        assert stats["removed_age"] == 0
        assert cache.metadata("note://keep") is not None

    def test_size_cap_evicts_oldest_first(self, cache):
        cache.put("https://oldest.test/", "x" * 4000, "html")
        cache.put("https://newer.test/", "y" * 4000, "html")
        age_entry(cache, "https://oldest.test/", 100)

        stats = cache.prune(max_mb=0.005)  # ~5 KB cap, total ~8 KB
        assert stats["removed_lru"] == 1
        assert cache.metadata("https://oldest.test/") is None
        assert cache.metadata("https://newer.test/") is not None

    def test_size_cap_never_evicts_synthesis(self, cache):
        cache.write("note://big", "z" * 8000)
        stats = cache.prune(max_mb=0.001)
        assert stats["removed_lru"] == 0
        assert cache.metadata("note://big") is not None

    def test_under_cap_nothing_is_lru_evicted(self, cache):
        cache.put("https://a.test/", "small", "html")
        stats = cache.prune(max_mb=10)
        assert stats == {"removed_age": 0, "removed_lru": 0, "bytes_freed": 0}


class TestFetchLog:
    def test_entries_come_back_newest_first(self, cache):
        cache.log_fetch("https://first.test/", "httpx", 10, "First")
        cache.log_fetch("https://second.test/", "plugin", 20, "Second")
        log = cache.get_log()
        assert [e["url"] for e in log] == [
            "https://second.test/",
            "https://first.test/",
        ]
        assert log[0]["method"] == "plugin"
        assert log[0]["words"] == 20
        assert log[0]["title"] == "Second"

    def test_limit_returns_most_recent_entries_only(self, cache):
        for i in range(5):
            cache.log_fetch(f"https://u{i}.test/", "httpx", i)
        log = cache.get_log(limit=2)
        assert [e["url"] for e in log] == ["https://u4.test/", "https://u3.test/"]

    def test_empty_log_returns_empty_list(self, cache):
        assert cache.get_log() == []

    def test_corrupt_lines_are_skipped(self, cache):
        cache.log_fetch("https://good.test/", "httpx", 1)
        (cache.cache_dir / "_log.jsonl").open("a").write("not json\n")
        cache.log_fetch("https://also-good.test/", "httpx", 2)
        log = cache.get_log()
        assert [e["url"] for e in log] == [
            "https://also-good.test/",
            "https://good.test/",
        ]

    def test_oversize_log_rotates_to_last_5000_lines(self, cache):
        log_path = cache.cache_dir / "_log.jsonl"
        line = json.dumps({"ts": "t", "url": "https://x.test/", "method": "httpx",
                           "words": 1, "title": "pad" * 300})
        log_path.write_text((line + "\n") * 6000)
        assert log_path.stat().st_size > 4 * 1024 * 1024

        cache.log_fetch("https://trigger.test/", "httpx", 1)
        lines = log_path.read_text().splitlines()
        assert len(lines) == 5000
        assert json.loads(lines[-1])["url"] == "https://trigger.test/"


class TestIndex:
    def test_empty_cache_yields_empty_index(self, cache):
        assert cache.index() == []

    def test_entries_are_listed_newest_first(self, cache):
        cache.put("https://old.test/", "old words here", "html")
        cache.put("https://new.test/", "new words here", "html")
        age_entry(cache, "https://old.test/", 100)
        urls = [e["url"] for e in cache.index()]
        assert urls == ["https://new.test/", "https://old.test/"]

    def test_entry_carries_metadata_and_word_count(self, cache):
        cache.put("https://a.test/", "# Title\n\none two three", "html", method="httpx")
        entry = cache.index()[0]
        assert entry["url"] == "https://a.test/"
        assert entry["title"] == "Title"
        assert entry["content_type"] == "html"
        assert entry["method"] == "httpx"
        assert entry["word_count"] == 5  # includes the heading line's words
        assert entry["stale"] is False
        assert entry["fetched_at"].endswith("Z")

    def test_snippet_skips_headings_and_rules(self, cache):
        cache.put(
            "https://a.test/", "# Heading\n\n---\n\nbody starts here", "html"
        )
        snippet = cache.index()[0]["snippet"]
        assert snippet.startswith("body starts")
        assert "Heading" not in snippet

    def test_snippet_is_capped(self, cache):
        cache.put("https://a.test/", "word " * 500, "html")
        entry = cache.index()[0]
        assert len(entry["snippet"]) <= 400
        assert len(entry["snippet"].split()) <= 80

    def test_expired_entry_is_flagged_stale(self, cache):
        cache.put("https://a.test/", "content", "html")
        age_entry(cache, "https://a.test/", 10_000)
        assert cache.index()[0]["stale"] is True

    def test_old_synthesis_entry_is_never_stale(self, cache):
        cache.write("note://x", "kept forever")
        age_entry(cache, "note://x", 10_000)
        assert cache.index()[0]["stale"] is False

    def test_entry_without_markdown_file_is_skipped(self, cache):
        cache.put("https://a.test/", "content", "html")
        md_path, _ = cache._paths("https://a.test/")
        md_path.unlink()
        assert cache.index() == []


class TestMetaRobustness:
    def test_corrupt_meta_json_is_treated_as_missing(self, cache):
        cache.put("https://a.test/", "content", "html")
        _, meta_path = cache._paths("https://a.test/")
        meta_path.write_text("{broken json")
        assert cache.get("https://a.test/") is None
        assert cache.metadata("https://a.test/") is None

    def test_unreadable_meta_is_skipped_by_index_and_health(self, cache):
        cache.put("https://good.test/", "content", "html")
        (cache.cache_dir / "zzzz.meta.json").write_text("{broken")
        assert cache.health()["total_entries"] == 1
        assert len(cache.index()) == 1

    def test_metadata_returns_precomputed_fields(self, cache):
        cache.put("https://a.test/", "# H1\n\n`symbol` text\n\n```py\ncode\n```", "html")
        meta = cache.metadata("https://a.test/")
        assert meta["title"] == "H1"
        assert meta["lines"] == 7
        # closing ``` fences count as "unknown" (behavior pinned in test_markdown.py)
        assert meta["code_blocks"] == {"py": 1, "unknown": 1}
        assert "symbol" in meta["symbols"]
        assert meta["toc"][0]["title"] == "H1"

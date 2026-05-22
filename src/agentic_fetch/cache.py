import hashlib
import json
import logging
import math
import re
import time
from collections import Counter
from pathlib import Path
from dataclasses import dataclass, asdict, field
from .config import settings, TRACKING_PARAMS
from .markdown import extract_toc, count_code_blocks, extract_symbols

log = logging.getLogger("agentic_fetch.cache")

# Synthesis entries never expire (10-year sentinel TTL)
_SYNTHESIS_TTL = 315_360_000

# Bound for the append-only fetch log (lines retained after each rotation pass)
_LOG_MAX_LINES = 5000


@dataclass
class CacheMeta:
    url: str
    fetched_at: float
    ttl: int
    content_type: str
    etag: str = ""
    # Tier that produced this entry (plugin/httpx/curl_cffi/httpx+browser/zendriver/synthesis).
    # Read-time replay lets cache hits report the original tier instead of always "httpx".
    method: str = ""
    # Precomputed at write time so reads never rescan the file.
    title: str = ""
    lines: int = 0
    size_bytes: int = 0
    toc: list[dict] = field(default_factory=list)
    code_blocks: dict[str, int] = field(default_factory=dict)
    symbols: list[str] = field(default_factory=list)


def _extract_h1(content: str) -> str:
    for line in content.splitlines()[:30]:
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class FetchCache:
    def __init__(self, cache_dir: str | None = None, ttl: int | None = None):
        self.cache_dir = Path(cache_dir or settings.cache_dir)
        self.ttl = ttl if ttl is not None else settings.cache_ttl
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def cache_key(self, url: str) -> str:
        from urllib.parse import urlparse, urlencode, parse_qsl
        u = urlparse(url)
        clean_q = urlencode([(k, v) for k, v in parse_qsl(u.query)
                              if k.lower() not in TRACKING_PARAMS])
        norm = u._replace(fragment="", query=clean_q).geturl()
        return hashlib.sha256(norm.encode()).hexdigest()[:16]

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = self.cache_key(url)
        return self.cache_dir / f"{key}.md", self.cache_dir / f"{key}.meta.json"

    def _load_meta(self, url: str) -> CacheMeta | None:
        _, meta_path = self._paths(url)
        try:
            return CacheMeta(**json.loads(meta_path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return None
        except Exception as exc:
            log.debug("corrupt cache meta for %s: %s", url, exc)
            return None

    def get(self, url: str) -> tuple[str, CacheMeta] | None:
        if self.ttl == 0:
            return None
        md_path, _ = self._paths(url)
        meta = self._load_meta(url)
        if not meta or not md_path.exists():
            return None
        if time.time() - meta.fetched_at > meta.ttl:
            return None
        return md_path.read_text(encoding="utf-8"), meta

    def get_etag(self, url: str) -> str | None:
        meta = self._load_meta(url)
        return (meta.etag or None) if meta else None

    def bump_ttl(self, url: str) -> None:
        meta = self._load_meta(url)
        if not meta:
            return
        meta.fetched_at = time.time()
        _, meta_path = self._paths(url)
        _atomic_write(meta_path, json.dumps(asdict(meta)))

    def put(
        self,
        url: str,
        markdown: str,
        content_type: str,
        etag: str = "",
        method: str = "",
    ) -> None:
        self._write(
            url=url, markdown=markdown, content_type=content_type,
            etag=etag, method=method, ttl=self.ttl,
        )

    def _write(
        self, url: str, markdown: str, content_type: str,
        etag: str, method: str, ttl: int,
    ) -> None:
        md_path, meta_path = self._paths(url)
        _atomic_write(md_path, markdown)
        meta = CacheMeta(
            url=url,
            fetched_at=time.time(),
            ttl=ttl,
            content_type=content_type,
            etag=etag,
            method=method,
            title=_extract_h1(markdown) or url,
            lines=len(markdown.splitlines()),
            size_bytes=md_path.stat().st_size,
            toc=extract_toc(markdown),
            code_blocks=count_code_blocks(markdown),
            symbols=extract_symbols(markdown),
        )
        _atomic_write(meta_path, json.dumps(asdict(meta)))

    def read_lines(self, url: str, start: int, end: int) -> str | None:
        md_path, _ = self._paths(url)
        if not md_path.exists():
            return None
        from .markdown import read_lines
        return read_lines(md_path.read_text(encoding="utf-8"), start, end)

    def grep(self, url: str, pattern: str, **kwargs) -> str | None:
        md_path, _ = self._paths(url)
        if not md_path.exists():
            return None
        from .markdown import grep_markdown
        return grep_markdown(md_path.read_text(encoding="utf-8"), pattern, **kwargs)

    def metadata(self, url: str) -> dict | None:
        """Return precomputed metadata (cheap — no re-scan of the markdown file)."""
        meta = self._load_meta(url)
        if not meta:
            return None
        return {
            "lines": meta.lines,
            "size_bytes": meta.size_bytes,
            "toc": meta.toc,
            "code_blocks": meta.code_blocks,
            "symbols": meta.symbols,
            "title": meta.title,
            "method": meta.method,
            "fetched_at": meta.fetched_at,
        }

    def evict(self, url: str) -> bool:
        """Delete a single cache entry. Returns True if anything was removed."""
        md_path, meta_path = self._paths(url)
        removed = False
        for p in (md_path, meta_path):
            if p.exists():
                p.unlink()
                removed = True
        return removed

    def write(self, url: str, markdown: str) -> None:
        """File synthesized content permanently — never expires."""
        self._write(
            url=url, markdown=markdown, content_type="synthesis",
            etag="", method="synthesis", ttl=_SYNTHESIS_TTL,
        )

    def log_fetch(self, url: str, method: str, word_count: int, title: str = "") -> None:
        """Append one line to the fetch log, auto-rotating once it grows past 2× the cap."""
        log_path = self.cache_dir / "_log.jsonl"
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "url": url,
            "method": method,
            "words": word_count,
            "title": title,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        # Rotate when the log has roughly doubled past the cap.
        try:
            if log_path.stat().st_size > 4 * 1024 * 1024:
                self._rotate_log(log_path)
        except OSError:
            pass

    def _rotate_log(self, log_path: Path) -> None:
        lines = log_path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= _LOG_MAX_LINES:
            return
        kept = lines[-_LOG_MAX_LINES:]
        _atomic_write(log_path, "\n".join(kept) + "\n")

    def get_log(self, limit: int = 50) -> list[dict]:
        """Return the last `limit` log entries, newest first."""
        log_path = self.cache_dir / "_log.jsonl"
        if not log_path.exists():
            return []
        lines = log_path.read_text(encoding="utf-8").splitlines()
        entries: list[dict] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
            if len(entries) >= limit:
                break
        return entries

    def _iter_meta(self):
        for meta_path in self.cache_dir.glob("*.meta.json"):
            try:
                yield meta_path, CacheMeta(**json.loads(meta_path.read_text(encoding="utf-8")))
            except Exception as exc:
                log.debug("skipping unreadable meta %s: %s", meta_path, exc)

    def index(self) -> list[dict]:
        """Return all cached entries as a structured index, newest first.

        Uses precomputed title and reads each .md once for a snippet only.
        """
        entries = []
        now = time.time()
        for meta_path, meta in self._iter_meta():
            md_path = meta_path.with_suffix("").with_suffix(".md")
            if not md_path.exists():
                continue
            try:
                content = md_path.read_text(encoding="utf-8")
            except OSError:
                continue
            body_words: list[str] = []
            for line in content.splitlines():
                if line.startswith("#") or line.startswith("---"):
                    continue
                body_words.extend(line.split())
                if len(body_words) >= 80:
                    break
            is_stale = (meta.content_type != "synthesis"
                        and now - meta.fetched_at > meta.ttl)
            entries.append({
                "url": meta.url,
                "title": meta.title or meta.url,
                "content_type": meta.content_type,
                "method": meta.method,
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                           time.gmtime(meta.fetched_at)),
                "word_count": len(content.split()),
                "stale": is_stale,
                "snippet": " ".join(body_words[:80])[:400],
            })
        entries.sort(key=lambda e: e["fetched_at"], reverse=True)
        return entries

    def prune(self, max_mb: float | None = None, max_age_factor: float = 4.0) -> dict:
        """Evict stale, oversize cache. Returns stats about what was removed.

        - max_age_factor: drop fresh-content entries older than ``ttl * factor``.
        - max_mb: when total cache exceeds this, evict LRU until under the cap.
        Synthesis entries are never evicted by age but count toward size.
        """
        now = time.time()
        removed_age = 0
        removed_lru = 0
        bytes_freed = 0
        entries: list[tuple[float, Path, Path, int, str]] = []  # (fetched_at, md, meta, size, ct)

        for meta_path, meta in self._iter_meta():
            md_path = meta_path.with_suffix("").with_suffix(".md")
            size = md_path.stat().st_size if md_path.exists() else 0
            # Age-based eviction skips synthesis entries.
            if meta.content_type != "synthesis":
                if now - meta.fetched_at > meta.ttl * max_age_factor:
                    bytes_freed += size
                    md_path.exists() and md_path.unlink()
                    meta_path.unlink()
                    removed_age += 1
                    continue
            entries.append((meta.fetched_at, md_path, meta_path, size, meta.content_type))

        if max_mb is not None:
            total = sum(e[3] for e in entries)
            cap = max_mb * 1024 * 1024
            entries.sort(key=lambda e: e[0])  # oldest first
            for fetched_at, md_path, meta_path, size, ct in entries:
                if total <= cap:
                    break
                if ct == "synthesis":
                    continue
                if md_path.exists():
                    md_path.unlink()
                meta_path.unlink()
                total -= size
                bytes_freed += size
                removed_lru += 1
        return {
            "removed_age": removed_age,
            "removed_lru": removed_lru,
            "bytes_freed": bytes_freed,
        }

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """BM25 search over all cached markdown content."""
        def tokenize(text: str) -> list[str]:
            return re.findall(r"[a-z0-9]+", text.lower())

        docs: list[dict] = []
        for meta_path, meta in self._iter_meta():
            md_path = meta_path.with_suffix("").with_suffix(".md")
            if not md_path.exists():
                continue
            try:
                content = md_path.read_text(encoding="utf-8")
            except OSError:
                continue
            docs.append({
                "url": meta.url,
                "title": meta.title or meta.url,
                "tokens": tokenize(content),
                "content": content,
            })

        if not docs:
            return []

        query_terms = tokenize(query)
        if not query_terms:
            return []

        # Document frequency across corpus
        doc_freq: Counter[str] = Counter()
        for doc in docs:
            for term in set(doc["tokens"]):
                doc_freq[term] += 1

        num_docs = len(docs)
        avg_dl = sum(len(d["tokens"]) for d in docs) / num_docs
        k1, b = 1.5, 0.75

        scored: list[dict] = []
        for doc in docs:
            tf_map: Counter[str] = Counter(doc["tokens"])
            dl = len(doc["tokens"])
            score = 0.0
            for term in query_terms:
                tf = tf_map.get(term, 0)
                if not tf:
                    continue
                df = doc_freq.get(term, 1)
                idf = math.log((num_docs - df + 0.5) / (df + 0.5) + 1)
                tf_norm = tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avg_dl))
                score += idf * tf_norm
            if score > 0:
                scored.append({
                    "url": doc["url"],
                    "title": doc["title"],
                    "score": round(score, 3),
                    "snippet": self._bm25_snippet(doc["content"], query_terms),
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    def _bm25_snippet(self, content: str, query_terms: list[str], window: int = 40) -> str:
        """Return a snippet of `window` words centered on the first query term match."""
        words = content.split()
        for i, w in enumerate(words):
            clean = re.sub(r"[^a-z0-9]", "", w.lower())
            if clean in query_terms:
                start = max(0, i - window // 2)
                end = min(len(words), start + window)
                return "…" + " ".join(words[start:end]) + "…"
        return " ".join(words[:window])

    def health(self) -> dict:
        """Lint the cache: count stale, synthesis, orphan entries and total size."""
        total = stale = synthesis = 0
        oldest: float | None = None
        newest: float | None = None
        total_bytes = 0
        now = time.time()

        for meta_path, meta in self._iter_meta():
            md_path = meta_path.with_suffix("").with_suffix(".md")
            total += 1
            if meta.content_type == "synthesis":
                synthesis += 1
            elif now - meta.fetched_at > meta.ttl:
                stale += 1
            if md_path.exists():
                total_bytes += md_path.stat().st_size
            if oldest is None or meta.fetched_at < oldest:
                oldest = meta.fetched_at
            if newest is None or meta.fetched_at > newest:
                newest = meta.fetched_at

        return {
            "total_entries": total,
            "fresh_entries": total - stale - synthesis,
            "stale_entries": stale,
            "synthesis_entries": synthesis,
            "total_size_kb": round(total_bytes / 1024, 1),
            "oldest_entry": (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(oldest))
                             if oldest else None),
            "newest_entry": (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(newest))
                             if newest else None),
        }


fetch_cache = FetchCache()

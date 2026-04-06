import hashlib
import json
import math
import re
import time
from collections import Counter
from pathlib import Path
from dataclasses import dataclass, asdict
from .config import settings
from .markdown import extract_toc, count_code_blocks, extract_symbols

TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term",
                   "utm_content", "fbclid", "gclid", "ref", "source"}

# Synthesis entries never expire (10-year sentinel TTL)
_SYNTHESIS_TTL = 315_360_000


@dataclass
class CacheMeta:
    url: str
    fetched_at: float
    ttl: int
    content_type: str
    etag: str = ""


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

    def get(self, url: str) -> tuple[str, CacheMeta] | None:
        if self.ttl == 0:
            return None
        key = self.cache_key(url)
        md_path = self.cache_dir / f"{key}.md"
        meta_path = self.cache_dir / f"{key}.meta.json"
        if not md_path.exists() or not meta_path.exists():
            return None
        try:
            meta = CacheMeta(**json.loads(meta_path.read_text(encoding="utf-8")))
        except Exception:
            return None
        if time.time() - meta.fetched_at > meta.ttl:
            return None
        return md_path.read_text(encoding="utf-8"), meta

    def get_etag(self, url: str) -> str | None:
        key = self.cache_key(url)
        meta_path = self.cache_dir / f"{key}.meta.json"
        try:
            meta = CacheMeta(**json.loads(meta_path.read_text(encoding="utf-8")))
            return meta.etag or None
        except Exception:
            return None

    def bump_ttl(self, url: str) -> None:
        key = self.cache_key(url)
        meta_path = self.cache_dir / f"{key}.meta.json"
        try:
            meta = CacheMeta(**json.loads(meta_path.read_text(encoding="utf-8")))
            meta.fetched_at = time.time()
            meta_path.write_text(json.dumps(asdict(meta)), encoding="utf-8")
        except Exception:
            pass

    def put(self, url: str, markdown: str, content_type: str, etag: str = "") -> None:
        key = self.cache_key(url)
        md_path = self.cache_dir / f"{key}.md"
        meta_path = self.cache_dir / f"{key}.meta.json"
        meta = CacheMeta(url=url, fetched_at=time.time(), ttl=self.ttl,
                         content_type=content_type, etag=etag)
        tmp_md = md_path.with_suffix(".tmp")
        tmp_md.write_text(markdown, encoding="utf-8")
        tmp_md.replace(md_path)
        meta_path.write_text(json.dumps(asdict(meta)), encoding="utf-8")

    def read_lines(self, url: str, start: int, end: int) -> str | None:
        key = self.cache_key(url)
        md_path = self.cache_dir / f"{key}.md"
        if not md_path.exists():
            return None
        from .markdown import read_lines
        return read_lines(md_path.read_text(encoding="utf-8"), start, end)

    def grep(self, url: str, pattern: str, **kwargs) -> str | None:
        key = self.cache_key(url)
        md_path = self.cache_dir / f"{key}.md"
        if not md_path.exists():
            return None
        from .markdown import grep_markdown
        return grep_markdown(md_path.read_text(encoding="utf-8"), pattern, **kwargs)

    def metadata(self, url: str) -> dict | None:
        key = self.cache_key(url)
        md_path = self.cache_dir / f"{key}.md"
        if not md_path.exists():
            return None
        content = md_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        return {
            "lines": len(lines),
            "size_bytes": md_path.stat().st_size,
            "toc": extract_toc(content),
            "code_blocks": count_code_blocks(content),
            "symbols": extract_symbols(content),
        }

    # ── Wiki operations (index / search / write / log / health) ───────────────

    def write(self, url: str, markdown: str) -> None:
        """File synthesized content permanently — never expires."""
        key = self.cache_key(url)
        md_path = self.cache_dir / f"{key}.md"
        meta_path = self.cache_dir / f"{key}.meta.json"
        meta = CacheMeta(url=url, fetched_at=time.time(), ttl=_SYNTHESIS_TTL,
                         content_type="synthesis", etag="")
        tmp = md_path.with_suffix(".tmp")
        tmp.write_text(markdown, encoding="utf-8")
        tmp.replace(md_path)
        meta_path.write_text(json.dumps(asdict(meta)), encoding="utf-8")

    def log_fetch(self, url: str, method: str, word_count: int, title: str = "") -> None:
        """Append one line to the append-only fetch log."""
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

    def index(self) -> list[dict]:
        """Return all cached entries as a structured index, newest first."""
        entries = []
        for meta_path in self.cache_dir.glob("*.meta.json"):
            try:
                meta = CacheMeta(**json.loads(meta_path.read_text(encoding="utf-8")))
                md_path = meta_path.with_suffix("").with_suffix(".md")
                content = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
                words = content.split()
                # First H1 as title
                title = ""
                for line in content.splitlines()[:15]:
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
                # Snippet: first non-heading words from body
                body_words: list[str] = []
                for line in content.splitlines():
                    if line.startswith("#") or line.startswith("---"):
                        continue
                    body_words.extend(line.split())
                    if len(body_words) >= 80:
                        break
                snippet = " ".join(body_words[:80])
                is_stale = (meta.content_type != "synthesis"
                            and time.time() - meta.fetched_at > meta.ttl)
                entries.append({
                    "url": meta.url,
                    "title": title or meta.url,
                    "content_type": meta.content_type,
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                               time.gmtime(meta.fetched_at)),
                    "word_count": len(words),
                    "stale": is_stale,
                    "snippet": snippet[:400],
                })
            except Exception:
                pass
        entries.sort(key=lambda e: e["fetched_at"], reverse=True)
        return entries

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """BM25 search over all cached markdown content."""
        def tokenize(text: str) -> list[str]:
            return re.findall(r"[a-z0-9]+", text.lower())

        # Load all docs
        docs: list[dict] = []
        for meta_path in self.cache_dir.glob("*.meta.json"):
            try:
                meta = CacheMeta(**json.loads(meta_path.read_text(encoding="utf-8")))
                md_path = meta_path.with_suffix("").with_suffix(".md")
                if not md_path.exists():
                    continue
                content = md_path.read_text(encoding="utf-8")
                tokens = tokenize(content)
                title = ""
                for line in content.splitlines()[:15]:
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
                docs.append({"url": meta.url, "title": title or meta.url,
                              "tokens": tokens, "content": content})
            except Exception:
                pass

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

        for meta_path in self.cache_dir.glob("*.meta.json"):
            try:
                meta = CacheMeta(**json.loads(meta_path.read_text(encoding="utf-8")))
                md_path = meta_path.with_suffix("").with_suffix(".md")
                total += 1
                if meta.content_type == "synthesis":
                    synthesis += 1
                elif time.time() - meta.fetched_at > meta.ttl:
                    stale += 1
                if md_path.exists():
                    total_bytes += md_path.stat().st_size
                if oldest is None or meta.fetched_at < oldest:
                    oldest = meta.fetched_at
                if newest is None or meta.fetched_at > newest:
                    newest = meta.fetched_at
            except Exception:
                pass

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

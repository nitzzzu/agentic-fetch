import hashlib
import json
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from .config import settings
from .markdown import extract_toc, count_code_blocks, extract_symbols

TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term",
                   "utm_content", "fbclid", "gclid", "ref", "source"}


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
            meta = CacheMeta(**json.loads(meta_path.read_text()))
        except Exception:
            return None
        if time.time() - meta.fetched_at > meta.ttl:
            return None
        return md_path.read_text(), meta

    def get_etag(self, url: str) -> str | None:
        key = self.cache_key(url)
        meta_path = self.cache_dir / f"{key}.meta.json"
        try:
            meta = CacheMeta(**json.loads(meta_path.read_text()))
            return meta.etag or None
        except Exception:
            return None

    def bump_ttl(self, url: str) -> None:
        key = self.cache_key(url)
        meta_path = self.cache_dir / f"{key}.meta.json"
        try:
            meta = CacheMeta(**json.loads(meta_path.read_text()))
            meta.fetched_at = time.time()
            meta_path.write_text(json.dumps(asdict(meta)))
        except Exception:
            pass

    def put(self, url: str, markdown: str, content_type: str, etag: str = "") -> None:
        key = self.cache_key(url)
        md_path = self.cache_dir / f"{key}.md"
        meta_path = self.cache_dir / f"{key}.meta.json"
        meta = CacheMeta(url=url, fetched_at=time.time(), ttl=self.ttl,
                         content_type=content_type, etag=etag)
        tmp_md = md_path.with_suffix(".tmp")
        tmp_md.write_text(markdown)
        tmp_md.replace(md_path)
        meta_path.write_text(json.dumps(asdict(meta)))

    def read_lines(self, url: str, start: int, end: int) -> str | None:
        key = self.cache_key(url)
        md_path = self.cache_dir / f"{key}.md"
        if not md_path.exists():
            return None
        from .markdown import read_lines
        return read_lines(md_path.read_text(), start, end)

    def grep(self, url: str, pattern: str, **kwargs) -> str | None:
        key = self.cache_key(url)
        md_path = self.cache_dir / f"{key}.md"
        if not md_path.exists():
            return None
        from .markdown import grep_markdown
        return grep_markdown(md_path.read_text(), pattern, **kwargs)

    def metadata(self, url: str) -> dict | None:
        key = self.cache_key(url)
        md_path = self.cache_dir / f"{key}.md"
        if not md_path.exists():
            return None
        content = md_path.read_text()
        lines = content.splitlines()
        return {
            "lines": len(lines),
            "size_bytes": md_path.stat().st_size,
            "toc": extract_toc(content),
            "code_blocks": count_code_blocks(content),
            "symbols": extract_symbols(content),
        }


fetch_cache = FetchCache()

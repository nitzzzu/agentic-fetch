import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from .models import (SearchRequest, SearchResponse, FetchRequest, FetchResponse,
                     FetchLinesRequest, GrepRequest, CacheWriteRequest,
                     BatchFetchRequest, BatchFetchResponse, BatchFetchResult,
                     CacheEvictRequest, CachePruneRequest, CacheSearchRequest)
from .browser import browser_pool
from .search import search_engine
from .fetch import fetch_engine
from .cache import fetch_cache
from .http_client import close as close_http_client


# Configure once at import time so test runners see the same level as the server.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("agentic_fetch.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await browser_pool.start()
    except Exception as exc:
        log.warning("browser_pool.start() failed: %s — Tier 3/4 fetches will be unavailable", exc)
    try:
        yield
    finally:
        try:
            await browser_pool.stop()
        except Exception as exc:
            log.debug("browser_pool.stop() failed: %s", exc)
        await close_http_client()


app = FastAPI(title="Agentic Fetch", version="0.2.0", lifespan=lifespan)


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    try:
        return await search_engine.search(req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/fetch", response_model=FetchResponse)
async def fetch(req: FetchRequest):
    try:
        result = await fetch_engine.fetch(req)
        if result.markdown and not result.cached:
            word_count = len(result.markdown.split())
            clean_title = re.sub(r"<[^>]+>", "", result.title or "")
            fetch_cache.log_fetch(result.url, result.method_used, word_count, clean_title)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Cache-bound endpoints are plain `def` on purpose: FastAPI runs them in its
# threadpool, so their synchronous file I/O never blocks the event loop.
@app.post("/fetch/lines")
def fetch_lines(req: FetchLinesRequest):
    result = fetch_cache.read_lines(req.url, req.start, req.end)
    if result is None:
        raise HTTPException(status_code=404,
            detail="URL not in cache — run POST /fetch first")
    return {"url": req.url, "start": req.start, "end": req.end, "content": result}


@app.post("/grep")
def grep(req: GrepRequest):
    try:
        re.compile(req.pattern)
    except re.error as e:
        raise HTTPException(status_code=400, detail=f"Invalid regex pattern: {e}")
    result = fetch_cache.grep(
        req.url, req.pattern,
        context_lines=req.context_lines,
        ignore_case=req.ignore_case,
        max_matches=req.max_matches,
    )
    if result is None:
        raise HTTPException(status_code=404,
            detail="URL not in cache — run POST /fetch first")
    return {"url": req.url, "pattern": req.pattern, "result": result}


@app.post("/fetch/batch", response_model=BatchFetchResponse)
async def fetch_batch(req: BatchFetchRequest):
    """Fetch many URLs concurrently and return a flat list of results.

    Crash-safe: per-URL failures become entries with ``ok=False`` and an error
    message instead of failing the whole batch. The browser semaphore still
    enforces tab limits, so this is safe to call with large URL lists.
    """
    sem = asyncio.Semaphore(req.max_concurrency)
    started = time.monotonic()
    # Dedupe while preserving order — duplicate URLs would race each other for
    # no benefit (same cache entry, double network cost).
    urls = list(dict.fromkeys(req.urls))

    async def fetch_one(url: str) -> BatchFetchResult:
        async with sem:
            try:
                r = await fetch_engine.fetch(FetchRequest(
                    url=url,
                    max_tokens=req.max_tokens_per_url,
                    force_browser=req.force_browser,
                    no_cache=req.no_cache,
                    include_links=req.include_links,
                    include_images=req.include_images,
                ))
                return BatchFetchResult(
                    url=r.url, ok=True, title=r.title,
                    markdown=r.markdown if req.return_markdown else "",
                    method_used=r.method_used, cached=r.cached,
                    total_lines=r.total_lines,
                    truncated=r.truncated, next_offset=r.next_offset,
                    toc=r.toc, error=r.error,
                )
            except Exception as exc:
                log.warning("batch fetch failed for %s: %s", url, exc)
                return BatchFetchResult(url=url, ok=False, error=str(exc))

    results = await asyncio.gather(*(fetch_one(u) for u in urls))
    duration_ms = int((time.monotonic() - started) * 1000)
    succeeded = sum(1 for r in results if r.ok)
    return BatchFetchResponse(
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        duration_ms=duration_ms,
        results=results,
    )


@app.post("/cache/write")
def cache_write(req: CacheWriteRequest):
    """File synthesized content into the cache permanently (never expires)."""
    fetch_cache.write(req.url, req.markdown)
    word_count = len(req.markdown.split())
    first_line = next((ln for ln in req.markdown.splitlines() if ln.strip()), req.url)
    fetch_cache.log_fetch(req.url, "synthesis", word_count,
                          first_line.lstrip("# ").strip()[:120])
    return {"url": req.url, "word_count": word_count, "status": "filed"}


@app.post("/cache/evict")
def cache_evict(req: CacheEvictRequest):
    """Delete a single cached entry by URL. Returns whether anything was removed."""
    removed = fetch_cache.evict(req.url)
    return {"url": req.url, "removed": removed}


@app.post("/cache/prune")
def cache_prune(req: CachePruneRequest):
    """Evict stale entries (and optionally LRU-trim) to keep the cache lean."""
    return fetch_cache.prune(max_mb=req.max_mb, max_age_factor=req.max_age_factor)


@app.post("/cache/search")
def cache_search(req: CacheSearchRequest):
    """BM25 search across all cached markdown documents."""
    return fetch_cache.search(req.query, limit=req.limit)


@app.get("/cache/index")
def cache_index():
    """Return a structured index of all cached pages, newest first."""
    return fetch_cache.index()


@app.get("/cache/log")
def cache_log(limit: int = 50):
    """Return the last `limit` fetch log entries, newest first."""
    return fetch_cache.get_log(limit=limit)


@app.get("/cache/health")
def cache_health():
    """Lint the cache: counts of fresh / stale / synthesis entries and total size."""
    return fetch_cache.health()


@app.get("/health")
def health():
    from .plugins import plugin_names
    return {
        "status": "ok",
        "version": app.version,
        "browser_running": browser_pool.is_running,
        "plugins": plugin_names(),
        "cache": fetch_cache.health(),
    }

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from .models import (SearchRequest, SearchResponse, FetchRequest, FetchResponse,
                     FetchLinesRequest, GrepRequest, CacheWriteRequest)
from .browser import browser_pool
from .search import search_engine
from .fetch import fetch_engine
from .cache import fetch_cache


@asynccontextmanager
async def lifespan(app: FastAPI):
    await browser_pool.start()
    yield
    await browser_pool.stop()


app = FastAPI(title="Agentic Fetch", version="0.1.0", lifespan=lifespan)


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
            import re as _re
            word_count = len(result.markdown.split())
            clean_title = _re.sub(r"<[^>]+>", "", result.title or "")
            fetch_cache.log_fetch(result.url, result.method_used, word_count, clean_title)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/fetch/lines")
async def fetch_lines(req: FetchLinesRequest):
    result = fetch_cache.read_lines(req.url, req.start, req.end)
    if result is None:
        raise HTTPException(status_code=404,
            detail="URL not in cache — run POST /fetch first")
    return {"url": req.url, "start": req.start, "end": req.end, "content": result}


@app.post("/grep")
async def grep(req: GrepRequest):
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


@app.post("/cache/write")
async def cache_write(req: CacheWriteRequest):
    """File synthesized content into the cache permanently (never expires)."""
    fetch_cache.write(req.url, req.markdown)
    word_count = len(req.markdown.split())
    fetch_cache.log_fetch(req.url, "synthesis", word_count,
                          req.markdown.splitlines()[0].lstrip("# ").strip()[:120])
    return {"url": req.url, "word_count": word_count, "status": "filed"}


@app.get("/cache/index")
async def cache_index():
    """Return a structured index of all cached pages, newest first."""
    return fetch_cache.index()


@app.get("/cache/log")
async def cache_log(limit: int = 50):
    """Return the last `limit` fetch log entries, newest first."""
    return fetch_cache.get_log(limit=limit)


@app.get("/cache/health")
async def cache_health():
    """Lint the cache: counts of fresh / stale / synthesis entries and total size."""
    return fetch_cache.health()


@app.get("/health")
async def health():
    return {"status": "ok", "browser_running": browser_pool.is_running}

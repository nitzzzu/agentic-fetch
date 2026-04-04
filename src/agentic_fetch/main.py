from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from .models import (SearchRequest, SearchResponse, FetchRequest, FetchResponse,
                     FetchLinesRequest, GrepRequest)
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
        return await fetch_engine.fetch(req)
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


@app.get("/health")
async def health():
    return {"status": "ok", "browser_running": browser_pool.is_running}

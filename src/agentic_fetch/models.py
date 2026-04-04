from pydantic import BaseModel
from typing import Literal


class SearchRequest(BaseModel):
    query: str
    max_results: int = 10
    engine: Literal["google", "duckduckgo", "auto"] = "auto"


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str


class SearchResponse(BaseModel):
    query: str
    engine_used: str
    results: list[SearchResult]
    error: str | None = None


class FetchRequest(BaseModel):
    url: str
    max_tokens: int | None = 8000
    selector: str | None = None
    offset: int = 0
    include_links: bool = True
    include_images: bool = False
    force_browser: bool = False
    no_cache: bool = False


class TOCEntry(BaseModel):
    level: int
    title: str
    start_line: int
    end_line: int


class FetchResponse(BaseModel):
    url: str
    title: str
    markdown: str
    plugin_used: str | None = None
    method_used: Literal["plugin", "httpx", "httpx+browser", "zendriver"]
    cached: bool = False
    truncated: bool = False
    next_offset: int | None = None
    toc: list[TOCEntry] = []
    total_lines: int = 0
    code_blocks: dict[str, int] = {}
    symbols: list[str] = []
    error: str | None = None


class FetchLinesRequest(BaseModel):
    url: str
    start: int
    end: int


class GrepRequest(BaseModel):
    url: str
    pattern: str
    context_lines: int = 2
    ignore_case: bool = False
    max_matches: int = 50

from datetime import date
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Literal


def _validate_fetch_url(url: str) -> str:
    """Only http(s) URLs are fetchable; reject anything else up front (422, not 500)."""
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"URL must use http:// or https:// (got {parsed.scheme or 'no'} scheme)"
        )
    if not parsed.netloc:
        raise ValueError("URL has no host")
    return url


def _validate_iso_date(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"expected YYYY-MM-DD date, got {value!r}")
    return value


FetchMethod = Literal["plugin", "httpx", "curl_cffi", "httpx+browser", "zendriver"]


class SearchRequest(BaseModel):
    query: str
    max_results: int = Field(default=10, ge=1, le=50)
    engine: Literal[
        "google",
        "duckduckgo",
        "reddit",
        "github",
        "hackernews",
        "goggames",
        "cache",
        "auto",
    ] = "auto"

    # Date filters — Google (tbs), GitHub (created: qualifier), HackerNews (numericFilters)
    date_from: str | None = Field(
        default=None,
        description="Filter results after this date (YYYY-MM-DD). Google, GitHub, HackerNews.",
    )
    date_to: str | None = Field(
        default=None,
        description="Filter results before this date (YYYY-MM-DD). Google, GitHub, HackerNews.",
    )
    date_preset: (
        Literal["past_hour", "past_day", "past_week", "past_month", "past_year"] | None
    ) = Field(
        default=None,
        description="Quick date preset for Google. Takes precedence over date_from/date_to.",
    )

    # Sort — Reddit: relevance|hot|top|new|comments; GitHub repos: stars|forks|updated
    sort: str | None = Field(
        default=None,
        description="Sort order. Reddit: relevance|hot|top|new|comments. GitHub repos: stars|forks|updated (default: stars).",
    )

    # Reddit: time window filter, most useful with sort=top
    time_filter: Literal["hour", "day", "week", "month", "year", "all"] | None = Field(
        default=None,
        description="Reddit time window (default: all). Works with any sort.",
    )

    # Reddit: subreddit scope — also parsed from 'subreddit:Name' query prefix
    subreddit: str | None = Field(
        default=None,
        description="Restrict Reddit search to this subreddit. Also parsed from 'subreddit:Name' in query.",
    )

    # GitHub filters
    search_type: Literal["repositories", "code"] | None = Field(
        default=None, description="GitHub search scope (default: repositories)."
    )
    language: str | None = Field(
        default=None,
        description="Programming language filter. GitHub search and trending.",
    )
    period: Literal["daily", "weekly", "monthly"] | None = Field(
        default=None,
        description="GitHub trending period (default: daily). Used when query is empty or 'trending'.",
    )

    # HackerNews filters
    min_points: int | None = Field(
        default=None, description="HackerNews: minimum points threshold."
    )
    min_comments: int | None = Field(
        default=None, description="HackerNews: minimum comments threshold."
    )
    story_type: Literal["story", "comment"] | None = Field(
        default=None, description="HackerNews item type to search (default: story)."
    )

    _check_dates = field_validator("date_from", "date_to")(_validate_iso_date)


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
    max_tokens: int | None = Field(default=8000, ge=1)
    selector: str | None = None
    offset: int = Field(default=0, ge=0)
    include_links: bool = True
    include_images: bool = False
    force_browser: bool = False
    no_cache: bool = False

    _check_url = field_validator("url")(_validate_fetch_url)


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
    method_used: FetchMethod
    cached: bool = False
    truncated: bool = False
    next_offset: int | None = None
    toc: list[TOCEntry] = []
    total_lines: int = 0
    code_blocks: dict[str, int] = {}
    symbols: list[str] = []
    error: str | None = None


class BatchFetchRequest(BaseModel):
    """Fetch many URLs concurrently with a shared budget.

    ``max_concurrency`` caps simultaneous requests; ``max_tokens_per_url`` is the
    per-URL paginate cap. ``return_markdown=False`` returns only the metadata
    summary (title/method/total_lines/toc) — handy for indexing a set of pages
    cheaply without paying for the full markdown payload over HTTP.
    """

    urls: list[str] = Field(..., min_length=1, max_length=50)
    max_concurrency: int = Field(default=5, ge=1, le=20)
    max_tokens_per_url: int | None = Field(default=4000, ge=1)
    force_browser: bool = False
    no_cache: bool = False
    include_links: bool = True
    include_images: bool = False
    return_markdown: bool = True

    @field_validator("urls")
    @classmethod
    def _check_urls(cls, urls: list[str]) -> list[str]:
        return [_validate_fetch_url(u) for u in urls]


class BatchFetchResult(BaseModel):
    url: str
    ok: bool
    title: str = ""
    markdown: str = ""
    method_used: str | None = None
    cached: bool = False
    total_lines: int = 0
    truncated: bool = False
    next_offset: int | None = None
    toc: list[TOCEntry] = []
    error: str | None = None


class BatchFetchResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    duration_ms: int
    results: list[BatchFetchResult]


class CacheEvictRequest(BaseModel):
    url: str


class CachePruneRequest(BaseModel):
    max_mb: float | None = Field(default=None, gt=0)
    max_age_factor: float = Field(default=4.0, ge=1.0)


class CacheSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=10, ge=1, le=100)


class FetchLinesRequest(BaseModel):
    url: str
    start: int = Field(..., ge=1)
    end: int = Field(..., ge=1)

    @model_validator(mode="after")
    def _check_range(self) -> "FetchLinesRequest":
        if self.end < self.start:
            raise ValueError(f"end ({self.end}) must be >= start ({self.start})")
        return self


class GrepRequest(BaseModel):
    url: str
    pattern: str = Field(..., min_length=1)
    context_lines: int = Field(default=2, ge=0, le=20)
    ignore_case: bool = False
    max_matches: int = Field(default=50, ge=1, le=500)


class CacheWriteRequest(BaseModel):
    url: str = Field(..., min_length=1)
    markdown: str = Field(..., min_length=1)

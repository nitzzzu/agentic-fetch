from pydantic import BaseModel, Field
from typing import Literal


class SearchRequest(BaseModel):
    query: str
    max_results: int = 10
    engine: Literal["google", "duckduckgo", "reddit", "github", "hackernews", "auto"] = "auto"

    # Date filters — Google (tbs), GitHub (created: qualifier), HackerNews (numericFilters)
    date_from: str | None = Field(default=None, description="Filter results after this date (YYYY-MM-DD). Google, GitHub, HackerNews.")
    date_to: str | None = Field(default=None, description="Filter results before this date (YYYY-MM-DD). Google, GitHub, HackerNews.")
    date_preset: Literal["past_hour", "past_day", "past_week", "past_month", "past_year"] | None = Field(
        default=None, description="Quick date preset for Google. Takes precedence over date_from/date_to."
    )

    # Sort — Reddit: relevance|hot|top|new|comments; GitHub repos: stars|forks|updated
    sort: str | None = Field(
        default=None,
        description="Sort order. Reddit: relevance|hot|top|new|comments. GitHub repos: stars|forks|updated (default: stars).",
    )

    # Reddit: time window filter, most useful with sort=top
    time_filter: Literal["hour", "day", "week", "month", "year", "all"] | None = Field(
        default=None, description="Reddit time window (default: all). Works with any sort."
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
        default=None, description="Programming language filter. GitHub search and trending."
    )
    period: Literal["daily", "weekly", "monthly"] | None = Field(
        default=None, description="GitHub trending period (default: daily). Used when query is empty or 'trending'."
    )

    # HackerNews filters
    min_points: int | None = Field(default=None, description="HackerNews: minimum points threshold.")
    min_comments: int | None = Field(default=None, description="HackerNews: minimum comments threshold.")
    story_type: Literal["story", "comment"] | None = Field(
        default=None, description="HackerNews item type to search (default: story)."
    )


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

# agentic-fetch

AI-optimized web search and fetch service for Claude Code skills. Returns clean markdown with token-aware pagination, TOC navigation, and grep support.

## Features

- **5-tier fetch strategy**: plugin → httpx → curl_cffi (bot-bypass) → httpx HTML in browser (data: URL) → zendriver full navigation
- **5 plugins**: Reddit, Medium (via Freedium), GitHub, HackerNews, Wikipedia — no browser needed
- **Search**: Google · DuckDuckGo (lite, no-browser path) · Reddit · GitHub (repos, code, trending) · HackerNews — with date, sort, and engine-specific filters
- **File cache**: TTL + ETag conditional requests, fully atomic writes, precomputed TOC/symbols, replayed `method_used` on hits
- **Batch fetch**: `POST /fetch/batch` runs up to 50 URLs concurrently behind a shared semaphore — perfect for indexing
- **Cross-cache BM25 search**: `POST /cache/search` returns ranked hits from everything fetched so far
- **Cache lifecycle**: `POST /cache/evict` (drop one URL) and `POST /cache/prune` (drop stale + LRU-trim to a size cap)
- **TOC navigation**: extract headings with line ranges, fetch targeted sections via `/fetch/lines`
- **Grep**: regex search within cached markdown, no re-fetch needed
- **Config-driven**: per-domain strip selectors, strip_lines regexes, proxy URLs, init scripts — no code changes needed
- **Shared connection pool**: a single `httpx.AsyncClient` per event loop reused across plugins and search backends
- **Structured logging**: failures in any tier go to `logging` (INFO/WARNING/DEBUG) instead of being silently swallowed
- **Docker + VNC**: xvfb + x11vnc + noVNC for browser debugging at `http://localhost:6080/vnc.html`

## Quick Start

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/)

```bash
git clone <repo>
cd agentic-fetch
uv sync
cp .env.example .env
uv run uvicorn agentic_fetch.main:app --reload --port 8000
```

## CLI Usage

```bash
# Install CLI tools into your environment
uv tool install .

# Search — Google / DuckDuckGo
agentic-search "python asyncio best practices"
agentic-search "fastapi tutorial" --engine duckduckgo --max-results 5
agentic-search "Claude API" --engine google --date-preset past_month
agentic-search "LLM agents" --engine google --date-from 2025-01-01 --date-to 2026-01-01

# Search — Reddit
agentic-search "agentic AI" --engine reddit --sort top --time-filter week
agentic-search "best Python library" --engine reddit --sort new
# Subreddit browsing — prefix query with 'subreddit:Name' or leave query empty with --subreddit
agentic-search "subreddit:Romania" --engine reddit --sort hot
agentic-search "subreddit:Romania elections" --engine reddit --sort new

# Search — GitHub (repositories)
agentic-search "vector database" --engine github --sort stars --language python
agentic-search "MCP server" --engine github --date-from 2025-01-01 --sort forks
# GitHub trending (query = "trending" or empty)
agentic-search "trending" --engine github --language typescript --period weekly

# Search — GitHub (code) — requires GITHUB_TOKEN
agentic-search "AsyncClient httpx" --engine github --search-type code --language python

# Search — HackerNews
agentic-search "LLM fine-tuning" --engine hackernews --min-points 100
agentic-search "MCP server" --engine hackernews --min-points 50 --min-comments 20 --date-from 2025-01-01

# Fetch
agentic-fetch "https://github.com/anthropics/anthropic-sdk-python"
agentic-fetch "https://news.ycombinator.com/item?id=12345"
agentic-fetch "https://en.wikipedia.org/wiki/Python_(programming_language)"
agentic-fetch "https://example.com" --browser          # force zendriver
agentic-fetch "https://example.com" --offset 32000     # next page
agentic-fetch "https://example.com" --selector "article.main"
agentic-fetch "https://example.com" --json             # full response with TOC
```

## API Reference

### `POST /search`

```json
{
  "query": "python asyncio",
  "max_results": 10,
  "engine": "auto"
}
```

`engine`: `"auto"` (Google → DDG fallback) | `"google"` | `"duckduckgo"` | `"reddit"` | `"github"` | `"hackernews"`

**Optional filters** (all `null` by default, engine-specific):

| Field | Type | Engines | Description |
|---|---|---|---|
| `date_from` | `YYYY-MM-DD` | google, github, hackernews | Results after this date |
| `date_to` | `YYYY-MM-DD` | google, github, hackernews | Results before this date |
| `date_preset` | `past_hour\|past_day\|past_week\|past_month\|past_year` | google | Quick preset (overrides date_from/to) |
| `sort` | string | reddit, github | Reddit: `relevance\|hot\|top\|new\|comments`; GitHub repos: `stars\|forks\|updated` |
| `time_filter` | `hour\|day\|week\|month\|year\|all` | reddit | Time window (default: `all`) |
| `subreddit` | string | reddit | Restrict to a subreddit. Also parsed from `subreddit:Name` query prefix. When no query remains, browses the listing directly (hot/new/top/rising). |
| `search_type` | `repositories\|code` | github | Search scope (default: `repositories`) |
| `language` | string | github | Language filter for search and trending |
| `period` | `daily\|weekly\|monthly` | github | Trending period (default: `daily`) |
| `min_points` | int | hackernews | Minimum points threshold |
| `min_comments` | int | hackernews | Minimum comments threshold |
| `story_type` | `story\|comment` | hackernews | Item type (default: `story`) |

**GitHub notes:**
- Set `GITHUB_TOKEN` or `AF_GITHUB_TOKEN` for higher rate limits and code search access
- `query = ""` or `query = "trending"` triggers trending repos mode; use `language` + `period` to filter
- Code search (`search_type: "code"`) requires authentication

### `POST /fetch`

```json
{
  "url": "https://example.com/article",
  "max_tokens": 8000,
  "offset": 0,
  "selector": null,
  "include_links": true,
  "include_images": false,
  "force_browser": false,
  "no_cache": false
}
```

**Response includes:**
- `markdown` — clean markdown content
- `toc` — `[{level, title, start_line, end_line}]` — use with `/fetch/lines`
- `truncated` / `next_offset` — pagination
- `code_blocks` — `{"python": 3}` — language → count
- `symbols` — backtick identifiers found in content
- `method_used` — which tier handled the request
- `cached` — whether result came from cache

### `POST /fetch/lines`

Read a specific line range from cached content (use `toc` entries from `/fetch`):

```json
{"url": "https://example.com", "start": 42, "end": 98}
```

### `POST /grep`

Regex search within cached markdown:

```json
{
  "url": "https://example.com",
  "pattern": "async def \\w+",
  "context_lines": 2,
  "ignore_case": false,
  "max_matches": 50
}
```

### `POST /fetch/batch`

Fetch up to 50 URLs concurrently. Per-URL failures are isolated — the batch
still returns 200 with partial results.

```json
{
  "urls": ["https://a.com", "https://b.com", "https://c.com"],
  "max_concurrency": 5,
  "max_tokens_per_url": 4000,
  "return_markdown": true
}
```

Set `return_markdown: false` for an index-only response (title, TOC, method,
total_lines) — useful when you just want to know what's worth reading.

### `POST /cache/search`

BM25 search across every cached markdown document in the local cache:

```json
{"query": "async def event loop", "limit": 10}
```

### `POST /cache/evict`

Drop a single cached entry by URL. Returns `{"removed": true|false}`.

### `POST /cache/prune`

Evict stale entries (older than `ttl × max_age_factor`) and optionally
LRU-trim until the cache fits under `max_mb`. Synthesis entries
(`POST /cache/write`) are never evicted.

```json
{"max_mb": 200, "max_age_factor": 4.0}
```

### `GET /health`

```json
{"status": "ok", "browser_running": true}
```

## Configuration

`config.yaml` controls content stripping without code changes:

```yaml
# Global DOM elements stripped from all pages
strip_selectors:
  - nav
  - footer
  - .cookie-banner

# Global line-level regex filters (applied after html→markdown)
strip_lines:
  - "^\\s*Subscribe"
  - "\\[Read more\\]"

# Per-domain JS injected before page scripts (paywall bypass)
init_scripts:
  wsj.com: |
    Object.defineProperty(document, 'cookie', { get: () => 'subscriber=true' });

# Per-domain overrides — merged with global list
domains:
  example.com:
    strip_selectors:
      - .sidebar
    strip_lines:
      - "Related articles"
    proxy_url: "https://some-mirror.com/"   # rewrites URL before fetch
```

Environment variables (prefix `AF_`):

| Variable | Default | Description |
|---|---|---|
| `AF_PORT` | `8000` | Server port |
| `AF_HEADLESS` | `true` | Chrome headless mode |
| `AF_CACHE_TTL` | `300` | Cache TTL in seconds (0 = disabled) |
| `AF_MAX_BROWSER_TABS` | `3` | Concurrent browser tabs |
| `AF_BROWSER_TIMEOUT` | `30.0` | Browser navigation timeout |
| `AF_HTTPX_TIMEOUT` | `10.0` | httpx request timeout |
| `AF_USER_DATA_DIR` | `/tmp/agentic-fetch-profile` | Chrome profile (persists cookies) |
| `AF_CACHE_DIR` | `/tmp/agentic-fetch-cache` | Markdown cache directory |

## Docker

```bash
docker compose up -d --build

# View browser (useful for debugging Cloudflare / login pages)
open http://localhost:6080/vnc.html
```

## Adding a Plugin

Create `src/agentic_fetch/plugins/mysite.py` — auto-discovered on startup:

```python
from .base import FetchPlugin
from ..models import FetchRequest, FetchResponse
from ..markdown import paginate

class MySitePlugin(FetchPlugin):
    name = "mysite"
    domains = ["mysite.com"]

    async def fetch(self, url: str, req: FetchRequest) -> FetchResponse | None:
        # Return None to fall through to httpx/browser tiers
        ...
        md, truncated, next_offset = paginate(content, req.offset, req.max_tokens)
        return FetchResponse(
            url=url, title="...", markdown=md,
            plugin_used=self.name, method_used="plugin",
            truncated=truncated, next_offset=next_offset if truncated else None,
        )
```

## Architecture

```
CLI / Skills
  agentic-search "query"     agentic-fetch "url"
         │ HTTP                      │ HTTP
         ▼                           ▼
     FastAPI :8000
  POST /search            POST /fetch
  POST /fetch/lines       POST /grep
  GET  /health
         │
  ┌──────┴──────────────────────────┐
  │ SearchEngine    FetchEngine      │
  │ ├─ Google       ├─ Plugin        │
  │ ├─ DuckDuckGo   ├─ httpx         │
  │ ├─ Reddit       ├─ httpx+browser │
  │ ├─ GitHub       └─ zendriver     │
  │ └─ HackerNews                    │
  │                 ├─ httpx+browser │
  │                 └─ zendriver     │
  │         BrowserPool (3 tabs)     │
  │         FetchCache (file, ETag)  │
  └──────────────────────────────────┘
```

## Development

```bash
uv run pytest tests/ -v          # run tests (no browser required for plugins)
uv run ruff check src/            # lint
uv run uvicorn agentic_fetch.main:app --reload --port 8000
```

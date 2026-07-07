# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run development server
uv run uvicorn agentic_fetch.main:app --reload --port 8000

# Run all tests
uv run pytest tests/ -v

# Run a single test file
uv run pytest tests/test_fetch.py -v

# Run a single test by name
uv run pytest tests/test_api.py::test_search_endpoint -v

# Lint
uv run ruff check src/

# Format
uv run ruff format src/

# Install CLI tools globally
uv tool install .

# Docker
docker compose up -d
# View browser (when AF_HEADLESS=false): http://localhost:6080/vnc.html
```

## Architecture

The service exposes a FastAPI HTTP API (`/search`, `/fetch`, `/fetch/batch`, `/fetch/lines`, `/grep`, `/cache/{search,write,evict,prune,index,log,health}`, `/health`) consumed by Claude Code skills via CLI wrappers (`agentic-search`, `agentic-fetch`).

### Fetch Pipeline (4-tier waterfall)

`FetchEngine` (`fetch.py`) tries each tier in order, stopping at first success:

1. **Plugin** — fast-path for known domains (no browser); returns immediately if matched
2. **httpx** — plain HTTP + readability extraction
3. **httpx + Browser** — httpx-fetched HTML loaded into browser via `data:` URL for light JS
4. **zendriver** — full Chromium headless; used when JS rendering is required

### Search Pipeline

`SearchEngine` (`search.py`) routes to one of six backends: `google`, `duckduckgo` (both via browser), `reddit` (JSON API), `github` (GraphQL/HTML), `hackernews` (Algolia API), or `auto` (tries all).

### Shared Infrastructure

- **BrowserPool** (`browser.py`) — manages a zendriver Chromium instance with a semaphore (default 3 concurrent tabs)
- **FetchCache** (`cache.py`) — file-based cache keyed by URL; supports TTL, ETag revalidation, and line-range/grep queries on cached markdown
- **MarkdownExtractor** (`markdown.py`) — readability-lxml → html-to-markdown conversion with token-aware pagination
- **SiteConfig** (`config.py`) — per-domain settings loaded from `config.yaml` (strip selectors, proxy URLs, init scripts for paywall bypass)

### Plugin System

Plugins live in `src/agentic_fetch/plugins/` and are **auto-discovered** at startup. Each plugin extends `FetchPlugin` (`plugins/base.py`) and declares `name` and `domains` (supports `fnmatch` patterns). Return `None` to fall through to the next tier.

```python
class MySitePlugin(FetchPlugin):
    name = "mysite"
    domains = ["mysite.com", "*.mysite.com"]

    async def fetch(self, url: str, req: FetchRequest) -> FetchResponse | None:
        ...
        # Return the FULL markdown — the FetchEngine caches it whole, then
        # paginates the response. Do NOT paginate inside the plugin.
        return FetchResponse(url=url, title="...", markdown=full_md,
            plugin_used=self.name, method_used="plugin")
```

Plugin responses with `error` set are returned to the caller but never cached.

Built-in plugins: `reddit`, `medium` (proxies via Freedium), `github`, `hackernews`, `wikipedia`.

## Configuration

Copy `.env.example` to `.env`. All env vars use the `AF_` prefix:

| Variable | Default | Description |
|---|---|---|
| `AF_PORT` | `8000` | Server port |
| `AF_HEADLESS` | `true` | Chrome headless mode |
| `AF_CACHE_TTL` | `300` | Cache TTL seconds (0 = disabled) |
| `AF_MAX_BROWSER_TABS` | `3` | Concurrent browser tabs |
| `AF_BROWSER_TIMEOUT` | `30.0` | zendriver navigation timeout |
| `AF_HTTPX_TIMEOUT` | `10.0` | httpx request timeout |
| `GITHUB_TOKEN` | — | GitHub API auth (also `AF_GITHUB_TOKEN`) |

`config.yaml` controls per-domain behavior without code changes: `strip_selectors`, `strip_lines` (regex), `init_scripts` (JS injected before load), and `proxy_url`.

## Key Files

- `src/agentic_fetch/main.py` — FastAPI app, lifespan, route handlers
- `src/agentic_fetch/fetch.py` — `FetchEngine` 4-tier logic
- `src/agentic_fetch/search.py` — `SearchEngine` multi-backend routing
- `src/agentic_fetch/browser.py` — `BrowserPool` zendriver lifecycle
- `src/agentic_fetch/cache.py` — `FetchCache` file cache with grep/line support
- `src/agentic_fetch/markdown.py` — HTML→markdown + `paginate()` helper
- `src/agentic_fetch/config.py` — `Settings` (env) and `SiteConfig` (yaml)
- `src/agentic_fetch/models.py` — All Pydantic request/response schemas
- `config.yaml` — Per-domain runtime configuration

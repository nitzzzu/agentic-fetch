# Ideas & Improvement Notes

A critical analysis of the codebase with actionable suggestions, grouped by priority.

---

## 🐛 Bugs / Correctness Issues

### 1. `FetchPlugin.matches()` uses `lstrip` incorrectly
`lstrip("www.")` strips individual characters `w`, `.`, `o`, not the prefix `"www."`.
`"wordpress.org".lstrip("www.")` → `"rdpress.rg"`. Use `removeprefix("www.")` (Python 3.9+).
Same problem with `lstrip("*.")`.

**File:** `plugins/base.py:19`

### 2. `FetchCache.put()` writes `.meta.json` non-atomically
The `.md` file is written atomically (`.tmp` → rename) but `.meta.json` is written directly.
If the process dies between the two writes you get an orphaned `.md` without metadata, silently skipped next read but wasting disk.
Fix: apply the same `.tmp` → rename pattern to the meta file.

**File:** `cache.py:86`

### 3. `GogGamesPlugin` is not a fast-path plugin — it calls the browser
The plugin tier is supposed to avoid the browser for known domains. `GogGamesPlugin` calls `browser_pool.get_html()`, which acquires a semaphore slot and blocks. If the browser is at capacity, this blocks the caller instead of falling through to the browser tier naturally. The plugin provides no benefit over tier 4.
Either remove the plugin and let tier 4 handle it, or convert to a pure httpx fetch.

**File:** `plugins/gog_games.py:19`

### 4. `detect_content_type` treats `.txt` and `.rst` as markdown
RST (reStructuredText) has completely different syntax. Feeding RST through the html-to-markdown pipeline produces garbage. Either drop `.rst` / `.txt` or add a plain-text passthrough path.

**File:** `config.py:95`

### 5. `_needs_js` parses HTML with BeautifulSoup a second time
`MarkdownExtractor.__init__` already parses HTML into `self.soup`. `_needs_js` creates a separate `BeautifulSoup(html)`. This is double-work for every httpx-tier page. Pass the soup or an already-stripped body count instead.

**File:** `fetch.py:166`, `markdown.py:51`

### 6. `BrowserPool._semaphore` is `None` before `start()` is called
`acquire_tab()` does `async with self._semaphore` which crashes with `TypeError` if called before startup. No guard. Add an `assert self._semaphore is not None` or raise `RuntimeError("browser not started")`.

**File:** `browser.py:76`

### 7. `paginate()` returns `len(text)` as `next_offset` when not truncated
When `truncated=False`, the returned `next_offset` equals the full text length. Callers ignore it only because they check `truncated` first — but the `FetchResponse.next_offset` field is still set to a misleading value via `next_offset if truncated else None`. No bug today because all callers check `truncated`, but confusing.

**File:** `markdown.py:221-228`

---

## 🔁 Duplication

### 8. GitHub trending is implemented twice
`plugins/github.py:_fetch_trending` and `search.py:_github_trending` scrape `github.com/trending` with identical HTML selectors, identical headers, and nearly identical markdown/result building. One is ~70 lines, the other ~45. They diverge in minor formatting. Extract a shared `_parse_trending_html(html, since)` helper.

**Files:** `plugins/github.py:56-125`, `search.py:286-358`

### 9. JSON interception handler is duplicated in `BrowserPool`
`get_html` and `execute_html` both define an identical `on_response_received` async closure (~20 lines each) with the same flat-dict expansion and `CONTENT_JSON_KEYS` check. Extract into a `_make_json_interceptor(intercepted_json, content_ready)` factory.

**File:** `browser.py:101-121`, `browser.py:173-192`

### 10. URL normalization / tracking-param stripping is duplicated
`cache.py:cache_key` and `config.py:normalize_url` both strip the same tracking params from URLs. `TRACKING_PARAMS` is defined in `cache.py` and the same set is hard-coded again in `normalize_url`. Extract to a single `normalize_url(url: str) -> str` in `config.py` and import it in `cache.py`.

**Files:** `cache.py:12-14`, `config.py:77-83`

### 11. Reddit snippet-building is duplicated
`search.py:_reddit` builds post snippets (lines 179-184, 255-263) using the same fields and format as `plugins/reddit.py:_format_post`. They diverge in minor details. The plugin version is richer. Extract a shared helper or have the search engine call the plugin's formatter for the preview.

**Files:** `search.py:179-185`, `plugins/reddit.py:57-78`

### 12. `FetchCache.put()` and `FetchCache.write()` are nearly identical
Both do: build `CacheMeta`, atomic-write `.md`, write `.meta.json`. `write()` differs only in `ttl=_SYNTHESIS_TTL` and `content_type="synthesis"`. Consolidate into one `_write(url, markdown, content_type, ttl, etag)` private method.

**File:** `cache.py:77-131`

### 13. `SiteConfig` is instantiated twice
`fetch.py:23` creates `site_config = SiteConfig(settings.config_file)` at module level, and `browser.py:BrowserPool.start()` creates `self._site_config = SiteConfig(settings.config_file)`. Both parse the same YAML file. Make `SiteConfig` a module-level singleton or pass it via dependency injection.

**Files:** `fetch.py:23`, `browser.py:50`

### 14. `cli/fetch.py` and `cli/search.py` duplicate `load_api_url` / `save_api_url`
Both CLIs define identical `load_api_url()` and `save_api_url()` functions pointing to the same `~/.agentic-fetch` file. Extract to a shared `cli/config.py` module.

**Files:** `cli/fetch.py:8-30`, `cli/search.py:12-34`

---

## ⚡ Performance

### 15. `FetchCache.metadata()` re-reads the freshly written file
After `_build_response` → `fetch_cache.put(url, md, ...)`, `_build_from_md` immediately calls `fetch_cache.metadata(url)` which reads the `.md` file again to compute TOC, code blocks, symbols and line count. This is a gratuitous re-read of content that is already in memory (`md`). Pass the markdown string directly into a `compute_metadata(md)` helper instead.

**File:** `fetch.py:250-272`, `cache.py:104-117`

### 16. `FetchCache.index()` and `search()` read every `.md` file on every call
Both methods `glob("*.meta.json")` and load every file. With hundreds of cached pages this becomes slow. Options:
- Store `title`, `word_count`, and `snippet` in `.meta.json` at write time (cheap, one-time cost).
- Use an in-memory index rebuilt on startup and updated on `put()`.

**File:** `cache.py:164-280`

### 17. Cache metadata read: 3 separate file reads for a single ETag-validated hit
`_httpx_fetch` calls `fetch_cache.get_etag(url)` (reads `.meta.json`), then if 304 `bump_ttl(url)` (reads + writes `.meta.json`), then `fetch_cache.get(url)` (reads `.meta.json` again + reads `.md`). That's 3 meta reads for a conditional-GET cache hit. Combine into one `check_etag(url) -> (etag, cached_content_or_none)` method.

**File:** `fetch.py:69-89`, `cache.py:42-75`

### 18. New `httpx.AsyncClient` per request
Every `_httpx_fetch`, `_curl_cffi_fetch`, plugin fetch, and search call creates a fresh `AsyncClient` that gets torn down immediately. TCP connection pooling is wasted. Use a module-level long-lived client (or lifespan-managed) with appropriate limits.

**Files:** `fetch.py:190`, `search.py:139`, `plugins/github.py:128`, etc.

### 19. `BrowserPool.acquire_tab` has no timeout
Requests queue indefinitely on the semaphore if all browser tabs are occupied by slow pages. Add `asyncio.wait_for(sem.acquire(), timeout=...)` to surface back-pressure as a proper error.

**File:** `browser.py:75`

---

## 🏗️ Architecture / Design

### 20. `FetchEngine` and `SearchEngine` are stateless — they don't need to be classes
Both are instantiated once as module-level singletons (`fetch_engine`, `search_engine`). They hold no instance state. They could be plain async functions or at minimum documented as singletons. The class adds an unnecessary layer and makes testing harder.

**Files:** `fetch.py:26-280`, `search.py:58-581`

### 21. Silent exception swallowing hides real bugs
Multiple places catch `Exception` and silently `pass`:
- Plugin failures in `fetch.py:62` — a syntax error in a plugin is indistinguishable from "plugin returned None".
- httpx tier in `fetch.py:104` — network errors and parse errors are all swallowed.
- `browser.py` has several `except Exception: pass` blocks.

At minimum, these should log at `DEBUG` or `WARNING` level. Consider adding a structured logger (stdlib `logging` is fine) so failures are observable in production.

### 22. The `engine="cache"` search option is undocumented and hidden
`SearchEngine._cache_search` wraps `FetchCache.search()` (BM25) but is not mentioned in the README, not listed in the CLI `--engine` choices, and the standalone `FetchCache.search()` / `/cache/search` endpoint doesn't exist. Either surface it properly or remove it.

**Files:** `search.py:534-542`, `cli/search.py:64`, `README.md`

### 23. `FetchResponse.method_used` is inaccurate for cache hits
When serving from cache, the response always says `method_used="httpx"` regardless of whether the original fetch used the browser or a plugin. Either store the original method in the cache metadata and replay it, or add a `cached_method` field.

**File:** `fetch.py:39`, `fetch.py:80`

### 24. `MediumPlugin` and `config.yaml` domains partially overlap
`config.yaml` lists `medium.com` with `strip_lines` and `proxy_url`. The plugin handles medium.com entirely in code with its own stripping logic. The config.yaml `proxy_url` for medium.com is never reached because the plugin exits before the httpx tier. The config.yaml `strip_lines` for medium.com are also never applied. These config entries are dead. Either remove the plugin and rely on the config `proxy_url` path, or remove the config entries.

**Files:** `plugins/medium.py`, `config.yaml:37-44`

### 25. Missing `/cache/search` API endpoint
`FetchCache.search()` implements BM25 over all cached documents — a useful capability for Claude skills to do cross-document search. It's wired through `engine="cache"` in search but there's no direct REST endpoint. Add `POST /cache/search` with `query` + optional `limit`.

**File:** `main.py`

### 26. Unbounded fetch log
`_log.jsonl` is append-only with no rotation or pruning. A long-running instance will accumulate logs indefinitely. Add a max-size cap or rotate after N lines in `log_fetch()`.

**File:** `cache.py:133-144`

### 27. The `markdownify` dependency is listed but never used
`pyproject.toml` lists `markdownify>=0.13` as a dependency. No import of `markdownify` exists in any source file. Only `html_to_markdown` is used. Remove the unused dependency.

**File:** `pyproject.toml:14`

### 28. `browser.py` `execute_html` uses a different, shorter blocked-URL list than `get_html`
`get_html` blocks ads, images, and fonts (12 patterns). `execute_html` blocks only 3 ad patterns. This inconsistency means Tier 3 (httpx+browser) may load images/fonts that Tier 4 blocks, making the two tiers behave differently for the same HTML.

**File:** `browser.py:94`, `browser.py:169`

---

## 🛠️ Simplification Opportunities

### 29. `FetchCache.get_etag()` parses `meta.json` just to return one field
Three methods (`get_etag`, `bump_ttl`, `get`) all independently load and parse the same `.meta.json`. A `_load_meta(url) -> CacheMeta | None` helper called once would reduce repetition.

**File:** `cache.py:42-75`

### 30. `_CHALLENGE_SIGNALS` list could be a frozenset
It's iterated with `any(sig in sample for sig in _CHALLENGE_SIGNALS)`. A `frozenset` + `any(sig in sample for sig in SIGNALS)` is fine, but for substring-in-string checks a joined regex like `re.search(pattern, sample)` would be faster for a growing list.

**File:** `fetch.py:10-21`

### 31. `FetchCache.index()` computes title/snippet in Python — store them at write time instead
The `index()` method scans up to 15 lines looking for an H1 heading and builds a word snippet on every call. Since titles don't change after caching, store them in `.meta.json` during `put()`. The `metadata()` call in `_build_from_md` already has the title; thread it through.

**File:** `cache.py:164-202`

### 32. `_json_to_markdown` only processes the first intercepted JSON response
`intercepted_json[0]` is used in both Tier 3 and Tier 4. Multiple JSON responses may be intercepted; taking the first isn't necessarily the best. Consider scoring by content key presence and length.

**File:** `fetch.py:132`, `fetch.py:151`

### 33. `HackerNewsPlugin._format_comments` and `RedditPlugin._format_comments` use the same mutable-closure anti-pattern
Both use `count = [0]` to get a mutable counter inside a nested `recurse` function. Python 3.10+ `nonlocal count` or a simple iterative DFS would be cleaner.

**Files:** `plugins/hackernews.py:90-113`, `plugins/reddit.py:80-113`

### 34. `config.yaml` `init_scripts` section is redundant with `domains[x].init_script`
The top-level `init_scripts` dict and the per-domain `init_script` key in `domains` serve the same purpose. `SiteConfig.init_script_for` checks both, with per-domain taking priority. This dual path is confusing. Use only `domains[x].init_script`.

**File:** `config.py:69-73`, `config.yaml:29-34`

---

## 🔒 Reliability / Robustness

### 35. `FetchEngine.fetch()` falls to Tier 4 even when the browser isn't running
If `browser_pool.start()` failed silently (or hasn't been called), Tier 4 (`browser_pool.get_html`) will crash with an obscure `AttributeError` or `NoneType` error. Check `browser_pool.is_running` before attempting Tier 3/4 and return a useful error.

**File:** `fetch.py:148`

### 36. `BrowserPool.is_running` is not a real health check
It returns `self._browser is not None`. If the underlying Chromium process dies, `self._browser` is still set. A proper check would ping the browser (e.g., a `cdp.browser.get_version()` call).

**File:** `browser.py:71`

### 37. No retry on Tier 2 httpx failures
Transient network errors (TCP reset, DNS blip) on the httpx tier immediately fall through to the browser. A single retry with exponential backoff on `httpx.RequestError` would recover most flakiness without touching the browser.

### 38. `fake_user_agent` is a hardcoded Chrome 132 string
Chrome 132 is from early 2025. By mid-2026 many sites may already fingerprint this. Make the version configurable or randomly sample from a short list of recent Chrome versions. Alternatively, since the browser tier uses a real Chromium with its own UA, only the httpx tier's UA matters — keep it easy to update via `AF_FAKE_USER_AGENT`.

**File:** `config.py:17-21`

---

## 🧪 Testing Gaps

### 39. No tests for `FetchEngine` fetch pipeline logic
There are tests for plugins, cache, and markdown individually, but no tests that exercise `FetchEngine.fetch()` with mocked httpx responses to verify the tier waterfall logic (e.g., "plugin throws → falls to httpx", "challenge page detected → skips to curl_cffi").

### 40. `test_api_live.py` hits real external APIs
Live tests are fragile in CI. They should either be skipped unless an environment variable `AF_LIVE_TESTS=1` is set, or converted to use `respx` mocks.

### 41. No test for `cache_key` URL normalization edge cases
The 16-character SHA-256 truncation gives 64 bits of hash space. With thousands of URLs, collision probability is negligible, but the truncation is worth documenting and testing with known tracking-param pairs.

---

## 💡 Feature Ideas

### 42. Expose `method_used` and timing in cache metadata
Storing which tier resolved a fetch (and how long it took) would help tune the tier waterfall. With this data it becomes easy to identify sites where Tier 2 always fails and a plugin should be written.

### 43. Add `POST /cache/evict` endpoint
There's no way to delete a specific cached entry via the API. A CLI or skill can't force a re-fetch of a stale page without `no_cache=true`. An explicit evict endpoint would be useful.

### 44. Add a `subreddit` field to `SearchResult` / normalize Reddit result URLs
Reddit search results come back with full `https://www.reddit.com/r/.../comments/...` URLs. Skills often need just the subreddit. Store it in `snippet` (already done) but also consider a structured metadata field in the response.

### 45. DuckDuckGo Lite for the DDG search backend
The current DDG implementation fetches `duckduckgo.com/?q=...&ia=web` via the browser (zendriver). DuckDuckGo has a lite HTML endpoint (`https://html.duckduckgo.com/html/?q=...`) that works with plain httpx, has no JS, and is scrape-friendly. This would make DDG search not require the browser at all.

### 46. Streaming response for large fetches
Large pages (100k+ tokens) currently require a full fetch + pagination. A `text/event-stream` response from `/fetch` that streams markdown chunks as they're extracted would let skills start processing before the full page arrives.

### 47. Plugin registry via entry points
Currently plugins must live in `src/agentic_fetch/plugins/`. Support third-party plugins installed as Python packages via `importlib.metadata.entry_points(group="agentic_fetch.plugins")`. This would let external packages add domain support without forking.

### 48. Cache eviction / LRU pruning
The cache grows without bound. Add a background task (or on-demand `/cache/prune`) that deletes stale entries older than N × TTL and caps total cache size at a configurable limit (e.g., `AF_CACHE_MAX_MB`).

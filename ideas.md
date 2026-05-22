# Ideas & Improvement Notes

A living roadmap. The "Resolved" section lists what landed in the current
cleanup pass; everything below is still open, with crazy-disruptive ideas at
the bottom.

---

## ✅ Resolved in the cleanup pass

Bug fixes
- `lstrip("www.")` → `removeprefix("www.")` everywhere (plugin/base, browser,
  config). The old code stripped any combination of `w`, `o`, `.` characters,
  so `wordpress.org` matched as `rdpress.rg`.
- `.meta.json` is now written atomically via `_atomic_write` (`.tmp` → rename),
  matching the existing `.md` flow.
- `detect_content_type` no longer treats `.rst`/`.txt` as markdown — they
  return `"plain"` and skip the html-to-markdown pipeline that would garble
  them.
- `BrowserPool.acquire_tab()` checks the semaphore/browser are initialized and
  surfaces a clean `RuntimeError("BrowserPool not started")` instead of an
  obscure `TypeError`.
- `BrowserPool.acquire_tab()` has a 60s timeout, so a saturated pool surfaces
  back-pressure as an error rather than queuing indefinitely.
- Tier 3 / Tier 4 gracefully return an error response when the browser pool
  isn't running, instead of crashing with `AttributeError`.

Duplication
- `TRACKING_PARAMS` moved to `config.py` and imported by `cache.py` (also
  expanded to cover `msclkid`, `yclid`, `mc_cid`, `mc_eid`, etc).
- `SiteConfig` is now a module-level singleton in `config.py`; both
  `browser.py` and `fetch.py` import it.
- `FetchCache.put()` and `FetchCache.write()` share a private `_write()` so
  metadata fields stay in sync.
- A new `_load_meta()` helper replaces three near-identical `meta.json`
  parses (`get`, `get_etag`, `bump_ttl`, `metadata`).
- `BrowserPool._make_json_interceptor()` replaces the duplicated handler in
  `get_html` and `execute_html`. Both tiers also share the same block list now.
- CLI `load_api_url` / `save_api_url` extracted to `cli/_config.py`. The CLI
  also honours the `AGENTIC_FETCH_URL` env var.

Performance
- A single `httpx.AsyncClient` per event loop is reused across every plugin,
  search backend, and the fetch engine. No more TCP/TLS handshake per request.
- Markdown metadata (title, line count, TOC, code-blocks, symbols) is
  computed once at write time and stored in `meta.json`. Read paths
  (`metadata`, `index`, `search`, cache-hit responses) no longer rescan the
  `.md` file.
- Cache `index()` and `search()` use the precomputed title instead of
  re-scanning the first 15 lines of every `.md`.
- `_CHALLENGE_SIGNALS` is a `frozenset`.
- The fetch log auto-rotates: keeps the last 5000 lines once the file passes
  ~4 MB.

Architecture / observability
- Silent `except Exception: pass` blocks replaced with `logging` calls at the
  appropriate level (DEBUG for benign tier fallthroughs, WARNING for plugin
  failures and partial-batch errors).
- `FetchResponse.method_used` is now replayed from cache metadata, so a hit
  reports the original tier (plugin / zendriver / etc) instead of always
  "httpx".
- `FetchResponse.title` survives cache hits via the precomputed title.
- `markdownify` removed from dependencies — it was never imported.
- `config.yaml` top-level `init_scripts:` deprecated in favour of
  `domains[x].init_script`. Both still load.

New endpoints / features
- `POST /fetch/batch` — concurrent multi-URL fetcher with a configurable
  semaphore. Per-URL failures are isolated so a flaky URL never poisons the
  batch.
- `POST /cache/evict` — drop a single cached entry by URL.
- `POST /cache/prune` — age-based eviction + LRU trim to a size cap. Honours
  synthesis entries (never evicted).
- `POST /cache/search` — BM25 over every cached markdown file, surfaced as
  a first-class endpoint (previously only available indirectly via
  `engine="cache"` on `/search`).
- DuckDuckGo Lite path — `_ddg_lite()` hits `html.duckduckgo.com/html/` with
  plain httpx and unwraps `uddg=…` redirect URLs. Falls back to the
  browser-rendered DDG only if Lite fails. Big win when the browser pool is
  cold.
- CLI gained `--engine cache` for searching the local index.

Tests / hygiene
- New `tests/test_new_features.py` covers batch fetch (success, partial
  failure, return-markdown-false), cache evict/prune/search endpoints,
  precomputed metadata round-trip, DDG-lite parser, and method replay.
- Lint: ruff passes (5 auto-fixed, 2 manual fixes for ambiguous `l` variable
  and a missing `TYPE_CHECKING` import in `plugins/base.py`).

---

## 🔍 Still open — high signal

### `FetchCache.get_etag` could be folded into a single check
Three reads of `meta.json` happen for a 304 hit (`get_etag` → `bump_ttl` →
`get`). The new `_load_meta()` helper makes this easier — a
`check_etag(url) -> (etag, cached) | None` method would let the fetch engine
do one round-trip.

### Tier 2 httpx has no retry
A single TCP reset / DNS blip drops us into curl_cffi or the browser. A
single exponential-backoff retry on `httpx.RequestError` (not `HTTPStatusError`)
would absorb most flakiness without burning a browser tab.

### `BrowserPool.is_running` is a shallow health check
Only checks `self._browser is not None`. If the Chromium process dies, this
still returns `True`. A periodic ping via `cdp.browser.get_version()` would
catch zombie state.

### `_curl_cffi_fetch` swallows ImportError silently
If `curl_cffi` isn't installed, the tier falls through without any visible
signal. A one-time WARN at startup would help users debug.

### `GogGamesPlugin` still calls the browser inside the plugin tier
It acquires a semaphore slot from inside the plugin tier, which defeats the
"fast path" promise. Either convert to a curl_cffi fetch with the existing
DOM-extraction logic, or remove the plugin and rely on tier 4 (losing the
curated download-link extraction).

### Reddit snippet building still duplicated
`search.py:_reddit` builds preview snippets in two places (subreddit-listing
and search). The plugin's `_format_post` is richer — search results could
call into a shared `_reddit_card(post)` helper.

### GitHub trending logic still appears twice
`plugins/github.py:_fetch_trending` and `search.py:_github_trending` use the
same selectors. A shared `_parse_trending_html(html, since)` would let one
fix benefit both.

### `_json_to_markdown` only inspects `intercepted_json[0]`
If multiple JSON responses contain `content` / `body` / `text`, we always
take the first one. A trivial "score by total string length of known keys"
would beat first-come-first-serve in noisy SPAs.

### `fake_user_agent` is a hardcoded Chrome 132 string
By the time this matters, Chrome 132 will read as a bot. Either rotate
across a small list at startup, or expose `AF_FAKE_USER_AGENT` for ops
override.

---

## 🚀 Disruptive ideas worth shipping next

### Embedding-based semantic cache search
BM25 finds keyword overlap. An embeddings index (sentence-transformers
locally, or a cheap API embedding) over chunks of each cached `.md` would
let `/cache/search` answer "what have I read about X" with semantic recall.
Bonus: per-result chunk pointers so callers can `fetch/lines` straight to
the relevant section.

### `POST /fetch/diff`
Re-fetch a URL bypassing the cache, then diff the new markdown against the
cached copy. Returns added/removed line ranges and a one-line summary. Lets
agents track "has this page changed since I read it" without dragging the
full text through context twice.

### `POST /fetch/stream` (Server-Sent Events)
Pages over 100k tokens block on the full conversion. Streaming markdown
chunks as readability emits them lets a downstream LLM start processing the
first chunk before the page is fully fetched.

### Recipe replay
After a `force_browser` + `selector` combo extracts an article cleanly,
store the recipe (`{domain, selector, strip_selectors, init_script}`) into
`config.yaml` automatically. Next visit auto-uses it. Effectively
self-tuning per-domain config.

### Auto-pin "important" URLs
The fetch log already records what's been fetched. A weekly background pass
could promote frequently-revisited URLs to synthesis (never-expire) entries
to dodge cache misses.

### `robots.txt` + sitemap awareness
Look up `/robots.txt` once per domain (cached) and respect crawl-delay /
disallow. Read `sitemap.xml` to bulk-prime the cache for documentation
domains — feed the URLs into `/fetch/batch` once and have an entire docs
site indexed for `/cache/search`.

### Plugin entry-point discovery
Currently plugins must live in `src/agentic_fetch/plugins/`. Loading them
via `importlib.metadata.entry_points(group="agentic_fetch.plugins")` would
let users `pip install agentic-fetch-substack` without forking.

### Multi-step "agent" recipes
A new `POST /fetch/action` endpoint accepts a small DSL: navigate, click,
type, wait-for-selector, extract. Lets agents handle login flows, paginated
SPAs, and "view full thread" expanders without writing per-site code.

### Per-domain freshness scoring
Track `bump_ttl` and `If-None-Match` hit rates per domain. Auto-extend TTL
for sites that never change (Wikipedia, RFCs) and shorten it for sites that
change every visit (HN front page, news homepages).

### Headless dashboard at `/`
A tiny HTML page listing the cache index, recent fetches, BM25 search box,
and live `/cache/health` stats. Optional — but very useful when debugging
cache decisions.

---

## 🔒 Reliability / robustness — still open

- `httpx_timeout` (10s) is global. Long PDFs or large repos sometimes need
  more. Either bump the default or add `req.timeout`.
- `paginate()` returns `len(text)` as `next_offset` when not truncated.
  Callers all guard with `truncated` first, but it's confusing — return
  `None`.
- `test_api_live.py` hits real services. It should default to skipped
  unless `AF_LIVE_TESTS=1` is set.
- No tests for the tier waterfall itself (plugin throws → falls to httpx,
  challenge page → curl_cffi, etc). `FetchEngine` is testable now that
  `get_client` is patchable — worth adding.

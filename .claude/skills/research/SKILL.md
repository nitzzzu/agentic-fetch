---
name: research
description: Research a topic, library, codebase, or question using the local agentic-fetch service. Use this skill any time the task requires reading more than one URL, searching documentation, comparing sources, or building an answer from web content. Beats raw WebFetch when you need parallelism, persistent caching, BM25 search across what you've already read, or targeted line/grep access to long pages.
---

# research

An optimized workflow for deep research using the local **agentic-fetch** service (`http://localhost:8000` by default, or `$AGENTIC_FETCH_URL`).

The service exposes five powerful primitives that work best when combined:

| Use this | When you need |
|---|---|
| `/search` | Find candidate URLs (Google, DDG-lite, Reddit, GitHub, HackerNews) |
| `/fetch/batch` | Pull many URLs in parallel, cache them all at once |
| `/cache/search` | BM25 across everything you've fetched — *don't re-fetch* |
| `/fetch/lines` + `/grep` | Surgical reads into long cached pages |
| `/fetch` | Single URL when you don't already have it |

## Step 0 — Confirm the service is up

```bash
BASE="${AGENTIC_FETCH_URL:-http://localhost:8000}"
curl -sf "$BASE/health" | jq .
```

If unreachable, tell the user to run `uv run uvicorn agentic_fetch.main:app --port 8000` (or `docker compose up -d`). Don't try to fetch URLs by other means — the cache is the whole point.

## Step 1 — Search to discover URLs

Prefer specific engines over `auto` when the topic suggests one:

```bash
# Library / API docs, blog posts → Google (with date filter if recency matters)
curl -sf -X POST "$BASE/search" -H 'Content-Type: application/json' -d '{
  "query": "fastapi lifespan example",
  "engine": "google",
  "max_results": 10,
  "date_preset": "past_year"
}' | jq -r '.results[] | "\(.title)\n  \(.url)\n  \(.snippet)\n"'

# Code / repos → GitHub
curl -sf -X POST "$BASE/search" -d '{"query":"agentic search","engine":"github","sort":"stars","language":"python"}' \
  -H 'Content-Type: application/json' | jq '.results'

# Community opinion → Reddit / HackerNews
curl -sf -X POST "$BASE/search" -d '{"query":"vector DB comparison","engine":"hackernews","min_points":50}' \
  -H 'Content-Type: application/json' | jq '.results'

# Already fetched this stuff before? Search local cache first — costs nothing
curl -sf -X POST "$BASE/cache/search" -d '{"query":"vector db comparison","limit":10}' \
  -H 'Content-Type: application/json' | jq .
```

**Optimization:** before running any web search, hit `/cache/search` first. If you find ≥3 strong matches (`score > 2.0`), you may not need to fetch anything new.

## Step 2 — Batch-fetch candidate URLs (the killer feature)

Once you have 5–50 URLs, **never** fetch them one at a time. Use the batch endpoint:

```bash
curl -sf -X POST "$BASE/fetch/batch" -H 'Content-Type: application/json' -d '{
  "urls": [
    "https://fastapi.tiangolo.com/advanced/events/",
    "https://www.starlette.io/lifespan/",
    "https://github.com/encode/starlette/blob/master/docs/lifespan.md"
  ],
  "max_concurrency": 5,
  "max_tokens_per_url": 4000,
  "return_markdown": false
}' | jq '.results[] | {url, ok, title, total_lines, method_used, toc_count: (.toc | length)}'
```

`return_markdown: false` is the trick: it gives you titles, TOCs, line counts, and which tier resolved each URL — without spending tokens on the full markdown. Use the output to decide which 2–3 URLs deserve a full read.

**Budgeting:** `max_concurrency` defaults to 5 — fine for most cases. Bump to 10–15 when fetching many small known-fast sites (HN comments, raw GitHub files). Leave at 5 when JS-heavy sites are likely (browser pool only has 3 tabs).

## Step 3 — Triage with TOC, deep-read with /fetch/lines

After batch fetch, you have TOCs in `result.toc[]` with `start_line` / `end_line`. Read only the sections you need:

```bash
# Example: jump straight to the "Lifespan events" section of a long doc
curl -sf -X POST "$BASE/fetch/lines" -H 'Content-Type: application/json' -d '{
  "url": "https://fastapi.tiangolo.com/advanced/events/",
  "start": 42,
  "end": 110
}' | jq -r .content
```

For pattern matching inside cached content (e.g. "find every `async def` in this page"), use `/grep` — it returns context lines like `grep -n -C2`:

```bash
curl -sf -X POST "$BASE/grep" -H 'Content-Type: application/json' -d '{
  "url": "https://fastapi.tiangolo.com/advanced/events/",
  "pattern": "async def \\w+",
  "context_lines": 2,
  "ignore_case": false
}' | jq -r .result
```

## Step 4 — Re-query the cache instead of re-fetching

Every page you fetched is now indexed. To answer follow-up questions about earlier reading, search the cache:

```bash
curl -sf -X POST "$BASE/cache/search" -d '{"query":"shutdown hook teardown","limit":5}' \
  -H 'Content-Type: application/json' | jq '.[] | {title, url, score, snippet}'
```

Then `/fetch/lines` into the top hit. **This is free, instant, and doesn't burn the network or the browser pool.**

## Step 5 — Pin synthesis, prune junk

When you've assembled an answer worth keeping, file it permanently:

```bash
curl -sf -X POST "$BASE/cache/write" -H 'Content-Type: application/json' -d '{
  "url": "synthesis://fastapi-lifespan-2026",
  "markdown": "# FastAPI lifespan notes\n\n..."
}'
```

Synthesis entries never expire and stay searchable via `/cache/search`.

Drop a stale entry when you know it's wrong / outdated:

```bash
curl -sf -X POST "$BASE/cache/evict" -d '{"url":"https://stale.example.com/old"}' \
  -H 'Content-Type: application/json'
```

At end of a long research session, trim:

```bash
curl -sf -X POST "$BASE/cache/prune" -d '{"max_mb": 200, "max_age_factor": 4.0}' \
  -H 'Content-Type: application/json'
```

## Recipes

### "Research X and give me a summary"

```
1. /cache/search "X"           → if score>2.0 hits exist, skip to step 4
2. /search engine=auto         → collect 8–15 candidate URLs
3. /fetch/batch return_markdown=false  → triage by title/TOC
4. /fetch/lines on the 2–3 best  OR  /cache/search to pull existing context
5. Synthesize → optionally /cache/write the result
```

### "Index a docs site"

```
1. /fetch on the docs homepage; read its TOC for sub-page links
2. /fetch/batch with return_markdown=false on all sub-pages (concurrency 10)
3. From now on use /cache/search instead of re-fetching
```

### "Compare 3 libraries"

```
1. /search engine=github sort=stars for each → 3 repo URLs
2. /fetch/batch on all three repo URLs at once  (the github plugin handles them)
3. /cache/search "performance" → cross-cuts all three READMEs
```

### "What changed since last time?"

There's no `/fetch/diff` yet — for now: `/fetch` with `no_cache=true`, then ask the cache for the previous version via the file path under `$AF_CACHE_DIR`. (This is on the roadmap in `ideas.md`.)

## Performance rules of thumb

- **Never** loop calling `/fetch` over a URL list. Always `/fetch/batch`.
- **Never** re-fetch a URL just to grep it. Use `/grep` against the cached copy.
- **Always** check `/cache/search` before `/search` — local BM25 is free.
- Set `max_tokens_per_url` to ~2000–4000 in batch calls; raise only for the few URLs you actually want full text from.
- Use `return_markdown: false` for triage passes (saves 10–100× on response size).
- `force_browser: true` only when a site is known to need JS — it's 10–50× slower than the httpx tier.

## Common pitfalls

- `engine=auto` falls back from Google → DDG-lite. If both fail, results will be empty and the response's `error` field explains why (never a raise). Always check `len(results)` and `.error`.
- `/fetch/lines` and `/grep` require the URL to already be in cache. If it isn't, you get 404 — run `/fetch` first.
- An invalid `/grep` regex returns **400** with the compile error — fix the pattern, don't retry.
- Bad inputs (non-http URL, `max_results` outside 1–50, malformed dates, `end < start`) return **422** with field details.
- The browser pool has 3 tabs by default. Setting `max_concurrency > 3` is fine for httpx-tier fetches but won't speed up zendriver-tier ones.
- `/fetch/batch` dedupes repeated URLs, so `total` in the response can be lower than the number you sent.
- A `method_used` of `"plugin"` in a result means a fast-path was hit (Reddit, GitHub, HN, Wikipedia, Medium-via-Freedium). These never touch the browser. The cache always stores the *full* document even when the response is truncated — paginate with `offset`, or `/grep` the rest.
- `GET /health` now reports `plugins` and `cache` stats — one call tells you what fast-paths exist and how warm the cache is.

## When *not* to use this skill

- Single URL, one-shot, won't revisit → plain `WebFetch` is fine.
- Hitting a site that requires login / 2FA → use the VNC view (`http://localhost:6080/vnc.html`) to authenticate the persistent profile, then come back here.

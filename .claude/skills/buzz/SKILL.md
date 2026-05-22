---
name: buzz
description: Take the community pulse on a topic, library, or trend by aggregating Reddit + HackerNews + GitHub trending via the local agentic-fetch service. Use this when the user asks "what are people saying about X", "is X getting popular", "what's hot in <domain> right now", "should I bet on X", "find me good discussions about X", or wants to track how sentiment / attention is changing over time. Different from the `research` skill: that one extracts facts, this one surfaces opinions, signals, and momentum.
---

# buzz

Aggregate community signal from the three places developers actually talk:

| Source | Best for | Endpoint |
|---|---|---|
| **HackerNews** | Tech launches, industry debates, hot takes from builders | `/search engine=hackernews` |
| **Reddit** | Long-form discussion, sentiment, real-world experience | `/search engine=reddit` |
| **GitHub trending** | What people are actually building / starring this week | `/search engine=github` (trending mode) |
| **Local cache** | Has buzz on this topic moved since last time we looked? | `/cache/search` |

The local agentic-fetch service runs at `${AGENTIC_FETCH_URL:-http://localhost:8000}`. Confirm it's up with `curl -sf $BASE/health` before starting; if down, follow the `research` skill's setup notes.

## Step 1 — Pulse check (the default move)

For any "what are people saying about X" question, fan out three searches **in parallel** and merge. Use Bash with `&` to dispatch:

```bash
BASE="${AGENTIC_FETCH_URL:-http://localhost:8000}"
Q="vector databases"

# All three calls fire concurrently
curl -sf -X POST "$BASE/search" -H 'Content-Type: application/json' \
  -d "{\"query\":\"$Q\",\"engine\":\"hackernews\",\"min_points\":50,\"max_results\":15}" > /tmp/hn.json &

curl -sf -X POST "$BASE/search" -H 'Content-Type: application/json' \
  -d "{\"query\":\"$Q\",\"engine\":\"reddit\",\"sort\":\"top\",\"time_filter\":\"month\",\"max_results\":15}" > /tmp/rd.json &

curl -sf -X POST "$BASE/search" -H 'Content-Type: application/json' \
  -d "{\"query\":\"$Q\",\"engine\":\"github\",\"sort\":\"stars\",\"date_from\":\"2026-01-01\",\"max_results\":10}" > /tmp/gh.json &
wait

jq -r '.results[] | "HN \(.title) — \(.url)\n   \(.snippet)\n"' /tmp/hn.json
jq -r '.results[] | "RD \(.title) — \(.url)\n   \(.snippet)\n"' /tmp/rd.json
jq -r '.results[] | "GH \(.title) — \(.url)\n   \(.snippet)\n"' /tmp/gh.json
```

This gives ~40 candidate signals across three communities in ~2 seconds.

## Step 2 — Quantify the buzz, don't just list it

Raw result counts mean nothing. Compute these numbers from the responses:

- **Engagement-weighted score:** HN snippet has `"123 pts · 87 comments"` — sum points + 2× comments across the top 10 results. Compare to a baseline topic (e.g. "kubernetes") to know if "viral" or "niche".
- **Velocity:** Reddit snippet has `"2026-05-15 · 480 pts"` — count posts in the last 7 days vs. previous 7. Big swing = the topic is moving.
- **Builder energy:** Number of GitHub repos created in the last 90 days mentioning the topic. High count + low average stars = early; low count + high stars = consolidated.

Report these as a small table to the user, not as prose. Three numbers beat three paragraphs.

## Step 3 — Dive into the highest-signal threads

The top 2–3 results by score will have the real discussion. Use **`/fetch/batch`** to pull all of them at once (the Reddit + HackerNews plugins format comment trees beautifully — no JS needed):

```bash
curl -sf -X POST "$BASE/fetch/batch" -H 'Content-Type: application/json' -d '{
  "urls": [
    "https://news.ycombinator.com/item?id=42123456",
    "https://www.reddit.com/r/MachineLearning/comments/.../",
    "https://news.ycombinator.com/item?id=42987654"
  ],
  "max_concurrency": 5,
  "max_tokens_per_url": 6000
}' | jq -r '.results[] | "\n=== \(.title) ===\n\(.markdown)\n"'
```

`max_tokens_per_url` ~6000 here because comment threads are dense; you want enough to see the top-level replies plus a few nested ones.

## Step 4 — Snapshot the buzz for later diffing

This is the killer use of `/cache/write`. After a buzz check, file a synthesis entry so next week you can answer "how has the conversation about X changed since May?":

```bash
DATE=$(date +%Y-%m-%d)
SYNTH="synthesis://buzz/vector-databases/$DATE"
SUMMARY="# Buzz: vector databases ($DATE)\n\n## HN top threads\n..."

curl -sf -X POST "$BASE/cache/write" -H 'Content-Type: application/json' \
  -d "{\"url\":\"$SYNTH\",\"markdown\":\"$SUMMARY\"}"
```

Then later:

```bash
# What did we say about this topic in the past?
curl -sf -X POST "$BASE/cache/search" \
  -d '{"query":"buzz vector databases","limit":20}' \
  -H 'Content-Type: application/json' | jq '.[] | {url, score, snippet}'
```

The URLs use `synthesis://` to make snapshots easy to filter — they'll never collide with real web URLs, and they never expire.

## Step 5 — Find subreddits / hashtags worth subscribing to

When the user wants ongoing monitoring (not a one-shot), surface the high-signal subreddits with `subreddit:Name` syntax:

```bash
# Browse a subreddit directly (no query)
curl -sf -X POST "$BASE/search" -d '{
  "query": "subreddit:LocalLLaMA",
  "engine": "reddit", "sort": "hot", "max_results": 20
}' -H 'Content-Type: application/json' | jq '.results[] | {title, url, snippet}'

# Or get the daily GitHub trending in a language
curl -sf -X POST "$BASE/search" -d '{
  "query": "trending", "engine": "github",
  "language": "python", "period": "weekly", "max_results": 25
}' -H 'Content-Type: application/json' | jq '.results'
```

Tell the user the subreddit names + the curl snippet so they can re-run themselves.

## Recipes

### "What are people saying about <X>?"

```
1. Three-way fan-out: HN min_points=50, Reddit sort=top time=month, GH stars + date filter
2. Sort the merged list by engagement score; show top 8 with one-line summaries
3. /fetch/batch the top 2–3 threads → quote 3–5 representative comments
4. /cache/write a synthesis snapshot dated today
```

### "Is <X> getting more or less popular?"

```
1. /cache/search "buzz <X>" → look for prior snapshots
2. Run the pulse-check workflow (step 1)
3. Diff today's engagement-weighted score vs. the most recent snapshot
4. Report direction + magnitude ("3× more HN attention, Reddit flat, GH starring trend up")
```

### "What's hot in <domain> right now?"

```
1. /search engine=github "trending" --period=weekly --language=<inferred from domain>
2. /search engine=hackernews date_from=<7 days ago> sort by points
3. For r/<top subreddits in the domain>: /search subreddit:Name --sort=hot
4. Merge → highlight repos / threads that show up in multiple sources (cross-signal)
```

### "Find good discussions about <X>"

```
1. /search engine=reddit sort=top time_filter=year max_results=30  (long-form > short-form here)
2. Filter to results with comments > 50 (signal of real debate)
3. /fetch/batch the top 5 → return the comment-tree markdown
4. The reddit plugin handles comment threading, OP badges, mod markers — no extra work
```

## Heuristics that matter

- **HN signal floor: `min_points >= 50`.** Below that is mostly noise / new-submissions.
- **Reddit signal: prefer `sort=top time_filter=month` over `hot`.** Hot is recency-biased; top with a time window finds posts that actually stuck.
- **GitHub trending is daily by default.** Use `period=weekly` for stable signal, `monthly` for "what's actually being maintained".
- **Comment count > vote count for finding debate.** A 500-point post with 10 comments is broadcast; a 200-point post with 300 comments is conversation.
- **The Reddit plugin's `_format_comments` already structures threads with `> ` blockquotes and OP/MOD badges.** Don't re-parse — trust the markdown it returns.
- **Use `subreddit:Name` prefix in the query** when scoping to a community; the plugin parses it.

## Cross-skill workflow

Buzz tells you **what** to look at; the `research` skill tells you **what it means**.

A common chain: `buzz` finds a hot thread → `research` extracts the actual facts → both write synthesis entries to the cache → future queries hit both via `/cache/search`.

## Pitfalls

- Reddit rate-limits hard. If you get a 429 in the response (`.error` field will say so), wait 5–10 seconds and retry — don't hammer.
- GitHub code search needs `GITHUB_TOKEN`. Trending and repo search don't, but rate limits are much tighter (60/hr) without a token.
- HN's Algolia API ranks by relevance, **not** points, even when you sort. Always apply `min_points` to filter signal.
- "Buzz" ≠ "good". The same workflow finds drama, hype cycles, and FUD. Sample dissenting threads, not just the top-voted one.

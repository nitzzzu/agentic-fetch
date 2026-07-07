# Roadmap v2 — 30 New Ideas & Improvements

Thirty new ideas for making agentic-fetch the best web-access layer an AI agent
can have. Each entry describes **what** to build, **why** it matters, a short
**implementation sketch** grounded in the current architecture, and **ten
concrete use cases**.

This document deliberately does **not** repeat anything already tracked in
`ideas.md` (embedding-based cache search, `/fetch/diff`, `/fetch/stream`,
recipe replay, auto-pin, robots/sitemap priming, entry-point plugins, the
action DSL, freshness scoring, the dashboard, httpx retries, UA rotation).
Everything below is new.

**Legend:** 🟢 small (≤1 day) · 🟡 medium (2–5 days) · 🔴 large (1–2 weeks)

---

## Contents

**A. Content acquisition** — 1. PDF ingestion · 2. YouTube transcripts · 3. StackExchange plugin · 4. RSS/Atom feeds · 5. Wayback Machine fallback · 6. Multi-page auto-stitching · 7. Named auth profiles · 8. Community filter lists

**B. Extraction & output** — 9. Structured data extraction · 10. Table extraction · 11. Screenshot endpoint · 12. Extraction confidence scoring · 13. Real tokenizer budgets · 14. Link map endpoint

**C. Search** — 15. Rank-fusion federated search · 16. Pluggable search backends · 17. Docs-site search adapters · 18. Extractive Q&A with citations

**D. Cache & knowledge** — 19. Versioned cache · 20. SQLite/FTS5 metadata index · 21. Near-duplicate detection · 22. Collections & tags · 23. Knowledge-pack export/import

**E. Agent ergonomics & API** — 24. Fetch trace / explain mode · 25. Async job queue · 26. URL watch & notifications · 27. Native MCP server mode

**F. Operations** — 28. Prometheus metrics · 29. Per-domain politeness scheduler · 30. Service auth & quotas

---

# A. Content acquisition

## 1. PDF → markdown ingestion tier 🟡

**What:** Detect `application/pdf` responses (and `.pdf` URLs) in Tier 2 and
route them through a PDF extraction pipeline (`pypdf` for text-native PDFs,
optional `pdfplumber` for layout/tables) instead of the HTML→markdown path,
producing markdown with per-page heading anchors (`## Page 12`).

**Why:** A huge share of the highest-value content on the web — papers,
standards, datasheets, government documents, financial filings — is PDF.
Today those URLs fall through every tier and return garbage or nothing.
Because output lands in the normal cache, agents immediately get pagination,
`/grep`, `/fetch/lines`, and BM25 over PDFs for free.

**Sketch:** Extend `detect_content_type()` with a `"pdf"` class; add
`pdf.py` with `pdf_to_markdown(bytes) -> str`; in `FetchEngine`, when Tier 2
sees a PDF content type, fetch bytes (`r.content`, raise `httpx_timeout` for
this path), convert, then reuse `_build_from_md`. Page anchors go into the
existing TOC extraction untouched. Add `AF_PDF_MAX_MB` (default 25) to bound
memory.

**Use cases:**
1. An agent researching a machine-learning technique fetches the arXiv PDF directly when the HTML abstract isn't enough, then `/grep`s for the hyperparameter table.
2. A compliance assistant ingests a 200-page GDPR guidance PDF from the EU commission site and answers questions via `/fetch/lines` on the cached markdown.
3. A hardware engineer's agent pulls an STM32 datasheet PDF and greps for `"electrical characteristics"` to extract voltage limits.
4. An investor-research agent fetches a company's 10-K filing PDF from SEC EDGAR and pages through the "Risk Factors" section with `offset`.
5. A grant-writing assistant reads the funding agency's PDF call-for-proposals and extracts eligibility rules into a synthesis entry.
6. A legal assistant caches a court opinion PDF and cites exact passages using line numbers from `/fetch/lines`.
7. A university student's agent batch-fetches all lecture-note PDFs linked from a course page in one `/fetch/batch` call.
8. A procurement bot ingests vendor spec-sheet PDFs and compares them via `/cache/search "operating temperature"` across all cached sheets.
9. An accessibility team converts a PDF-only municipal report into markdown for a screen-reader-friendly summary.
10. A journalist's agent fetches a leaked/archived report PDF from a document host and greps names across its 500 pages without reading it linearly.

## 2. YouTube transcript plugin 🟡

**What:** A `youtube` plugin (`youtube.com`, `youtu.be`) that fetches the
video's transcript (via the timedtext API / `youtube-transcript-api`
approach), plus title, channel, date, and description, and formats it as
timestamped markdown (`**[12:34]** …`).

**Why:** Talks, tutorials, interviews, and product announcements
increasingly exist only as video. A transcript in the cache makes an hour of
video greppable in milliseconds and costs ~10k tokens instead of being
inaccessible. No browser tab needed — it's a pure fast-path plugin.

**Sketch:** `plugins/youtube.py` extracts the video ID, calls the innertube
player endpoint for caption tracks (prefer manual > auto-generated, honor a
`lang` preference from `AF_YT_LANGS`), stitches cues into paragraph blocks
with minute-level timestamps. Falls through (`return None`) for videos
without captions so the normal tiers can at least get the description.

**Use cases:**
1. An agent asked "summarize this conference talk" fetches the YouTube URL and works from the transcript instead of refusing.
2. A developer's agent greps a 90-minute framework-release keynote for `"breaking change"` to build an upgrade checklist.
3. A buzz-skill run pulls transcripts of the three most-viewed reviews of a new GPU and mines sentiment.
4. A student pastes a lecture URL; the agent extracts the transcript and generates flashcards from minutes 20–45 via `/fetch/lines`.
5. A support engineer's agent transcribes a customer's screen-recording walkthrough posted as an unlisted video to file a precise bug report.
6. A researcher tracking a public figure fetches interview transcripts across months and searches the cache for evolving positions on one topic.
7. A localization team greps transcripts for product-name pronunciations and terminology before subtitling.
8. An agent following a cooking tutorial extracts the ingredient list mentioned in the first two minutes without watching the video.
9. A podcast producer checks whether a guest already covered a topic elsewhere by caching transcripts of their previous appearances.
10. A due-diligence agent pulls a startup founder's pitch and demo-day videos and cross-references claims against the company's docs already in cache.

## 3. StackExchange plugin 🟢

**What:** A `stackexchange` plugin (`stackoverflow.com`, `*.stackexchange.com`,
`superuser.com`, `serverfault.com`, `askubuntu.com`) using the public
`api.stackexchange.com` API (`filter=withbody`) to render a question, its
accepted answer first, then top answers by score, with vote counts, author
reputation, and code blocks preserved.

**Why:** Stack Overflow is one of the most-fetched domains in real agent
sessions, and its HTML is heavy with nav, ads, and "related questions" noise
that survives readability. The API gives clean, ranked content in one call —
and the site's Cloudflare protection makes browser-tier fetches slow and
flaky, so a fast path pays off doubly.

**Sketch:** `plugins/stackexchange.py`: map hostname → API `site` parameter,
parse `/questions/{id}` URLs, two API calls (question + answers,
`sort=votes`), convert body HTML via `html_to_markdown` with backtick code
style. Honor `AF_STACKAPPS_KEY` for the 10k/day quota tier. Accepted answer
gets a `✔ Accepted` badge line.

**Use cases:**
1. A coding agent hits a cryptic `asyncio` traceback, searches, and fetches the top SO question — getting the accepted answer first instead of 300 lines of page furniture.
2. An agent comparing solutions greps a cached high-traffic question for `"python 3.12"` to find version-specific caveats among 40 answers.
3. A DevOps agent pulls a ServerFault thread about nginx reverse-proxy timeouts and extracts the exact config block.
4. A support bot answering "how do I do X in Excel" cites the SuperUser accepted answer with its vote count as a confidence signal.
5. A library maintainer's agent batch-fetches the 15 most-voted questions tagged with their library to mine the docs' biggest gaps.
6. An agent debugging an Ubuntu boot issue fetches an AskUbuntu thread where the accepted answer differs from the top-voted one — both visible, clearly labeled.
7. A code-review agent verifies a suggested workaround is not the known-dangerous one by checking the answer's comment warnings preserved in markdown.
8. A student's agent collects three different explanations of Big-O notation from the CS StackExchange for a study sheet.
9. An SRE incident review greps cached StackExchange threads for `"kernel: TCP: out of memory"` gathered during the incident.
10. A prompt-engineering agent researching LLM API quirks pulls the top StackOverflow questions mentioning the SDK and builds a known-issues synthesis entry.

## 4. RSS/Atom feed plugin + feed discovery 🟢

**What:** Detect and parse RSS/Atom/JSON-feed responses into a markdown
digest (title, date, author, summary, link per entry). Add `/fetch` support
for feed URLs via a `feeds` plugin, and a `discover_feeds=true` option that
returns `<link rel="alternate">` feeds found on any HTML page.

**Why:** Feeds are the cheapest possible "what's new on this site" primitive
— one request, no browser, structured by design. Agents currently have to
scrape blog index pages and guess at dates. Feeds also make recurring
monitoring workflows (buzz skill, watch feature idea #26) dramatically
cheaper.

**Sketch:** `plugins/feeds.py` matches on content type
(`application/rss+xml`, `application/atom+xml`, `application/feed+json`) and
common paths (`/feed`, `/rss`, `.xml` heuristics) — parse with
`xml.etree`/`json`, no new heavy dependency. Feed discovery hooks into
`MarkdownExtractor` and returns candidates in a new `feeds: list[str]`
response field.

**Use cases:**
1. An agent monitoring a competitor's engineering blog fetches its Atom feed daily and only full-fetches genuinely new posts.
2. A security agent pulls the `curl` and `openssl` release feeds to check whether a CVE fix has shipped.
3. A newsroom assistant aggregates 12 city-government RSS feeds into a single morning digest via `/fetch/batch`.
4. A user asks "what has this researcher published lately" — the agent discovers the feed on their homepage and reads the last 10 entries.
5. A changelog bot watches the GitHub releases Atom feed of five dependencies (works even without API tokens).
6. A podcast agent parses a show's RSS to list episodes with dates and picks the one matching the user's question.
7. A buzz-skill run supplements Reddit/HN with the r/LocalLLaMA RSS feed when Reddit's JSON API is rate-limiting.
8. A legal-watch agent subscribes to a regulator's rulings feed and greps new entries for client-relevant statutes.
9. An academic agent tracks an arXiv category feed (`cs.CL`) and caches abstracts of the day's papers for BM25 querying.
10. A migration project discovers that a docs site exposes a feed of updated pages, letting the agent re-fetch only changed docs instead of recrawling.

## 5. Wayback Machine fallback tier 🟡

**What:** When every live tier fails (site down, DNS dead, hard paywall,
challenge page that even zendriver can't pass) — or when the caller passes
`archive=true` / `archive_date=2023-06-01` — fetch the page from the
Internet Archive (`web.archive.org/web/{ts}/{url}`) and label the response
`method_used="wayback"` with the snapshot date.

**Why:** "The page is gone" is one of the worst answers an agent can give.
Link rot is measured at 20–40% over a decade; a fallback that transparently
recovers dead content converts hard failures into slightly-stale successes,
and `archive_date` unlocks point-in-time research the live web simply cannot
do.

**Sketch:** New final tier in `FetchEngine.fetch()` gated by
`AF_WAYBACK_FALLBACK` (default on) — call the availability API
(`archive.org/wayback/available?url=…&timestamp=…`), fetch the `id_`-flagged
raw snapshot, strip the Wayback toolbar chrome with `strip_selectors`, then
reuse the normal extraction path. Add `snapshot_date` to `FetchResponse`.

**Use cases:**
1. An agent following a 2019 blog link from an HN thread gets the archived copy instead of a 404, clearly labeled with the snapshot date.
2. A journalist verifies what a company's pricing page claimed before last month's controversy using `archive_date=2026-05-01`.
3. A dependency's documentation site is down during an incident; the on-call agent still reads the config reference from yesterday's snapshot.
4. A researcher citing a defunct startup's technical whitepaper retrieves it from the archive with a stable provenance note.
5. A legal assistant captures how terms-of-service read on a specific date relevant to a dispute.
6. An SEO agent compares a client's archived landing page from last year against today's live version (paired with the cached copy).
7. A historian's agent walks a government agency's homepage across five yearly snapshots to trace policy language changes.
8. An agent hits a paywalled article that the archive crawled before the paywall went up.
9. A trust-and-safety analyst documents a deleted forum post that was archived, with the snapshot URL as evidence.
10. A user pastes a link from an old bookmark file; the domain is now parked, and the agent silently serves the last good snapshot instead of the ad page.

## 6. Multi-page article auto-stitching 🟡

**What:** Detect "next page" links (`rel="next"`, `link[rel=next]`, visible
`Next ›`/`Page 2` anchors matching the same path pattern) and, when the
caller passes `follow_pages: N` (default 1 = off), fetch up to N continuation
pages and concatenate them into one cached document with `## Page k` markers.

**Why:** Paginated articles, multi-page tutorials, and forum threads defeat
the whole cache model today: each page is a separate cache entry, TOC and
grep only see fragments, and the agent has to notice and follow pagination
manually — most don't, and silently reason from 1/5th of the content.

**Sketch:** In `_build_response`, after extraction, scan the *original* HTML
for next-link candidates (readability strips them); loop through the
existing tier logic per page (respecting the same method), concatenate, cache
under the first page's URL. Guards: same-registrable-domain only, cycle
detection via seen-URL set, `AF_MAX_FOLLOW_PAGES=10` hard cap.

**Use cases:**
1. An agent reads a 6-page in-depth CPU review as one document and greps benchmarks across all pages at once.
2. A forum thread spanning 12 pages of replies becomes one cached doc, so `/grep "workaround"` finds the fix buried on page 9.
3. A recipe agent fetches a listicle split across pages purely for ad impressions and gets the full list in one call.
4. A tutorial series with `Part 1 → Part 2` rel-next links is stitched so code from the final part is available when summarizing part one.
5. A researcher caches a multi-page interview and quotes an exchange from the last page with correct line numbers.
6. A vBulletin support forum's pagination is followed to capture the moderator's resolution post at the end of the thread.
7. A news archive's "continued on next page" 1990s-style article is retrieved whole for a historical fact-check.
8. A documentation site with Previous/Next chapter navigation is fetched chapter-by-chapter (`follow_pages=8`) to prime the cache in one request.
9. A product-comparison article that puts the verdict table on the final page no longer misleads the agent that read only page 1.
10. A photo-essay's caption text across 15 pages is aggregated so the agent can answer which image mentioned a location.

## 7. Named auth session profiles 🔴

**What:** Multiple named browser profiles (`AF_PROFILE=work`,
`req.profile="github-sso"`) each with its own `user_data_dir` cookie jar,
plus `/auth/profiles` (list, with logged-in-domain hints), and a documented
VNC flow for logging in once. httpx tiers get a matching per-profile
`httpx.Cookies` jar exported from the browser profile.

**Why:** The single shared profile is already the mechanism for
authenticated fetches (via VNC), but one jar means one identity — agents
can't separate work/personal accounts, can't fetch an internal wiki and a
public site under different sessions, and the httpx fast path never benefits
from logins at all (it always hits the anonymous page and burns a browser
tab).

**Sketch:** `profiles/{name}/` directories under `user_data_dir`; a
`BrowserPool` per profile created lazily (LRU-cap concurrent Chromes at 2);
cookie export via CDP `Network.getCookies` into a shared jar the fetch
engine attaches when `profile` is set. `FetchRequest.profile: str | None`.
Profiles are strictly opt-in per request — no accidental authenticated
fetches.

**Use cases:**
1. A developer logs into their company's Confluence once via VNC; the agent then fetches internal runbooks with `profile="work"` during incidents.
2. An agent reads a private GitHub Enterprise wiki page that has no API, using the SSO session captured in the browser profile.
3. A subscriber fetches articles from a news site they pay for, without sharing that session with unrelated fetches.
4. A QA engineer's agent tests how a marketing page renders for logged-in vs anonymous users by fetching with and without a profile.
5. A freelancer keeps `client-a` and `client-b` profiles so fetches against each client's staging environment never leak the other's cookies.
6. An agent retrieves the user's own forum post history from a community that requires login to view profiles.
7. A course assistant fetches lecture materials from a university LMS (Moodle/Canvas) behind the student's SSO.
8. A data analyst pulls internal Grafana/dashboard HTML snapshots for a weekly report using the `ops` profile.
9. An agent checks the user's SaaS usage/billing page to answer "how close am I to my plan limit."
10. A community moderator's agent fetches the mod-only queue page to summarize pending reports each morning.

## 8. Community filter lists for overlays 🟡

**What:** Bundle and periodically refresh compiled versions of EasyList
Cookie / Fanboy Annoyances selector lists (a curated, size-capped subset),
applying them in two places: as CSS-selector strips in `MarkdownExtractor`
and as element hiding in the browser tier before HTML capture.

**Why:** The hand-maintained `COOKIE_DISMISS_JS` and `strip_selectors` in
`config.yaml` cover a dozen patterns; the community lists cover tens of
thousands, maintained daily by people fighting this war full-time.
Newsletter modals, "read 3 free articles" curtains, and GDPR walls are the
single biggest source of garbage markdown in real sessions.

**Sketch:** Ship a compiled `filters.json` (list → plain CSS selectors,
dropping procedural rules) generated by a `scripts/update_filters.py` script;
load at startup into `SiteConfig` as low-priority global strips (site
`config.yaml` still wins). `AF_FILTER_LISTS=off` opt-out. Cap at ~5k
selectors and benchmark `soup.select` cost; pre-bucket selectors by
domain-specific rules.

**Use cases:**
1. A recipe fetch no longer returns 40 lines of "We value your privacy" vendor lists before the ingredients.
2. A European user's agent fetches a US news article and the GDPR consent wall text disappears from the markdown instead of dominating it.
3. A research batch over 30 marketing blogs isn't polluted by identical HubSpot newsletter-popup markup in every cached doc.
4. `/cache/search` relevance improves because consent-banner boilerplate no longer inflates BM25 term frequencies across every document.
5. An agent quoting an article verbatim doesn't accidentally include "Subscribe to continue reading" mid-paragraph.
6. Token budgets stretch further: a 3k-token article no longer costs 4.5k because of overlay cruft, across every fetch in a session.
7. A screenshot (idea #11) taken after element-hiding shows the article, not a cookie dialog, so vision-model analysis works.
8. The `digi24.ro`-style per-domain strip lists in `config.yaml` shrink to genuinely site-specific rules, cutting maintenance.
9. A price-tracking agent stops misreading a "€2/month subscription" banner as the product's price.
10. An accessibility summary of a page reflects its real content hierarchy instead of modal-dialog headings.

---

# B. Extraction & output

## 9. Structured data extraction endpoint 🟡

**What:** `POST /extract` — given a URL (fetched via the normal waterfall,
cache-aware), return structured JSON: JSON-LD blocks, OpenGraph/Twitter meta,
microdata, and optionally a caller-supplied CSS map
(`{"price": ".price-tag", "sku": "[data-sku]"}`) evaluated against the raw
HTML.

**Why:** Markdown is right for prose but wrong for *facts*. Sites already
publish machine-readable Schema.org data (products, events, recipes, jobs,
articles) that the markdown pipeline throws away during `script` tag
stripping. Agents currently regex prices and dates out of prose — brittle
and token-expensive — when `<script type="application/ld+json">` had the
answer verbatim.

**Sketch:** New `extract.py`: reuse `FetchEngine` to get raw HTML (store raw
HTML alongside `.md` when `/extract` is used), parse
`script[type="application/ld+json"]` with graceful JSON repair, `meta[property^="og:"]`,
and itemprop attributes. Response: `{url, jsonld: [...], opengraph: {...},
microdata: [...], selectors: {...}}`.

**Use cases:**
1. A shopping agent extracts exact price, currency, and availability from a product page's Schema.org `Offer` instead of parsing "was $99 now $79!" prose.
2. An event-planning agent pulls structured start time, venue, and ticket URL from an Eventbrite/venue page's `Event` JSON-LD.
3. A recipe agent gets ingredients as a JSON array with quantities from `Recipe` markup — directly convertible to a shopping list.
4. A job-search agent extracts salary range, location, and employment type from `JobPosting` data across 20 listings in a batch.
5. A citation manager pulls canonical title, author, and publish date from `Article` metadata rather than guessing from the byline.
6. An SEO auditor diffs a client's OpenGraph tags against their competitors' across 50 pages.
7. A real-estate agent extracts beds/baths/price from listing pages' structured data for a comparison table.
8. A news aggregator uses `datePublished` from JSON-LD to sort articles reliably when visible dates say "3 hours ago."
9. A price-history tracker calls `/extract` with a CSS map for a shop that lacks Schema.org markup, keeping the scraping recipe out of agent prompts.
10. A misinformation researcher collects `author` and `publisher` structured fields to build a source-attribution dataset.

## 10. Table extraction to JSON/CSV 🟢

**What:** `include_tables: "json" | "markdown" | "off"` on `/fetch` (and a
standalone `POST /tables`): parse `<table>` elements with header inference
(thead, first-row-th, or first-row heuristic), colspan/rowspan expansion, and
return them as `tables: [{caption, headers, rows}]` alongside the markdown.

**Why:** HTML→markdown mangles real-world tables — nested markup, spans, and
wide tables become unreadable pipe soup that LLMs mis-align. Structured rows
let an agent *compute* over the data (sort, filter, sum) instead of
squinting at markdown, and they survive pagination (a table isn't split
mid-row by `paginate()`).

**Sketch:** `tables.py` using BeautifulSoup (already a dependency): walk
tables in the extracted content root, expand spans into a dense grid, emit
JSON; markdown mode renders the *normalized* grid back to clean pipes.
Store table JSON in cache metadata so `/tables` on a cached URL is free.

**Use cases:**
1. An agent comparing cloud-instance pricing pulls AWS's on-demand table as JSON and computes the cheapest 16 GB option itself.
2. A sports assistant extracts a league standings table and answers "who's on a 5-game win streak" by processing rows, not prose.
3. A Wikipedia country-statistics table with rowspan region groupings arrives as a dense grid instead of broken markdown.
4. A financial agent pulls the quarterly-results table from an investor-relations page and sums segment revenue.
5. A hardware buyer's agent extracts a motherboard spec-comparison table and filters rows to models with 4 RAM slots.
6. A data journalist exports a government open-data HTML table to CSV for a spreadsheet in one call.
7. An API-migration agent parses the "old endpoint → new endpoint" mapping table from a deprecation notice into a lookup dict it applies to code.
8. A nutrition tracker reads the USDA nutrient table for an ingredient with correct column alignment.
9. A dependency auditor extracts a compatibility matrix (library × framework versions) and answers whether two versions are jointly supported.
10. A travel agent parses a train-timetable page and finds the last departure after 21:00 by comparing time cells numerically.

## 11. Screenshot endpoint for vision models 🟡

**What:** `POST /screenshot` — `{url, full_page: bool, width, wait_ms,
selector}` → PNG (base64 or binary) captured via the existing zendriver
pool (`Page.captureScreenshot`), with the same init-scripts, cookie
dismissal, and filter-list hiding as normal fetches. Optionally cached
alongside the markdown entry.

**Why:** Some information is irreducibly visual — charts without data
tables, complex layouts, canvas-rendered dashboards, "is this page broken?"
questions. Multimodal agents are the norm now; the service has a warm
browser sitting right there, and a screenshot is often *cheaper* in tokens
than mangled markdown of a highly visual page.

**Sketch:** Reuse `BrowserPool.acquire_tab()`; add
`tab.send(zd.cdp.page.capture_screenshot(...))` with clip support for
`selector` (via `DOM.getBoxModel`). Response is `image/png` with
`X-Final-Url` header, or JSON with base64 when `format=json`. Enforce
`AF_SCREENSHOT_MAX_HEIGHT` for full-page captures.

**Use cases:**
1. An agent asked "what does this chart show" screenshots the interactive D3 visualization that produces no useful markdown and reads it with vision.
2. A frontend developer's agent captures their staging page after a deploy and confirms the hero section renders, catching a broken build.
3. A design-review bot screenshots a competitor's redesigned pricing page for a visual teardown alongside the extracted text.
4. An agent debugging "the docs say click the gear icon" grabs a screenshot to locate the icon and give pixel-accurate guidance.
5. A trading assistant captures a canvas-rendered market heat-map that has no DOM text at all.
6. A QA workflow screenshots the same URL at 375px and 1440px widths to check responsive breakage.
7. An archival task saves visual evidence of a page (paired with the Wayback idea) before it changes, for a dispute record.
8. A form-filling assistant (future action DSL) screenshots the failing validation state to show the user exactly which field is rejected.
9. An agent evaluating "is this site legitimate" inspects the screenshot for trust signals that markdown can't convey (layout quality, badges).
10. A newsletter author captures a referenced infographic as an image attachment while quoting the article text from the cache.

## 12. Extraction confidence scoring & auto-escalation 🟢

**What:** Score every extraction (0–1) from cheap signals — extracted/raw
text ratio, meaningful-line count, boilerplate-phrase density ("enable
javascript", "subscribe to read"), link-to-text ratio — and (a) return it as
`extraction_score` on `FetchResponse`, (b) when the httpx tier scores below
`AF_MIN_EXTRACTION_SCORE` (default 0.35), *automatically* escalate to the
browser tier instead of returning thin content.

**Why:** Today `_needs_js()` is a binary word-count heuristic that decides
*before* extraction; nothing checks whether the final markdown is actually
any good. Agents burn a round-trip discovering the content is a skeleton and
then must know to retry with `force_browser=true` — most don't. A score
makes quality visible and the waterfall self-correcting.

**Sketch:** `quality.py` with `score_extraction(raw_html, markdown) ->
float` (pure, unit-testable); call it in `_build_response`; on low score in
Tier 2/2.5, fall through to Tier 3/4 rather than returning; annotate final
response with the score and which tier won. Log scores to the fetch log for
tuning.

**Use cases:**
1. A React-SPA docs site that serves an empty shell over httpx silently escalates to zendriver — the agent never sees the empty version.
2. An agent triaging a 20-URL batch sorts by `extraction_score` and re-fetches only the 3 weak ones with `force_browser=true`.
3. A soft-paywalled article scores 0.2 (teaser paragraph + subscribe wall), signaling the agent to try the archive fallback instead of summarizing the teaser as if complete.
4. A research skill treats scores below 0.5 as "don't cite from this" and excludes them from synthesis, preventing confident answers from thin content.
5. Site-config tuning: the operator greps the fetch log for chronically low-scoring domains and adds init scripts/selectors for exactly those.
6. A regression alarm: a plugin's average score drops after a site redesign, flagging that its selectors need updating before users notice.
7. An agent explains itself: "content retrieved with low confidence (0.3) — the page may require login," improving trust in negative answers.
8. Batch indexing of a docs site skips caching entries scoring <0.3 so garbage never pollutes BM25 results.
9. A localized site serving a JS-only language switcher escalates automatically, retrieving the actual article rather than the switcher menu.
10. Monitoring (idea #28) charts mean extraction score per tier per day, revealing when a bot-detection vendor update starts degrading Tier 2 globally.

## 13. Real tokenizer budgets 🟢

**What:** Replace the `TOKENS_PER_CHAR = 0.25` heuristic in `paginate()`
with a real tokenizer (`tiktoken`'s `o200k_base` by default, configurable
via `AF_TOKENIZER`), lazily loaded, with a fast char-based pre-slice so only
the boundary region is tokenized. Report `token_count` on every response.

**Why:** The 4-chars-per-token guess is off by 2–3× on code, CJK text, and
URLs — a "max_tokens: 8000" fetch of a Chinese article can deliver 20k+
actual tokens, blowing the calling agent's context budget, while dense
English prose under-fills it. Agents plan context precisely; the service
should speak the same units.

**Sketch:** `markdown.paginate()` gains a tokenizer path: pre-slice at
`chars = max_tokens * 6`, encode once, cut at the token boundary, map back
to a char offset (offsets stay char-based for backward compatibility).
Cache token counts in `CacheMeta` at write time. Keep the heuristic as
fallback when `tiktoken` isn't installed.

**Use cases:**
1. An agent with 12k tokens of headroom requests exactly `max_tokens: 11000` and receives content that actually fits, instead of overshooting and truncating its own prompt.
2. A Japanese news article no longer returns 2.5× the requested token volume, which previously caused mid-conversation context overflows.
3. A code-heavy GitHub README (dense in tokenizer-expensive symbols) fills the budget accurately instead of arriving 40% under-length.
4. `/fetch/batch` with `max_tokens_per_url: 2000` over 25 URLs produces a predictable ~50k-token total, enabling reliable batch sizing in the research skill.
5. The response's `token_count` lets an orchestrator decide whether to summarize a page before injecting it into a sub-agent's prompt.
6. A cost dashboard (idea #28) reports tokens-served-per-session accurately enough to estimate LLM spend attributable to web content.
7. An agent paginating a book-length PDF (idea #1) plans "this is 92k tokens → 12 chunks" up front from metadata rather than discovering the length page by page.
8. A synthesis writer checks its `/cache/write` payload's token count to keep pinned notes under a self-imposed 1k-token cap.
9. Cross-model workflows set `AF_TOKENIZER` to match a non-OpenAI tokenizer so budgets are correct for the model actually consuming the text.
10. Truncation warnings become meaningful: `truncated: true, token_count: 7998` tells the agent it got a full budget's worth, not a random fraction.

## 14. Link map endpoint 🟢

**What:** `POST /links` — for a (cache-aware) URL, return all outbound links
*classified*: `content` (inside the readability-extracted region), `nav`,
`pagination` (rel=next/prev, page-number patterns), `external` vs
`internal`, plus anchor text and a same-page TOC of fragment links. Options:
`internal_only`, `dedupe`, `limit`.

**Why:** Crawling decisions are the heart of agentic browsing — "which of
these 200 links is worth fetching next?" Today an agent either fetches with
`include_links=true` and regexes markdown link syntax (losing all context
about *where* the link sat), or fetches blind. A classified link map is the
navigation primitive that composes with `/fetch/batch`: map → choose →
batch.

**Sketch:** `links.py`: run readability to get the content region, walk all
`<a href>` in raw HTML tagging containment (content vs stripped region),
classify pagination via rel attributes and `\bpage[=/]\d+` patterns,
absolutize against final URL, dedupe by normalized URL. Cache the map in
metadata.

**Use cases:**
1. A docs-indexing agent calls `/links internal_only=true` on a documentation homepage and batch-fetches exactly the guide pages, skipping the 80 footer/nav links.
2. A research agent fetches a survey blog post and follows only the `content` links — the actual sources the author cited — for verification.
3. A crawler primitive: map → filter unseen URLs against `/cache/index` → batch, iterated three times, indexes a small site with zero wasted fetches.
4. An agent on a category page uses `pagination` links to walk listing pages 2–5 without HTML-parsing heuristics in the prompt.
5. A link-rot auditor extracts all external links from a company's resources page and HEAD-checks them for 404s.
6. A competitive analyst maps a rival's homepage to see which products get above-the-fold `content` links this quarter.
7. An SEO agent counts internal vs external outbound links per page across a site section for an internal-linking report.
8. A citation-graph builder records which papers a lab's publications page links to, using anchor text as the paper titles.
9. An agent answering "where do I download X" ranks `content` links whose anchor text matches `download|release` instead of grepping markdown.
10. A safety filter checks the link map for known-bad domains before the agent recommends a page to the user.

---

# C. Search

## 15. Rank-fusion federated search 🟢

**What:** `engine: "all"` — run Google (browser), DDG-lite (httpx), and any
configured API backends (idea #16) concurrently, merge with Reciprocal Rank
Fusion (`score = Σ 1/(60 + rank_i)`), dedupe by normalized URL, and return a
single ranked list with `sources: ["google", "ddg"]` per result.

**Why:** Engines disagree, and their disagreement is signal: a URL ranked
top-5 by two independent engines is far more likely relevant than either
engine's #1 alone. Today `auto` means "google, else ddg" — a fallback, not a
fusion. Concurrency means the fused search costs the same wall-clock as the
slowest single engine.

**Sketch:** In `SearchEngine`, `asyncio.gather` over available engines
(skip browser engines when the pool is down), normalize URLs with the
existing `normalize_url`, RRF-merge, keep the best snippet per URL.
`SearchResult` gains optional `sources` and `fused_score` fields.

**Use cases:**
1. A research skill's discovery step surfaces the canonical tutorial that Google buries under SEO farms but DDG ranks #2 — cross-engine agreement floats it up.
2. An agent fact-checking a niche claim needs recall over precision: fusion returns 25 unique URLs where a single engine returned 10.
3. Google serves a CAPTCHA mid-session; fused results still arrive from DDG-lite, and `sources` shows the degradation transparently.
4. A medical-info query benefits from dedup: the same Mayo Clinic page appearing in both engines is confidently placed first.
5. A user asks for "official docs, not blogspam" — the agent weights results where the domain appears in multiple engines' top-10.
6. A non-English query fuses engines with different language biases, giving usable coverage for a Romanian technical topic.
7. Benchmarking: the operator compares per-engine hit rates in the fused metadata to decide whether paying for a Brave API key is worth it.
8. A time-boxed agent does one `/search engine=all` instead of two sequential searches, halving discovery latency in every research loop.
9. Long-tail product research (an obscure part number) hits a forum post only indexed by one engine — fusion includes it without the agent knowing which engine to try.
10. The buzz skill's web leg uses fusion so "what are people saying" isn't hostage to one engine's news-carousel biases.

## 16. Pluggable search backends (Brave, SearXNG, Kagi) 🟡

**What:** A `SearchBackend` protocol mirroring the plugin system:
`name`, `available() -> bool` (checks API key/URL config), `search(req) ->
list[SearchResult]`. Ship adapters for Brave Search API, SearXNG (self-hosted
URL), Kagi, and Serper — enabled purely by env vars
(`AF_BRAVE_API_KEY`, `AF_SEARXNG_URL`, …).

**Why:** Browser-scraped Google is the least reliable component of the whole
service: CAPTCHAs, layout churn, and a burned browser tab per query. API
backends are faster (no browser), stable (versioned JSON), and legal to
automate — and self-hosted SearXNG gives privacy-conscious users a zero-cost
aggregator. This also feeds fusion (#15) with better raw material.

**Sketch:** `search_backends/` package with auto-discovery like
`plugins/`; `SearchEngine.search()` consults registry first for the
requested engine name, falls back to built-ins. Each adapter maps the
common `SearchRequest` filters (dates, max_results) to its API's params and
reports unsupported filters in the response `error` field, consistent with
Reddit's current behavior.

**Use cases:**
1. An ops team sets `AF_BRAVE_API_KEY` and search latency drops from ~6s (browser Google) to ~400ms for every agent in the company.
2. A privacy-focused user points the service at their SearXNG instance so no query ever reaches Google with their IP.
3. Google starts CAPTCHA-walling the datacenter IP; the operator flips the default engine to Brave in config with zero code changes.
4. A Kagi subscriber gets their paid, SEO-spam-filtered results inside agent workflows, not just their browser.
5. An air-gapped-ish corporate network allows only the internal SearXNG host; the service works fully within policy.
6. A high-volume batch pipeline (500 searches/day) uses an API backend with known quotas instead of gambling on scraper stability.
7. Regional research uses SearXNG configured with region-specific engines that the built-in backends don't expose.
8. A/B evaluation: the operator runs the same query set through two backends via the `engine` parameter and measures which finds more later-cited URLs.
9. CI tests for the search pipeline hit a mock backend implementing the protocol, making search logic testable offline for the first time.
10. When the browser pool is down entirely, `engine=all` still returns rich results from API backends — search stops depending on Chrome at all.

## 17. Docs-site search adapters 🟡

**What:** Recognize documentation-site search infrastructure and query it
directly: Algolia DocSearch (powers most OSS docs), MkDocs/mkdocs-material's
`search_index.json`, Sphinx's `searchindex.js`, and readthedocs' API. New
engine value `engine: "docs"` with `site: "https://docs.example.com"`, or
auto-detection when a `site:` filter targets a known docs host.

**Why:** Web engines index docs sites poorly (version duplication, weak
recall on symbol names), but the sites *ship their own excellent search
indexes* — DocSearch answers `useEffect cleanup` better than Google does.
Querying the native index is one HTTP call, returns section-level anchors,
and works for docs that web engines haven't crawled (new releases, self-hosted
internal docs).

**Sketch:** `docs_search.py`: probe order — Algolia config sniffing (well-known
`docsearch.js` init params in homepage HTML, cached per domain), then
`search/search_index.json` (MkDocs), then `searchindex.js` (Sphinx). Each
returns section title + URL#anchor + snippet. Cache the discovered adapter
per domain in `SiteConfig`-adjacent state.

**Use cases:**
1. An agent asks "how do I configure retries in httpx" against `www.python-httpx.org` and gets the exact section anchor from the MkDocs index instead of a homepage link.
2. A developer working with a 3-day-old library release searches its docs directly — web engines haven't recrawled, the native index is current.
3. A symbol-level query (`model_validator mode="after"`) hits Algolia DocSearch on the pydantic docs, which tokenizes code identifiers properly.
4. An internal-platform team's self-hosted MkDocs portal becomes searchable by agents with `site:` pointing at the intranet host — no crawler needed.
5. A migration agent searches both v1 and v2 doc versions of a framework (version-scoped indexes) to build an upgrade mapping.
6. The research skill's "index a docs site" recipe becomes one search call instead of a 40-URL batch crawl when only two sections are needed.
7. An agent answering from Sphinx-based CPython docs jumps straight to the `asyncio.wait_for` reference section via the search index anchor.
8. Doc-writers audit their own search quality: run the top 50 user questions through `/search engine=docs` and count misses.
9. A support bot deflects tickets by querying the product's DocSearch index and linking the precise anchor, with the section text fetched into cache for quoting.
10. When DocSearch returns nothing, the agent knows the topic is genuinely undocumented (high-precision negative), rather than wondering if Google just missed it.

## 18. Extractive Q&A with citations (`/cache/answer`) 🟡

**What:** `POST /cache/answer {question, limit}` — BM25 over cached docs,
then passage-level re-ranking (sentence-window scoring against the
question), returning the top passages verbatim with exact provenance:
`{answer_passages: [{text, url, title, start_line, end_line, score}]}`. No
LLM involved — pure extractive retrieval.

**Why:** The current flow (search cache → pick doc → grep/lines → read) is
four round-trips an agent must orchestrate correctly. Collapsing it into one
call returns exactly what agents need for grounded answers: quotable text
plus line-level citations that plug straight into `/fetch/lines` for
expansion. It's RAG's retrieval half as a primitive, with zero API-key
dependencies.

**Sketch:** `answer.py`: reuse cache BM25 for candidate docs (top 5), split
each into overlapping 5-line windows, score windows with BM25 against the
question terms plus exact-phrase and heading-proximity bonuses, return top-k
windows with their line ranges from the existing metadata. ~150 lines, all
stdlib + existing code.

**Use cases:**
1. After batch-indexing a framework's docs, an agent answers "what's the default connection-pool size" with a quoted passage and `url#L120-124` citation in one call.
2. A research session's follow-up question ("wait, which version introduced that?") is answered from cache without any new network fetch.
3. A support agent quotes the exact refund-policy sentence from the company's cached terms page, with line numbers for the human to verify.
4. A code assistant retrieves the passage documenting an env var it's about to recommend, guarding against hallucinated configuration.
5. A journalist greps a 40-document research corpus with a natural question and receives the three passages that actually address it, ranked.
6. A compliance workflow answers audit questions from cached policy documents with verbatim citations, satisfying evidence requirements.
7. An agent composing a comparison quotes each library's own docs on threading guarantees, each passage tied to its source URL.
8. In a long session where context has been compacted, the agent re-derives earlier findings by asking the cache instead of re-reading whole pages.
9. A teacher's assistant answers a student question from the cached textbook chapter and shows exactly where in the chapter the answer lives.
10. A synthesis-note writer pulls the top passages for each section heading before composing, ensuring every claim in `/cache/write` output traces to a source.

---

# D. Cache & knowledge

## 19. Versioned cache with history 🟡

**What:** Keep the last N versions (default 3, `AF_CACHE_VERSIONS`) of each
URL's markdown: on re-fetch with changed content (hash differs), rotate
`{key}.md` → `{key}.v1.md` etc. New endpoints: `GET /cache/versions?url=…`
(list with dates and sizes) and `/fetch/lines` / `/grep` gaining an optional
`version` parameter.

**Why:** The web mutates; the cache currently has amnesia. `ideas.md`
proposes a one-shot `/fetch/diff`, but diffing requires something to diff
*against* — retention is the primitive. With versions, "what changed"
becomes answerable at any time, not only if you diffed at the right moment,
and accidental cache-overwrites of good content by a bad fetch become
recoverable.

**Sketch:** In `FetchCache._write`, compare content hash with the current
entry; on change, rotate files (bounded by N) and append a `versions:` list
(timestamp, hash, size, extraction_score) to `CacheMeta`. Prune counts
versions toward size caps, oldest versions evicted first. Storage stays
plain files — no database required.

**Use cases:**
1. A pricing-watch agent re-fetches a vendor page weekly; when the user asks "when did the price change," version timestamps answer it.
2. A bad fetch (site was serving an error page that scored well enough to cache) is recovered by reading `version=1` — yesterday's good copy.
3. A regulatory-tracking agent compares the current and previous versions of an agency guidance page to brief the user on amendments.
4. A docs-maintainer agent detects that an upstream API's docs changed since the integration was written and flags exactly which endpoint section rotated.
5. A researcher citing a volatile page pins their citation to the specific cached version hash they actually read.
6. An SEO consultant tracks a competitor's homepage messaging across a month of versions to document a positioning shift.
7. A changelog synthesizer diffs three successive versions of a release-notes page that gets edited in place after publication.
8. During an incident, the agent compares the status-page's current text with the version from an hour ago to see what the vendor quietly edited.
9. A news-integrity check shows a story's headline was rewritten between fetches — versions provide before/after evidence.
10. A weekly buzz snapshot (buzz skill) stores trending-page versions, letting "is X still trending" be answered by version comparison instead of new synthesis entries.

## 20. SQLite/FTS5 metadata index 🟡

**What:** Replace the glob-every-`.meta.json` pattern with a single
`cache.db` (SQLite, WAL mode): one row per entry (url, key, title, method,
fetched_at, ttl, size, token_count, score, tags) plus an FTS5 virtual table
over the markdown for search. Markdown stays in files; the DB is a
rebuildable index (`agentic-cache reindex` recovers from corruption).

**Why:** `index()`, `search()`, `health()`, and `prune()` are all O(total
cache size) — every call reads every meta file, and BM25 re-tokenizes every
document from scratch. At 5k cached pages that's seconds of blocking I/O per
search. FTS5 gives millisecond BM25 (it implements BM25 natively), plus
ordered/filtered queries (by date, method, tag) that are currently
impossible without full scans.

**Sketch:** `index_db.py` with a thin sync API used by `FetchCache`;
inserts/updates on `_write`, delete on `evict`. `cache/search` becomes an
FTS5 `MATCH` with `bm25()` ranking + snippet(). Migration: lazily backfill
from existing meta files at startup. Keep the file-scan implementations as
fallback when the DB is absent.

**Use cases:**
1. A month-long research project accumulates 8,000 cached pages and `/cache/search` still answers in ~20ms instead of 4 seconds.
2. `/cache/index?since=2026-07-01&method=plugin` lists only recent plugin-fetched entries — an impossible query today — for auditing fast-path coverage.
3. An always-on team cache (shared service) handles concurrent search requests without each one hammering 8k files through the threadpool.
4. Prune runs become instant metadata queries (`SELECT … ORDER BY fetched_at`) rather than a full directory walk, so a cron can run them every 10 minutes harmlessly.
5. Search results include FTS5 `snippet()` highlights, giving agents better relevance judgment than the current first-match window.
6. Tag-scoped search (idea #22) is a `WHERE tags MATCH` clause instead of a new bespoke scan.
7. The health endpoint reports percentile fetch ages and per-domain entry counts from one aggregate query, enriching monitoring.
8. A laptop user's antivirus no longer flags thousands of tiny file reads per search; disk I/O drops an order of magnitude.
9. Rebuildability is a safety story: after a botched sync between machines, `agentic-cache reindex` restores a perfect index from the `.md` files.
10. Phrase queries (`"connection pool" NEAR timeout`) become possible via FTS5 syntax, sharpening `/cache/answer` (idea #18) candidate retrieval.

## 21. Near-duplicate detection 🟢

**What:** Compute a SimHash (64-bit, over word shingles) for every cached
document at write time; on cache writes and in `/cache/search` results, flag
near-duplicates (Hamming distance ≤ 6). Also honor `<link rel="canonical">`
during fetches: when the canonical URL differs and is already cached, alias
instead of re-storing.

**Why:** The same content lives at many URLs — mirrors, AMP pages, print
views, tracking variants beyond known params, syndicated copies, `en/` vs
default locales. Duplicates waste storage, *and* they poison research: BM25
returns the same article three times, crowding out genuinely distinct
sources, and agents "corroborate" a claim with what is actually one source
wearing three URLs.

**Sketch:** `simhash.py` (~60 lines, stdlib); store hash in `CacheMeta`;
`search()` groups results within distance ≤ 6 keeping the best-scoring
representative with `duplicates: [urls]` attached; `_write` checks canonical
URL from extraction metadata before storing. Batch endpoint reports
`duplicate_of` in results.

**Use cases:**
1. A research agent's `/cache/search` returns five *distinct* sources instead of the top hit plus its AMP and print-view clones.
2. A fact-checking agent is warned that its two "independent" confirmations are syndicated copies of one wire story.
3. Batch-fetching a link list from a forum thread dedupes the four differently-parameterized links to the same announcement post.
4. Storage stays lean on a docs crawl where `/latest/` and `/v2.9/` serve identical pages — one stored, one aliased.
5. A news aggregator groups 12 outlets' republications of the same press release into one cluster with a representative.
6. The canonical-URL alias means a user fetching `example.com/post?ref=twitter` after `example.com/post` gets an instant cache hit rather than a duplicate store.
7. A plagiarism-adjacent check: an agent notices a blog post is a near-duplicate of a cached StackOverflow answer and attributes properly.
8. Prune preferentially evicts duplicate members before unique documents, preserving maximum knowledge per megabyte.
9. A localization audit finds that `/de/pricing` is still a near-duplicate of the English page (untranslated), flagging incomplete rollout.
10. The buzz skill's cross-source signal ("appears in multiple communities") stops being fooled by the same URL shared with different UTM tags.

## 22. Collections & tags 🟢

**What:** Optional `collection: "project-x"` on `/fetch`, `/fetch/batch`,
and `/cache/write`; `tags: [...]` on write. Scoped operations everywhere:
`/cache/search {collection: "project-x"}`, `/cache/index?collection=…`,
`/cache/prune {collection}`, plus `GET /collections` (list with counts/sizes)
and `DELETE /collections/{name}`.

**Why:** The cache is one global soup. An agent researching topic A gets
BM25 noise from last week's unrelated topic B; ending a project means either
keeping its junk forever or nuking the shared cache. Collections give
sessions and projects a namespace — the difference between "a cache" and "a
knowledge base you can manage."

**Sketch:** Add `collection: str = ""` and `tags: list[str]` to `CacheMeta`;
filter in `_iter_meta`-based operations (trivial) or as indexed columns with
#20. A URL fetched into two collections stores once with a collection set
(membership list), not duplicate files. CLI: `--collection` flags.

**Use cases:**
1. An agent working two client projects keeps their research separated; "what did we learn about auth?" searches only the relevant client's collection.
2. Project wrap-up: `DELETE /collections/client-a` cleanly removes 300 cached pages without touching anything else.
3. The research skill auto-tags fetches with the session date, letting a future session ask "what did I read last Tuesday?"
4. A long-running monitoring collection (`watch-competitors`) is excluded from aggressive pruning while ad-hoc fetches expire normally.
5. A team's shared instance namespaces by user (`collection=alice`) so one person's cooking research doesn't pollute another's security audit.
6. Synthesis entries tagged `verified` vs `draft` let the answer endpoint (#18) prefer vetted knowledge.
7. An agent builds a `sources-for-report` collection during discovery, then generates the bibliography by listing exactly that collection.
8. Cache health per collection shows the "kubernetes-migration" knowledge base is 40 MB and 3 weeks stale — time to refresh just that slice.
9. A/B research: two competing approaches get sibling collections, and the final comparison searches each side independently for balanced evidence.
10. Exporting (idea #23) targets a collection, turning "everything about topic X" into a shareable artifact in one command.

## 23. Knowledge-pack export/import 🟢

**What:** `GET /cache/export?collection=…` streams a tar.zst of the selected
entries (markdown + metadata + a manifest with schema version), and
`POST /cache/import` ingests one (merge policies: `skip_existing`,
`overwrite`, `keep_newer`). CLI: `agentic-cache export research.pack` /
`import`.

**Why:** A researched cache is hours of agent work crystallized into files —
and it's currently trapped on one machine in a temp directory. Export/import
makes knowledge portable across machines, sharable between teammates, and
archivable with a project. It's also the pragmatic backup story (temp dirs
get wiped on reboot on many systems).

**Sketch:** Stream tar entries from the cache dir filtered by
collection/URL-pattern; manifest carries entry hashes for integrity and the
producing version. Import validates URLs through the existing normalizer,
rejects path-traversal names, and re-registers metadata (or DB rows with
#20). ~1 day including CLI.

**Use cases:**
1. A consultant researches a domain on their laptop, exports the pack, and imports it on the client-site workstation to continue with full cache context.
2. A team lead shares `k8s-migration.pack` so every teammate's agent answers from the same 200 vetted pages instead of re-fetching (and re-rate-limiting) independently.
3. Nightly cron exports the synthesis collection as a backup; a reboot that wipes `/tmp` costs nothing.
4. A CI documentation-checker imports a pre-built pack of upstream docs, running fully offline and deterministic in the pipeline.
5. An educator distributes a curated pack of course readings; students' agents answer questions from identical, verified sources.
6. Compliance archives the exact web evidence a report relied on, with content hashes, alongside the report itself.
7. An open-source maintainer publishes a "everything about our ecosystem" pack so contributors' agents onboard without hammering the project's docs site.
8. Moving from a laptop to a beefy homelab server, the user migrates months of accumulated cache in one export/import.
9. Two agents with different network permissions cooperate: the connected one exports fresh fetches, the air-gapped one imports and analyzes.
10. A reproducibility reviewer re-runs a published agent experiment against the archived pack, seeing exactly the web the original agent saw.

---

# E. Agent ergonomics & API

## 24. Fetch trace / explain mode 🟢

**What:** `trace: true` on `/fetch` adds a `trace` field to the response:
an ordered list of tier attempts —
`[{tier: "plugin:reddit", outcome: "no_match"}, {tier: "httpx", status: 403,
elapsed_ms: 210, outcome: "challenge_page"}, {tier: "curl_cffi", elapsed_ms:
890, outcome: "success"}]` — plus top-level `elapsed_ms` on **every**
response (trace or not).

**Why:** The waterfall is a black box. When a fetch is slow, thin, or wrong,
neither the agent nor the operator can see *why* without reading server
logs. A trace turns every fetch into its own diagnostic: agents can react
("challenge page → try archive fallback"), users get honest answers about
paywalls, and site-config maintainers see exactly which tier needs tuning.

**Sketch:** Thread a `trace: list[dict]` accumulator through
`FetchEngine.fetch()` (each tier appends attempt + outcome + timing); this
is pure bookkeeping in existing code paths, no behavior change. `elapsed_ms`
via one `time.monotonic()` pair. Also write the winning tier + total ms to
the fetch log for #28.

**Use cases:**
1. An agent whose fetch returned thin content reads `outcome: "challenge_page"` in the trace and pivots to the Wayback fallback instead of retrying blindly.
2. A user asks "why did that take 40 seconds?" and the agent answers precisely: httpx timed out (10s), curl_cffi got a challenge, zendriver rendered (28s).
3. The operator tunes `config.yaml` for a misbehaving domain armed with proof that Tier 2 always yields `needs_js` there — add it to a force-browser list.
4. A plugin author debugging their matcher sees `plugin:mysite → exception` with the message inline instead of ssh-ing into logs.
5. The research skill's batch triage sorts URLs by `elapsed_ms` and marks chronically slow domains for lower-priority fetching.
6. A latency SLO dashboard (#28) is fed by per-tier timings without any additional instrumentation work.
7. During an incident ("all fetches slow"), one traced fetch distinguishes browser-pool saturation from upstream network trouble in seconds.
8. An agent explains a paywall honestly to the user — "the site returned a subscriber wall (tier trace attached)" — rather than presenting teaser text as the article.
9. Regression testing asserts that `reddit.com` URLs resolve at `plugin` tier; a trace showing `httpx` catches a broken matcher before users do.
10. Cost-aware orchestration learns that a domain always ends at zendriver and sets `force_browser: true` upfront, saving two doomed tier attempts per fetch.

## 25. Async job queue for large batches 🔴

**What:** `POST /jobs {type: "batch_fetch", urls: [...up to 5000],
options}` → `{job_id}`; `GET /jobs/{id}` → status with progress
(`done/total`, failures, ETA); `GET /jobs/{id}/results?offset=` pages
results; `DELETE /jobs/{id}` cancels. Jobs persist to disk and resume after
a service restart. Optional completion webhook.

**Why:** `/fetch/batch` caps at 50 URLs and holds the HTTP connection open
— right for interactive use, wrong for "index this entire docs site"
(hundreds of URLs, many minutes). Agents need fire-and-forget: submit,
continue working, poll. Restart-persistence matters because big jobs are
exactly the ones that hit a service redeploy.

**Sketch:** `jobs.py`: an asyncio worker pool consuming a
JSONL-journaled queue in the cache dir (crash-safe, no new infra); reuse the
existing per-URL fetch path and politeness scheduler (#29). Results are
stored as cache entries anyway — the results endpoint returns metadata
summaries. Job records pruned after `AF_JOB_RETENTION_DAYS`.

**Use cases:**
1. An agent indexes a 600-page documentation site: submits one job, keeps interacting with the user, and starts `/cache/answer` queries as pages land.
2. A nightly cron job re-fetches the 400 URLs of a monitored competitor set, and the morning agent reads the results without triggering any fetches.
3. A migration team primes the cache with every page of their legacy wiki before a workshop, tracking progress on the jobs endpoint.
4. A service redeploy mid-crawl doesn't lose 45 minutes of work — the job resumes from its journal.
5. An academic bulk-fetches 2,000 arXiv abstract pages for a literature survey with per-domain politeness keeping the crawl civil.
6. The research skill escalates: interactive batch for 20 URLs, background job for the 300-URL "index everything this page links to" request.
7. A completion webhook pings an n8n/Zapier flow that kicks off the analysis agent the moment the crawl finishes.
8. A rate-limited API domain is crawled slowly (politeness scheduler) over 2 hours as a job, which would be impossible in a single HTTP request lifetime.
9. Ops cancels a runaway job started with a bad URL pattern before it wastes an hour of browser-pool time.
10. A weekly "refresh all synthesis source pages" job keeps the knowledge base warm with zero human involvement.

## 26. URL watch & change notifications 🔴

**What:** `POST /watch {url, interval: "6h", notify: {webhook | log},
threshold: 0.05}` — the service re-fetches on schedule (with ETag/304
efficiency), compares against the cached/versioned copy, and on meaningful
change (normalized diff ratio above threshold, ignoring boilerplate lines)
records a change event and fires the webhook. `GET /watch` lists watches
with last-change info; `GET /watch/{id}/events` gives the change history.

**Why:** "Tell me when this changes" is a top-3 recurring user request that
agents currently fake with manual re-fetching — which only works while a
session is alive. The service is the natural home: it's long-running, owns
the cache and versions (#19), and can watch efficiently (conditional
requests) around the clock.

**Sketch:** `watch.py`: an asyncio scheduler loop over watch records
persisted as JSON in the cache dir; each tick reuses `FetchEngine` with
`no_cache=true`, then rotates versions and computes a line-diff ratio
against the previous copy (excluding lines matching global `strip_lines`).
Webhook POSTs `{url, changed_at, diff_ratio, added: [...first 20 lines],
removed: [...]}`.

**Use cases:**
1. A DevRel agent watches a partner's API changelog page and posts to Slack (webhook) the moment new deprecations appear.
2. A shopper watches a product page at 2h intervals and gets pinged when "Out of stock" flips.
3. Legal watches a regulator's guidance page; the compliance agent summarizes the diff into an internal memo the same hour it changes.
4. An open-source maintainer watches a dependency's security-advisories page — faster than waiting for the ecosystem scanner's weekly run.
5. A job seeker watches a company's careers page for postings matching their role, checked every 6 hours.
6. An SRE watches three vendors' status pages during a multi-cloud incident, getting diffs instead of manually refreshing tabs.
7. A researcher watches a conference CFP page for the "notification date" edit that always arrives late.
8. A PR team watches their Wikipedia article for edits, receiving the added/removed lines for review.
9. A localization manager watches the English source page of a translated site so translations start the day the source changes.
10. A landlord-hunting agent watches a rental listings page overnight and wakes the user's phone (webhook → push) when a new unit appears — beating everyone who checks in the morning.

## 27. Native MCP server mode 🟡

**What:** Ship the service as an MCP (Model Context Protocol) server:
`agentic-fetch-mcp` (stdio) and an HTTP/SSE transport on the existing port
(`/mcp`). Tools mirror the API 1:1 — `search`, `fetch`, `fetch_batch`,
`grep`, `read_lines`, `cache_search`, `cache_write` — with descriptions
tuned from the research skill's guidance, plus the cache index exposed as
MCP *resources*.

**Why:** Skills + curl work only inside Claude Code. MCP is the lingua
franca: Claude Desktop, Cursor, Windsurf, LibreChat, and custom Agent-SDK
apps all speak it. One thin adapter multiplies the audience of every feature
in this roadmap, and typed tool schemas beat "here's a curl snippet" for
reliability — models mis-quote JSON in bash far more often than they mis-call
a tool.

**Sketch:** `mcp_server.py` using the official `mcp` Python SDK: each tool
handler calls the existing engine functions in-process (no HTTP hop for
stdio mode); tool descriptions embed the pagination/caching workflow hints;
resources map `cache://` URIs to cached markdown. Entry point in
`pyproject.toml`; ~300 lines.

**Use cases:**
1. A Claude Desktop user adds one line to their MCP config and gets cached, paginated, plugin-accelerated fetching in every conversation — no terminal involved.
2. A Cursor user's coding agent greps a library's cached docs mid-completion via MCP tools instead of pasting docs into the prompt.
3. An Agent SDK application ships agentic-fetch as its web layer, inheriting the whole tier waterfall without writing fetch code.
4. Tool-schema typing eliminates a class of agent errors: `max_tokens` is an integer field the model fills, not JSON it string-escapes into curl.
5. The MCP resource list turns the cache index into a browsable sidebar in clients that render resources, making the knowledge base visible to the user.
6. A LibreChat self-hoster gives every user in their org the same shared research cache through one MCP endpoint.
7. Multi-agent systems hand the same MCP server to a researcher agent and a writer agent — shared cache, no duplicated fetches, consistent citations.
8. A security-conscious org exposes only `cache_search`/`read_lines` tools (no live fetch) to a low-trust agent, using MCP's tool filtering.
9. The stdio transport means a laptop user gets all of it with zero open ports — relevant for locked-down corporate machines.
10. Claude Code itself can drop the curl-based skill for direct tool calls, cutting the per-request token overhead of bash quoting and JSON escaping.

---

# F. Operations

## 28. Prometheus metrics & structured logging 🟢

**What:** `GET /metrics` (Prometheus text format): counters
(`af_fetch_total{tier,outcome,domain_bucket}`, `af_search_total{engine}`,
`af_cache_events{hit|miss|write|evict}`), histograms
(`af_fetch_duration_seconds{tier}`, `af_extraction_score`), gauges
(`af_browser_tabs_in_use`, `af_cache_entries`, `af_cache_bytes`). Plus
`AF_LOG_FORMAT=json` for structured logs with request IDs.

**Why:** "Production ready" ends at observability today: one log stream and
a health endpoint. Whether the browser pool is saturating, which tier wins
how often, cache hit rate, and p95 latency are all unknowable without
grepping logs. Metrics make regressions visible *before* users feel them and
make every tuning decision (tab count, TTLs, timeouts) data-driven.

**Sketch:** `prometheus-client` (tiny, no deps) with a `metrics.py` module;
instrument the fetch waterfall (pairs naturally with #24's timing hooks),
search dispatch, cache methods, and `BrowserPool.acquire_tab`. JSON logging
via a stdlib `logging.Formatter`. Grafana dashboard JSON checked into
`ops/`.

**Use cases:**
1. The operator sees cache hit rate drop from 60%→10% after a TTL misconfiguration and fixes it the same hour, not after a slow week.
2. An alert on `af_browser_tabs_in_use == max for 5m` catches pool saturation and prompts raising `AF_MAX_BROWSER_TABS` before requests start timing out.
3. p95 fetch latency per tier shows curl_cffi degrading after a dependency upgrade — pinned and rolled back with evidence.
4. Tier-win rates reveal that 30% of fetches end at zendriver for one domain bucket; a plugin for that domain gets prioritized with data, not vibes.
5. A capacity plan for a team deployment is based on real requests/minute and duration histograms rather than guesses.
6. The extraction-score histogram (#12) trends down for `method=httpx` one week — early warning that a bot-detection vendor changed something globally.
7. JSON logs with request IDs let a support engineer trace one user's failed fetch through tiers in a log aggregator in seconds.
8. Cache-size gauge trends predict disk exhaustion on a small VPS a week out, triggering a prune-policy adjustment.
9. A Grafana dashboard on a wall shows fetch volume per engine during a company research sprint, making rate-limit risk visible before Reddit bans the IP.
10. After deploying idea #15, `af_search_total{engine}` proves fused search halved Google browser usage — validating the change quantitatively.

## 29. Per-domain politeness scheduler 🟡

**What:** A per-host token-bucket rate limiter in front of all outbound
requests (default: 1 req/sec/host, burst 3; configurable per domain in
`config.yaml`), honoring `Retry-After` headers with in-process backoff and
tracking a per-host cooldown after 429/403 responses. Batch and job fetches
interleave hosts so no single site gets hammered.

**Why:** `/fetch/batch` with 20 URLs from one docs site currently fires
near-simultaneously — exactly the pattern that triggers WAF bans and burns
the IP for hours. Agents can't coordinate politeness; the service is the
only place with a global view. Being a good citizen is also self-interest:
banned IPs are the #1 way this service degrades permanently.

**Sketch:** `throttle.py`: `async def acquire(host)` keyed on registrable
domain, token buckets in-process; wrap `get_client().get` calls and browser
navigations. 429 handling moves from `search.py`'s local retry into the
shared layer (dedup win). Batch's semaphore composes with it: concurrency
caps parallelism, throttle shapes per-host pacing.

**Use cases:**
1. A 40-URL batch against one documentation site paces at 1/sec and completes clean, where today it trips Cloudflare after request 8 and poisons the rest.
2. Reddit's 429 sets a shared cooldown, so the buzz skill's three parallel Reddit calls don't each independently slam into the limit and triple the penalty.
3. A big job (#25) mixing 10 domains fetches round-robin across hosts — full overall throughput, gentle per-site footprint.
4. The user's home IP stays unbanned from their favorite forum even after an enthusiastic "index this whole site" request.
5. A `github.com: 5/sec` override in config exploits the authenticated rate limit fully while defaults protect small blogs.
6. `Retry-After: 120` from an API is respected once, centrally — instead of three call sites implementing three different backoffs.
7. Two concurrent agent sessions sharing the service transparently share the per-host budget, preventing their combined traffic from looking like an attack.
8. A watch schedule (#26) with twelve URLs on one news site spreads its checks instead of firing all twelve at the top of the hour.
9. Crawl-delay from robots.txt (paired with the existing ideas.md item) maps directly onto the same bucket configuration.
10. During a rate-limit cooldown, fetches to that host fail fast with a clear "cooling down 90s for example.com" error the agent can relay or schedule around, instead of hanging.

## 30. Service auth & per-key quotas 🟢

**What:** Optional bearer-token auth (`AF_API_KEYS=key1:alice,key2:bob`):
when set, all endpoints except `/health` require
`Authorization: Bearer …`. Per-key request-rate and browser-tab-time
quotas, per-key attribution in the fetch log and metrics, and per-key
default collection (#22). Off by default for the localhost single-user case.

**Why:** Every multi-user idea above (shared team cache, MCP endpoint,
watches, jobs) assumes the service might be reachable by more than one
trusted process — and today anyone who can reach the port can evict the
cache, burn the browser pool, and use the machine's IP to fetch anything.
Auth is the gate that makes deploying beyond `localhost` responsible, and
quotas keep one greedy agent from starving the rest.

**Sketch:** FastAPI dependency checking a constant-time token compare;
in-memory token buckets per key (reuse #29's bucket code); key name injected
into log records and metric labels. `AF_ADMIN_KEYS` for cache-destructive
endpoints (`evict`, `prune`, `collections delete`). ~½ day plus tests.

**Use cases:**
1. A five-person team shares one beefy instance; each member's key scopes their default collection and shows up in the fetch log for accountability.
2. The instance is deployed on a Tailscale network — auth adds a second layer so a compromised peer device can't silently use the browser pool.
3. A greedy experimental agent with a 100-req/min habit hits its key's quota and backs off, while the on-call agent's key keeps working during an incident.
4. The admin key separation means a junior teammate's agent can read and fetch but can't `prune` away the team's accumulated knowledge base.
5. An MCP endpoint (#27) exposed to a low-trust internal tool gets a key limited to cache-read tools' rate, making the trust boundary explicit.
6. Usage attribution answers "who fetched 4 GB from that vendor's site" during a politeness incident review.
7. A CI pipeline gets its own key with a tight quota so a misconfigured test loop can't consume the team's Reddit rate-limit budget.
8. Rotating a leaked key is a one-env-var change that doesn't disturb other users — versus today's option of firewalling the whole service.
9. A hosted "research cache as a service" for a small community becomes feasible: keys are the billing/abuse boundary.
10. Metrics per key (#28) show which team's agents benefit most from the cache, informing whose workflows to optimize next.

---

## Suggested sequencing

| Wave | Ideas | Theme |
|---|---|---|
| 1 (quick wins) | 3, 4, 10, 12, 13, 14, 15, 21, 22, 24, 28, 30 | 🟢 small, immediately felt by agents |
| 2 (capability) | 1, 2, 5, 6, 8, 9, 11, 17, 18, 19, 20, 23, 29 | new content types + knowledge base maturity |
| 3 (platform) | 7, 16, 25, 26, 27 | multi-user, always-on, ecosystem reach |

Dependencies worth respecting: **19 → 26** (versions before watch),
**24 → 28** (trace timings feed metrics), **22 → 23/30** (collections before
export and per-key scoping), **29 → 25** (politeness before big jobs),
**20** unlocks fast paths for **18/21/22** at scale.

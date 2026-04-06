import asyncio
import json as _json
import os
import httpx
from html import unescape
from datetime import datetime
from urllib.parse import quote_plus
from bs4 import BeautifulSoup

from .models import SearchRequest, SearchResponse, SearchResult
from .browser import browser_pool

_GITHUB_HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "agentic-fetch/1.0",
}
_REDDIT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
}
_TREND_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Retry budget for rate-limited engines (Reddit, GitHub, HN)
_RETRY_ATTEMPTS = 2
_RETRY_BACKOFF = 2.0  # seconds


def _decode_json(r: httpx.Response) -> dict:
    """Decode JSON from raw bytes to avoid CP1252/Latin-1 misdetection on Windows."""
    return _json.loads(r.content)


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict | None = None,
    attempts: int = _RETRY_ATTEMPTS,
    backoff: float = _RETRY_BACKOFF,
) -> httpx.Response:
    """GET with automatic retry on 429 Rate Limit responses."""
    for attempt in range(attempts):
        r = await client.get(url, params=params)
        if r.status_code != 429 or attempt == attempts - 1:
            return r
        retry_after = float(r.headers.get("Retry-After", backoff * (attempt + 1)))
        await asyncio.sleep(retry_after)
    return r  # unreachable but satisfies type checker


class SearchEngine:
    async def search(self, req: SearchRequest) -> SearchResponse:
        if req.engine == "reddit":
            return await self._reddit(req)
        if req.engine == "github":
            return await self._github(req)
        if req.engine == "hackernews":
            return await self._hackernews(req)
        if req.engine in ("auto", "google"):
            try:
                return await self._google(req)
            except Exception:
                if req.engine == "google":
                    raise
        return await self._duckduckgo(req)

    # ── Google ────────────────────────────────────────────────────────────────

    async def _google(self, req: SearchRequest) -> SearchResponse:
        url = f"https://www.google.com/search?q={quote_plus(req.query)}&num={req.max_results}"
        tbs = self._google_tbs(req)
        if tbs:
            url += f"&tbs={tbs}"
        html, _, _ = await browser_pool.get_html(url)
        results = self._parse_google(html, req.max_results)
        return SearchResponse(query=req.query, engine_used="google", results=results)

    def _google_tbs(self, req: SearchRequest) -> str:
        """Build the tbs= query parameter for Google date filtering."""
        if req.date_preset:
            return {
                "past_hour": "qdr:h",
                "past_day": "qdr:d",
                "past_week": "qdr:w",
                "past_month": "qdr:m",
                "past_year": "qdr:y",
            }[req.date_preset]
        if req.date_from or req.date_to:
            def _fmt(d: str) -> str:
                return datetime.fromisoformat(d).strftime("%m/%d/%Y")
            cd_min = _fmt(req.date_from) if req.date_from else ""
            cd_max = _fmt(req.date_to) if req.date_to else ""
            return f"cdr:1,cd_min:{cd_min},cd_max:{cd_max}"
        return ""

    # ── DuckDuckGo ────────────────────────────────────────────────────────────

    async def _duckduckgo(self, req: SearchRequest) -> SearchResponse:
        url = f"https://duckduckgo.com/?q={quote_plus(req.query)}&ia=web"
        html, _, _ = await browser_pool.get_html(url)
        results = self._parse_ddg(html, req.max_results)
        return SearchResponse(query=req.query, engine_used="duckduckgo", results=results)

    # ── Reddit ────────────────────────────────────────────────────────────────

    async def _reddit(self, req: SearchRequest) -> SearchResponse:
        sort = req.sort or "relevance"
        time_filter = req.time_filter or "all"

        # Parse 'subreddit:Name' prefix from query
        query = req.query.strip()
        subreddit = req.subreddit
        if not subreddit:
            import re as _re
            m = _re.match(r"subreddit:(\w+)\s*", query, _re.IGNORECASE)
            if m:
                subreddit = m.group(1)
                query = query[m.end():].strip()

        # When browsing a subreddit with no search query, use listing endpoint
        if subreddit and not query:
            listing_sort = sort if sort in ("hot", "new", "top", "rising") else "hot"
            listing_params: dict = {"limit": req.max_results}
            if listing_sort == "top" and time_filter:
                listing_params["t"] = time_filter
            json_url = f"https://www.reddit.com/r/{subreddit}/{listing_sort}.json"
            try:
                async with httpx.AsyncClient(
                    headers=_REDDIT_HEADERS, follow_redirects=True, timeout=30
                ) as c:
                    r = await _get_with_retry(c, json_url, params=listing_params)
                    if r.status_code == 429:
                        return SearchResponse(
                            query=req.query, engine_used=f"reddit/r/{subreddit}", results=[],
                            error="Reddit rate limit (429). Try again in a few seconds.",
                        )
                    if r.headers.get("content-type", "").startswith("text/html"):
                        return SearchResponse(
                            query=req.query, engine_used=f"reddit/r/{subreddit}", results=[],
                            error="Reddit blocked the request (returned HTML). Retry shortly.",
                        )
                    r.raise_for_status()
                    data = _decode_json(r)
            except httpx.HTTPStatusError as e:
                return SearchResponse(
                    query=req.query, engine_used=f"reddit/r/{subreddit}", results=[],
                    error=f"Reddit HTTP {e.response.status_code}: {e.response.text[:200]}",
                )
            except httpx.RequestError as e:
                return SearchResponse(
                    query=req.query, engine_used=f"reddit/r/{subreddit}", results=[],
                    error=f"Reddit request failed: {e}",
                )

            results = []
            for child in data.get("data", {}).get("children", []):
                if child.get("kind") != "t3":
                    continue
                post = child.get("data", {})
                title = unescape(post.get("title", ""))
                permalink = post.get("permalink", "")
                url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink
                sub = post.get("subreddit", "")
                author = post.get("author", "")
                score = post.get("score", 0)
                num_comments = post.get("num_comments", 0)
                created = datetime.utcfromtimestamp(post.get("created_utc", 0)).strftime("%Y-%m-%d")
                snippet = (f"**r/{sub}** · u/{author} · {created} "
                           f"· {score:,} pts · {num_comments:,} comments")
                selftext = post.get("selftext", "")
                if selftext and selftext not in ("[deleted]", "[removed]"):
                    preview = unescape(selftext)[:200]
                    snippet += f"\n> {preview}{'…' if len(selftext) > 200 else ''}"
                results.append(SearchResult(title=title, url=url, snippet=snippet))

            return SearchResponse(query=req.query, engine_used=f"reddit/r/{subreddit}", results=results)

        params: dict = {
            "q": query,
            "type": "link",
            "sort": sort,
            "t": time_filter,
            "limit": req.max_results,
        }

        # Scope search to subreddit when specified
        if subreddit:
            search_url = f"https://www.reddit.com/r/{subreddit}/search.json"
            params["restrict_sr"] = "1"
        else:
            search_url = "https://www.reddit.com/search.json"

        # date_from / date_to are not supported by Reddit's search API
        unsupported = []
        if req.date_from:
            unsupported.append(f"date_from={req.date_from}")
        if req.date_to:
            unsupported.append(f"date_to={req.date_to}")
        warning = (f"Reddit search does not support exact date ranges "
                   f"({', '.join(unsupported)} ignored). "
                   f"Use time_filter=hour|day|week|month|year instead."
                   ) if unsupported else None

        try:
            async with httpx.AsyncClient(
                headers=_REDDIT_HEADERS, follow_redirects=True, timeout=30
            ) as c:
                r = await _get_with_retry(c, search_url, params=params)
                if r.status_code == 429:
                    return SearchResponse(
                        query=req.query, engine_used="reddit", results=[],
                        error=f"Reddit rate limit (429). Try again in a few seconds.",
                    )
                if r.headers.get("content-type", "").startswith("text/html"):
                    return SearchResponse(
                        query=req.query, engine_used="reddit", results=[],
                        error="Reddit blocked the request (returned HTML). "
                              "The service may be rate-limited; retry shortly.",
                    )
                r.raise_for_status()
                data = _decode_json(r)
        except httpx.HTTPStatusError as e:
            return SearchResponse(
                query=req.query, engine_used="reddit", results=[],
                error=f"Reddit HTTP {e.response.status_code}: {e.response.text[:200]}",
            )
        except httpx.RequestError as e:
            return SearchResponse(
                query=req.query, engine_used="reddit", results=[],
                error=f"Reddit request failed: {e}",
            )

        results = []
        for child in data.get("data", {}).get("children", []):
            if child.get("kind") != "t3":
                continue
            post = child.get("data", {})
            title = unescape(post.get("title", ""))
            permalink = post.get("permalink", "")
            url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink
            post_subreddit = post.get("subreddit", "")
            author = post.get("author", "")
            score = post.get("score", 0)
            num_comments = post.get("num_comments", 0)
            created = datetime.utcfromtimestamp(post.get("created_utc", 0)).strftime("%Y-%m-%d")
            snippet = (f"**r/{post_subreddit}** · u/{author} · {created} "
                       f"· {score:,} pts · {num_comments:,} comments")
            selftext = post.get("selftext", "")
            if selftext and selftext not in ("[deleted]", "[removed]"):
                preview = unescape(selftext)[:200]
                snippet += f"\n> {preview}{'…' if len(selftext) > 200 else ''}"
            results.append(SearchResult(title=title, url=url, snippet=snippet))

        engine_used = f"reddit/r/{subreddit}" if subreddit else "reddit"
        return SearchResponse(
            query=req.query, engine_used=engine_used, results=results, error=warning
        )

    # ── GitHub ────────────────────────────────────────────────────────────────

    async def _github(self, req: SearchRequest) -> SearchResponse:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("AF_GITHUB_TOKEN", "")
        headers = {**_GITHUB_HEADERS}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        q = req.query.strip()
        if not q or q.lower() in ("trending", "trending repos", "trending repositories"):
            return await self._github_trending(req)

        if (req.search_type or "repositories") == "code":
            return await self._github_search_code(req, headers, q)
        return await self._github_search_repos(req, headers, q)

    async def _github_trending(self, req: SearchRequest) -> SearchResponse:
        lang = req.language or ""
        period = req.period or "daily"
        trend_url = f"https://github.com/trending/{lang}" if lang else "https://github.com/trending"

        try:
            async with httpx.AsyncClient(
                headers=_TREND_HEADERS, timeout=15, follow_redirects=True
            ) as c:
                r = await _get_with_retry(c, trend_url, params={"since": period})
                if r.status_code == 429:
                    return SearchResponse(
                        query=req.query, engine_used="github trending", results=[],
                        error="GitHub rate limit (429). Set GITHUB_TOKEN for higher limits.",
                    )
                r.raise_for_status()
        except httpx.HTTPStatusError as e:
            return SearchResponse(
                query=req.query, engine_used="github trending", results=[],
                error=f"GitHub trending HTTP {e.response.status_code}: {e.response.text[:200]}",
            )
        except httpx.RequestError as e:
            return SearchResponse(
                query=req.query, engine_used="github trending", results=[],
                error=f"GitHub trending request failed: {e}",
            )

        soup = BeautifulSoup(r.text, "html.parser")
        period_label = {"daily": "today", "weekly": "this week", "monthly": "this month"}.get(period, period)
        results = []

        for article in soup.select("article.Box-row"):
            h2_a = article.select_one("h2 a, h1 a")
            if not h2_a:
                continue
            repo_path = h2_a.get("href", "").strip()
            parts = repo_path.strip("/").split("/")
            if len(parts) != 2:
                continue
            owner, repo_name = parts

            desc_el = article.select_one("p")
            description = desc_el.get_text(strip=True) if desc_el else ""
            lang_el = article.select_one("[itemprop='programmingLanguage']")
            language_name = lang_el.get_text(strip=True) if lang_el else ""
            stars_el = article.select_one("a[href$='/stargazers']")
            stars = stars_el.get_text(strip=True) if stars_el else "0"
            forks_el = article.select_one("a[href$='/forks'], a[href$='/network/members']")
            forks = forks_el.get_text(strip=True) if forks_el else "0"
            period_stars = ""
            for span in article.select("span"):
                t = span.get_text(strip=True)
                if any(kw in t for kw in ("stars today", "star today", "stars this week", "stars this month")):
                    period_stars = t
                    break

            repo_url = f"https://github.com/{owner}/{repo_name}"
            snippet = f"★ {stars.strip()} total"
            if period_stars:
                snippet += f" · ★ {period_stars}"
            if forks.strip():
                snippet += f" · {forks.strip()} forks"
            if language_name:
                snippet += f" · {language_name}"
            if description:
                snippet += f"\n{description}"

            results.append(SearchResult(title=f"{owner}/{repo_name}", url=repo_url, snippet=snippet))
            if len(results) >= req.max_results:
                break

        engine_label = f"github trending{' ' + lang if lang else ''} ({period_label})"
        return SearchResponse(query=req.query, engine_used=engine_label, results=results)

    async def _github_search_repos(self, req: SearchRequest, headers: dict, q: str) -> SearchResponse:
        if req.language:
            q += f" language:{req.language}"
        if req.date_from and req.date_to:
            q += f" created:{req.date_from}..{req.date_to}"
        elif req.date_from:
            q += f" created:>{req.date_from}"
        elif req.date_to:
            q += f" created:<{req.date_to}"

        sort = req.sort or "stars"
        params: dict = {"q": q, "sort": sort, "order": "desc", "per_page": req.max_results}

        try:
            async with httpx.AsyncClient(headers=headers, timeout=15) as c:
                r = await _get_with_retry(c, "https://api.github.com/search/repositories", params=params)
                if r.status_code == 429:
                    return SearchResponse(
                        query=req.query, engine_used="github", results=[],
                        error="GitHub API rate limit (429). Set GITHUB_TOKEN for 5,000 req/hr.",
                    )
                if r.status_code == 403:
                    msg = _decode_json(r).get("message", r.text[:200])
                    return SearchResponse(
                        query=req.query, engine_used="github", results=[],
                        error=f"GitHub API forbidden (403): {msg}. Set GITHUB_TOKEN.",
                    )
                r.raise_for_status()
                data = _decode_json(r)
        except httpx.HTTPStatusError as e:
            return SearchResponse(
                query=req.query, engine_used="github", results=[],
                error=f"GitHub HTTP {e.response.status_code}: {e.response.text[:200]}",
            )
        except httpx.RequestError as e:
            return SearchResponse(
                query=req.query, engine_used="github", results=[],
                error=f"GitHub request failed: {e}",
            )

        results = []
        for item in data.get("items", []):
            stars = item.get("stargazers_count", 0)
            forks = item.get("forks_count", 0)
            lang = item.get("language") or ""
            desc = item.get("description") or ""
            updated = (item.get("updated_at") or "")[:10]
            snippet = f"**{stars:,}** stars · {forks:,} forks · {lang} · updated {updated}"
            if desc:
                snippet += f"\n{desc}"
            results.append(SearchResult(
                title=f"{item['full_name']} ★{stars:,}",
                url=item["html_url"],
                snippet=snippet,
            ))

        return SearchResponse(query=req.query, engine_used="github", results=results)

    async def _github_search_code(self, req: SearchRequest, headers: dict, q: str) -> SearchResponse:
        if req.language:
            q += f" language:{req.language}"
        params: dict = {"q": q, "per_page": req.max_results}

        try:
            async with httpx.AsyncClient(headers=headers, timeout=15) as c:
                r = await _get_with_retry(c, "https://api.github.com/search/code", params=params)
                if r.status_code == 401:
                    return SearchResponse(
                        query=req.query, engine_used="github-code", results=[],
                        error="GitHub code search requires authentication. "
                              "Set GITHUB_TOKEN or AF_GITHUB_TOKEN env var.",
                    )
                if r.status_code == 403:
                    msg = _decode_json(r).get("message", r.text[:200])
                    return SearchResponse(
                        query=req.query, engine_used="github-code", results=[],
                        error=f"GitHub code search forbidden (403): {msg}. "
                              "Set GITHUB_TOKEN or AF_GITHUB_TOKEN env var.",
                    )
                if r.status_code == 429:
                    return SearchResponse(
                        query=req.query, engine_used="github-code", results=[],
                        error="GitHub API rate limit (429). Set GITHUB_TOKEN for 5,000 req/hr.",
                    )
                r.raise_for_status()
                data = _decode_json(r)
        except httpx.HTTPStatusError as e:
            return SearchResponse(
                query=req.query, engine_used="github-code", results=[],
                error=f"GitHub code HTTP {e.response.status_code}: {e.response.text[:200]}",
            )
        except httpx.RequestError as e:
            return SearchResponse(
                query=req.query, engine_used="github-code", results=[],
                error=f"GitHub code request failed: {e}",
            )

        results = []
        for item in data.get("items", []):
            repo = item["repository"]
            title = f"{item['path']} — {repo['full_name']}"
            snippet = f"**{repo['full_name']}**"
            if repo.get("description"):
                snippet += f" · {repo['description']}"
            results.append(SearchResult(title=title, url=item["html_url"], snippet=snippet))

        return SearchResponse(query=req.query, engine_used="github-code", results=results)

    # ── HackerNews ────────────────────────────────────────────────────────────

    async def _hackernews(self, req: SearchRequest) -> SearchResponse:
        story_type = req.story_type or "story"
        params: dict = {
            "query": req.query,
            "tags": story_type,
            "hitsPerPage": req.max_results,
        }
        numeric_filters: list[str] = []
        if req.min_points is not None:
            numeric_filters.append(f"points>={req.min_points}")
        if req.min_comments is not None:
            numeric_filters.append(f"num_comments>={req.min_comments}")
        if req.date_from:
            ts = int(datetime.fromisoformat(req.date_from).timestamp())
            numeric_filters.append(f"created_at_i>={ts}")
        if req.date_to:
            ts = int(datetime.fromisoformat(req.date_to).timestamp())
            numeric_filters.append(f"created_at_i<={ts}")
        if numeric_filters:
            params["numericFilters"] = ",".join(numeric_filters)

        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await _get_with_retry(c, "https://hn.algolia.com/api/v1/search", params=params)
                if r.status_code == 429:
                    return SearchResponse(
                        query=req.query, engine_used="hackernews", results=[],
                        error="HackerNews (Algolia) rate limit (429). Retry in a few seconds.",
                    )
                r.raise_for_status()
                data = _decode_json(r)
        except httpx.HTTPStatusError as e:
            return SearchResponse(
                query=req.query, engine_used="hackernews", results=[],
                error=f"HackerNews HTTP {e.response.status_code}: {e.response.text[:200]}",
            )
        except httpx.RequestError as e:
            return SearchResponse(
                query=req.query, engine_used="hackernews", results=[],
                error=f"HackerNews request failed: {e}",
            )

        results = []
        for hit in data.get("hits", []):
            raw_title = (hit.get("title")
                         or hit.get("story_title")
                         or (hit.get("comment_text") or "")[:80])
            title = raw_title + ("…" if hit.get("comment_text") and len(hit["comment_text"]) > 80 else "")
            object_id = hit.get("objectID", "")
            hn_url = f"https://news.ycombinator.com/item?id={object_id}"
            story_url = hit.get("url") or hn_url
            points = hit.get("points") or 0
            num_comments = hit.get("num_comments") or 0
            author = hit.get("author", "")
            created = (hit.get("created_at") or "")[:10]
            snippet = f"**{points}** pts · {num_comments} comments · {author} · {created}"
            if hit.get("url"):
                snippet += f"\n[HN discussion]({hn_url})"
            results.append(SearchResult(title=title, url=story_url, snippet=snippet))

        return SearchResponse(query=req.query, engine_used="hackernews", results=results)

    # ── Parsers ───────────────────────────────────────────────────────────────

    def _parse_google(self, html: str, limit: int) -> list[SearchResult]:
        soup = BeautifulSoup(html, "html.parser")
        results = []
        cards = soup.select("div.yuRUbf") or soup.select("div.g")
        for card in cards[:limit * 2]:
            a = card.select_one("a[href]")
            title_el = card.select_one("h3")
            if not a or not title_el:
                continue
            href = a["href"]
            if href.startswith("/url?"):
                from urllib.parse import parse_qs, urlparse
                href = parse_qs(urlparse(href).query).get("q", [href])[0]
            if not href.startswith("http"):
                continue
            snippet_el = None
            ancestor = card.parent
            for _ in range(4):
                if ancestor is None:
                    break
                snippet_el = ancestor.select_one(".VwiC3b, [data-sncf], span.st")
                if snippet_el:
                    break
                ancestor = ancestor.parent
            results.append(SearchResult(
                title=title_el.get_text(strip=True),
                url=href,
                snippet=(snippet_el.get_text(strip=True) if snippet_el else ""),
            ))
            if len(results) >= limit:
                break
        return results

    def _parse_ddg(self, html: str, limit: int) -> list[SearchResult]:
        soup = BeautifulSoup(html, "html.parser")
        results = []
        for card in soup.select("article[data-testid='result']"):
            title_el = card.select_one("h2 a")
            snippet_el = card.select_one("[data-result='snippet']")
            if not title_el:
                continue
            href = title_el.get("href", "")
            if not href.startswith("http"):
                continue
            results.append(SearchResult(
                title=title_el.get_text(strip=True),
                url=href,
                snippet=(snippet_el.get_text(strip=True) if snippet_el else ""),
            ))
            if len(results) >= limit:
                break
        return results


search_engine = SearchEngine()

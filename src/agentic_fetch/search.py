import httpx
from urllib.parse import quote_plus
from bs4 import BeautifulSoup

from .models import SearchRequest, SearchResponse, SearchResult
from .browser import browser_pool


class SearchEngine:
    async def search(self, req: SearchRequest) -> SearchResponse:
        if req.engine in ("auto", "google"):
            try:
                return await self._google(req)
            except Exception:
                if req.engine == "google":
                    raise
        return await self._duckduckgo(req)

    async def _google(self, req: SearchRequest) -> SearchResponse:
        url = f"https://www.google.com/search?q={quote_plus(req.query)}&num={req.max_results}"
        html, _, _ = await browser_pool.get_html(url)
        results = self._parse_google(html, req.max_results)
        return SearchResponse(query=req.query, engine_used="google", results=results)

    async def _duckduckgo(self, req: SearchRequest) -> SearchResponse:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(req.query)}"
        async with httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/132.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://duckduckgo.com/",
            },
            follow_redirects=True, timeout=10,
        ) as c:
            r = await c.get(url)
            r.raise_for_status()
        results = self._parse_ddg(r.text, req.max_results)
        return SearchResponse(query=req.query, engine_used="duckduckgo", results=results)

    def _parse_google(self, html: str, limit: int) -> list[SearchResult]:
        soup = BeautifulSoup(html, "html.parser")
        results = []
        for card in soup.select("div.g")[:limit * 2]:
            a = card.select_one("a[href]")
            title_el = card.select_one("h3")
            snippet_el = card.select_one("div.VwiC3b, span.st, div[data-sncf]")
            if not a or not title_el:
                continue
            href = a["href"]
            if href.startswith("/url?"):
                from urllib.parse import parse_qs, urlparse
                href = parse_qs(urlparse(href).query).get("q", [href])[0]
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

    def _parse_ddg(self, html: str, limit: int) -> list[SearchResult]:
        from urllib.parse import parse_qs, urlparse, unquote
        soup = BeautifulSoup(html, "html.parser")
        results = []
        for card in soup.select(".result.results_links_deep")[:limit]:
            title_el = card.select_one(".result__title a")
            snippet_el = card.select_one(".result__snippet")
            if not title_el:
                continue
            href = title_el.get("href", "")
            # Normalise protocol-relative URLs
            if href.startswith("//"):
                href = "https:" + href
            # Unwrap DDG redirect URLs: //duckduckgo.com/l/?uddg=<encoded-url>
            if "duckduckgo.com/l/" in href:
                qs = parse_qs(urlparse(href).query)
                href = unquote(qs.get("uddg", [href])[0])
            if not href.startswith("http"):
                continue
            results.append(SearchResult(
                title=title_el.get_text(strip=True),
                url=href,
                snippet=(snippet_el.get_text(strip=True) if snippet_el else ""),
            ))
        return results


search_engine = SearchEngine()

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
        url = f"https://duckduckgo.com/?q={quote_plus(req.query)}&ia=web"
        html, _, _ = await browser_pool.get_html(url)
        results = self._parse_ddg(html, req.max_results)
        return SearchResponse(query=req.query, engine_used="duckduckgo", results=results)

    def _parse_google(self, html: str, limit: int) -> list[SearchResult]:
        soup = BeautifulSoup(html, "html.parser")
        results = []
        # yuRUbf: the per-result link container used in current Google HTML
        # Fall back to div.g for older cached pages
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
            # snippet lives outside the yuRUbf card — look in the ancestor container
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

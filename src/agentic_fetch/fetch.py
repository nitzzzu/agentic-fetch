import re
import httpx
from .models import FetchRequest, FetchResponse, TOCEntry
from .browser import browser_pool
from .markdown import MarkdownExtractor, paginate, apply_strip_lines
from .config import settings, SiteConfig, detect_content_type
from .plugins import get_plugin
from .cache import fetch_cache

site_config = SiteConfig(settings.config_file)


class FetchEngine:
    async def fetch(self, req: FetchRequest) -> FetchResponse:
        url = req.url

        # Cache check
        if not req.no_cache and settings.cache_ttl > 0:
            cached = fetch_cache.get(url)
            if cached:
                md, meta = cached
                meta_info = fetch_cache.metadata(url) or {}
                md_chunk, truncated, next_offset = paginate(md, req.offset, req.max_tokens)
                return FetchResponse(
                    url=url, title="", markdown=md_chunk,
                    method_used="httpx",
                    cached=True,
                    truncated=truncated,
                    next_offset=next_offset if truncated else None,
                    toc=[TOCEntry(**e) for e in meta_info.get("toc", [])],
                    total_lines=meta_info.get("lines", 0),
                    code_blocks=meta_info.get("code_blocks", {}),
                    symbols=meta_info.get("symbols", []),
                )

        # Proxy URL override
        proxy_url = site_config.proxy_url_for(url)
        fetch_url = proxy_url or url

        # Tier 1: Plugin
        if not req.force_browser:
            plugin_cls = get_plugin(url)
            if plugin_cls:
                try:
                    result = await plugin_cls().fetch(url, req)
                    if result is not None:
                        self._cache_result(result)
                        return result
                except Exception:
                    pass  # fall through to Tier 2

        # Tier 2: httpx fast path
        html_from_httpx: str | None = None
        final_url_from_httpx: str | None = None
        if not req.force_browser:
            etag = fetch_cache.get_etag(url)
            try:
                html_from_httpx, final_url_from_httpx, resp_etag, content_type_header = \
                    await self._httpx_fetch(fetch_url, etag=etag)
                if html_from_httpx is None:
                    fetch_cache.bump_ttl(url)
                    cached = fetch_cache.get(url)
                    if cached:
                        md, _ = cached
                        md_chunk, truncated, next_offset = paginate(md, req.offset, req.max_tokens)
                        meta_info = fetch_cache.metadata(url) or {}
                        return FetchResponse(
                            url=url, title="", markdown=md_chunk,
                            method_used="httpx", cached=True,
                            truncated=truncated,
                            next_offset=next_offset if truncated else None,
                            toc=[TOCEntry(**e) for e in meta_info.get("toc", [])],
                            total_lines=meta_info.get("lines", 0),
                            code_blocks=meta_info.get("code_blocks", {}),
                            symbols=meta_info.get("symbols", []),
                        )
                content_type = detect_content_type(fetch_url, content_type_header)
                if content_type == "markdown":
                    md = apply_strip_lines(html_from_httpx, site_config.strip_lines_for(url))
                    fetch_cache.put(url, md, "markdown", etag=resp_etag)
                    return self._build_from_md(md, url, "httpx", req=req)
                if not self._needs_js(html_from_httpx):
                    strip_sels = site_config.selectors_for(final_url_from_httpx)
                    strip_lines = site_config.strip_lines_for(url)
                    return self._build_response(
                        html_from_httpx, final_url_from_httpx, req, "httpx",
                        strip_sels, strip_lines, etag=resp_etag,
                    )
            except Exception:
                pass

        # Tier 2.5: httpx HTML loaded into browser via data: URL
        if html_from_httpx and not req.force_browser:
            try:
                html, final_url, intercepted_json = await browser_pool.execute_html(
                    html_from_httpx, origin_url=req.url
                )
                strip_sels = site_config.selectors_for(req.url)
                if intercepted_json:
                    md = self._json_to_markdown(intercepted_json[0], req)
                    if md and len(md) > 200:
                        md, truncated, next_offset = paginate(md, req.offset, req.max_tokens)
                        return FetchResponse(
                            url=req.url,
                            title=intercepted_json[0].get("title", ""),
                            markdown=md,
                            method_used="httpx+browser",
                            truncated=truncated,
                            next_offset=next_offset if truncated else None,
                        )
                return self._build_response(html, req.url, req, "httpx+browser", strip_sels)
            except Exception:
                pass

        # Tier 3: zendriver
        html, final_url, intercepted_json = await browser_pool.get_html(req.url)
        strip_sels = site_config.selectors_for(final_url)

        if intercepted_json:
            md = self._json_to_markdown(intercepted_json[0], req)
            if md and len(md) > 200:
                md, truncated, next_offset = paginate(md, req.offset, req.max_tokens)
                return FetchResponse(
                    url=final_url,
                    title=intercepted_json[0].get("title", ""),
                    markdown=md,
                    method_used="zendriver",
                    truncated=truncated,
                    next_offset=next_offset if truncated else None,
                )

        return self._build_response(html, final_url, req, "zendriver", strip_sels)

    def _needs_js(self, html: str) -> bool:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        body = soup.get_text(separator=" ", strip=True)
        word_count = len(body.split())
        script_count = html.lower().count("<script")
        return word_count < 120 and script_count >= 2

    async def _httpx_fetch(
        self, url: str, etag: str | None = None
    ) -> tuple[str | None, str, str, str]:
        headers = {
            "User-Agent": settings.fake_user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1",
        }
        if etag:
            headers["If-None-Match"] = etag
        async with httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
            timeout=settings.httpx_timeout,
        ) as c:
            r = await c.get(url)
            if r.status_code == 304:
                return None, str(r.url), etag or "", ""
            r.raise_for_status()
            ct = r.headers.get("content-type", "")
            resp_etag = r.headers.get("etag", "")
            return r.text, str(r.url), resp_etag, ct

    def _json_to_markdown(self, data: dict, req: FetchRequest) -> str:
        for key in ("content", "body", "article", "text", "html", "description", "selftext"):
            value = data.get(key)
            if not isinstance(value, str) or len(value) < 100:
                continue
            if re.search(r'<[a-z][^>]*>', value, re.I):
                ext = MarkdownExtractor(value)
                return ext.to_markdown(
                    include_links=req.include_links,
                    include_images=req.include_images,
                )
            return value
        return ""

    def _build_response(
        self, html, url, req, method, strip_sels,
        strip_lines=(), etag=""
    ) -> FetchResponse:
        ext = MarkdownExtractor(html, base_url=url)
        md = ext.to_markdown(
            selector=req.selector,
            strip_selectors=strip_sels,
            include_links=req.include_links,
            include_images=req.include_images,
        )
        md = apply_strip_lines(md, list(strip_lines))
        fetch_cache.put(url, md, "html", etag=etag)
        return self._build_from_md(md, url, method, title=ext.title, req=req)

    def _build_from_md(
        self, md, url, method, title="", req=None
    ) -> FetchResponse:
        offset = req.offset if req else 0
        max_tokens = req.max_tokens if req else None
        md_chunk, truncated, next_offset = paginate(md, offset, max_tokens)
        meta = fetch_cache.metadata(url) or {}
        return FetchResponse(
            url=url,
            title=title,
            markdown=md_chunk,
            method_used=method,
            cached=False,
            truncated=truncated,
            next_offset=next_offset if truncated else None,
            toc=[TOCEntry(**e) for e in meta.get("toc", [])],
            total_lines=meta.get("lines", 0),
            code_blocks=meta.get("code_blocks", {}),
            symbols=meta.get("symbols", []),
        )

    def _cache_result(self, result: FetchResponse) -> None:
        if result.markdown:
            fetch_cache.put(result.url, result.markdown,
                            content_type=result.plugin_used or "plugin")


fetch_engine = FetchEngine()

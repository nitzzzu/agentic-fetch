import httpx
import html2text
import re
from urllib.parse import urlparse, unquote

from .base import FetchPlugin
from ..models import FetchRequest, FetchResponse
from ..markdown import paginate
from ..config import settings

# Wikimedia REST API blocks generic browser UAs — requires an app-identifying
# UA with contact info. Configurable via AF_WIKIPEDIA_USER_AGENT env var.
_HEADERS = {
    "User-Agent": settings.wikipedia_user_agent,
    "Accept": "application/json",
}


def _section_to_markdown(html: str, base_url: str, include_links: bool) -> str:
    """Convert a Wikipedia section HTML fragment to markdown.

    Bypasses readability — section fragments are already clean, focused HTML
    and are too small to survive readability's content-length thresholds.
    """
    h = html2text.HTML2Text(baseurl=base_url)
    h.ignore_links = not include_links
    h.ignore_images = True
    h.body_width = 0
    h.unicode_snob = True
    h.mark_code = True
    h.skip_internal_links = True
    md = h.handle(html)
    return re.sub(r'\n{3,}', '\n\n', md).strip()


class WikipediaPlugin(FetchPlugin):
    name = "wikipedia"
    domains = ["en.wikipedia.org", "*.wikipedia.org"]

    async def fetch(self, url: str, req: FetchRequest) -> FetchResponse | None:
        parsed = urlparse(url)
        lang = parsed.netloc.split(".")[0]
        m = re.match(r'^/wiki/(.+)$', parsed.path)
        if not m:
            return None
        title = unquote(m.group(1))

        api_base = f"https://{lang}.wikipedia.org/api/rest_v1"

        action_base = f"https://{lang}.wikipedia.org/w/api.php"

        try:
            async with httpx.AsyncClient(headers=_HEADERS, timeout=20) as c:
                summary_r = await c.get(f"{api_base}/page/summary/{title}")
                summary_r.raise_for_status()
                summary = summary_r.json()

                # mobile-sections is deprecated — use MediaWiki Action API instead
                extract_r = await c.get(action_base, params={
                    "action": "query", "prop": "extracts",
                    "titles": title, "format": "json",
                })
                extract_data = extract_r.json() if extract_r.is_success else {}
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            error_msg = (f"Wikipedia API error {status}: {url}"
                         if status else f"Wikipedia API unreachable: {exc}")
            md = f"# {title}\n\n**Error:** {error_msg}\n"
            md, truncated, next_offset = paginate(md, req.offset, req.max_tokens)
            return FetchResponse(
                url=url, title=title, markdown=md,
                plugin_used=self.name, method_used="plugin",
                error=error_msg,
                truncated=truncated, next_offset=next_offset if truncated else None,
            )

        display_title = summary.get("displaytitle", title)

        md = f"# {display_title}\n\n"
        if summary.get("description"):
            md += f"*{summary['description']}*\n\n"

        # Full article HTML from Action API
        pages = extract_data.get("query", {}).get("pages", {})
        full_html = next(iter(pages.values()), {}).get("extract", "") if pages else ""
        if full_html:
            md += _section_to_markdown(full_html, url, req.include_links) + "\n\n"
        else:
            md += summary.get("extract", "") + "\n\n"

        md += f"\n[Wikipedia: {display_title}]({url})"
        md, truncated, next_offset = paginate(md, req.offset, req.max_tokens)
        return FetchResponse(
            url=url, title=display_title, markdown=md,
            plugin_used=self.name, method_used="plugin",
            truncated=truncated, next_offset=next_offset if truncated else None,
        )

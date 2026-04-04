import httpx
import re
from urllib.parse import urlparse, unquote

from .base import FetchPlugin
from ..models import FetchRequest, FetchResponse
from ..markdown import paginate


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

        async with httpx.AsyncClient(timeout=20) as c:
            summary_r = await c.get(f"{api_base}/page/summary/{title}")
            summary_r.raise_for_status()
            summary = summary_r.json()

            sections_r = await c.get(f"{api_base}/page/mobile-sections/{title}")
            sections = sections_r.json() if sections_r.is_success else {}

        display_title = summary.get("displaytitle", title)
        extract = summary.get("extract", "")

        md = f"# {display_title}\n\n"
        if summary.get("description"):
            md += f"*{summary['description']}*\n\n"
        md += extract + "\n\n"

        if sections:
            from ..markdown import MarkdownExtractor
            for section in sections.get("remaining", {}).get("sections", []):
                if section.get("toclevel", 0) <= 2:
                    heading_level = "#" * (section.get("toclevel", 1) + 1)
                    md += f"\n{heading_level} {section.get('line', '')}\n\n"
                    html = section.get("text", "")
                    if html:
                        extractor = MarkdownExtractor(html, base_url=url)
                        md += extractor.to_markdown(include_links=req.include_links) + "\n\n"

        md += f"\n[Wikipedia: {display_title}]({url})"
        md, truncated, next_offset = paginate(md, req.offset, req.max_tokens)
        return FetchResponse(
            url=url, title=display_title, markdown=md,
            plugin_used=self.name, method_used="plugin",
            truncated=truncated, next_offset=next_offset if truncated else None,
        )

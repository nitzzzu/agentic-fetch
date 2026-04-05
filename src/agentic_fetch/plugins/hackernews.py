import httpx
import html2text
import re
from html import unescape

from .base import FetchPlugin
from ..models import FetchRequest, FetchResponse
from ..markdown import paginate


def _html_to_text(html: str, base_url: str = "") -> str:
    """Convert HN comment/story HTML to clean markdown."""
    if not html:
        return ""
    h = html2text.HTML2Text(baseurl=base_url)
    h.ignore_links = False
    h.ignore_images = True
    h.body_width = 0
    h.unicode_snob = True
    return h.handle(unescape(html)).strip()


class HackerNewsPlugin(FetchPlugin):
    name = "hackernews"
    domains = ["news.ycombinator.com"]

    RE_ITEM = re.compile(r'[?&]id=(\d+)')

    async def fetch(self, url: str, req: FetchRequest) -> FetchResponse | None:
        m = self.RE_ITEM.search(url)
        if not m:
            return None

        item_id = m.group(1)
        algolia_url = f"https://hn.algolia.com/api/v1/items/{item_id}"

        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(algolia_url)
                r.raise_for_status()
                data = r.json()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            error_msg = (f"HN API error {status}: {url}"
                         if status else f"HN API unreachable: {exc}")
            md = f"**Error:** {error_msg}\n"
            md, truncated, next_offset = paginate(md, req.offset, req.max_tokens)
            return FetchResponse(
                url=url, title="", markdown=md,
                plugin_used=self.name, method_used="plugin",
                error=error_msg,
                truncated=truncated, next_offset=next_offset if truncated else None,
            )

        md = self._format_story(data, url)
        md, truncated, next_offset = paginate(md, req.offset, req.max_tokens)
        return FetchResponse(
            url=url,
            title=data.get("title", ""),
            markdown=md,
            plugin_used=self.name,
            method_used="plugin",
            truncated=truncated,
            next_offset=next_offset if truncated else None,
        )

    def _format_story(self, data: dict, url: str) -> str:
        title = data.get("title", "")
        author = data.get("author", "")
        points = data.get("points") or 0
        created = data.get("created_at", "")[:10]
        story_url = data.get("url", "")
        # items API returns 'id'; 'objectID' is only in search API responses
        item_id = data.get("id") or data.get("objectID", "")
        hn_url = f"https://news.ycombinator.com/item?id={item_id}" if item_id else url

        md = f"# {title}\n\n"
        md += f"**{points} points** · {author} · {created} · [HN Discussion]({hn_url})\n\n"
        if story_url:
            md += f"**Link:** {story_url}\n\n"
        if data.get("text"):
            md += _html_to_text(data["text"], base_url=url) + "\n\n"

        children = data.get("children", [])
        if children:
            md += "---\n\n## Comments\n\n"
            md += self._format_comments(children, base_url=url)

        return md

    def _format_comments(self, items: list, depth: int = 0, limit: int = 100,
                          base_url: str = "") -> str:
        out = ""
        count = [0]

        def recurse(items, d):
            nonlocal out
            for item in items:
                if count[0] >= limit:
                    return
                if item.get("type") == "comment" and item.get("text"):
                    count[0] += 1
                    prefix = "> " * d if d > 0 else ""
                    author = item.get("author", "?")
                    text = _html_to_text(item["text"], base_url=base_url)
                    out += f"{prefix}**{author}**\n"
                    for line in text.splitlines():
                        out += f"{prefix}{line}\n"
                    out += "\n"
                    if item.get("children"):
                        recurse(item["children"], d + 1)

        recurse(items, 0)
        return out

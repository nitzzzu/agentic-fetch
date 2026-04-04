import httpx
import re
from datetime import datetime

from .base import FetchPlugin
from ..models import FetchRequest, FetchResponse
from ..markdown import paginate


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

        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(algolia_url)
            r.raise_for_status()
            data = r.json()

        md = self._format_story(data)
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

    def _format_story(self, data: dict) -> str:
        title = data.get("title", "")
        author = data.get("author", "")
        points = data.get("points") or 0
        created = data.get("created_at", "")[:10]
        story_url = data.get("url", "")
        hn_url = f"https://news.ycombinator.com/item?id={data['objectID']}"

        md = f"# {title}\n\n"
        md += f"**{points} points** · {author} · {created} · [HN Discussion]({hn_url})\n\n"
        if story_url:
            md += f"**Link:** {story_url}\n\n"
        if data.get("text"):
            md += data["text"] + "\n\n"

        children = data.get("children", [])
        if children:
            md += "---\n\n## Comments\n\n"
            md += self._format_comments(children)

        return md

    def _format_comments(self, items: list, depth: int = 0, limit: int = 100) -> str:
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
                    out += f"{prefix}**{author}**\n"
                    for line in (item["text"] or "").splitlines():
                        out += f"{prefix}{line}\n"
                    out += "\n"
                    if item.get("children"):
                        recurse(item["children"], d + 1)

        recurse(items, 0)
        return out

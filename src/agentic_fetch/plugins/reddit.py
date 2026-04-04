import httpx
import re
from urllib.parse import urlparse
from html import unescape
from datetime import datetime

from .base import FetchPlugin
from ..models import FetchRequest, FetchResponse
from ..markdown import paginate


class RedditPlugin(FetchPlugin):
    domains = ["reddit.com", "www.reddit.com", "old.reddit.com", "redd.it"]
    name = "reddit"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    async def fetch(self, url: str, req: FetchRequest) -> FetchResponse:
        url = self._normalize_url(url)
        json_url = url.rstrip("/") + ".json"

        async with httpx.AsyncClient(headers=self.HEADERS, follow_redirects=True, timeout=30) as client:
            resp = await client.get(json_url)
            resp.raise_for_status()
            data = resp.json()

        if not isinstance(data, list) or len(data) < 2:
            raise ValueError("Unexpected Reddit API response format")

        post = data[0]["data"]["children"][0]["data"]
        comments = data[1]["data"]["children"]

        md = self._format_post(post) + self._format_comments(comments, post["author"])
        md, truncated, next_offset = paginate(md, req.offset, req.max_tokens)

        return FetchResponse(
            url=url,
            title=post.get("title", ""),
            markdown=md,
            plugin_used=self.name,
            method_used="plugin",
            truncated=truncated,
            next_offset=next_offset if truncated else None,
        )

    def _normalize_url(self, url: str) -> str:
        if not url.startswith("http"):
            url = "https://reddit.com" + url
        parsed = urlparse(url)
        return f"https://www.reddit.com{parsed.path}"

    def _format_post(self, post: dict) -> str:
        title = unescape(post.get("title", ""))
        author = post.get("author", "unknown")
        subreddit = post.get("subreddit", "")
        score = f"{post.get('score', 0):,}"
        num_comments = f"{post.get('num_comments', 0):,}"
        created = datetime.utcfromtimestamp(post.get("created_utc", 0)).strftime("%Y-%m-%d %H:%M UTC")
        permalink = f"https://reddit.com{post.get('permalink', '')}"

        header = f"# {title}\n\n"
        header += f"**r/{subreddit}** · u/{author} · {created} · {score} points · {num_comments} comments\n\n"
        header += f"[Original post]({permalink})\n\n"

        if post.get("selftext"):
            header += "---\n\n" + unescape(post["selftext"]) + "\n\n"

        if post.get("url") and not post.get("is_self"):
            link_url = post["url"]
            if not link_url.endswith(('.jpg', '.jpeg', '.png', '.gif', '.mp4', '.webp')):
                header += f"**Link:** {link_url}\n\n"

        return header

    def _format_comments(self, comments: list, op: str, depth: int = 0, limit: int = 200) -> str:
        if not comments:
            return ""
        out = "---\n\n## Comments\n\n" if depth == 0 else ""
        count = [0]

        def recurse(items, d):
            nonlocal out
            for item in items:
                if count[0] >= limit:
                    return
                if item.get("kind") == "more":
                    continue
                data = item.get("data", {})
                body = unescape(data.get("body") or "").strip()
                if not body or data.get("author") in ("[deleted]", "[removed]"):
                    continue
                count[0] += 1
                author = data.get("author", "?")
                score = data.get("score", 0)
                badge = " **[OP]**" if author == op else ""
                if data.get("distinguished") == "moderator":
                    badge += " **[MOD]**"
                prefix = "> " * d if d > 0 else ""
                out_parts = [f"{prefix}**u/{author}**{badge} · {score} pts\n"]
                for line in body.splitlines():
                    out_parts.append(f"{prefix}{line}\n")
                out += "".join(out_parts) + "\n"
                replies = data.get("replies")
                if isinstance(replies, dict):
                    recurse(replies["data"]["children"], d + 1)

        recurse(comments, 0)
        return out

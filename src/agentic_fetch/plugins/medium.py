import httpx
import re
from bs4 import BeautifulSoup
import html_to_markdown
from html_to_markdown import ConversionOptions
from urllib.parse import urlparse

from .base import FetchPlugin
from ..models import FetchRequest, FetchResponse
from ..markdown import paginate
from ..config import settings

MEDIUM_DOMAINS = {
    "medium.com", "towardsdatascience.com", "betterprogramming.pub",
    "betterhumans.pub", "uxdesign.cc", "levelup.gitconnected.com",
    "hackernoon.com", "aws.plainenglish.io", "javascript.plainenglish.io",
    "python.plainenglish.io", "pub.towardsai.net",
}

FREEDIUM = "https://freedium-mirror.cfd/"

SKIP_PATTERNS = [
    "Freedium", "Ko-fi", "Patreon", "Liberapay",
    "We've reached", "Milestone:", "< Go to the original",
    "Preview image", "Reporting a Problem", "min read ·",
    "Free: No", "Free: Yes", "Sign up", "Sign in", "Open in app",
]


class MediumPlugin(FetchPlugin):
    name = "medium"
    domains = list(MEDIUM_DOMAINS)

    HEADERS = {
        "User-Agent": settings.fake_user_agent,
        "Accept-Language": "en-US,en;q=0.9",
    }

    async def fetch(self, url: str, req: FetchRequest) -> FetchResponse:
        freedium_url = FREEDIUM + url

        async with httpx.AsyncClient(
            headers=self.HEADERS,
            follow_redirects=True,
            timeout=30,
        ) as client:
            resp = await client.get(freedium_url)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        title = ""
        if t := soup.find("title"):
            title = re.sub(r'\s*[|•-]\s*(Medium|Freedium).*$', '', t.get_text(strip=True))
        author = ""
        if a := soup.find("meta", attrs={"name": "author"}):
            author = a.get("content", "")

        for sel in ["header", "footer", "nav", ".sidebar", ".donation", "#top-bar"]:
            for el in soup.select(sel):
                el.decompose()

        strip_tags: set[str] = set()
        if not req.include_links:
            strip_tags.add("a")
        opts = ConversionOptions(
            skip_images=not req.include_images,
            strip_tags=strip_tags or None,
            code_block_style="backticks",
        )
        raw_md = html_to_markdown.convert(resp.text, options=opts)["content"] or ""
        md = self._clean(raw_md, title)

        if author:
            md = f"*Author: {author}*\n\n" + md

        md, truncated, next_offset = paginate(md, req.offset, req.max_tokens)
        return FetchResponse(
            url=url, title=title, markdown=md,
            plugin_used=self.name, method_used="plugin",
            truncated=truncated,
            next_offset=next_offset if truncated else None,
        )

    def _clean(self, md: str, title: str) -> str:
        lines = md.splitlines()
        result = []
        in_article = False

        for line in lines:
            if any(pat in line for pat in SKIP_PATTERNS):
                continue
            if re.match(r'^\s*\[.*\]\(.*\)\s*$', line) and len(line.strip()) < 100:
                if not in_article:
                    continue
            if not in_article and line.startswith('#'):
                if len(line.strip()) > 5:
                    in_article = True
            if in_article:
                result.append(line)

        text = '\n'.join(result)
        return re.sub(r'\n{3,}', '\n\n', text).strip()

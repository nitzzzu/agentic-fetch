import httpx
import re
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup

from .base import FetchPlugin
from ..models import FetchRequest, FetchResponse
from ..markdown import paginate, MarkdownExtractor


class GitHubPlugin(FetchPlugin):
    name = "github"
    domains = ["github.com", "www.github.com", "raw.githubusercontent.com"]

    HEADERS = {"Accept": "application/vnd.github.v3+json", "User-Agent": "agentic-fetch/1.0"}
    TRENDING_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    RE_TRENDING = re.compile(r'^/trending(/[^/?]+)?$')
    RE_REPO = re.compile(r'^/([^/]+)/([^/]+)/?$')
    RE_FILE = re.compile(r'^/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$')
    RE_ISSUE = re.compile(r'^/([^/]+)/([^/]+)/issues/(\d+)$')
    RE_PR = re.compile(r'^/([^/]+)/([^/]+)/pull/(\d+)$')

    async def fetch(self, url: str, req: FetchRequest) -> FetchResponse | None:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/") or "/"

        if m := self.RE_TRENDING.match(path):
            lang = (m.group(1) or "").lstrip("/")
            since = parse_qs(parsed.query).get("since", ["daily"])[0]
            return await self._fetch_trending(lang, since, req, url)
        if m := self.RE_FILE.match(path):
            return await self._fetch_file(*m.groups(), req, url)
        if m := self.RE_ISSUE.match(path):
            return await self._fetch_issue(*m.groups(), req, url)
        if m := self.RE_PR.match(path):
            return await self._fetch_pr(*m.groups(), req, url)
        if m := self.RE_REPO.match(path):
            return await self._fetch_repo(*m.groups(), req, url)

        return None

    async def _fetch_trending(self, language: str, since: str, req: FetchRequest, url: str) -> FetchResponse:
        trend_url = f"https://github.com/trending/{language}" if language else "https://github.com/trending"
        async with httpx.AsyncClient(headers=self.TRENDING_HEADERS, timeout=15, follow_redirects=True) as c:
            r = await c.get(trend_url, params={"since": since})
            r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        repos = []
        for article in soup.select("article.Box-row"):
            # repo path: /owner/repo
            h2_a = article.select_one("h2 a, h1 a")
            if not h2_a:
                continue
            repo_path = h2_a.get("href", "").strip()
            parts = repo_path.strip("/").split("/")
            if len(parts) != 2:
                continue
            owner, repo = parts

            desc_el = article.select_one("p")
            description = desc_el.get_text(strip=True) if desc_el else ""

            lang_el = article.select_one("[itemprop='programmingLanguage']")
            language_name = lang_el.get_text(strip=True) if lang_el else ""

            # total stars: link to /stargazers
            stars_el = article.select_one("a[href$='/stargazers']")
            stars = stars_el.get_text(strip=True).replace(",", "") if stars_el else "0"

            # forks: link to /forks or /network/members
            forks_el = article.select_one("a[href$='/forks'], a[href$='/network/members']")
            forks = forks_el.get_text(strip=True).replace(",", "") if forks_el else "0"

            # stars today: last span containing "stars today"
            today_stars = ""
            for span in article.select("span"):
                t = span.get_text(strip=True)
                if "stars today" in t or "star today" in t:
                    today_stars = t.replace("stars today", "").replace("star today", "").strip()
                    break

            repos.append({
                "owner": owner, "repo": repo,
                "description": description,
                "language": language_name,
                "stars": stars,
                "forks": forks,
                "today": today_stars,
            })

        period = {"daily": "today", "weekly": "this week", "monthly": "this month"}.get(since, since)
        lang_label = f" · {language}" if language else ""
        title = f"GitHub Trending{lang_label} — {period}"

        if not repos:
            md = f"# {title}\n\nNo trending repositories found.\n"
        else:
            md = f"# {title}\n\n"
            md += f"| # | Repository | Description | Lang | Stars | Forks | {period.capitalize()} |\n"
            md += f"|---|------------|-------------|------|------:|------:|-------|\n"
            for i, r in enumerate(repos, 1):
                repo_url = f"https://github.com/{r['owner']}/{r['repo']}"
                desc = r["description"].replace("|", "\\|")[:80] + ("…" if len(r["description"]) > 80 else "")
                md += (f"| {i} | [{r['owner']}/{r['repo']}]({repo_url}) "
                       f"| {desc} | {r['language']} | {r['stars']} | {r['forks']} | ⭐ {r['today']} |\n")

        md, truncated, next_offset = paginate(md, req.offset, req.max_tokens)
        return FetchResponse(url=url, title=title, markdown=md,
                             plugin_used=self.name, method_used="plugin",
                             truncated=truncated, next_offset=next_offset if truncated else None)

    async def _fetch_repo(self, owner, repo, req, url) -> FetchResponse:
        async with httpx.AsyncClient(headers=self.HEADERS, timeout=15) as c:
            r = await c.get(f"https://api.github.com/repos/{owner}/{repo}")
            r.raise_for_status()
            info = r.json()
            readme_r = await c.get(f"https://api.github.com/repos/{owner}/{repo}/readme",
                                   headers={**self.HEADERS, "Accept": "application/vnd.github.raw"})

        md = f"# {info['full_name']}\n\n"
        if info.get("description"):
            md += f"{info['description']}\n\n"
        md += f"**Stars:** {info['stargazers_count']:,} · **Forks:** {info['forks_count']:,} · "
        md += f"**Language:** {info.get('language', 'N/A')} · **License:** {info.get('license', {}).get('spdx_id', 'N/A')}\n\n"
        if info.get("topics"):
            md += f"**Topics:** {', '.join(info['topics'])}\n\n"
        md += f"[GitHub]({url})\n\n---\n\n"
        if readme_r.is_success:
            md += readme_r.text

        md, truncated, next_offset = paginate(md, req.offset, req.max_tokens)
        return FetchResponse(url=url, title=info["full_name"], markdown=md,
                             plugin_used=self.name, method_used="plugin",
                             truncated=truncated, next_offset=next_offset if truncated else None)

    async def _fetch_file(self, owner, repo, branch, path, req, url) -> FetchResponse:
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(raw_url)
            r.raise_for_status()

        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        lang_map = {"py": "python", "ts": "typescript", "js": "javascript",
                    "rs": "rust", "go": "go", "java": "java", "md": ""}
        lang = lang_map.get(ext, ext)

        md = f"# {path}\n\n"
        if lang:
            md += f"```{lang}\n{r.text}\n```"
        else:
            md += r.text

        md, truncated, next_offset = paginate(md, req.offset, req.max_tokens)
        return FetchResponse(url=url, title=path, markdown=md,
                             plugin_used=self.name, method_used="plugin",
                             truncated=truncated, next_offset=next_offset if truncated else None)

    async def _fetch_issue(self, owner, repo, number, req, url) -> FetchResponse:
        async with httpx.AsyncClient(headers=self.HEADERS, timeout=15) as c:
            r = await c.get(f"https://api.github.com/repos/{owner}/{repo}/issues/{number}")
            r.raise_for_status()
            issue = r.json()
            comments_r = await c.get(f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments")
            comments = comments_r.json() if comments_r.is_success else []

        state_badge = "Open" if issue["state"] == "open" else "Closed"
        md = f"# {issue['title']}\n\n"
        md += f"**#{number}** · {state_badge} · {issue['user']['login']} · {issue['created_at'][:10]}\n\n"
        if issue.get("body"):
            md += issue["body"] + "\n\n"
        if comments:
            md += "---\n\n## Comments\n\n"
            for comment in comments:
                md += f"**{comment['user']['login']}** · {comment['created_at'][:10]}\n\n{comment['body']}\n\n---\n\n"

        md, truncated, next_offset = paginate(md, req.offset, req.max_tokens)
        return FetchResponse(url=url, title=issue["title"], markdown=md,
                             plugin_used=self.name, method_used="plugin",
                             truncated=truncated, next_offset=next_offset if truncated else None)

    async def _fetch_pr(self, owner, repo, number, req, url) -> FetchResponse:
        async with httpx.AsyncClient(headers=self.HEADERS, timeout=15) as c:
            r = await c.get(f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}")
            r.raise_for_status()
            pr = r.json()

        state_badge = "Open" if pr["state"] == "open" else "Merged" if pr.get("merged") else "Closed"
        md = f"# {pr['title']}\n\n"
        md += f"**#{number}** · {state_badge} · {pr['user']['login']} · {pr['created_at'][:10]}\n\n"
        md += f"**Branch:** `{pr['head']['ref']}` -> `{pr['base']['ref']}`\n\n"
        md += f"**+{pr['additions']} / -{pr['deletions']}** lines across {pr['changed_files']} files\n\n"
        if pr.get("body"):
            md += pr["body"]

        md, truncated, next_offset = paginate(md, req.offset, req.max_tokens)
        return FetchResponse(url=url, title=pr["title"], markdown=md,
                             plugin_used=self.name, method_used="plugin",
                             truncated=truncated, next_offset=next_offset if truncated else None)

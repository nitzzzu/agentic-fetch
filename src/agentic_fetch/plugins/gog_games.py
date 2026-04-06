from bs4 import BeautifulSoup
from urllib.parse import urlparse

from .base import FetchPlugin
from ..models import FetchRequest, FetchResponse
from ..markdown import paginate


class GogGamesPlugin(FetchPlugin):
    name = "goggames"
    domains = ["gog-games.to"]

    async def fetch(self, url: str, req: FetchRequest) -> FetchResponse | None:
        # Only handle game detail pages
        if not urlparse(url).path.startswith("/game/"):
            return None

        from ..browser import browser_pool
        html, final_url, _ = await browser_pool.get_html(url)
        soup = BeautifulSoup(html, "html.parser")

        # Title
        title_el = soup.select_one(".game-info-title.text-3xl")
        title = title_el.get_text(strip=True) if title_el else ""

        # Meta rows: rating/date/rank · developer/publisher · genres · tags
        meta_els = soup.select(".game-info-title.text-lg")
        rating = release_date = gog_rank = developer = publisher = genres = tags = ""
        if len(meta_els) >= 1:
            parts = meta_els[0].get_text(strip=True).split("|")
            rating       = parts[0].strip() if len(parts) > 0 else ""
            release_date = parts[1].strip() if len(parts) > 1 else ""
            gog_rank     = parts[2].strip() if len(parts) > 2 else ""
        if len(meta_els) >= 2:
            parts = meta_els[1].get_text(strip=True).split("|")
            developer = parts[0].strip() if len(parts) > 0 else ""
            publisher = parts[1].strip() if len(parts) > 1 else ""
        if len(meta_els) >= 3:
            genres = meta_els[2].get_text(strip=True)
        if len(meta_els) >= 4:
            tags = meta_els[3].get_text(strip=True)

        # Torrent / magnet link
        magnet = ""
        torrent_a = soup.select_one("a.btn-torrent")
        if torrent_a:
            magnet = torrent_a.get("href", "")

        # Direct download links per host
        download_links: list[tuple[str, str, str]] = []  # (host, filename, url)
        for details in soup.select(".game-section-with-accordion-game details"):
            host_el = details.select_one("summary p")
            host = host_el.get_text(strip=True) if host_el else "Unknown"
            for a in details.select("a[href]"):
                link_url = a.get("href", "")
                div_title = a.select_one("div[title]")
                filename = div_title.get("title", "") if div_title else a.get_text(strip=True)
                if link_url:
                    download_links.append((host, filename, link_url))

        # GOG installer file list (filenames + sizes, no direct links)
        installers: list[tuple[str, str]] = []
        for row in soup.select(".game-section-with-list-game .flex.justify-between"):
            spans = row.select("span")
            if len(spans) >= 2:
                filename = spans[0].get_text(strip=True)
                size     = spans[1].get_text(strip=True)
                if filename:
                    installers.append((filename, size))

        # Build markdown
        lines: list[str] = [f"# {title}\n"]
        if rating or release_date:
            meta = f"**Rating:** {rating}"
            if release_date:
                meta += f" · **Released:** {release_date}"
            if gog_rank:
                meta += f" · **GOG rank:** {gog_rank}"
            lines.append(meta + "\n")
        if developer:
            dev_line = f"**Developer:** {developer}"
            if publisher and publisher != developer:
                dev_line += f" · **Publisher:** {publisher}"
            lines.append(dev_line + "\n")
        if genres:
            lines.append(f"**Genres:** {genres}\n")
        if tags:
            lines.append(f"**Tags:** {tags}\n")
        lines.append("")

        if magnet or download_links:
            lines.append("## Download Links\n")
            if magnet:
                lines.append(f"- **Torrent:** [Open in torrent client]({magnet})\n")
            for host, filename, link_url in download_links:
                lines.append(f"- **{host}:** [{filename}]({link_url})\n")
            lines.append("")

        if installers:
            lines.append("## GOG Installer Files\n")
            for filename, size in installers:
                lines.append(f"- `{filename}` — {size}\n")
            lines.append("")

        md = "\n".join(lines)
        md_chunk, truncated, next_offset = paginate(md, req.offset, req.max_tokens)

        return FetchResponse(
            url=final_url,
            title=title,
            markdown=md_chunk,
            plugin_used=self.name,
            method_used="plugin",
            truncated=truncated,
            next_offset=next_offset if truncated else None,
        )

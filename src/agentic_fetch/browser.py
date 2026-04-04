import asyncio
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
import zendriver as zd
from .config import settings, SiteConfig

BLOCKED_PATTERNS = [
    "*googlesyndication.com*", "*doubleclick.net*", "*googleadservices.com*",
    "*adnxs.com*", "*moatads.com*", "*amazon-adsystem.com*",
    "*.jpg", "*.jpeg", "*.png", "*.gif", "*.webp", "*.svg",
    "*.woff", "*.woff2", "*.ttf",
]

COOKIE_DISMISS_JS = """
(function() {
    const selectors = [
        '[id*="cookie"] button[class*="accept" i]',
        '[class*="cookie"] button[class*="accept" i]',
        '[id*="consent"] button[class*="agree" i]',
        '[class*="consent"] button[class*="agree" i]',
        '#onetrust-accept-btn-handler',
        '.cc-btn.cc-allow',
        '[data-cookiebanner="accept_button"]',
        'button[aria-label*="accept" i][class*="cookie" i]',
    ];
    for (const sel of selectors) {
        const btn = document.querySelector(sel);
        if (btn) { btn.click(); return true; }
    }
    return false;
})();
"""

CONTENT_JSON_KEYS = {"content", "body", "text", "article", "description", "selftext", "html"}


def _host(url: str) -> str:
    return urlparse(url).netloc.lstrip("www.")


class BrowserPool:
    _browser: zd.Browser | None = None
    _semaphore: asyncio.Semaphore | None = None
    _site_config: SiteConfig | None = None

    async def start(self):
        self._site_config = SiteConfig(settings.config_file)
        user_data_dir = str(Path(settings.user_data_dir).resolve())
        config = zd.Config(
            headless=settings.headless,
            user_data_dir=user_data_dir,
            browser_args=[
                f"--user-agent={settings.fake_user_agent}",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
            ],
        )
        self._browser = await zd.start(config)
        self._semaphore = asyncio.Semaphore(settings.max_browser_tabs)

    async def stop(self):
        if self._browser:
            await self._browser.stop()

    @property
    def is_running(self) -> bool:
        return self._browser is not None

    @asynccontextmanager
    async def acquire_tab(self):
        async with self._semaphore:
            tab = await self._browser.get("about:blank", new_tab=True)
            try:
                yield tab
            finally:
                try:
                    await tab.close()
                except Exception:
                    pass

    async def get_html(self, url: str) -> tuple[str, str, list[dict]]:
        init_script = self._site_config.init_script_for(url) if self._site_config else None

        intercepted_json: list[dict] = []
        content_ready = asyncio.Event()

        async with self.acquire_tab() as tab:
            await tab.send(zd.cdp.network.enable())
            await tab.send(zd.cdp.network.set_blocked_ur_ls(urls=BLOCKED_PATTERNS))

            if init_script:
                await tab.send(
                    zd.cdp.page.add_script_to_evaluate_on_new_document(source=init_script)
                )

            async def on_response_received(event):
                resp = event.response
                ct = resp.headers.get("content-type", "")
                if "json" not in ct or resp.status != 200:
                    return
                try:
                    body_result = await tab.send(
                        zd.cdp.network.get_response_body(request_id=event.request_id)
                    )
                    body_str = body_result.body if body_result else ""
                    if not body_str:
                        return
                    data = json.loads(body_str)
                    if isinstance(data, dict):
                        flat = {**data, **{k: v for d in data.values()
                                           if isinstance(d, dict) for k, v in d.items()}}
                        if CONTENT_JSON_KEYS & flat.keys():
                            intercepted_json.append(flat)
                            content_ready.set()
                except Exception:
                    pass

            tab.add_handler(zd.cdp.network.ResponseReceived, on_response_received)

            await tab.get(url)

            try:
                await asyncio.wait_for(content_ready.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass

            if not content_ready.is_set():
                try:
                    await asyncio.wait_for(asyncio.shield(tab), timeout=settings.browser_timeout)
                except (asyncio.TimeoutError, Exception):
                    pass

            try:
                await tab.evaluate(COOKIE_DISMISS_JS)
            except Exception:
                pass

            final_url = await tab.evaluate("window.location.href")
            top_html = await tab.get_content()

            frame_htmls: list[str] = []
            try:
                frames = await tab.evaluate("""
                    Array.from(document.querySelectorAll('iframe[src]'))
                        .map(f => f.src)
                        .filter(s => s.startsWith('http'))
                """)
                if frames:
                    frame_htmls.append(f"<!-- iframe-srcs: {json.dumps(frames)} -->")
            except Exception:
                pass

            html = top_html + "\n".join(frame_htmls)
            return html, final_url, intercepted_json

    async def execute_html(self, html: str, origin_url: str) -> tuple[str, str, list[dict]]:
        import urllib.parse

        intercepted_json: list[dict] = []
        content_ready = asyncio.Event()

        async with self.acquire_tab() as tab:
            await tab.send(zd.cdp.network.enable())
            await tab.send(zd.cdp.network.set_blocked_ur_ls(urls=[
                "*googlesyndication.com*", "*doubleclick.net*", "*adnxs.com*",
            ]))

            async def on_response_received(event):
                resp = event.response
                ct = resp.headers.get("content-type", "")
                if "json" not in ct or resp.status != 200:
                    return
                try:
                    body_result = await tab.send(
                        zd.cdp.network.get_response_body(request_id=event.request_id)
                    )
                    body_str = body_result.body if body_result else ""
                    if not body_str:
                        return
                    data = json.loads(body_str)
                    if isinstance(data, dict):
                        flat = {**data, **{k: v for d in data.values()
                                           if isinstance(d, dict) for k, v in d.items()}}
                        if CONTENT_JSON_KEYS & flat.keys():
                            intercepted_json.append(flat)
                            content_ready.set()
                except Exception:
                    pass

            tab.add_handler(zd.cdp.network.ResponseReceived, on_response_received)

            encoded = urllib.parse.quote(html)
            data_url = f"data:text/html;charset=utf-8,{encoded}"
            await tab.get(data_url)

            try:
                await asyncio.wait_for(content_ready.wait(), timeout=8.0)
            except asyncio.TimeoutError:
                try:
                    await asyncio.wait_for(asyncio.shield(tab), timeout=5.0)
                except (asyncio.TimeoutError, Exception):
                    pass

            try:
                await tab.evaluate(COOKIE_DISMISS_JS)
            except Exception:
                pass
            rendered_html = await tab.get_content()

        return rendered_html, origin_url, intercepted_json


browser_pool = BrowserPool()

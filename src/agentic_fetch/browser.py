import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import zendriver as zd
from .config import settings, site_config

log = logging.getLogger("agentic_fetch.browser")

BLOCKED_PATTERNS = [
    "*googlesyndication.com*",
    "*doubleclick.net*",
    "*googleadservices.com*",
    "*adnxs.com*",
    "*moatads.com*",
    "*amazon-adsystem.com*",
    "*.jpg",
    "*.jpeg",
    "*.png",
    "*.gif",
    "*.webp",
    "*.svg",
    "*.woff",
    "*.woff2",
    "*.ttf",
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

CONTENT_JSON_KEYS = {
    "content",
    "body",
    "text",
    "article",
    "description",
    "selftext",
    "html",
}


def _host(url: str) -> str:
    return urlparse(url).netloc.removeprefix("www.")


class BrowserPool:
    _browser: zd.Browser | None = None
    _semaphore: asyncio.Semaphore | None = None
    _restart_lock: asyncio.Lock | None = None
    # Bumped on every relaunch so concurrent failures trigger exactly one restart.
    _generation: int = 0
    # Bound for how long acquire_tab() may wait before raising. Surfaces back-pressure
    # as a real error instead of letting requests queue forever on a stuck browser.
    _acquire_timeout: float = 60.0

    async def start(self) -> None:
        # Keep semaphore/lock across relaunches — in-flight holders must pair
        # acquire/release on the same object.
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(settings.max_browser_tabs)
        if self._restart_lock is None:
            self._restart_lock = asyncio.Lock()
        await self._launch()

    async def _launch(self) -> None:
        user_data_dir = str(Path(settings.user_data_dir).resolve())
        browser_args = (
            ["--no-sandbox", "--start-maximized"] if settings.container else []
        )
        config = zd.Config(
            headless=settings.headless,
            user_data_dir=user_data_dir,
            browser_connection_timeout=0.5,
            browser_connection_max_tries=60,
            browser_args=browser_args,
        )
        self._browser = await zd.start(config)

    async def stop(self) -> None:
        if self._browser:
            await self._browser.stop()
            self._browser = None

    @property
    def is_running(self) -> bool:
        # `stopped` checks the actual Chrome process, so a crashed browser
        # reports not-running instead of hanging every request.
        return self._browser is not None and not self._browser.stopped

    async def _restart(self, seen_generation: int, force: bool = False) -> None:
        """Relaunch Chrome. Serialized: if another coroutine already restarted
        (generation moved on), or the browser is healthy and force is off, no-op."""
        assert self._restart_lock is not None, "BrowserPool not started"
        async with self._restart_lock:
            if self._generation != seen_generation:
                return
            if not force and self.is_running:
                return
            log.warning("browser unavailable — relaunching Chrome")
            try:
                if self._browser:
                    await self._browser.stop()
            except Exception as exc:
                log.debug("stopping dead browser failed: %s", exc)
            self._browser = None
            await self._launch()
            self._generation += 1

    @asynccontextmanager
    async def acquire_tab(self) -> AsyncIterator[zd.Tab]:
        if self._semaphore is None or self._browser is None:
            raise RuntimeError(
                "BrowserPool not started — call await browser_pool.start() first"
            )
        sem = self._semaphore
        try:
            await asyncio.wait_for(sem.acquire(), timeout=self._acquire_timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"Timed out waiting {self._acquire_timeout}s for a browser tab — "
                f"pool is saturated (max_browser_tabs={settings.max_browser_tabs})"
            ) from None
        try:
            gen = self._generation
            if not self.is_running:
                await self._restart(gen)
                gen = self._generation
            assert self._browser is not None
            try:
                tab = await self._browser.get("about:blank", new_tab=True)
            except Exception as exc:
                # Process may be alive but CDP wedged — force one relaunch, retry once.
                log.warning("opening tab failed (%s) — restarting browser", exc)
                await self._restart(gen, force=True)
                assert self._browser is not None
                tab = await self._browser.get("about:blank", new_tab=True)
            try:
                yield tab
            finally:
                try:
                    await tab.close()
                except Exception as exc:
                    log.debug("tab close failed: %s", exc)
        finally:
            sem.release()

    def _make_json_interceptor(
        self, tab: zd.Tab, intercepted: list[dict[str, Any]], ready: asyncio.Event
    ) -> Callable[[zd.cdp.network.ResponseReceived], Coroutine[Any, Any, None]]:
        """Build a handler that captures interesting JSON responses for content extraction."""

        async def on_response_received(event: zd.cdp.network.ResponseReceived) -> None:
            resp = event.response
            ct = resp.headers.get("content-type", "")
            if "json" not in ct or resp.status != 200:
                return
            try:
                body_result = await tab.send(
                    zd.cdp.network.get_response_body(request_id=event.request_id)
                )
                body_str = body_result[0] if body_result else ""
                if not body_str:
                    return
                data = json.loads(body_str)
                if isinstance(data, dict):
                    flat = {
                        **data,
                        **{
                            k: v
                            for d in data.values()
                            if isinstance(d, dict)
                            for k, v in d.items()
                        },
                    }
                    if CONTENT_JSON_KEYS & flat.keys():
                        intercepted.append(flat)
                        ready.set()
            except Exception as exc:
                log.debug("json intercept failed: %s", exc)

        return on_response_received

    async def get_html(self, url: str) -> tuple[str, str, list[dict[str, Any]]]:
        init_script = site_config.init_script_for(url)

        intercepted_json: list[dict[str, Any]] = []
        content_ready = asyncio.Event()

        async with self.acquire_tab() as tab:
            await tab.send(zd.cdp.network.enable())
            await tab.send(zd.cdp.network.set_blocked_ur_ls(urls=BLOCKED_PATTERNS))

            if init_script:
                await tab.send(
                    zd.cdp.page.add_script_to_evaluate_on_new_document(
                        source=init_script
                    )
                )

            tab.add_handler(
                zd.cdp.network.ResponseReceived,
                self._make_json_interceptor(tab, intercepted_json, content_ready),
            )

            await tab.get(url)

            try:
                await asyncio.wait_for(content_ready.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass

            if not content_ready.is_set():
                try:
                    await asyncio.wait_for(
                        asyncio.shield(tab), timeout=settings.browser_timeout
                    )
                except (asyncio.TimeoutError, Exception) as exc:
                    log.debug("browser navigation wait timed out: %s", exc)

            try:
                await tab.evaluate(COOKIE_DISMISS_JS)
            except Exception as exc:
                log.debug("cookie dismiss failed: %s", exc)

            loc = await tab.evaluate("window.location.href")
            final_url = loc if isinstance(loc, str) else url
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
            except Exception as exc:
                log.debug("iframe scan failed: %s", exc)

            html = top_html + "\n".join(frame_htmls)
            return html, final_url, intercepted_json

    async def execute_html(
        self, html: str, origin_url: str
    ) -> tuple[str, str, list[dict[str, Any]]]:
        import urllib.parse

        intercepted_json: list[dict[str, Any]] = []
        content_ready = asyncio.Event()

        async with self.acquire_tab() as tab:
            await tab.send(zd.cdp.network.enable())
            # Use the same block list as get_html so the two tiers see consistent network behavior.
            await tab.send(zd.cdp.network.set_blocked_ur_ls(urls=BLOCKED_PATTERNS))

            tab.add_handler(
                zd.cdp.network.ResponseReceived,
                self._make_json_interceptor(tab, intercepted_json, content_ready),
            )

            encoded = urllib.parse.quote(html)
            data_url = f"data:text/html;charset=utf-8,{encoded}"
            await tab.get(data_url)

            try:
                await asyncio.wait_for(content_ready.wait(), timeout=8.0)
            except asyncio.TimeoutError:
                try:
                    await asyncio.wait_for(asyncio.shield(tab), timeout=5.0)
                except (asyncio.TimeoutError, Exception) as exc:
                    log.debug("execute_html navigation wait timed out: %s", exc)

            try:
                await tab.evaluate(COOKIE_DISMISS_JS)
            except Exception as exc:
                log.debug("cookie dismiss failed: %s", exc)
            rendered_html = await tab.get_content()

        return rendered_html, origin_url, intercepted_json


browser_pool = BrowserPool()

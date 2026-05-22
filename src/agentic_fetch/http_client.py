"""Shared, lazily-initialized httpx.AsyncClient with connection pooling.

A single client is reused across the process so TCP / TLS handshakes don't burn
on every request. The client is created on first call and closed by the FastAPI
lifespan so tests and short-lived CLIs don't crash on shutdown.
"""
import asyncio
import weakref

import httpx

from .config import settings

# One client per running event loop. Each test (and each app process) typically
# has exactly one loop; a fresh loop gets a fresh client transparently, so
# clients are never reused across closed loops.
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = (
    weakref.WeakKeyDictionary()
)


def get_client() -> httpx.AsyncClient:
    """Return the client bound to the current event loop, creating it on first use."""
    loop = asyncio.get_event_loop()
    client = _clients.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=settings.httpx_timeout,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
        _clients[loop] = client
    return client


async def close() -> None:
    """Close the client for the current event loop (called from lifespan shutdown)."""
    loop = asyncio.get_event_loop()
    client = _clients.pop(loop, None)
    if client is not None and not client.is_closed:
        await client.aclose()

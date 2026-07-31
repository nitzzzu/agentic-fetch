"""Acceptance scenarios (Gherkin) — offline, no real network or browser.

Feature files live in tests/features/. Each scenario exercises the service
through the public HTTP API with the network layer mocked via respx and the
cache isolated to a per-test directory.
"""

import re
from unittest.mock import AsyncMock, patch

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response
from pytest_bdd import given, parsers, scenarios, then, when

from agentic_fetch.cache import FetchCache

scenarios("features")


ARTICLE_HTML = (
    "<html><head><title>Offline Testing</title></head><body><article>"
    "<h1>Offline Testing</h1>"
    + "".join(
        f"<p>Paragraph {i} explains how deterministic acceptance tests exercise "
        f"the fetch pipeline without touching the real network or a browser, "
        f"covering conversion, caching and pagination behavior end to end.</p>"
        for i in range(1, 13)
    )
    + "</article></body></html>"
)


@pytest.fixture
def cache(tmp_path):
    """Real FetchCache in a per-test directory, wired into the app and engine."""
    c = FetchCache(cache_dir=str(tmp_path / "cache"), ttl=300)
    with (
        patch("agentic_fetch.main.fetch_cache", c),
        patch("agentic_fetch.fetch.fetch_cache", c),
    ):
        yield c


@pytest.fixture
def client(cache):
    """TestClient with the browser pool mocked so no Chrome process starts."""
    with patch("agentic_fetch.main.browser_pool") as mock_pool:
        mock_pool.start = AsyncMock()
        mock_pool.stop = AsyncMock()
        mock_pool.is_running = True
        from agentic_fetch.main import app

        with TestClient(app) as c:
            yield c


@pytest.fixture
def ctx():
    """Mutable scenario state shared between steps."""
    return {}


# ── Given ────────────────────────────────────────────────────────────────────


@given("an empty cache")
def empty_cache(cache):
    return cache


@given(
    parsers.parse('a cached document at "{url}" with {n:d} numbered lines'),
    target_fixture="cached_doc",
)
def cached_doc(cache, url, n):
    body = "\n".join(f"this is line {i} of the guide" for i in range(1, n + 1))
    cache.put(url, body, "html", method="httpx")
    return url


@given(parsers.parse('the network serves a static HTML article at "{url}"'))
def network_article(ctx, url):
    router = respx.mock(assert_all_called=False)
    router.get(url).mock(
        return_value=Response(200, html=ARTICLE_HTML, headers={"content-type": "text/html"})
    )
    router.start()
    ctx["router"] = router
    yield
    router.stop()


@given(parsers.parse('"{url}" has already been fetched once'))
def already_fetched(client, url):
    resp = client.post("/fetch", json={"url": url})
    assert resp.status_code == 200
    assert resp.json()["cached"] is False


@given(
    parsers.parse(
        'a fetch engine where "{ok_url}" succeeds and "{bad_url}" raises an error'
    )
)
def split_engine(ctx, ok_url, bad_url):
    from agentic_fetch.models import FetchRequest, FetchResponse

    async def fake_fetch(req: FetchRequest) -> FetchResponse:
        if req.url == bad_url:
            raise RuntimeError("upstream exploded")
        return FetchResponse(
            url=req.url, title="OK", markdown="# OK\n\ncontent", method_used="httpx"
        )

    engine = AsyncMock()
    engine.fetch = AsyncMock(side_effect=fake_fetch)
    patcher = patch("agentic_fetch.main.fetch_engine", engine)
    patcher.start()
    yield
    patcher.stop()


# ── When ─────────────────────────────────────────────────────────────────────


@when(
    parsers.parse('I file synthesized markdown at "{url}" saying "{body}"'),
    target_fixture="response",
)
def file_synthesis(client, url, body):
    return client.post("/cache/write", json={"url": url, "markdown": f"# Note\n\n{body}"})


@when(
    parsers.parse('I request lines {start:d} to {end:d} of "{url}"'),
    target_fixture="response",
)
def request_lines(client, url, start, end):
    return client.post("/fetch/lines", json={"url": url, "start": start, "end": end})


@when(
    parsers.parse('I grep "{url}" for the pattern "{pattern}"'),
    target_fixture="response",
)
def grep_doc(client, url, pattern):
    return client.post("/grep", json={"url": url, "pattern": pattern})


@when(parsers.parse('I evict "{url}" from the cache'), target_fixture="evict_response")
def evict_doc(client, url):
    resp = client.post("/cache/evict", json={"url": url})
    assert resp.status_code == 200
    assert resp.json()["removed"] is True
    return resp


@when(parsers.parse('I fetch "{url}"'), target_fixture="response")
def fetch_url(client, url):
    return client.post("/fetch", json={"url": url})


@when(
    parsers.parse('I fetch "{url}" with a budget of {max_tokens:d} tokens'),
    target_fixture="response",
)
def fetch_url_budget(client, url, max_tokens):
    return client.post("/fetch", json={"url": url, "max_tokens": max_tokens})


@when(
    parsers.parse('I batch-fetch "{url_a}" and "{url_b}"'),
    target_fixture="response",
)
def batch_fetch(client, url_a, url_b):
    return client.post("/fetch/batch", json={"urls": [url_a, url_b]})


@when("I request the service health", target_fixture="response")
def request_health(client):
    return client.get("/health")


# ── Then ─────────────────────────────────────────────────────────────────────


@then(
    parsers.parse('searching the cache for "{query}" returns "{url}" as the top hit')
)
def assert_search_top_hit(client, response, query, url):
    assert response.status_code == 200
    results = client.post("/cache/search", json={"query": query}).json()
    assert results, f"no cache-search results for {query!r}"
    assert results[0]["url"] == url


@then(parsers.parse("the line response contains lines {start:d} through {end:d} and no others"))
def assert_line_range(response, start, end):
    assert response.status_code == 200
    content = response.json()["content"]
    present = {int(m) for m in re.findall(r"this is line (\d+)", content)}
    assert present == set(range(start, end + 1))


@then(parsers.parse("the request fails with status {status:d}"))
def assert_status(response, status):
    assert response.status_code == status


@then(parsers.parse("the grep result marks line {lineno:d} as a match"))
def assert_grep_match(response, lineno):
    assert response.status_code == 200
    result = response.json()["result"]
    assert re.search(rf"^\s*{lineno}\*", result, re.M), result


@then(parsers.parse('the fetch succeeds with method "{method}"'))
def assert_fetch_method(response, method):
    assert response.status_code == 200
    assert response.json()["method_used"] == method


@then(parsers.parse('the markdown contains the article heading "{heading}"'))
def assert_markdown_heading(response, heading):
    assert heading in response.json()["markdown"]


@then("the response is marked as cached")
def assert_cached(response):
    assert response.status_code == 200
    assert response.json()["cached"] is True


@then("the response is truncated and reports a positive next offset")
def assert_truncated(response):
    assert response.status_code == 200
    data = response.json()
    assert data["truncated"] is True
    assert data["next_offset"] is not None and data["next_offset"] > 0


@then(parsers.parse("the batch reports {ok:d} success and {failed:d} failure"))
def assert_batch_counts(response, ok, failed):
    assert response.status_code == 200
    data = response.json()
    assert data["succeeded"] == ok
    assert data["failed"] == failed
    assert data["total"] == ok + failed


@then(parsers.parse('the failed entry names "{url}" with an error message'))
def assert_failed_entry(response, url):
    failures = [r for r in response.json()["results"] if not r["ok"]]
    assert len(failures) == 1
    assert failures[0]["url"] == url
    assert failures[0]["error"]


@then(parsers.parse('the service reports status "{status}"'))
def assert_health_status(response, status):
    assert response.status_code == 200
    assert response.json()["status"] == status


@then(parsers.parse('the discovered plugins include "{p1}", "{p2}" and "{p3}"'))
def assert_plugins(response, p1, p2, p3):
    plugins = response.json()["plugins"]
    assert {p1, p2, p3} <= set(plugins)

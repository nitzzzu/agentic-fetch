"""
Tests for Wikipedia plugin fixes:
1. Proper User-Agent sent to Wikimedia API (fixes 403)
2. Friendly error response on API failure (no bare raise_for_status)
3. Section HTML converted without readability (small fragments shouldn't be filtered)
4. Wildcard domain matching (fr.wikipedia.org, de.wikipedia.org, etc.)
"""
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch, call

from agentic_fetch.plugins.wikipedia import WikipediaPlugin
from agentic_fetch.plugins.base import FetchPlugin
from agentic_fetch.models import FetchRequest, FetchResponse


def make_req(url="https://en.wikipedia.org/wiki/Python_(programming_language)", **kw):
    return FetchRequest(url=url, **kw)


def make_summary(title="Python (programming language)"):
    return {
        "displaytitle": title,
        "description": "High-level programming language",
        "extract": "Python is a high-level, general-purpose programming language.",
    }


def make_extract_data():
    """Simulates MediaWiki Action API ?action=query&prop=extracts response."""
    return {
        "query": {
            "pages": {
                "12345": {
                    "pageid": 12345,
                    "title": "Python (programming language)",
                    "extract": (
                        "<p>Python was created by Guido van Rossum.</p>"
                        "<h2>Design philosophy</h2>"
                        "<p>Python emphasizes code readability.</p>"
                    ),
                }
            }
        }
    }


def _mock_client(summary_data, extract_data=None, summary_status=200):
    """Build an AsyncClient mock that returns given data."""
    summary_resp = MagicMock()
    summary_resp.status_code = summary_status
    if summary_status == 200:
        summary_resp.raise_for_status = MagicMock()
    else:
        summary_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                f"{summary_status}",
                request=MagicMock(),
                response=MagicMock(status_code=summary_status),
            )
        )
    summary_resp.json = MagicMock(return_value=summary_data)

    extract_resp = MagicMock()
    extract_resp.is_success = extract_data is not None
    extract_resp.json = MagicMock(return_value=extract_data or {})

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=[summary_resp, extract_resp])
    return mock_client


# ---------------------------------------------------------------------------
# Bug 1: Proper User-Agent sent to Wikimedia API
# ---------------------------------------------------------------------------

class TestUserAgent:
    @pytest.mark.asyncio
    async def test_user_agent_header_sent(self):
        """Plugin must send a descriptive User-Agent to avoid Wikimedia 403."""
        plugin = WikipediaPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.wikipedia.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client(make_summary(), make_extract_data())
            await plugin.fetch(req.url, req)

        # Check the headers passed to AsyncClient constructor
        _, kwargs = mock_cls.call_args
        headers = kwargs.get("headers", {})
        assert "User-Agent" in headers, "User-Agent header must be set"
        ua = headers["User-Agent"]
        assert len(ua) > 10, "User-Agent must be descriptive, not empty"
        assert ua != "python-httpx", "Must not use default httpx User-Agent"

    @pytest.mark.asyncio
    async def test_user_agent_is_not_default_httpx(self):
        """Default httpx User-Agent gets 403 — plugin must override it."""
        plugin = WikipediaPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.wikipedia.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client(make_summary(), make_extract_data())
            await plugin.fetch(req.url, req)

        _, kwargs = mock_cls.call_args
        ua = kwargs.get("headers", {}).get("User-Agent", "")
        assert "python-httpx" not in ua.lower()


# ---------------------------------------------------------------------------
# Bug 2: Friendly error response on API failure
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_403_returns_error_response_not_exception(self):
        """A 403 from the Wikimedia API must return a FetchResponse, not raise."""
        plugin = WikipediaPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.wikipedia.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client(None, summary_status=403)
            result = await plugin.fetch(req.url, req)

        assert isinstance(result, FetchResponse)
        assert result.error is not None or "403" in result.markdown or "error" in result.markdown.lower()

    @pytest.mark.asyncio
    async def test_500_returns_error_response_not_exception(self):
        """Any non-200 from the API must return a FetchResponse, not raise."""
        plugin = WikipediaPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.wikipedia.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client(None, summary_status=500)
            result = await plugin.fetch(req.url, req)

        assert isinstance(result, FetchResponse)

    @pytest.mark.asyncio
    async def test_network_error_returns_error_response(self):
        """A network error must return a FetchResponse, not raise."""
        plugin = WikipediaPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.wikipedia.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))
            mock_cls.return_value = mock_client

            result = await plugin.fetch(req.url, req)

        assert isinstance(result, FetchResponse)


# ---------------------------------------------------------------------------
# Bug 3: Section HTML should not run through readability
# ---------------------------------------------------------------------------

class TestSectionRendering:
    @pytest.mark.asyncio
    async def test_section_content_preserved(self):
        """Small section HTML must survive conversion — readability would strip it."""
        plugin = WikipediaPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.wikipedia.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client(make_summary(), make_extract_data())
            result = await plugin.fetch(req.url, req)

        assert isinstance(result, FetchResponse)
        assert "Guido van Rossum" in result.markdown
        assert "code readability" in result.markdown

    @pytest.mark.asyncio
    async def test_full_extract_body_included(self):
        """Full HTML extract from Action API should appear in output."""
        plugin = WikipediaPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.wikipedia.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client(make_summary(), make_extract_data())
            result = await plugin.fetch(req.url, req)

        assert "Design philosophy" in result.markdown

    @pytest.mark.asyncio
    async def test_summary_always_present(self):
        plugin = WikipediaPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.wikipedia.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client(make_summary(), make_extract_data())
            result = await plugin.fetch(req.url, req)

        assert "Guido van Rossum" in result.markdown        # from full extract
        assert "High-level programming language" in result.markdown  # description from summary

    @pytest.mark.asyncio
    async def test_no_extract_falls_back_to_summary(self):
        """When Action API returns nothing, falls back to summary extract."""
        plugin = WikipediaPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.wikipedia.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client(make_summary(), extract_data=None)
            result = await plugin.fetch(req.url, req)

        assert isinstance(result, FetchResponse)
        assert "general-purpose" in result.markdown


# ---------------------------------------------------------------------------
# Domain matching
# ---------------------------------------------------------------------------

class TestDomainMatching:
    def test_en_wikipedia_matches(self):
        assert WikipediaPlugin.matches("https://en.wikipedia.org/wiki/Python")

    def test_fr_wikipedia_matches(self):
        assert WikipediaPlugin.matches("https://fr.wikipedia.org/wiki/Python")

    def test_de_wikipedia_matches(self):
        assert WikipediaPlugin.matches("https://de.wikipedia.org/wiki/Python")

    def test_non_wiki_path_returns_none(self):
        # /wiki/ path check is inside fetch(), but matching should still hit the plugin
        assert WikipediaPlugin.matches("https://en.wikipedia.org/")

    def test_other_domain_does_not_match(self):
        assert not WikipediaPlugin.matches("https://example.com/wiki/Foo")

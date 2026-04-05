"""
Tests for four bugs in the GitHub plugin and fetch engine:

1. fetch.py: Plugin exceptions are not caught — should fall through to next tier
2. github.py _fetch_file: r.raise_for_status() on 404 — should return friendly FetchResponse
3. github.py _fetch_repo: default_branch not exposed in output
4. github.py: raw.githubusercontent.com URLs that 404 fall through to zendriver
"""
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from respx import MockRouter

from agentic_fetch.plugins.github import GitHubPlugin
from agentic_fetch.models import FetchRequest, FetchResponse
from agentic_fetch.fetch import FetchEngine


def make_req(url="https://github.com/owner/repo", **kwargs):
    return FetchRequest(url=url, **kwargs)


# ---------------------------------------------------------------------------
# Bug 2: _fetch_file raises on 404 instead of returning a friendly error
# ---------------------------------------------------------------------------

class TestFetchFileOn404:
    """GitHubPlugin._fetch_file should return a FetchResponse, never raise, on 404."""

    @pytest.mark.asyncio
    async def test_fetch_file_404_returns_error_response_not_exception(self):
        plugin = GitHubPlugin()
        req = make_req("https://github.com/owner/repo/blob/main/README.md")

        with patch("agentic_fetch.plugins.github.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "404", request=MagicMock(), response=MagicMock(status_code=404)
            )
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            # Must NOT raise — must return a FetchResponse
            result = await plugin._fetch_file("owner", "repo", "main", "README.md", req,
                                               "https://github.com/owner/repo/blob/main/README.md")

        assert isinstance(result, FetchResponse)
        assert result.error is not None or "404" in result.markdown or "not found" in result.markdown.lower()

    @pytest.mark.asyncio
    async def test_fetch_file_network_error_returns_error_response(self):
        plugin = GitHubPlugin()
        req = make_req("https://github.com/owner/repo/blob/main/README.md")

        with patch("agentic_fetch.plugins.github.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))
            mock_client_cls.return_value = mock_client

            result = await plugin._fetch_file("owner", "repo", "main", "README.md", req,
                                               "https://github.com/owner/repo/blob/main/README.md")

        assert isinstance(result, FetchResponse)
        assert result.error is not None or "error" in result.markdown.lower() or "not found" in result.markdown.lower()

    @pytest.mark.asyncio
    async def test_fetch_file_success_still_works(self):
        plugin = GitHubPlugin()
        req = make_req("https://github.com/owner/repo/blob/main/README.md")

        with patch("agentic_fetch.plugins.github.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()  # no-op
            mock_resp.text = "# Hello\n\nThis is the readme."
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await plugin._fetch_file("owner", "repo", "main", "README.md", req,
                                               "https://github.com/owner/repo/blob/main/README.md")

        assert isinstance(result, FetchResponse)
        assert "Hello" in result.markdown


# ---------------------------------------------------------------------------
# Bug 3: _fetch_repo doesn't expose default_branch
# ---------------------------------------------------------------------------

class TestFetchRepoDefaultBranch:
    """_fetch_repo should include the default_branch in its markdown output."""

    @pytest.mark.asyncio
    async def test_default_branch_included_in_output(self):
        plugin = GitHubPlugin()
        req = make_req("https://github.com/owner/repo")

        repo_info = {
            "full_name": "owner/repo",
            "description": "A test repo",
            "stargazers_count": 42,
            "forks_count": 5,
            "language": "Python",
            "license": {"spdx_id": "MIT"},
            "topics": [],
            "default_branch": "master",
        }

        with patch("agentic_fetch.plugins.github.httpx.AsyncClient") as mock_client_cls:
            repo_resp = MagicMock()
            repo_resp.raise_for_status = MagicMock()
            repo_resp.json.return_value = repo_info

            readme_resp = MagicMock()
            readme_resp.is_success = True
            readme_resp.text = "# Readme content"

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=[repo_resp, readme_resp])
            mock_client_cls.return_value = mock_client

            result = await plugin._fetch_repo("owner", "repo", req, "https://github.com/owner/repo")

        assert isinstance(result, FetchResponse)
        assert "master" in result.markdown

    @pytest.mark.asyncio
    async def test_default_branch_main_also_shown(self):
        plugin = GitHubPlugin()
        req = make_req("https://github.com/owner/repo")

        repo_info = {
            "full_name": "owner/repo",
            "description": "",
            "stargazers_count": 0,
            "forks_count": 0,
            "language": "Go",
            "license": None,
            "topics": [],
            "default_branch": "main",
        }

        with patch("agentic_fetch.plugins.github.httpx.AsyncClient") as mock_client_cls:
            repo_resp = MagicMock()
            repo_resp.raise_for_status = MagicMock()
            repo_resp.json.return_value = repo_info

            readme_resp = MagicMock()
            readme_resp.is_success = False

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=[repo_resp, readme_resp])
            mock_client_cls.return_value = mock_client

            result = await plugin._fetch_repo("owner", "repo", req, "https://github.com/owner/repo")

        assert "main" in result.markdown


# ---------------------------------------------------------------------------
# Bug 1: Plugin exception in fetch.py not caught — should fall through
# ---------------------------------------------------------------------------

class TestPluginExceptionFallthrough:
    """FetchEngine should catch plugin exceptions and fall through to Tier 2/3."""

    @pytest.mark.asyncio
    async def test_plugin_exception_does_not_propagate(self):
        """When plugin raises, fetch() should not raise — it should fall through."""
        engine = FetchEngine()
        req = make_req("https://github.com/owner/repo/blob/main/README.md")

        raising_plugin = MagicMock()
        raising_plugin.return_value.fetch = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "404", request=MagicMock(), response=MagicMock(status_code=404)
            )
        )

        fallback_response = FetchResponse(
            url=req.url, title="Fallback", markdown="fallback content",
            method_used="httpx",
        )

        with patch("agentic_fetch.fetch.get_plugin", return_value=raising_plugin), \
             patch.object(engine, "_httpx_fetch", AsyncMock(return_value=("fallback content", req.url, "", "text/html"))), \
             patch.object(engine, "_build_response", return_value=fallback_response), \
             patch.object(engine, "_needs_js", return_value=False):

            # Must NOT raise
            result = await engine.fetch(req)

        assert isinstance(result, FetchResponse)

    @pytest.mark.asyncio
    async def test_plugin_generic_exception_does_not_propagate(self):
        """Any exception from a plugin (not just HTTP) should be caught."""
        engine = FetchEngine()
        req = make_req("https://github.com/owner/repo/blob/main/README.md")

        raising_plugin = MagicMock()
        raising_plugin.return_value.fetch = AsyncMock(
            side_effect=ValueError("unexpected plugin error")
        )

        fallback_response = FetchResponse(
            url=req.url, title="Fallback", markdown="fallback content",
            method_used="httpx",
        )

        with patch("agentic_fetch.fetch.get_plugin", return_value=raising_plugin), \
             patch.object(engine, "_httpx_fetch", AsyncMock(return_value=("<html>fallback</html>", req.url, "", "text/html"))), \
             patch.object(engine, "_build_response", return_value=fallback_response), \
             patch.object(engine, "_needs_js", return_value=False):

            result = await engine.fetch(req)

        assert isinstance(result, FetchResponse)


# ---------------------------------------------------------------------------
# Bug 4: raw.githubusercontent.com 404 wastes a zendriver session
# ---------------------------------------------------------------------------

class TestRawGitHubUrlHandling:
    """raw.githubusercontent.com URLs should be handled directly, not fall to zendriver."""

    @pytest.mark.asyncio
    async def test_raw_url_404_returns_error_response_not_zendriver(self):
        """A 404 on a raw.githubusercontent.com URL should return an error FetchResponse."""
        plugin = GitHubPlugin()
        req = make_req("https://raw.githubusercontent.com/owner/repo/main/README.md")

        # The plugin should handle raw URLs and return an error on 404,
        # rather than returning None (which causes zendriver fallback)
        result = await plugin.fetch(
            "https://raw.githubusercontent.com/owner/repo/main/README.md", req
        )

        # Plugin must NOT return None for raw.githubusercontent.com URLs
        # (returning None causes expensive zendriver fallback)
        assert result is not None

    @pytest.mark.asyncio
    async def test_raw_url_success_returns_file_content(self):
        """A successful raw.githubusercontent.com URL returns the file content."""
        plugin = GitHubPlugin()
        req = make_req("https://raw.githubusercontent.com/owner/repo/main/README.md")

        with patch("agentic_fetch.plugins.github.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.text = "# Hello from raw"
            mock_resp.status_code = 200
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await plugin.fetch(
                "https://raw.githubusercontent.com/owner/repo/main/README.md", req
            )

        assert result is not None
        assert isinstance(result, FetchResponse)
        assert "Hello from raw" in result.markdown

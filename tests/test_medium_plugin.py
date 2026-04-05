"""
Tests for Medium plugin:
1. Freedium proxy is used to bypass paywall
2. Title and author extracted from HTML meta tags
3. SKIP_PATTERNS lines filtered from output
4. Article content starts after first heading (_clean logic)
5. include_links=False strips anchor tags
6. HTTP errors return FetchResponse without raising
7. Domain matching covers medium.com and partner publications
"""
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from agentic_fetch.plugins.medium import MediumPlugin
from agentic_fetch.models import FetchRequest, FetchResponse

ARTICLE_URL = "https://realz.medium.com/running-android-on-kubernetes-be73b940833f"

# Minimal Freedium-style HTML for "Running Android on Kubernetes"
FREEDIUM_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>Running Android on Kubernetes | Freedium</title>
  <meta name="author" content="Realz">
</head>
<body>
  <header><a href="/">Freedium</a> <a href="/donate">Ko-fi</a></header>
  <nav>Sign in Sign up Open in app</nav>
  <div id="top-bar">Free: Yes</div>
  <main>
    <h1>Running Android on Kubernetes</h1>
    <p>5 min read · some extra text</p>
    <p>Android is typically run on physical devices, but what if you could
       run it inside a Kubernetes cluster using <a href="https://waydro.id/">Waydroid</a>?</p>
    <h2>Architecture</h2>
    <p>The solution uses <strong>KVM</strong> for hardware acceleration and
       a custom container image based on <code>lineageos</code>.</p>
    <h2>Deployment</h2>
    <p>A sample manifest is provided. Apply it with
       <code>kubectl apply -f android.yaml</code>.</p>
    <pre><code>apiVersion: apps/v1
kind: Deployment
metadata:
  name: android
</code></pre>
  </main>
  <footer>< Go to the original Reporting a Problem</footer>
</body>
</html>"""


def make_req(url=ARTICLE_URL, **kw):
    return FetchRequest(url=url, **kw)


def _mock_client(html=FREEDIUM_HTML, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = html
    if status == 200:
        resp.raise_for_status = MagicMock()
    else:
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                str(status),
                request=MagicMock(),
                response=MagicMock(status_code=status),
            )
        )

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=resp)
    return mock_client


# ---------------------------------------------------------------------------
# Freedium proxy
# ---------------------------------------------------------------------------

class TestFreedriumProxy:
    @pytest.mark.asyncio
    async def test_freedium_url_is_used(self):
        """Plugin must fetch via Freedium, not the original Medium URL."""
        plugin = MediumPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.medium.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client()
            await plugin.fetch(req.url, req)

        mock_client = mock_cls.return_value.__aenter__.return_value
        called_url = mock_client.get.call_args[0][0]
        assert "freedium" in called_url
        assert ARTICLE_URL in called_url

    @pytest.mark.asyncio
    async def test_response_url_is_original(self):
        """FetchResponse.url must be the original Medium URL, not Freedium."""
        plugin = MediumPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.medium.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client()
            result = await plugin.fetch(req.url, req)

        assert result.url == ARTICLE_URL


# ---------------------------------------------------------------------------
# Title and author extraction
# ---------------------------------------------------------------------------

class TestMetaExtraction:
    @pytest.mark.asyncio
    async def test_title_stripped_of_medium_suffix(self):
        """'| Freedium' suffix must be removed from the page title."""
        plugin = MediumPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.medium.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client()
            result = await plugin.fetch(req.url, req)

        assert result.title == "Running Android on Kubernetes"
        assert "Freedium" not in result.title

    @pytest.mark.asyncio
    async def test_author_prepended_when_present(self):
        """Author from <meta name='author'> must appear at the top of the markdown."""
        plugin = MediumPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.medium.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client()
            result = await plugin.fetch(req.url, req)

        assert result.markdown.startswith("*Author: Realz*")

    @pytest.mark.asyncio
    async def test_no_author_when_meta_missing(self):
        html_no_author = FREEDIUM_HTML.replace('<meta name="author" content="Realz">', "")

        plugin = MediumPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.medium.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client(html=html_no_author)
            result = await plugin.fetch(req.url, req)

        assert "*Author:" not in result.markdown


# ---------------------------------------------------------------------------
# Content filtering (_clean)
# ---------------------------------------------------------------------------

class TestContentFiltering:
    @pytest.mark.asyncio
    async def test_skip_patterns_removed(self):
        """Lines matching SKIP_PATTERNS (Freedium, Ko-fi, Sign in, etc.) must be absent."""
        plugin = MediumPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.medium.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client()
            result = await plugin.fetch(req.url, req)

        for banned in ["Ko-fi", "Sign in", "Sign up", "Open in app", "Free: Yes",
                       "Go to the original", "Reporting a Problem"]:
            assert banned not in result.markdown, f"'{banned}' should be stripped"

    @pytest.mark.asyncio
    async def test_article_content_preserved(self):
        """Core article content must be present after filtering."""
        plugin = MediumPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.medium.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client()
            result = await plugin.fetch(req.url, req)

        assert "Kubernetes" in result.markdown
        assert "Waydroid" in result.markdown
        assert "KVM" in result.markdown

    @pytest.mark.asyncio
    async def test_headings_preserved(self):
        plugin = MediumPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.medium.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client()
            result = await plugin.fetch(req.url, req)

        assert "Architecture" in result.markdown
        assert "Deployment" in result.markdown


# ---------------------------------------------------------------------------
# Link and image handling
# ---------------------------------------------------------------------------

class TestLinksAndImages:
    @pytest.mark.asyncio
    async def test_links_included_by_default(self):
        plugin = MediumPlugin()
        req = make_req(include_links=True)

        with patch("agentic_fetch.plugins.medium.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client()
            result = await plugin.fetch(req.url, req)

        assert "waydro.id" in result.markdown

    @pytest.mark.asyncio
    async def test_links_stripped_when_disabled(self):
        plugin = MediumPlugin()
        req = make_req(include_links=False)

        with patch("agentic_fetch.plugins.medium.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client()
            result = await plugin.fetch(req.url, req)

        assert "waydro.id" not in result.markdown
        assert "Waydroid" in result.markdown  # text content preserved


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_403_raises_http_error(self):
        """403 from Freedium propagates as HTTPStatusError (no try/except in plugin)."""
        plugin = MediumPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.medium.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client(status=403)
            with pytest.raises(httpx.HTTPStatusError):
                await plugin.fetch(req.url, req)

    @pytest.mark.asyncio
    async def test_network_error_propagates(self):
        plugin = MediumPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.medium.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))
            mock_cls.return_value = mock_client

            with pytest.raises(httpx.ConnectError):
                await plugin.fetch(req.url, req)


# ---------------------------------------------------------------------------
# Domain matching
# ---------------------------------------------------------------------------

class TestDomainMatching:
    def test_medium_com_matches(self):
        assert MediumPlugin.matches("https://medium.com/some/article")

    def test_subdomain_medium_matches(self):
        assert MediumPlugin.matches(ARTICLE_URL)

    def test_towardsdatascience_matches(self):
        assert MediumPlugin.matches("https://towardsdatascience.com/article-slug")

    def test_betterprogramming_matches(self):
        assert MediumPlugin.matches("https://betterprogramming.pub/article-slug")

    def test_other_domain_does_not_match(self):
        assert not MediumPlugin.matches("https://example.com/article")

    def test_github_does_not_match(self):
        assert not MediumPlugin.matches("https://github.com/org/repo")

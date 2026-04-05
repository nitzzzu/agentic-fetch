"""
Tests for HackerNews plugin fixes:
1. KeyError: 'objectID' — items API uses 'id', not 'objectID'
2. Comment/story text is HTML — entities and tags need to be converted
3. Missing error handling on raise_for_status()
"""
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from agentic_fetch.plugins.hackernews import HackerNewsPlugin
from agentic_fetch.models import FetchRequest, FetchResponse


def make_req(item_id="43574847"):
    return FetchRequest(url=f"https://news.ycombinator.com/item?id={item_id}")


def make_story(**overrides):
    base = {
        "id": 43574847,
        "title": "Texas children treated for Vitamin A toxicity",
        "author": "croes",
        "points": 19,
        "created_at": "2026-04-05T10:00:00.000Z",
        "url": "https://example.com/article",
        "text": None,
        "type": "story",
        "children": [],
    }
    base.update(overrides)
    return base


def make_comment(text="A plain comment", **overrides):
    base = {
        "id": 99001,
        "author": "user1",
        "type": "comment",
        "text": text,
        "children": [],
        "created_at": "2026-04-05T10:01:00.000Z",
    }
    base.update(overrides)
    return base


def _mock_client(story_data, status=200):
    resp = MagicMock()
    resp.status_code = status
    if status == 200:
        resp.raise_for_status = MagicMock()
    else:
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                str(status), request=MagicMock(),
                response=MagicMock(status_code=status),
            )
        )
    resp.json = MagicMock(return_value=story_data)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=resp)
    return mock_client


# ---------------------------------------------------------------------------
# Bug 1: objectID -> id
# ---------------------------------------------------------------------------

class TestItemId:
    @pytest.mark.asyncio
    async def test_does_not_raise_on_missing_objectID(self):
        """Algolia items API returns 'id', not 'objectID' — must not KeyError."""
        plugin = HackerNewsPlugin()
        req = make_req()
        story = make_story()  # has 'id', no 'objectID'
        assert "objectID" not in story

        with patch("agentic_fetch.plugins.hackernews.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client(story)
            result = await plugin.fetch(req.url, req)

        assert isinstance(result, FetchResponse)
        assert result.error is None

    @pytest.mark.asyncio
    async def test_hn_url_uses_id_field(self):
        """HN discussion link must use the 'id' field from the response."""
        plugin = HackerNewsPlugin()
        req = make_req("43574847")

        with patch("agentic_fetch.plugins.hackernews.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client(make_story(id=43574847))
            result = await plugin.fetch(req.url, req)

        assert "43574847" in result.markdown


# ---------------------------------------------------------------------------
# Bug 2: HTML in text fields
# ---------------------------------------------------------------------------

class TestHtmlDecoding:
    @pytest.mark.asyncio
    async def test_html_entities_in_comment_decoded(self):
        """HTML entities like &quot; &#x27; must be decoded in comments."""
        plugin = HackerNewsPlugin()
        req = make_req()
        story = make_story(children=[
            make_comment(text="I&apos;m &quot;amazed&quot; by this &amp; that")
        ])

        with patch("agentic_fetch.plugins.hackernews.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client(story)
            result = await plugin.fetch(req.url, req)

        assert "&quot;" not in result.markdown
        assert "&amp;" not in result.markdown
        assert "amazed" in result.markdown

    @pytest.mark.asyncio
    async def test_html_tags_in_comment_stripped_or_converted(self):
        """HTML tags like <p>, <a href>, <i> must not appear raw in markdown."""
        plugin = HackerNewsPlugin()
        req = make_req()
        story = make_story(children=[
            make_comment(text="<p>See <a href='https://example.com'>this link</a> for details.</p>")
        ])

        with patch("agentic_fetch.plugins.hackernews.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client(story)
            result = await plugin.fetch(req.url, req)

        assert "<p>" not in result.markdown
        assert "<a href" not in result.markdown
        assert "this link" in result.markdown  # text content preserved
        assert "details" in result.markdown

    @pytest.mark.asyncio
    async def test_html_in_story_text_decoded(self):
        """Ask HN posts use 'text' field with HTML — must be converted."""
        plugin = HackerNewsPlugin()
        req = make_req()
        story = make_story(
            url=None,
            text="<p>Has anyone tried <i>this approach</i>? It&apos;s interesting.</p>"
        )

        with patch("agentic_fetch.plugins.hackernews.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client(story)
            result = await plugin.fetch(req.url, req)

        assert "<p>" not in result.markdown
        assert "&apos;" not in result.markdown
        assert "this approach" in result.markdown


# ---------------------------------------------------------------------------
# Bug 3: error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_404_returns_error_response(self):
        plugin = HackerNewsPlugin()
        req = make_req("99999999")

        with patch("agentic_fetch.plugins.hackernews.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client(None, status=404)
            result = await plugin.fetch(req.url, req)

        assert isinstance(result, FetchResponse)
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_network_error_returns_error_response(self):
        plugin = HackerNewsPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.hackernews.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))
            mock_cls.return_value = mock_client

            result = await plugin.fetch(req.url, req)

        assert isinstance(result, FetchResponse)
        assert result.error is not None


# ---------------------------------------------------------------------------
# General correctness
# ---------------------------------------------------------------------------

class TestGeneral:
    @pytest.mark.asyncio
    async def test_non_item_url_returns_none(self):
        plugin = HackerNewsPlugin()
        req = FetchRequest(url="https://news.ycombinator.com/")
        result = await plugin.fetch(req.url, req)
        assert result is None

    @pytest.mark.asyncio
    async def test_title_and_meta_present(self):
        plugin = HackerNewsPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.hackernews.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client(make_story())
            result = await plugin.fetch(req.url, req)

        assert "Vitamin A toxicity" in result.markdown
        assert "croes" in result.markdown
        assert "19" in result.markdown  # points

    @pytest.mark.asyncio
    async def test_story_link_present(self):
        plugin = HackerNewsPlugin()
        req = make_req()

        with patch("agentic_fetch.plugins.hackernews.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_client(make_story())
            result = await plugin.fetch(req.url, req)

        assert "example.com/article" in result.markdown

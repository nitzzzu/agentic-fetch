"""Offline RedditPlugin tests — the Reddit JSON API is mocked via respx."""

import pytest
import respx
from httpx import Response

from agentic_fetch.models import FetchRequest
from agentic_fetch.plugins.reddit import RedditPlugin

pytestmark = pytest.mark.asyncio

plugin = RedditPlugin()

POST_URL = "https://www.reddit.com/r/python/comments/abc123/async_tips/"


def comment(body: str, author: str = "commenter", replies=None, **extra) -> dict:
    data = {"body": body, "author": author, "score": 5, **extra}
    if replies is not None:
        data["replies"] = {"data": {"children": replies}}
    return {"kind": "t1", "data": data}


def thread_payload(selftext: str = "Post body here", comments=()) -> list:
    return [
        {
            "data": {
                "children": [
                    {
                        "data": {
                            "title": "Async tips &amp; tricks",
                            "author": "op_user",
                            "subreddit": "python",
                            "score": 321,
                            "num_comments": 2,
                            "created_utc": 1700000000,
                            "permalink": "/r/python/comments/abc123/async_tips/",
                            "selftext": selftext,
                            "is_self": True,
                        }
                    }
                ]
            }
        },
        {"data": {"children": list(comments)}},
    ]


def mock_thread(payload: list) -> None:
    respx.get("https://www.reddit.com/r/python/comments/abc123/async_tips.json").mock(
        return_value=Response(200, json=payload)
    )


class TestUrlMatching:
    def test_matches_reddit_domains(self):
        assert RedditPlugin.matches("https://www.reddit.com/r/python/comments/x/y/")
        assert RedditPlugin.matches("https://old.reddit.com/r/python/comments/x/y/")
        assert RedditPlugin.matches("https://redd.it/abc123")

    def test_does_not_match_other_domains(self):
        assert not RedditPlugin.matches("https://example.com/r/python")


class TestPostFormatting:
    @respx.mock
    async def test_post_header_includes_title_author_and_score(self):
        mock_thread(thread_payload())
        resp = await plugin.fetch(POST_URL, FetchRequest(url=POST_URL))
        assert resp.plugin_used == "reddit"
        assert resp.method_used == "plugin"
        assert resp.title == "Async tips & tricks"  # HTML entities unescaped
        assert "# Async tips & tricks" in resp.markdown
        assert "u/op_user" in resp.markdown
        assert "321 points" in resp.markdown
        assert "Post body here" in resp.markdown

    @respx.mock
    async def test_old_reddit_urls_are_normalized_to_www(self):
        mock_thread(thread_payload())
        old_url = "https://old.reddit.com/r/python/comments/abc123/async_tips/"
        resp = await plugin.fetch(old_url, FetchRequest(url=old_url))
        assert resp.url.startswith("https://www.reddit.com/")

    @respx.mock
    async def test_unexpected_payload_shape_raises(self):
        respx.get(
            "https://www.reddit.com/r/python/comments/abc123/async_tips.json"
        ).mock(return_value=Response(200, json={"not": "a list"}))
        with pytest.raises(ValueError, match="Unexpected Reddit API response"):
            await plugin.fetch(POST_URL, FetchRequest(url=POST_URL))


class TestCommentFormatting:
    @respx.mock
    async def test_comments_render_with_authors_and_op_badge(self):
        mock_thread(
            thread_payload(
                comments=[
                    comment("First!", author="op_user"),
                    comment("Great post"),
                ]
            )
        )
        resp = await plugin.fetch(POST_URL, FetchRequest(url=POST_URL))
        assert "## Comments" in resp.markdown
        assert "**u/op_user** **[OP]**" in resp.markdown
        assert "Great post" in resp.markdown

    @respx.mock
    async def test_nested_replies_are_quoted(self):
        mock_thread(
            thread_payload(
                comments=[comment("Parent", replies=[comment("Child reply")])]
            )
        )
        resp = await plugin.fetch(POST_URL, FetchRequest(url=POST_URL))
        assert "> Child reply" in resp.markdown

    @respx.mock
    async def test_deleted_and_removed_comments_are_dropped(self):
        mock_thread(
            thread_payload(
                comments=[
                    comment("visible"),
                    comment("hidden", author="[deleted]"),
                    {"kind": "more", "data": {}},
                ]
            )
        )
        resp = await plugin.fetch(POST_URL, FetchRequest(url=POST_URL))
        assert "visible" in resp.markdown
        assert "hidden" not in resp.markdown

    @respx.mock
    async def test_moderator_comments_get_mod_badge(self):
        mock_thread(
            thread_payload(comments=[comment("locked", distinguished="moderator")])
        )
        resp = await plugin.fetch(POST_URL, FetchRequest(url=POST_URL))
        assert "**[MOD]**" in resp.markdown

    @respx.mock
    async def test_post_without_comments_has_no_comments_section(self):
        mock_thread(thread_payload(comments=[]))
        resp = await plugin.fetch(POST_URL, FetchRequest(url=POST_URL))
        assert "## Comments" not in resp.markdown

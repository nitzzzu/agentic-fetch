"""Tests for FetchEngine utility methods."""
import pytest
from agentic_fetch.fetch import FetchEngine
from agentic_fetch.models import FetchRequest

engine = FetchEngine()


class TestNeedsJs:
    def test_static_page_no_js_needed(self):
        html = """
        <html><body>
        <h1>Hello</h1>
        <p>This is a real static page with lots of content and words. It has many sentences
        and multiple paragraphs so the word count is well above the threshold required to
        determine that this page does not need JavaScript to render its content. Here are
        more words to make the count even higher. Testing testing one two three four five.</p>
        </body></html>
        """
        assert not engine._needs_js(html)

    def test_js_heavy_page_needs_js(self):
        # Few words + multiple scripts = needs JS
        html = """
        <html>
        <head>
        <script src="bundle.js"></script>
        <script src="vendor.js"></script>
        <script src="app.js"></script>
        </head>
        <body><div id="root"></div></body>
        </html>
        """
        assert engine._needs_js(html)

    def test_many_scripts_but_enough_text(self):
        words = " ".join(["word"] * 200)
        html = f"""
        <html>
        <head>
        <script src="a.js"></script>
        <script src="b.js"></script>
        </head>
        <body><p>{words}</p></body>
        </html>
        """
        assert not engine._needs_js(html)


class TestJsonToMarkdown:
    def make_req(self, **kwargs):
        return FetchRequest(url="https://example.com", **kwargs)

    def test_extracts_content_field(self):
        # Minimum 100 chars required by the implementation
        data = {"content": "This is the article body with enough text to pass the threshold. " * 3}
        result = engine._json_to_markdown(data, self.make_req())
        assert "article body" in result

    def test_extracts_body_field(self):
        data = {"body": "Body text with sufficient length to be processed correctly here. " * 3}
        result = engine._json_to_markdown(data, self.make_req())
        assert "Body text" in result

    def test_extracts_html_content(self):
        data = {"content": "<p>HTML paragraph content with enough text to process.</p>" * 5}
        result = engine._json_to_markdown(data, self.make_req())
        assert "HTML paragraph" in result

    def test_skips_short_values(self):
        data = {"content": "short"}
        result = engine._json_to_markdown(data, self.make_req())
        assert result == ""

    def test_skips_non_string_values(self):
        data = {"content": 12345, "body": ["list", "items"]}
        result = engine._json_to_markdown(data, self.make_req())
        assert result == ""

    def test_empty_dict(self):
        result = engine._json_to_markdown({}, self.make_req())
        assert result == ""

    def test_prefers_first_matching_key(self):
        # "content" comes before "body" in the key priority list; both >= 100 chars
        data = {
            "content": "Content field text with enough characters to qualify properly. " * 3,
            "body": "Body field text with enough characters to qualify properly here. " * 3,
        }
        result = engine._json_to_markdown(data, self.make_req())
        assert "Content field" in result

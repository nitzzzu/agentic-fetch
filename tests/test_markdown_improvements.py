"""
Tests for markdown extraction improvements inspired by the reddit post:
- readability-lxml: extract main article content before converting to markdown
- Cleaner output: boilerplate (nav/footer/sidebar/ads) stripped automatically
"""
import pytest
from agentic_fetch.markdown import MarkdownExtractor


# Realistic page with nav, main article, sidebar, footer — like a docs page
ARTICLE_PAGE = """
<html>
<head><title>How to use asyncio</title></head>
<body>
  <nav>
    <a href="/">Home</a>
    <a href="/docs">Docs</a>
    <a href="/about">About</a>
    <ul>
      <li><a href="/page1">Link 1</a></li>
      <li><a href="/page2">Link 2</a></li>
    </ul>
  </nav>
  <header>
    <div class="site-header">My Documentation Site</div>
    <div class="breadcrumbs">Home > Docs > asyncio</div>
  </header>
  <main>
    <article>
      <h1>How to use asyncio</h1>
      <p>Python's asyncio library provides infrastructure for writing asynchronous code.
      It is the foundation for many modern Python frameworks including FastAPI and aiohttp.</p>
      <h2>Getting started</h2>
      <p>To run a coroutine, use <code>asyncio.run()</code>. This is the standard entry
      point for asyncio programs in Python 3.7 and later.</p>
      <pre><code class="language-python">import asyncio

async def main():
    print("Hello asyncio")

asyncio.run(main())
</code></pre>
      <h2>Event loop</h2>
      <p>The event loop is the core of every asyncio application. It runs async tasks,
      handles I/O, and manages callbacks. You rarely need to interact with it directly.</p>
    </article>
  </main>
  <aside class="sidebar">
    <div>Advertisement</div>
    <div>Related articles</div>
    <ul>
      <li>Another article</li>
      <li>Yet another article</li>
    </ul>
  </aside>
  <footer>
    <p>Copyright 2024 My Site. All rights reserved.</p>
    <a href="/privacy">Privacy Policy</a>
    <a href="/terms">Terms of Service</a>
  </footer>
</body>
</html>
"""

# Simple page with lots of boilerplate — readability should keep main content
BLOG_POST_PAGE = """
<html>
<head><title>Understanding Python Decorators</title></head>
<body>
  <div class="navbar">Nav Nav Nav Nav Nav Nav Nav Nav Nav Nav</div>
  <div class="cookie-banner">We use cookies. Accept? Yes No Maybe</div>
  <div class="content">
    <h1>Understanding Python Decorators</h1>
    <p>Decorators are a powerful feature in Python that allow you to modify or
    enhance functions and classes without changing their source code directly.</p>
    <p>A decorator is essentially a function that takes another function as an
    argument, adds some functionality, and returns a modified function.</p>
    <h2>Basic syntax</h2>
    <p>The <code>@</code> symbol is syntactic sugar for applying a decorator.
    Writing <code>@my_decorator</code> above a function is equivalent to
    calling <code>my_decorator(func)</code> after defining it.</p>
    <pre><code>def my_decorator(func):
    def wrapper(*args, **kwargs):
        print("Before call")
        result = func(*args, **kwargs)
        print("After call")
        return result
    return wrapper

@my_decorator
def greet(name):
    print(f"Hello, {name}!")
</code></pre>
  </div>
  <div class="sidebar">
    <div>Subscribe to newsletter</div>
    <div>Follow us on social media</div>
  </div>
  <div class="footer">Footer Footer Footer Footer Footer Footer</div>
</body>
</html>
"""

MINIMAL_HTML = "<html><body><p>Hello world</p></body></html>"
EMPTY_HTML = "<html><body></body></html>"


class TestReadabilityExtraction:
    """readability-lxml strips boilerplate, keeping main article content."""

    def test_strips_nav_from_output(self):
        ext = MarkdownExtractor(ARTICLE_PAGE)
        md = ext.to_markdown()
        # nav links should not dominate the output
        assert md.count("Home") <= 1  # may appear in breadcrumb, not nav list too

    def test_strips_footer_boilerplate(self):
        ext = MarkdownExtractor(ARTICLE_PAGE)
        md = ext.to_markdown()
        assert "Privacy Policy" not in md
        assert "Terms of Service" not in md
        assert "All rights reserved" not in md

    def test_strips_sidebar(self):
        ext = MarkdownExtractor(ARTICLE_PAGE)
        md = ext.to_markdown()
        assert "Advertisement" not in md

    def test_keeps_article_heading(self):
        ext = MarkdownExtractor(ARTICLE_PAGE)
        md = ext.to_markdown()
        assert "asyncio" in md.lower()

    def test_keeps_article_body_text(self):
        ext = MarkdownExtractor(ARTICLE_PAGE)
        md = ext.to_markdown()
        assert "infrastructure for writing asynchronous" in md

    def test_keeps_code_block(self):
        ext = MarkdownExtractor(ARTICLE_PAGE)
        md = ext.to_markdown()
        assert "asyncio.run" in md

    def test_keeps_subheadings(self):
        ext = MarkdownExtractor(ARTICLE_PAGE)
        md = ext.to_markdown()
        assert "Getting started" in md or "Event loop" in md

    def test_blog_post_keeps_main_content(self):
        ext = MarkdownExtractor(BLOG_POST_PAGE)
        md = ext.to_markdown()
        assert "Decorators" in md
        assert "syntactic sugar" in md

    def test_blog_post_strips_navbar_boilerplate(self):
        ext = MarkdownExtractor(BLOG_POST_PAGE)
        md = ext.to_markdown()
        # "Nav Nav Nav..." repeated boilerplate should be gone
        assert md.count("Nav") < 3

    def test_blog_post_strips_footer_boilerplate(self):
        ext = MarkdownExtractor(BLOG_POST_PAGE)
        md = ext.to_markdown()
        assert md.count("Footer") < 3

    def test_selector_still_overrides_readability(self):
        """When explicit CSS selector is given, readability is bypassed."""
        ext = MarkdownExtractor(ARTICLE_PAGE)
        md = ext.to_markdown(selector="footer")
        assert "Privacy Policy" in md or "All rights reserved" in md

    def test_minimal_page_does_not_crash(self):
        ext = MarkdownExtractor(MINIMAL_HTML)
        md = ext.to_markdown()
        assert "Hello world" in md

    def test_empty_page_does_not_crash(self):
        ext = MarkdownExtractor(EMPTY_HTML)
        md = ext.to_markdown()
        assert isinstance(md, str)

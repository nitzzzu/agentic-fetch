"""
Live API tests — hit the running agentic-fetch service at http://127.0.0.1:8000.

Requirements:
  - The service must be running: uvicorn agentic_fetch.main:app --port 8000
  - Chrome must be installed (Google search uses zendriver)

Run all:
    pytest tests/test_api_live.py -v -s

Run only Google search tests:
    pytest tests/test_api_live.py::TestGoogleSearchLive -v -s

Skip if the server is not up:
    Tests are auto-skipped when the service is unreachable.
"""
import pytest
import httpx

BASE_URL = "http://127.0.0.1:8000"
TIMEOUT = 60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _post_search(query: str, engine: str = "google", max_results: int = 5) -> dict:
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.post(f"{BASE_URL}/search", json={
            "query": query,
            "engine": engine,
            "max_results": max_results,
        })
    r.raise_for_status()
    return r.json()


def _check_service():
    try:
        with httpx.Client(timeout=5) as c:
            c.get(f"{BASE_URL}/health")
    except httpx.ConnectError:
        pytest.skip("agentic-fetch service not running on http://127.0.0.1:8000")


# ---------------------------------------------------------------------------
# Shared fixture — one Google search per topic, reused across assertions
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def google_ai_news():
    """POST /search  query='ai news'  engine=google  — result cached for the module."""
    _check_service()
    return _post_search("ai news", engine="google", max_results=5)


@pytest.fixture(scope="module")
def google_python():
    """POST /search  query='python programming language'  engine=google."""
    _check_service()
    return _post_search("python programming language", engine="google", max_results=5)


@pytest.fixture(scope="module")
def google_single_result():
    """POST /search  max_results=1 — for limit enforcement tests."""
    _check_service()
    return _post_search("openai gpt", engine="google", max_results=1)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_service_is_up(self):
        _check_service()
        with httpx.Client(timeout=5) as c:
            r = c.get(f"{BASE_URL}/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

    def test_browser_running(self):
        _check_service()
        with httpx.Client(timeout=5) as c:
            r = c.get(f"{BASE_URL}/health")
        assert r.json()["browser_running"] is True


# ---------------------------------------------------------------------------
# /search  —  engine=google
# ---------------------------------------------------------------------------

class TestGoogleSearchLive:
    """Tests against POST /search with engine='google'."""

    # --- response structure ---

    def test_status_200(self, google_ai_news):
        # fixture already raises on non-200; reaching here means 200
        assert isinstance(google_ai_news, dict)

    def test_response_has_required_fields(self, google_ai_news):
        for field in ("query", "engine_used", "results"):
            assert field in google_ai_news, f"Missing field: {field!r}"

    def test_engine_used_is_google(self, google_ai_news):
        assert google_ai_news["engine_used"] == "google"

    def test_query_echoed_back(self, google_ai_news):
        assert google_ai_news["query"] == "ai news"

    # --- result count ---

    def test_returns_multiple_results(self, google_ai_news):
        assert len(google_ai_news["results"]) >= 3, (
            f"Expected ≥3 results, got {len(google_ai_news['results'])}"
        )

    def test_max_results_limit_respected(self, google_single_result):
        assert len(google_single_result["results"]) <= 1

    # --- per-result fields ---

    def test_all_results_have_title(self, google_ai_news):
        for r in google_ai_news["results"]:
            assert r["title"], f"Empty title in: {r}"

    def test_all_results_have_valid_url(self, google_ai_news):
        for r in google_ai_news["results"]:
            assert r["url"].startswith("http"), f"Bad URL: {r['url']!r}"

    def test_snippet_field_present(self, google_ai_news):
        for r in google_ai_news["results"]:
            assert "snippet" in r, f"Missing snippet key in: {r}"

    def test_at_least_one_snippet_non_empty(self, google_ai_news):
        snippets = [r["snippet"] for r in google_ai_news["results"] if r["snippet"]]
        assert snippets, "All snippets are empty"

    def test_no_google_redirect_urls(self, google_ai_news):
        """Results must not contain raw /url?q= Google redirect hrefs."""
        for r in google_ai_news["results"]:
            assert "/url?q=" not in r["url"], f"Unresolved redirect URL: {r['url']!r}"

    def test_no_relative_urls(self, google_ai_news):
        for r in google_ai_news["results"]:
            assert r["url"].startswith("http"), f"Relative URL leaked: {r['url']!r}"

    # --- content relevance ---

    def test_results_are_ai_related(self, google_ai_news):
        all_text = " ".join(
            r["title"] + " " + r["snippet"] for r in google_ai_news["results"]
        ).lower()
        ai_terms = ["ai", "artificial intelligence", "llm", "gpt", "openai",
                    "model", "machine learning", "deep learning", "neural"]
        assert any(t in all_text for t in ai_terms), (
            f"No AI-related terms in result text:\n{all_text[:500]}"
        )

    def test_python_results_are_python_related(self, google_python):
        all_text = " ".join(
            r["title"] + " " + r["snippet"] for r in google_python["results"]
        ).lower()
        assert "python" in all_text, (
            f"'python' not found in results:\n{all_text[:500]}"
        )

    # --- second independent query ---

    def test_different_queries_give_different_results(self, google_ai_news, google_python):
        urls_ai = {r["url"] for r in google_ai_news["results"]}
        urls_py = {r["url"] for r in google_python["results"]}
        # Overlap should be minimal (at most 1 coincidental shared URL)
        overlap = urls_ai & urls_py
        assert len(overlap) <= 1, (
            f"Suspicious overlap between 'ai news' and 'python' results: {overlap}"
        )


# ---------------------------------------------------------------------------
# /search  —  engine=duckduckgo  (sanity via API, not browser)
# ---------------------------------------------------------------------------

class TestDuckDuckGoSearchLive:
    @pytest.fixture(scope="class")
    def ddg_response(self):
        _check_service()
        return _post_search("climate change news", engine="duckduckgo", max_results=5)

    def test_status_200(self, ddg_response):
        assert isinstance(ddg_response, dict)

    def test_engine_used_is_duckduckgo(self, ddg_response):
        assert ddg_response["engine_used"] == "duckduckgo"

    def test_returns_results(self, ddg_response):
        assert len(ddg_response["results"]) >= 1

    def test_all_urls_valid(self, ddg_response):
        for r in ddg_response["results"]:
            assert r["url"].startswith("http"), f"Bad URL: {r['url']!r}"


# ---------------------------------------------------------------------------
# /search  —  engine=auto  (should fall back gracefully)
# ---------------------------------------------------------------------------

class TestAutoEngineLive:
    @pytest.fixture(scope="class")
    def auto_response(self):
        _check_service()
        return _post_search("latest tech news", engine="auto", max_results=5)

    def test_engine_used_is_set(self, auto_response):
        assert auto_response["engine_used"] in ("google", "duckduckgo")

    def test_returns_results(self, auto_response):
        assert len(auto_response["results"]) >= 1


# ---------------------------------------------------------------------------
# /search  —  error / validation cases
# ---------------------------------------------------------------------------

class TestSearchValidationLive:
    def test_missing_query_returns_422(self):
        _check_service()
        with httpx.Client(timeout=10) as c:
            r = c.post(f"{BASE_URL}/search", json={"engine": "google"})
        assert r.status_code == 422

    def test_invalid_engine_returns_422(self):
        _check_service()
        with httpx.Client(timeout=10) as c:
            r = c.post(f"{BASE_URL}/search", json={"query": "test", "engine": "bing"})
        assert r.status_code == 422

    def test_empty_query_handled(self):
        """Empty string query should return 200 (may return 0 results) without crashing."""
        _check_service()
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post(f"{BASE_URL}/search", json={"query": "", "engine": "google"})
        assert r.status_code in (200, 500)  # server decides; must not hang

    def test_max_results_zero(self):
        _check_service()
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post(f"{BASE_URL}/search", json={
                "query": "test", "engine": "google", "max_results": 0
            })
        # 0 results is a valid response
        assert r.status_code == 200
        assert r.json()["results"] == []


# ---------------------------------------------------------------------------
# End-to-end: search today's AI news via Google, then fetch each article
# ---------------------------------------------------------------------------

from datetime import date

TODAY = date.today().strftime("%B %d, %Y")   # e.g. "April 04, 2026"
AI_NEWS_QUERY = f"AI news {TODAY}"
FETCH_TIMEOUT = 90   # single-article fetch can be slow (browser rendering)
MAX_ARTICLES = 3     # fetch this many results from the search


@pytest.fixture(scope="module")
def ai_news_search():
    """Google search for today's AI news — module-scoped so it runs once."""
    _check_service()
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.post(f"{BASE_URL}/search", json={
            "query": AI_NEWS_QUERY,
            "engine": "google",
            "max_results": MAX_ARTICLES + 2,   # small buffer in case some fetches fail
        })
    r.raise_for_status()
    data = r.json()
    assert data["results"], f"Google returned no results for: {AI_NEWS_QUERY!r}"
    return data


@pytest.fixture(scope="module")
def ai_news_fetched(ai_news_search):
    """Fetch the top MAX_ARTICLES articles found in the search.
    Returns list of (search_result, fetch_response | None) tuples."""
    results = []
    for sr in ai_news_search["results"][:MAX_ARTICLES]:
        with httpx.Client(timeout=FETCH_TIMEOUT) as c:
            r = c.post(f"{BASE_URL}/fetch", json={
                "url": sr["url"],
                "max_tokens": 4000,
                "no_cache": True,
            })
        fetch_data = r.json() if r.status_code == 200 else None
        results.append((sr, fetch_data))
    return results


class TestAiNewsTodayE2E:
    """End-to-end: Google search → fetch article content for today's AI news."""

    # --- search phase ---

    def test_search_uses_google(self, ai_news_search):
        assert ai_news_search["engine_used"] == "google"

    def test_search_returns_enough_results(self, ai_news_search):
        assert len(ai_news_search["results"]) >= 1, (
            f"Expected results for query: {AI_NEWS_QUERY!r}"
        )

    def test_search_urls_are_real(self, ai_news_search):
        for r in ai_news_search["results"]:
            assert r["url"].startswith("http"), f"Bad URL: {r['url']!r}"

    # --- fetch phase ---

    def test_all_articles_fetched_without_crash(self, ai_news_fetched):
        failed = [(sr["url"], ) for sr, fd in ai_news_fetched if fd is None]
        assert not failed, f"Fetch failed for: {failed}"

    def test_articles_have_content(self, ai_news_fetched):
        for sr, fd in ai_news_fetched:
            assert fd is not None
            assert len(fd["markdown"]) > 100, (
                f"Article too short ({len(fd['markdown'])} chars) for {sr['url']!r}"
            )

    def test_articles_have_title(self, ai_news_fetched):
        for sr, fd in ai_news_fetched:
            assert fd is not None
            assert fd["title"], f"Empty title fetching {sr['url']!r}"

    def test_fetch_url_echoed_back(self, ai_news_fetched):
        for sr, fd in ai_news_fetched:
            assert fd is not None
            assert fd["url"].startswith("http")

    def test_method_used_is_valid(self, ai_news_fetched):
        valid = {"plugin", "httpx", "httpx+browser", "zendriver"}
        for sr, fd in ai_news_fetched:
            assert fd is not None
            assert fd["method_used"] in valid, (
                f"Unexpected method_used={fd['method_used']!r} for {sr['url']!r}"
            )

    def test_articles_mention_ai_topics(self, ai_news_fetched):
        """At least one fetched article should contain AI-related content."""
        ai_terms = ["ai", "artificial intelligence", "llm", "gpt", "openai",
                    "model", "machine learning", "deep learning", "neural",
                    "anthropic", "gemini", "copilot", "chatgpt"]
        hits = []
        for sr, fd in ai_news_fetched:
            if fd and any(t in fd["markdown"].lower() for t in ai_terms):
                hits.append(sr["url"])
        assert hits, (
            "No AI-related content found in any fetched article.\n"
            + "\n".join(
                f"  {sr['url']}: {(fd['markdown'][:200] if fd else 'FAILED')!r}"
                for sr, fd in ai_news_fetched
            )
        )

    def test_search_title_relates_to_article_content(self, ai_news_fetched):
        """The first meaningful word of the search title should appear in the article."""
        mismatches = []
        for sr, fd in ai_news_fetched:
            if not fd:
                continue
            # Take the first 3 meaningful words from the search snippet/title
            words = [
                w.lower().strip(".,\"'()") for w in (sr["title"] + " " + sr["snippet"]).split()
                if len(w) > 4
            ][:5]
            content_lower = fd["markdown"].lower()
            if not any(w in content_lower for w in words):
                mismatches.append({
                    "url": sr["url"],
                    "words_checked": words,
                    "article_start": fd["markdown"][:200],
                })
        # Allow at most 1 mismatch (paywalls / redirects can change content)
        assert len(mismatches) <= 1, (
            f"Too many articles where content didn't match search title:\n"
            + "\n".join(str(m) for m in mismatches)
        )

    def test_print_summary(self, ai_news_search, ai_news_fetched, capsys):
        """Print a readable summary of what was searched and fetched."""
        print(f"\n=== AI News E2E: {AI_NEWS_QUERY} ===")
        print(f"Search engine: {ai_news_search['engine_used']}  |  "
              f"Results: {len(ai_news_search['results'])}\n")
        for i, (sr, fd) in enumerate(ai_news_fetched, 1):
            status = f"{len(fd['markdown'])} chars via {fd['method_used']}" if fd else "FAILED"
            print(f"{i}. [{status}]")
            print(f"   Title : {sr['title']}")
            print(f"   URL   : {sr['url']}")
            if fd:
                first_line = fd["markdown"].splitlines()[0][:120] if fd["markdown"] else ""
                print(f"   Lead  : {first_line}")
            print()

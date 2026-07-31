"""Behavioral tests for SiteConfig resolution and request model validation."""

import pytest
from pydantic import ValidationError

from agentic_fetch.config import SiteConfig, detect_content_type, normalize_url
from agentic_fetch.models import BatchFetchRequest, FetchRequest, SearchRequest


@pytest.fixture
def site_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
strip_selectors: [".global-ad"]
strip_lines: ["^Subscribe"]
domains:
  example.com:
    strip_selectors: [".site-ad"]
    strip_lines: ["^Cookie"]
    proxy_url: "https://proxy.test/"
    init_script: "window.a=1"
init_scripts:
  scripted.test: "window.b=2"
"""
    )
    return SiteConfig(str(cfg))


class TestSiteConfig:
    def test_missing_file_yields_empty_config(self, tmp_path):
        sc = SiteConfig(str(tmp_path / "nope.yaml"))
        assert sc.selectors_for("https://example.com/") == []
        assert sc.proxy_url_for("https://example.com/") is None
        assert sc.init_script_for("https://example.com/") is None

    def test_domain_selectors_are_appended_to_globals(self, site_config):
        assert site_config.selectors_for("https://example.com/page") == [
            ".global-ad",
            ".site-ad",
        ]

    def test_unknown_domain_gets_only_globals(self, site_config):
        assert site_config.selectors_for("https://other.test/") == [".global-ad"]
        assert site_config.strip_lines_for("https://other.test/") == ["^Subscribe"]

    def test_subdomains_inherit_parent_domain_config(self, site_config):
        assert site_config.selectors_for("https://news.example.com/x") == [
            ".global-ad",
            ".site-ad",
        ]

    def test_strip_lines_merge_globals_and_domain(self, site_config):
        assert site_config.strip_lines_for("https://example.com/") == [
            "^Subscribe",
            "^Cookie",
        ]

    def test_proxy_url_prepends_proxy_without_double_slash(self, site_config):
        assert (
            site_config.proxy_url_for("https://example.com/article")
            == "https://proxy.test/https://example.com/article"
        )

    def test_domain_init_script_wins_over_global_map(self, site_config):
        assert site_config.init_script_for("https://example.com/") == "window.a=1"

    def test_init_scripts_map_matches_host_ignoring_www(self, site_config):
        assert site_config.init_script_for("https://www.scripted.test/") == "window.b=2"

    def test_no_init_script_returns_none(self, site_config):
        assert site_config.init_script_for("https://plain.test/") is None


class TestNormalizeUrl:
    def test_tracking_params_and_fragment_are_removed(self):
        url = "https://a.test/p?utm_source=x&keep=1&fbclid=y#frag"
        assert normalize_url(url) == "https://a.test/p?keep=1"

    def test_plain_url_is_unchanged(self):
        assert normalize_url("https://a.test/p?q=1") == "https://a.test/p?q=1"


class TestDetectContentType:
    def test_html_header_wins(self):
        assert detect_content_type("https://a.test/x.md", "text/html") == "html"

    def test_markdown_header(self):
        assert detect_content_type("https://a.test/x", "text/markdown") == "markdown"

    def test_markdown_extension_without_header(self):
        assert detect_content_type("https://a.test/README.md", "") == "markdown"
        assert detect_content_type("https://a.test/doc.markdown", "") == "markdown"

    def test_plain_extensions(self):
        assert detect_content_type("https://a.test/notes.txt", "") == "plain"
        assert detect_content_type("https://a.test/spec.rst", "") == "plain"

    def test_default_is_html(self):
        assert detect_content_type("https://a.test/page", "") == "html"


class TestFetchUrlValidation:
    def test_surrounding_whitespace_is_stripped(self):
        assert FetchRequest(url="  https://a.test/  ").url == "https://a.test/"

    def test_non_http_scheme_is_rejected_naming_the_scheme(self):
        with pytest.raises(ValidationError, match="ftp"):
            FetchRequest(url="ftp://a.test/")

    def test_missing_scheme_is_rejected(self):
        with pytest.raises(ValidationError, match="no scheme"):
            FetchRequest(url="a.test/page")

    def test_missing_host_is_rejected(self):
        with pytest.raises(ValidationError, match="no host"):
            FetchRequest(url="https:///path-only")

    def test_batch_urls_are_each_validated(self):
        with pytest.raises(ValidationError):
            BatchFetchRequest(urls=["https://ok.test/", "ftp://bad.test/"])


class TestSearchDateValidation:
    def test_iso_dates_accepted(self):
        req = SearchRequest(query="q", date_from="2026-01-31", date_to="2026-02-01")
        assert req.date_from == "2026-01-31"

    def test_non_iso_date_rejected_with_expected_format(self):
        with pytest.raises(ValidationError, match="YYYY-MM-DD"):
            SearchRequest(query="q", date_from="31/01/2026")

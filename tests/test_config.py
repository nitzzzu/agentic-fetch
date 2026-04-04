"""Tests for config utilities."""
import pytest
import tempfile
import os
import yaml
from agentic_fetch.config import SiteConfig, normalize_url, detect_content_type

SAMPLE_CONFIG = {
    "strip_selectors": [".global-nav", ".footer"],
    "strip_lines": [r"^\s*Advertisement"],
    "domains": {
        "example.com": {
            "strip_selectors": [".sidebar"],
            "strip_lines": [r"Subscribe now"],
            "proxy_url": "https://proxy.example.com",
        },
        "other.com": {
            "init_script": "window.__bypass = true;",
        },
    },
}


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(SAMPLE_CONFIG))
    return str(path)


@pytest.fixture
def site_config(config_file):
    return SiteConfig(config_file)


class TestSiteConfig:
    def test_global_selectors(self, site_config):
        sels = site_config.selectors_for("https://unknown.com/page")
        assert ".global-nav" in sels
        assert ".footer" in sels

    def test_domain_selectors_merged(self, site_config):
        sels = site_config.selectors_for("https://example.com/page")
        assert ".global-nav" in sels
        assert ".sidebar" in sels

    def test_www_prefix_ignored(self, site_config):
        sels = site_config.selectors_for("https://www.example.com/page")
        assert ".sidebar" in sels

    def test_strip_lines_merged(self, site_config):
        lines = site_config.strip_lines_for("https://example.com/page")
        assert r"^\s*Advertisement" in lines
        assert r"Subscribe now" in lines

    def test_global_strip_lines_only(self, site_config):
        lines = site_config.strip_lines_for("https://other.com/page")
        assert r"^\s*Advertisement" in lines
        assert r"Subscribe now" not in lines

    def test_proxy_url_for_known_domain(self, site_config):
        proxy = site_config.proxy_url_for("https://example.com/article")
        assert proxy is not None
        assert "https://example.com/article" in proxy

    def test_proxy_url_for_unknown_domain(self, site_config):
        assert site_config.proxy_url_for("https://other.com/page") is None

    def test_init_script_for_domain(self, site_config):
        script = site_config.init_script_for("https://other.com/page")
        assert script == "window.__bypass = true;"

    def test_init_script_missing(self, site_config):
        assert site_config.init_script_for("https://example.com/page") is None

    def test_missing_config_file_is_empty(self, tmp_path):
        config = SiteConfig(str(tmp_path / "nonexistent.yaml"))
        assert config.selectors_for("https://example.com") == []
        assert config.strip_lines_for("https://example.com") == []
        assert config.proxy_url_for("https://example.com") is None


class TestNormalizeUrl:
    def test_tracking_params_removed(self):
        url = "https://example.com/page?utm_source=x&utm_medium=y&id=42"
        norm = normalize_url(url)
        assert "utm_source" not in norm
        assert "utm_medium" not in norm
        assert "id=42" in norm

    def test_fragment_removed(self):
        url = "https://example.com/page#section"
        norm = normalize_url(url)
        assert "#section" not in norm
        assert "example.com/page" in norm

    def test_plain_url_unchanged(self):
        url = "https://example.com/path?q=search"
        assert normalize_url(url) == url

    def test_fbclid_removed(self):
        url = "https://example.com/?fbclid=abc123&page=2"
        norm = normalize_url(url)
        assert "fbclid" not in norm
        assert "page=2" in norm


class TestDetectContentType:
    def test_html_content_type_header(self):
        assert detect_content_type("https://example.com", "text/html; charset=utf-8") == "html"

    def test_xhtml_content_type(self):
        assert detect_content_type("https://example.com", "application/xhtml+xml") == "html"

    def test_markdown_content_type_header(self):
        assert detect_content_type("https://example.com", "text/markdown") == "markdown"

    def test_md_extension(self):
        assert detect_content_type("https://example.com/README.md", "") == "markdown"

    def test_rst_extension(self):
        assert detect_content_type("https://example.com/doc.rst", "") == "markdown"

    def test_txt_extension(self):
        assert detect_content_type("https://example.com/notes.txt", "") == "markdown"

    def test_html_extension_fallback(self):
        assert detect_content_type("https://example.com/page.html", "") == "html"

    def test_unknown_defaults_to_html(self):
        assert detect_content_type("https://example.com/", "") == "html"

import tempfile
from pydantic_settings import BaseSettings
from pathlib import Path
import yaml


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    headless: bool = True
    user_data_dir: str = str(Path(tempfile.gettempdir()) / "agentic-fetch-profile")
    cache_dir: str = str(Path(tempfile.gettempdir()) / "agentic-fetch-cache")
    cache_ttl: int = 300
    max_browser_tabs: int = 3
    browser_timeout: float = 30.0
    httpx_timeout: float = 10.0
    fake_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/132.0.0.0 Safari/537.36"
    )
    config_file: str = "config.yaml"
    container: bool = False

    model_config = {"env_file": ".env", "env_prefix": "AF_"}


class SiteConfig:
    """
    Loads config.yaml. Resolves per-request selectors, strip_lines,
    proxy_url, and init_scripts by hostname.
    """

    def __init__(self, path: str = "config.yaml"):
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except FileNotFoundError:
            data = {}
        self._global_selectors: list[str] = data.get("strip_selectors", [])
        self._global_strip_lines: list[str] = data.get("strip_lines", [])
        self._domains: dict[str, dict] = data.get("domains", {})
        self._init_scripts: dict[str, str] = data.get("init_scripts", {})

    def _domain_cfg(self, url: str) -> dict:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower().lstrip("www.")
        return self._domains.get(host, self._domains.get(f"www.{host}", {}))

    def selectors_for(self, url: str) -> list[str]:
        return self._global_selectors + self._domain_cfg(url).get("strip_selectors", [])

    def strip_lines_for(self, url: str) -> list[str]:
        return self._global_strip_lines + self._domain_cfg(url).get("strip_lines", [])

    def proxy_url_for(self, url: str) -> str | None:
        proxy = self._domain_cfg(url).get("proxy_url")
        if proxy:
            return proxy.rstrip("/") + "/" + url
        return None

    def init_script_for(self, url: str) -> str | None:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower().lstrip("www.")
        return (self._domain_cfg(url).get("init_script")
                or self._init_scripts.get(host))


def normalize_url(url: str) -> str:
    from urllib.parse import urlparse, urlencode, parse_qsl
    u = urlparse(url)
    TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                "fbclid", "gclid", "ref", "source"}
    clean_query = urlencode([(k, v) for k, v in parse_qsl(u.query)
                              if k.lower() not in TRACKING])
    return u._replace(fragment="", query=clean_query).geturl()


def detect_content_type(url: str, content_type_header: str) -> str:
    from pathlib import PurePosixPath
    from urllib.parse import urlparse
    ct = content_type_header.lower()
    if "text/html" in ct or "application/xhtml" in ct:
        return "html"
    if "text/markdown" in ct or "text/x-markdown" in ct:
        return "markdown"
    ext = PurePosixPath(urlparse(url).path).suffix.lower()
    if ext in (".md", ".markdown", ".txt", ".rst"):
        return "markdown"
    return "html"


settings = Settings()

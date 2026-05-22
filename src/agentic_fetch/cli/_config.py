"""Shared helpers for the agentic-search and agentic-fetch CLIs."""
import json
import os
from pathlib import Path

CONFIG_FILE = Path.home() / ".agentic-fetch"
DEFAULT_URL = "http://localhost:8000"


def load_api_url() -> str:
    """Return the saved API base URL, env override, or the default."""
    env_url = os.environ.get("AGENTIC_FETCH_URL")
    if env_url:
        return env_url.rstrip("/")
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            return data.get("api_url", DEFAULT_URL).rstrip("/")
        except Exception:
            pass
    return DEFAULT_URL


def save_api_url(url: str) -> None:
    """Persist the API base URL to ~/.agentic-fetch, preserving other keys."""
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    data["api_url"] = url.rstrip("/")
    CONFIG_FILE.write_text(json.dumps(data, indent=2))

import importlib
import pkgutil
from pathlib import Path
from .base import FetchPlugin

_registry: list[type[FetchPlugin]] = []


def _discover():
    pkg_dir = Path(__file__).parent
    for _, name, _ in pkgutil.iter_modules([str(pkg_dir)]):
        if name in ("__init__", "base"):
            continue
        mod = importlib.import_module(f"agentic_fetch.plugins.{name}")
        for attr in vars(mod).values():
            if isinstance(attr, type) and issubclass(attr, FetchPlugin) and attr is not FetchPlugin:
                _registry.append(attr)


def get_plugin(url: str) -> type[FetchPlugin] | None:
    for plugin_cls in _registry:
        if plugin_cls.matches(url):
            return plugin_cls
    return None


_discover()

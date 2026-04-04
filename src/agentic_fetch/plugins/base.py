from abc import ABC, abstractmethod
import fnmatch
from urllib.parse import urlparse


class FetchPlugin(ABC):
    name: str = ""
    domains: list[str] = []

    @abstractmethod
    async def fetch(self, url: str, req) -> "FetchResponse | None":
        """Return FetchResponse or None to fall through to default path."""
        ...

    @classmethod
    def matches(cls, url: str) -> bool:
        host = urlparse(url).netloc.lstrip("www.")
        for pattern in cls.domains:
            p = pattern.lstrip("www.").lstrip("*.")
            if fnmatch.fnmatch(host, p) or host == p or host.endswith("." + p):
                return True
        return False

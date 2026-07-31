from abc import ABC, abstractmethod
import fnmatch
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from ..models import FetchRequest, FetchResponse


class FetchPlugin(ABC):
    name: str = ""
    domains: list[str] = []

    @abstractmethod
    async def fetch(self, url: str, req: "FetchRequest") -> "FetchResponse | None":
        """Return FetchResponse or None to fall through to default path."""
        ...

    @classmethod
    def matches(cls, url: str) -> bool:
        host = urlparse(url).netloc.removeprefix("www.")
        for pattern in cls.domains:
            p = pattern.removeprefix("www.").removeprefix("*.")
            if fnmatch.fnmatch(host, p) or host == p or host.endswith("." + p):
                return True
        return False

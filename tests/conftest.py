import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_browser_pool():
    """Patch browser_pool so tests never start a real Chrome process."""
    with patch("agentic_fetch.main.browser_pool") as mock:
        mock.start = AsyncMock()
        mock.stop = AsyncMock()
        mock.is_running = True
        yield mock

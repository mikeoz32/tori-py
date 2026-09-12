import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # The sync Playwright fixture owns a session-scoped event loop, so run its
    # tests after asyncio-based tests have finished using their loops.
    items.sort(key=lambda item: item.get_closest_marker("browser") is not None)

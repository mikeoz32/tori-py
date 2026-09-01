"""Platform-compatible event loops for workplace integration tests."""

from __future__ import annotations

import asyncio
import selectors
import sys
from collections.abc import Callable, Mapping
from typing import Any


def pytest_asyncio_loop_factories(
    config: Any, item: Any
) -> Mapping[str, Callable[[], asyncio.AbstractEventLoop]]:
    del config, item
    if sys.platform == "win32":
        return {
            "selector": lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
        }
    return {"default": asyncio.new_event_loop}

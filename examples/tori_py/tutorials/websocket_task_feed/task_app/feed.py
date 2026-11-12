"""In-process wake-ups for connected task feed clients."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class TaskFeed:
    """Wake every subscribed connection in this process when tasks change."""

    def __init__(self) -> None:
        self._wakeups: set[asyncio.Event] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._wakeups)

    def notify(self) -> None:
        for wakeup in self._wakeups:
            wakeup.set()

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Event]:
        wakeup = asyncio.Event()
        self._wakeups.add(wakeup)
        try:
            yield wakeup
        finally:
            self._wakeups.discard(wakeup)

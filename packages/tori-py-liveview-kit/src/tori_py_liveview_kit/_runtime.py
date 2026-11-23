"""Run a model generator for a page and batch what it yields.

The model task never changes what the page renders. It appends events to the
buffer of its run and asks the page for a flush; the page takes the batch in
``handle_info`` and renders once. The page owns three callbacks:

- ``handle_info(FLUSH, token)`` calls ``take(token)``;
- ``handle_async(REPLY, result)`` calls ``complete(result)``;
- ``disconnect()`` calls ``abandon()``.
"""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from functools import partial

from tori_py_liveview import AsyncResult, LiveView

from tori_py_liveview_kit.events import EVENT_TYPES, ChatEvent, Error, TextDelta

FLUSH = "tori-kit:flush"
REPLY = "tori-kit:reply"
# How long to wait before asking again when the page's info queue is full.
_MIN_RETRY_SECONDS = 0.01

type Source = Callable[[], AsyncIterator[str | ChatEvent]]


class _Run:
    """The buffer of one generator; events arriving after it closes are discarded."""

    __slots__ = ("closed", "flushed_at", "pending", "queued", "timer")

    def __init__(self) -> None:
        self.pending: list[ChatEvent] = []
        # A flush for this run waits in the page's info queue.
        self.queued = False
        self.timer: asyncio.TimerHandle | None = None
        self.flushed_at = -math.inf
        self.closed = False


@dataclass(frozen=True, slots=True)
class Completion:
    """How a run ended, with the events no flush had taken yet."""

    events: list[ChatEvent]
    error: BaseException | None = None
    cancelled: bool = False


class ReplyRuntime:
    """Own at most one running generator for ``page``."""

    def __init__(self, page: LiveView, *, flush_interval: float = 0.05) -> None:
        if (
            isinstance(flush_interval, bool)
            or not isinstance(flush_interval, int | float)
            or not math.isfinite(flush_interval)
            or flush_interval < 0
        ):
            raise ValueError("flush interval must be a finite number of seconds")
        self._page = page
        self._interval = float(flush_interval)
        self._run: _Run | None = None

    @property
    def active(self) -> bool:
        return self._run is not None

    def start(self, source: Source) -> None:
        """Start reading ``source()`` in a task the page's connection owns."""
        if self._run is not None:
            raise RuntimeError("a reply is already being written")
        run = _Run()
        self._run = run
        self._page.start_async(REPLY, partial(self._consume, run, source))

    def take(self, token: object) -> list[ChatEvent] | None:
        """Take the batch a flush announced; ``None`` for a run that ended."""
        run = self._run
        if run is None or token is not run:
            return None
        run.queued = False
        run.flushed_at = asyncio.get_running_loop().time()
        return self._drain(run)

    def stop(self) -> list[ChatEvent]:
        """Cancel the run and return the events no flush had taken yet."""
        run = self._run
        if run is None:
            return []
        self._close(run)
        self._page.cancel_async(REPLY)
        return self._drain(run)

    def abandon(self) -> list[ChatEvent]:
        """End the run of a page whose connection has already cancelled it."""
        run = self._run
        if run is None:
            return []
        self._close(run)
        return self._drain(run)

    def complete(self, result: AsyncResult[object]) -> Completion | None:
        """Settle the finished task; ``None`` when the run was stopped first.

        LiveView drops the result of a task that a later ``start`` replaced,
        so a result that arrives while a run is open belongs to that run.
        """
        run = self._run
        if run is None:
            return None
        self._close(run)
        failed = result.failed
        cancelled = isinstance(failed, asyncio.CancelledError)
        return Completion(self._drain(run), None if cancelled else failed, cancelled)

    async def _consume(self, run: _Run, source: Source) -> None:
        events = source()
        if not isinstance(events, AsyncIterator):
            if inspect.iscoroutine(events):
                events.close()
            raise TypeError(
                "respond must return an async iterator, such as an async generator"
            )
        try:
            async for item in events:
                event = TextDelta(item) if isinstance(item, str) else item
                if not isinstance(event, EVENT_TYPES):
                    raise TypeError(
                        "respond must yield ChatEvent values or strings, not "
                        + type(item).__name__
                    )
                if run.closed:
                    return
                run.pending.append(event)
                self._request(run)
                if isinstance(event, Error):
                    return
        finally:
            # Release what the generator holds, such as a provider stream.
            close = getattr(events, "aclose", None)
            if close is not None:
                await close()

    def _request(self, run: _Run) -> None:
        if run.closed or run.queued or run.timer is not None:
            return
        loop = asyncio.get_running_loop()
        delay = run.flushed_at + self._interval - loop.time()
        if delay > 0:
            run.timer = loop.call_later(delay, self._fire, run)
        elif self._page.send_info(FLUSH, run):
            run.queued = True
        else:
            # The info queue is full. Completion drains the buffer anyway.
            run.timer = loop.call_later(
                max(self._interval, _MIN_RETRY_SECONDS), self._fire, run
            )

    def _fire(self, run: _Run) -> None:
        run.timer = None
        if run.pending:
            self._request(run)

    def _close(self, run: _Run) -> None:
        run.closed = True
        if run.timer is not None:
            run.timer.cancel()
            run.timer = None
        self._run = None

    @staticmethod
    def _drain(run: _Run) -> list[ChatEvent]:
        events, run.pending = run.pending, []
        return events


__all__ = ["FLUSH", "REPLY", "Completion", "ReplyRuntime", "Source"]

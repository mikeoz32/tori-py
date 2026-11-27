from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from typing import ClassVar

import pytest
from tori_py_liveview import (
    AsyncResult,
    LiveView,
    MountContext,
    UnknownEventError,
    live_view,
)
from tori_py_liveview_kit import ChatEvent, Error, TextDelta
from tori_py_liveview_kit._runtime import FLUSH, REPLY, ReplyRuntime


@live_view("/runtime")
class RuntimeLive(LiveView):
    """A page that records what the runtime hands it."""

    script: ClassVar[Callable[[RuntimeLive], AsyncIterator[str | ChatEvent]]]
    interval: ClassVar[float] = 0.0
    current: ClassVar[RuntimeLive | None] = None

    def __init__(self) -> None:
        self.runtime = ReplyRuntime(self, flush_interval=type(self).interval)
        self.batches: list[list[ChatEvent]] = []
        self.flushed_at: list[float] = []
        self.outcome = "idle"
        self.failure: BaseException | None = None
        self.noise = 0
        self.abandoned: list[ChatEvent] | None = None

    async def mount(self, context: MountContext) -> None:
        if context.connected:
            type(self).current = self

    @property
    def text(self) -> str:
        return "".join(
            event.text
            for batch in self.batches
            for event in batch
            if isinstance(event, TextDelta)
        )

    async def handle_event(self, event: str, value: object) -> None:
        del value
        match event:
            case "start":
                self.outcome = "running"
                self.runtime.start(lambda: type(self).script(self))
            case "stop":
                self._record(self.runtime.stop())
                self.outcome = "stopped"
            case "ping":
                pass
            case _:
                raise UnknownEventError(event)

    async def handle_info(self, name: str, value: object) -> None:
        if name == "noise":
            self.noise += 1
            return
        if name != FLUSH:
            await super().handle_info(name, value)
            return
        events = self.runtime.take(value)
        if events is not None:
            self.flushed_at.append(asyncio.get_running_loop().time())
            self._record(events)

    async def handle_async(self, name: str, result: AsyncResult[object]) -> None:
        if name != REPLY:
            await super().handle_async(name, result)
            return
        completion = self.runtime.complete(result)
        if completion is None:
            return
        self._record(completion.events)
        self.failure = completion.error
        if completion.cancelled:
            self.outcome = "cancelled"
        else:
            self.outcome = "done" if completion.error is None else "failed"

    async def disconnect(self) -> None:
        self.abandoned = self.runtime.abandon()

    def _record(self, events: list[ChatEvent]) -> None:
        if events:
            self.batches.append(events)

    def render(self):
        return t"<p>{self.text}</p><output>{self.outcome}</output><i>{self.noise}</i>"


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    RuntimeLive.interval = 0.0
    RuntimeLive.current = None
    yield
    RuntimeLive.current = None


def _page() -> RuntimeLive:
    page = RuntimeLive.current
    assert page is not None
    return page


def _deltas(*texts: str) -> list[ChatEvent]:
    return [TextDelta(text) for text in texts]


@pytest.mark.asyncio
async def test_events_that_arrive_together_render_once(open_page) -> None:
    gate = asyncio.Event()

    async def script(page: RuntimeLive):
        for token in "abcde":
            yield token
        await gate.wait()

    RuntimeLive.script = script
    channel = await open_page(RuntimeLive)
    page = _page()

    await channel.event("start")
    await channel.until(lambda: page.text == "abcde")

    assert page.batches == [_deltas("a", "b", "c", "d", "e")]
    assert len(channel.pushes) == 1
    assert page.runtime.active

    gate.set()
    await channel.until(lambda: page.outcome == "done")
    assert not page.runtime.active
    assert len(channel.pushes) == 2


@pytest.mark.asyncio
async def test_flushes_keep_their_distance(open_page) -> None:
    RuntimeLive.interval = 0.2
    second, third, hold = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def script(page: RuntimeLive):
        yield "a"
        await second.wait()
        yield "b"
        await third.wait()
        yield "c"
        await hold.wait()

    RuntimeLive.script = script
    channel = await open_page(RuntimeLive)
    page = _page()

    await channel.event("start")
    # Nothing was flushed before, so the first event does not wait.
    await channel.until(lambda: page.text == "a")
    second.set()
    await asyncio.sleep(0.03)
    assert page.text == "a"
    third.set()
    await channel.until(lambda: page.text == "abc")

    assert page.batches == [_deltas("a"), _deltas("b", "c")]
    first_flush, second_flush = page.flushed_at
    assert second_flush - first_flush >= 0.2 - 0.001


@pytest.mark.asyncio
async def test_a_full_info_queue_loses_nothing_when_the_generator_ends(
    open_page,
) -> None:
    async def script(page: RuntimeLive):
        while page.send_info("noise"):
            pass
        yield "kept"

    RuntimeLive.script = script
    channel = await open_page(RuntimeLive)
    page = _page()

    await channel.event("start")
    await channel.until(lambda: page.outcome == "done")

    assert page.noise == 32
    assert page.batches == [_deltas("kept")]


@pytest.mark.asyncio
async def test_a_refused_flush_is_retried_while_the_generator_stays_open(
    open_page,
) -> None:
    hold = asyncio.Event()

    async def script(page: RuntimeLive):
        while page.send_info("noise"):
            pass
        yield "kept"
        await hold.wait()

    RuntimeLive.script = script
    channel = await open_page(RuntimeLive)
    page = _page()

    await channel.event("start")
    await channel.until(lambda: page.text == "kept")

    assert page.outcome == "running"
    assert page.noise == 32


@pytest.mark.asyncio
async def test_completion_delivers_the_tail_without_waiting_for_the_interval(
    open_page,
) -> None:
    RuntimeLive.interval = 30.0
    gate = asyncio.Event()

    async def script(page: RuntimeLive):
        yield "a"
        await gate.wait()
        yield "b"

    RuntimeLive.script = script
    channel = await open_page(RuntimeLive)
    page = _page()

    await channel.event("start")
    await channel.until(lambda: page.text == "a")
    gate.set()
    await channel.until(lambda: page.outcome == "done")

    assert page.batches == [_deltas("a"), _deltas("b")]


@pytest.mark.asyncio
async def test_stop_returns_what_arrived_and_closes_the_generator(open_page) -> None:
    RuntimeLive.interval = 30.0
    gate, hold = asyncio.Event(), asyncio.Event()
    marks: list[str] = []

    async def script(page: RuntimeLive):
        try:
            yield "a"
            await gate.wait()
            yield "b"
            marks.append("b was read")
            await hold.wait()
        finally:
            marks.append("closed")

    RuntimeLive.script = script
    channel = await open_page(RuntimeLive)
    page = _page()

    await channel.event("start")
    await channel.until(lambda: page.text == "a")
    gate.set()
    await channel.until(lambda: marks == ["b was read"])
    assert page.text == "a"

    await channel.event("stop")
    await channel.until(lambda: marks == ["b was read", "closed"])

    assert page.batches == [_deltas("a"), _deltas("b")]
    assert not page.runtime.active
    # The cancelled task's result arrives later and changes nothing.
    await channel.event("ping")
    await channel.event("ping")
    assert page.outcome == "stopped"


@pytest.mark.asyncio
async def test_a_raised_exception_is_reported_and_the_connection_stays_open(
    open_page,
) -> None:
    async def script(page: RuntimeLive):
        yield "a"
        raise RuntimeError("boom")

    RuntimeLive.script = script
    channel = await open_page(RuntimeLive)
    page = _page()

    await channel.event("start")
    await channel.until(lambda: page.outcome == "failed")

    assert isinstance(page.failure, RuntimeError)
    assert page.text == "a"
    assert not page.runtime.active
    await channel.event("ping")
    assert channel.close_code is None


@pytest.mark.asyncio
async def test_an_error_event_ends_the_run_and_closes_the_generator(open_page) -> None:
    marks: list[str] = []

    async def script(page: RuntimeLive):
        try:
            yield "a"
            yield Error("The model is overloaded.")
            marks.append("read past the error")
            yield "never"
        finally:
            marks.append("closed")

    RuntimeLive.script = script
    channel = await open_page(RuntimeLive)
    page = _page()

    await channel.event("start")
    await channel.until(lambda: page.outcome == "done")

    assert marks == ["closed"]
    assert page.batches == [[TextDelta("a"), Error("The model is overloaded.")]]


@pytest.mark.asyncio
async def test_events_of_a_stopped_run_never_reach_the_next_run(open_page) -> None:
    release, hold = asyncio.Event(), asyncio.Event()
    marks: list[str] = []
    runs = 0

    async def script(page: RuntimeLive):
        nonlocal runs
        runs += 1
        if runs == 2:
            yield "new"
            await hold.wait()
            return
        try:
            yield "old"
            await hold.wait()
        except asyncio.CancelledError:
            # A generator that ignores cancellation for a while.
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    pass
            marks.append("resumed")
            yield "stale"
        finally:
            marks.append("closed")

    RuntimeLive.script = script
    channel = await open_page(RuntimeLive)
    page = _page()

    await channel.event("start")
    await channel.until(lambda: page.text == "old")
    await channel.event("stop")
    await channel.event("start")
    await channel.until(lambda: page.text == "oldnew")

    release.set()
    await channel.until(lambda: marks == ["resumed", "closed"])
    await channel.event("ping")
    await channel.event("ping")

    assert page.text == "oldnew"
    assert page.outcome == "running"
    assert page.runtime.active


@pytest.mark.asyncio
async def test_disconnect_cancels_the_run_and_hands_back_the_tail(open_page) -> None:
    RuntimeLive.interval = 30.0
    gate, hold = asyncio.Event(), asyncio.Event()
    marks: list[str] = []

    async def script(page: RuntimeLive):
        try:
            yield "a"
            await gate.wait()
            yield "b"
            marks.append("b was read")
            await hold.wait()
        finally:
            marks.append("closed")

    RuntimeLive.script = script
    channel = await open_page(RuntimeLive)
    page = _page()

    await channel.event("start")
    await channel.until(lambda: page.text == "a")
    gate.set()
    await channel.until(lambda: marks == ["b was read"])
    await channel.close()

    assert marks == ["b was read", "closed"]
    assert page.abandoned == _deltas("b")
    assert not page.runtime.active


def test_one_run_at_a_time() -> None:
    async def script(page: RuntimeLive):
        yield "a"

    page = RuntimeLive()
    # A page without a connection starts no task, but the run is open.
    page.runtime.start(lambda: script(page))

    with pytest.raises(RuntimeError, match="already being written"):
        page.runtime.start(lambda: script(page))
    assert page.runtime.abandon() == []
    assert not page.runtime.active


def test_calls_without_a_run_are_harmless() -> None:
    runtime = ReplyRuntime(RuntimeLive())

    assert runtime.take(object()) is None
    assert runtime.stop() == []
    assert runtime.abandon() == []
    assert runtime.complete(AsyncResult(ok=True)) is None


@pytest.mark.parametrize("interval", [-0.1, float("inf"), float("nan")])
def test_flush_interval_is_a_finite_non_negative_number(interval: float) -> None:
    with pytest.raises(ValueError, match="finite number of seconds"):
        ReplyRuntime(RuntimeLive(), flush_interval=interval)

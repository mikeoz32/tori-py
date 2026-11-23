from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from typing import Any, ClassVar

import pytest
from tori_py_liveview import MountContext, live_view
from tori_py_liveview_kit import (
    AssistantMessage,
    ChatEvent,
    ChatLiveView,
    Error,
    Message,
    TextPart,
    UserMessage,
)
from tori_py_liveview_kit import chat as chat_module

_RETRY = 'phx-click="chat:retry"'


@live_view("/chat")
class ErrorsLive(ChatLiveView):
    """A chat whose model is the generator a test assigns to ``script``."""

    script: ClassVar[Callable[[Sequence[Message]], Any]]
    describe: ClassVar[Callable[[BaseException], Any] | None] = None
    current: ClassVar[ErrorsLive | None] = None
    calls: ClassVar[list[Sequence[Message]]] = []
    finished: ClassVar[list[AssistantMessage]] = []

    flush_interval = 0.0

    async def mount(self, context: MountContext) -> None:
        await super().mount(context)
        if context.connected:
            ErrorsLive.current = self

    def respond(self, messages: Sequence[Message]) -> AsyncIterator[str | ChatEvent]:
        ErrorsLive.calls.append(messages)
        return ErrorsLive.script(messages)

    def describe_error(self, error: BaseException) -> str:
        describe = ErrorsLive.describe
        return super().describe_error(error) if describe is None else describe(error)

    async def reply_finished(self, message: AssistantMessage) -> None:
        ErrorsLive.finished.append(message)


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    ErrorsLive.current = None
    ErrorsLive.describe = None
    ErrorsLive.calls = []
    ErrorsLive.finished = []
    ErrorsLive.flush_interval = 0.0
    yield
    ErrorsLive.current = None


def _page() -> ErrorsLive:
    page = ErrorsLive.current
    assert page is not None
    return page


_USER = UserMessage("turn-1-user", "go")


@pytest.mark.asyncio
async def test_a_failed_batch_reports_the_terminal_reply_once(
    open_page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = asyncio.Event()

    async def script(messages: Sequence[Message]):
        try:
            yield "partial"
            await asyncio.Event().wait()
        finally:
            closed.set()

    def fail_batch(*args: object, **kwargs: object):
        raise RuntimeError("injected batch failure")

    ErrorsLive.script = script
    channel = await open_page(ErrorsLive)
    monkeypatch.setattr(chat_module, "fold_events", fail_batch)
    await channel.event("chat:send", {"message": "go"})
    page = _page()
    await channel.until(lambda: not page.busy and closed.is_set())

    reply = page.messages[-1]
    assert isinstance(reply, AssistantMessage)
    assert reply.status == "error"
    assert ErrorsLive.finished == [page.messages[-1]]
    assert channel.close_code is None
    await channel.close()
    assert len(ErrorsLive.finished) == 1


@pytest.mark.asyncio
async def test_a_retry_for_an_older_message_does_not_restart_the_latest_reply(
    open_page,
) -> None:
    async def script(messages: Sequence[Message]):
        yield Error("Failed")

    ErrorsLive.script = script
    channel = await open_page(ErrorsLive)
    await channel.event("chat:send", {"message": "go"})
    page = _page()
    await channel.until(lambda: not page.busy)
    original = page.messages

    await channel.event("chat:retry", {"message_id": "an-older-reply"})
    assert page.messages == original
    assert len(ErrorsLive.calls) == 1

    await channel.event("chat:retry", {"message_id": original[-1].id})
    await channel.until(lambda: not page.busy)
    assert len(ErrorsLive.calls) == 2


@pytest.mark.asyncio
async def test_a_raised_exception_becomes_an_error_reply(
    open_page, caplog: pytest.LogCaptureFixture
) -> None:
    async def script(messages: Sequence[Message]):
        yield "Half an answer"
        raise RuntimeError("connection to 10.0.0.7 failed: key sk-secret")

    ErrorsLive.script = script
    channel = await open_page(ErrorsLive)
    page = _page()

    with caplog.at_level(logging.WARNING, logger="tori_py_liveview.page"):
        await channel.event("chat:send", {"message": "go"})
        await channel.until(lambda: not page.busy)

    failed = AssistantMessage(
        "turn-1-assistant",
        (TextPart("Half an answer"),),
        "error",
        error="Something went wrong.",
    )
    assert page.messages == (_USER, failed)
    assert ErrorsLive.finished == [failed]
    ending = channel.sent_text(-1)
    assert "Half an answer" in ending
    assert "tori-ui-alert--danger" in ending
    assert "Something went wrong." in ending
    assert _RETRY in ending
    assert 'aria-label="Send"' in ending
    # The exception is for the log, not for the visitor.
    assert "sk-secret" not in channel.sent_text(0)
    assert "sk-secret" in caplog.text
    assert channel.close_code is None


@pytest.mark.parametrize(
    ("describe", "shown"),
    [
        (lambda error: f"{type(error).__name__}: {error}", "RuntimeError: boom"),
        (lambda error: "  ", "Something went wrong."),
        (lambda error: None, "Something went wrong."),
        (lambda error: 1 / 0, "Something went wrong."),
    ],
)
@pytest.mark.asyncio
async def test_describe_error_chooses_the_text_and_cannot_break_the_page(
    open_page, describe: Callable[[BaseException], Any], shown: str
) -> None:
    async def script(messages: Sequence[Message]):
        raise RuntimeError("boom")
        yield ""

    ErrorsLive.script = script
    ErrorsLive.describe = describe
    channel = await open_page(ErrorsLive)
    page = _page()

    await channel.event("chat:send", {"message": "go"})
    await channel.until(lambda: not page.busy)

    assert page.messages[-1] == AssistantMessage(
        "turn-1-assistant", status="error", error=shown
    )
    assert shown in channel.sent_text(-1)
    assert channel.close_code is None


@pytest.mark.asyncio
async def test_a_value_that_is_not_an_event_becomes_an_error_reply(open_page) -> None:
    async def script(messages: Sequence[Message]):
        yield "ok so far"
        yield {"text": "not an event"}

    ErrorsLive.script = script
    channel = await open_page(ErrorsLive)
    page = _page()

    await channel.event("chat:send", {"message": "go"})
    await channel.until(lambda: not page.busy)

    reply = page.messages[-1]
    assert isinstance(reply, AssistantMessage)
    assert reply.status == "error"
    assert reply.text == "ok so far"
    assert channel.close_code is None


@pytest.mark.asyncio
async def test_an_error_event_shows_its_message_and_ends_the_reply(open_page) -> None:
    marks: list[str] = []

    async def script(messages: Sequence[Message]):
        try:
            yield "Partial."
            yield Error("The model is overloaded. Try again in a minute.")
            yield "never shown"
        finally:
            marks.append("closed")

    ErrorsLive.script = script
    channel = await open_page(ErrorsLive)
    page = _page()

    await channel.event("chat:send", {"message": "go"})
    await channel.until(lambda: not page.busy)

    failed = AssistantMessage(
        "turn-1-assistant",
        (TextPart("Partial."),),
        "error",
        error="The model is overloaded. Try again in a minute.",
    )
    assert marks == ["closed"]
    assert page.messages[-1] == failed
    assert ErrorsLive.finished == [failed]
    ending = channel.sent_text(-1)
    assert "The model is overloaded. Try again in a minute." in ending
    assert _RETRY in ending
    assert "never shown" not in channel.sent_text(0)


@pytest.mark.asyncio
async def test_retry_replaces_a_failed_reply_in_place(open_page) -> None:
    attempts = 0

    async def script(messages: Sequence[Message]):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("boom")
        yield "Second time lucky."

    ErrorsLive.script = script
    channel = await open_page(ErrorsLive)
    page = _page()

    await channel.event("chat:send", {"message": "go"})
    await channel.until(lambda: not page.busy)
    assert len(page.messages) == 2

    retried = await channel.event("chat:retry")
    await channel.until(lambda: not page.busy)

    reply = AssistantMessage("turn-1-assistant", (TextPart("Second time lucky."),))
    assert page.messages == (_USER, reply)
    # Both attempts answered the same conversation.
    assert ErrorsLive.calls == [(_USER,), (_USER,)]
    assert [message.status for message in ErrorsLive.finished] == ["error", "done"]
    # The retry rewrote the same stream item instead of adding one.
    assert 'id="turn-1-assistant"' in "".join(_strings(retried))
    assert "turn-2" not in channel.sent_text(0)
    ending = channel.sent_text(-1)
    assert "Second time lucky." in ending
    assert "tori-ui-alert--danger" not in ending
    assert _RETRY not in ending


@pytest.mark.asyncio
async def test_retry_replaces_a_stopped_reply(open_page) -> None:
    hold = asyncio.Event()
    attempts = 0

    async def script(messages: Sequence[Message]):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            yield "Slow"
            await hold.wait()
        yield "Fast."

    ErrorsLive.script = script
    channel = await open_page(ErrorsLive)
    page = _page()

    await channel.event("chat:send", {"message": "go"})
    await channel.until(lambda: "<p>Slow</p>" in channel.sent_text(2))
    stopped = await channel.event("chat:stop")
    assert _RETRY in "".join(_strings(stopped))

    await channel.event("chat:retry")
    await channel.until(lambda: not page.busy)

    assert page.messages == (
        _USER,
        AssistantMessage("turn-1-assistant", (TextPart("Fast."),)),
    )


@pytest.mark.asyncio
async def test_retry_needs_an_idle_page_and_a_last_reply_that_did_not_finish(
    open_page,
) -> None:
    hold = asyncio.Event()

    async def script(messages: Sequence[Message]):
        yield "Fine."
        if len(messages) > 1:
            await hold.wait()

    ErrorsLive.script = script
    channel = await open_page(ErrorsLive)
    page = _page()

    # Nothing to retry in an empty conversation.
    await channel.event("chat:retry")
    assert page.messages == ()

    await channel.event("chat:send", {"message": "go"})
    await channel.until(lambda: not page.busy)
    done = page.messages
    # A finished reply is not retried.
    await channel.event("chat:retry")
    assert page.messages == done
    assert not page.busy
    assert not page.can_retry(done[-1])

    await channel.event("chat:send", {"message": "again"})
    await channel.until(lambda: "turn-2-assistant" in channel.sent_text(0))
    # Nor is anything while a reply is being written.
    await channel.event("chat:retry")
    assert len(ErrorsLive.calls) == 2
    assert page.busy


@pytest.mark.asyncio
async def test_a_reply_stops_offering_retry_once_a_later_turn_starts(open_page) -> None:
    attempts = 0

    async def script(messages: Sequence[Message]):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("boom")
        yield "Answer to the second question."

    ErrorsLive.script = script
    channel = await open_page(ErrorsLive)
    page = _page()

    await channel.event("chat:send", {"message": "go"})
    await channel.until(lambda: not page.busy)
    failed = page.messages[-1]
    assert page.can_retry(failed)
    assert _RETRY in channel.sent_text(-1)

    next_turn = "".join(_strings(await channel.event("chat:send", {"message": "next"})))
    await channel.until(lambda: not page.busy)

    # The failed reply was rendered again, now without its retry control.
    assert 'id="turn-1-assistant"' in next_turn
    assert "Something went wrong." in next_turn
    assert _RETRY not in next_turn
    assert not page.can_retry(failed)
    # The model sees the failed reply and decides what to make of it.
    assert ErrorsLive.calls[1] == (_USER, failed, UserMessage("turn-2-user", "next"))
    assert [message.id for message in page.messages] == [
        "turn-1-user",
        "turn-1-assistant",
        "turn-2-user",
        "turn-2-assistant",
    ]


def test_only_a_reply_can_be_retried() -> None:
    page = ErrorsLive()

    assert not page.can_retry(_USER)
    assert not page.can_retry(AssistantMessage("reply", status="error"))


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)

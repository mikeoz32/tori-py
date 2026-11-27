from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from string.templatelib import Template
from typing import Annotated, ClassVar

import pytest
from starlette.datastructures import QueryParams
from tori_py import Inject, injectable, module
from tori_py_liveview import (
    AsyncResult,
    MountContext,
    UnknownAsyncError,
    UnknownEventError,
    UnknownInfoError,
    html,
    live_view,
)
from tori_py_liveview_kit import (
    AssistantMessage,
    ChatEvent,
    ChatLiveView,
    Citation,
    Message,
    ReasoningDelta,
    ReasoningPart,
    TextPart,
    ToolCall,
    ToolPart,
    ToolResult,
    Usage,
    UserMessage,
)
from tori_py_liveview_ui import chat_message


class _Scripted(ChatLiveView):
    """A chat whose model is the generator a test assigns to ``script``."""

    script: ClassVar[Callable[[Sequence[Message]], AsyncIterator[str | ChatEvent]]]
    current: ClassVar[_Scripted | None] = None
    stored: ClassVar[Sequence[Message]] = ()
    calls: ClassVar[list[Sequence[Message]]] = []
    finished: ClassVar[list[AssistantMessage]] = []

    flush_interval = 0.0

    async def mount(self, context: MountContext) -> None:
        await super().mount(context)
        if context.connected:
            _Scripted.current = self

    async def initial_messages(self, context: MountContext) -> Sequence[Message]:
        del context
        return _Scripted.stored

    def respond(self, messages: Sequence[Message]) -> AsyncIterator[str | ChatEvent]:
        _Scripted.calls.append(messages)
        return _Scripted.script(messages)

    async def reply_finished(self, message: AssistantMessage) -> None:
        _Scripted.finished.append(message)


@live_view("/chat")
class ChatLive(_Scripted):
    placeholder = "Ask anything"
    suggestions = (("Short", "A longer suggested prompt"),)


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    _Scripted.current = None
    _Scripted.stored = ()
    _Scripted.calls = []
    _Scripted.finished = []
    ChatLive.flush_interval = 0.0
    yield
    _Scripted.current = None


def _page() -> _Scripted:
    page = _Scripted.current
    assert page is not None
    return page


def _context() -> MountContext:
    return MountContext(
        request=None,
        params={},
        resource="",
        connected=False,
        query_params=QueryParams(),
    )


def _markup(value: object) -> str:
    assert isinstance(value, Template)
    return html(value).to_html()


async def _say(text: str) -> AsyncIterator[str]:
    yield text


@pytest.mark.asyncio
async def test_the_first_render_welcomes_the_visitor(open_page) -> None:
    _Scripted.script = lambda messages: _say("unused")
    channel = await open_page(ChatLive, join=False)

    document = await channel.get()

    assert "How can I help?" in document
    assert 'phx-value-prompt="A longer suggested prompt"' in document
    assert 'phx-submit="chat:send"' in document
    assert 'placeholder="Ask anything"' in document
    assert ">Assistant</title>" in document
    assert 'id="chat-messages"' not in document
    assert 'phx-click="chat:stop"' not in document


@pytest.mark.asyncio
async def test_a_turn_streams_a_reply_and_records_the_conversation(open_page) -> None:
    gate = asyncio.Event()

    async def script(messages: Sequence[Message]):
        yield "Hello "
        await gate.wait()
        yield "**world**"

    _Scripted.script = script
    channel = await open_page(ChatLive)
    page = _page()

    await channel.event("chat:send", {"message": "  Hi there  "})
    opening = channel.sent_text(1)
    assert 'id="turn-1-user"' in opening
    assert "Hi there" in opening
    assert 'id="turn-1-assistant"' in opening
    assert 'phx-click="chat:stop"' in opening
    assert page.busy
    assert page.messages == (UserMessage("turn-1-user", "Hi there"),)

    await channel.until(lambda: "<p>Hello</p>" in channel.sent_text(2))
    assert 'aria-busy="true"' in channel.sent_text(2)

    gate.set()
    await channel.until(lambda: not page.busy)
    # The last frame renders the finished reply.
    ending = channel.sent_text(-1)

    reply = AssistantMessage("turn-1-assistant", (TextPart("Hello **world**"),))
    assert "<strong>world</strong>" in ending
    assert 'aria-busy="true"' not in ending
    assert 'aria-label="Send"' in ending
    assert page.messages == (UserMessage("turn-1-user", "Hi there"), reply)
    assert _Scripted.finished == [reply]


@pytest.mark.asyncio
async def test_respond_receives_the_conversation_through_the_new_message(
    open_page,
) -> None:
    _Scripted.script = lambda messages: _say(f"reply {len(messages)}")
    channel = await open_page(ChatLive)
    page = _page()

    await channel.event("chat:send", {"message": "one"})
    await channel.until(lambda: not page.busy)
    await channel.event("chat:send", {"message": "two"})
    await channel.until(lambda: not page.busy)

    first = AssistantMessage("turn-1-assistant", (TextPart("reply 1"),))
    assert _Scripted.calls == [
        (UserMessage("turn-1-user", "one"),),
        (
            UserMessage("turn-1-user", "one"),
            first,
            UserMessage("turn-2-user", "two"),
        ),
    ]
    assert page.messages[-1] == AssistantMessage(
        "turn-2-assistant", (TextPart("reply 3"),)
    )


@pytest.mark.asyncio
async def test_blank_and_busy_sends_are_ignored(open_page) -> None:
    hold = asyncio.Event()

    async def script(messages: Sequence[Message]):
        yield "working"
        await hold.wait()

    _Scripted.script = script
    channel = await open_page(ChatLive)
    page = _page()

    await channel.event("chat:send", {"message": "   \n "})
    assert page.messages == ()
    assert not page.busy

    await channel.event("chat:send", {"message": "first"})
    await channel.event("chat:send", {"message": "second"})
    await channel.event("chat:suggest", {"prompt": "third"})

    assert page.messages == (UserMessage("turn-1-user", "first"),)
    assert len(_Scripted.calls) == 1


@pytest.mark.asyncio
async def test_a_suggestion_starts_a_turn(open_page) -> None:
    _Scripted.script = lambda messages: _say("ok")
    channel = await open_page(ChatLive)
    page = _page()

    await channel.event("chat:suggest", {"prompt": "A longer suggested prompt"})
    await channel.until(lambda: not page.busy)

    assert page.messages[0] == UserMessage("turn-1-user", "A longer suggested prompt")


@pytest.mark.asyncio
async def test_stop_keeps_what_was_written_and_the_chat_goes_on(open_page) -> None:
    ChatLive.flush_interval = 30.0
    gate, hold = asyncio.Event(), asyncio.Event()
    marks: list[str] = []

    async def script(messages: Sequence[Message]):
        if len(messages) > 1:
            yield "Again."
            return
        try:
            yield "Half"
            await gate.wait()
            yield " an answer"
            marks.append("read")
            await hold.wait()
        finally:
            marks.append("closed")

    _Scripted.script = script
    channel = await open_page(ChatLive)
    page = _page()

    await channel.event("chat:send", {"message": "go"})
    await channel.until(lambda: "<p>Half</p>" in channel.sent_text(2))
    gate.set()
    await channel.until(lambda: marks == ["read"])

    before_the_stop = len(channel.frames)
    await channel.event("chat:stop")
    await channel.until(lambda: marks == ["read", "closed"])
    stopped = AssistantMessage(
        "turn-1-assistant", (TextPart("Half an answer"),), "stopped"
    )

    assert not page.busy
    assert page.messages[-1] == stopped
    assert _Scripted.finished == [stopped]
    ending = channel.sent_text(before_the_stop)
    assert "Half an answer" in ending
    assert "Stopped." in ending
    assert 'aria-label="Send"' in ending

    await channel.event("chat:send", {"message": "again"})
    await channel.until(lambda: not page.busy)
    assert page.messages[-1] == AssistantMessage(
        "turn-2-assistant", (TextPart("Again."),)
    )
    # A stop without a reply being written changes nothing.
    await channel.event("chat:stop")
    assert len(page.messages) == 4


@pytest.mark.asyncio
async def test_a_reply_shows_reasoning_tools_sources_and_usage(open_page) -> None:
    gate = asyncio.Event()

    async def script(messages: Sequence[Message]):
        yield ReasoningDelta("The visitor wants a search.")
        yield ToolCall("call-1", "search_docs", '{"query": "tori"}')
        await gate.wait()
        yield ToolResult("call-1", '{"matches": 3}')
        yield "Found **three** pages."
        yield Citation("Guide", "https://example.com/guide")
        yield Usage(1240, 312, "$0.004")

    _Scripted.script = script
    channel = await open_page(ChatLive)
    page = _page()

    await channel.event("chat:send", {"message": "search"})
    await channel.until(lambda: "search_docs" in channel.sent_text(2))
    running = channel.sent_text(2)
    assert 'id="turn-1-assistant-reasoning-0"' in running
    assert "The visitor wants a search." in running
    assert 'id="turn-1-assistant-tool-1"' in running
    assert "tori-ui-tool-call--running" in running
    assert "Running" in running
    assert "tori-ui-sources" not in running

    before_the_end = len(channel.frames)
    gate.set()
    await channel.until(lambda: not page.busy)
    ending = channel.sent_text(before_the_end)

    assert "tori-ui-tool-call--done" in ending
    assert "<strong>three</strong>" in ending
    assert 'href="https://example.com/guide"' in ending
    assert 'id="turn-1-assistant-sources-1"' in ending
    assert "1.2k" in ending
    assert "$0.004" in ending
    assert page.messages[-1] == AssistantMessage(
        "turn-1-assistant",
        (
            ReasoningPart("The visitor wants a search."),
            ToolPart("call-1", "search_docs", '{"query": "tori"}', '{"matches": 3}'),
            TextPart("Found **three** pages."),
        ),
        citations=(Citation("Guide", "https://example.com/guide"),),
        usage=Usage(1240, 312, "$0.004"),
    )


@pytest.mark.asyncio
async def test_tokens_that_arrive_together_render_once(open_page) -> None:
    hold = asyncio.Event()

    async def script(messages: Sequence[Message]):
        for index in range(20):
            yield f"token-{index} "
        await hold.wait()

    _Scripted.script = script
    channel = await open_page(ChatLive)

    await channel.event("chat:send", {"message": "go"})
    await channel.until(lambda: "token-19" in channel.sent_text(2))

    assert len(channel.pushes) == 1


@pytest.mark.asyncio
async def test_a_stored_conversation_is_restored_on_every_mount(open_page) -> None:
    _Scripted.stored = (
        UserMessage("question-1", "Earlier question"),
        AssistantMessage("answer-1", (TextPart("Earlier answer"),)),
        UserMessage("turn-1-user", "An ID the page would have used"),
        AssistantMessage("turn-1-assistant", (TextPart("Cut off"),), "streaming"),
    )
    _Scripted.script = lambda messages: _say("New answer")
    channel = await open_page(ChatLive)
    page = _page()

    for rendered in (channel.document, channel.sent_text(0)):
        assert "How can I help?" not in rendered
        assert 'id="question-1"' in rendered
        assert "Earlier answer" in rendered
        assert "Cut off" in rendered
        # Nothing is writing the restored reply any more.
        assert "Stopped." in rendered
    assert [message.id for message in page.messages] == [
        "question-1",
        "answer-1",
        "turn-1-user",
        "turn-1-assistant",
    ]
    assert page.messages[-1] == AssistantMessage(
        "turn-1-assistant", (TextPart("Cut off"),), "stopped"
    )

    await channel.event("chat:send", {"message": "next"})
    await channel.until(lambda: not page.busy)

    assert [message.id for message in page.messages[4:]] == [
        "turn-2-user",
        "turn-2-assistant",
    ]
    assert len(_Scripted.calls[0]) == 5


@pytest.mark.asyncio
async def test_initial_messages_are_messages_with_distinct_ids() -> None:

    _Scripted.stored = (UserMessage("same", "a"), AssistantMessage("same"))
    with pytest.raises(ValueError, match="'same' twice"):
        await ChatLive().mount(_context())


@pytest.mark.asyncio
async def test_a_disconnect_ends_the_reply_and_reports_it_once(open_page) -> None:
    hold = asyncio.Event()
    marks: list[str] = []

    async def script(messages: Sequence[Message]):
        try:
            yield "partial"
            await hold.wait()
        finally:
            marks.append("closed")

    _Scripted.script = script
    channel = await open_page(ChatLive)
    page = _page()

    await channel.event("chat:send", {"message": "go"})
    await channel.until(lambda: "<p>partial</p>" in channel.sent_text(2))
    await channel.close()

    cut_off = AssistantMessage("turn-1-assistant", (TextPart("partial"),), "stopped")
    assert marks == ["closed"]
    assert _Scripted.finished == [cut_off]
    assert page.messages[-1] == cut_off
    assert not page.busy


@live_view("/failing-hook")
class FailingHookLive(_Scripted):
    async def reply_finished(self, message: AssistantMessage) -> None:
        raise RuntimeError("the store is down")


@pytest.mark.asyncio
async def test_a_failing_reply_finished_does_not_end_the_connection(
    open_page, caplog: pytest.LogCaptureFixture
) -> None:
    _Scripted.script = lambda messages: _say("ok")
    channel = await open_page(FailingHookLive)
    page = _page()

    with caplog.at_level(logging.ERROR, logger="tori_py_liveview_kit.chat"):
        await channel.event("chat:send", {"message": "go"})
        await channel.until(lambda: not page.busy)

    assert "reply_finished failed: page=FailingHookLive" in caplog.text
    assert page.messages[-1] == AssistantMessage("turn-1-assistant", (TextPart("ok"),))
    await channel.event("chat:send", {"message": "again"})
    await channel.until(lambda: not page.busy)
    assert channel.close_code is None


@live_view("/failing-renderer")
class FailingRendererLive(_Scripted):
    wrong_id: ClassVar[bool] = False

    def render_assistant_message(self, message: AssistantMessage):
        if type(self).wrong_id:
            return chat_message("A root with another ID", id="another-id")
        raise RuntimeError("a bug in the application's renderer")


@pytest.mark.parametrize("wrong_id", [False, True])
@pytest.mark.asyncio
async def test_a_renderer_that_fails_falls_back_and_keeps_the_connection(
    open_page, caplog: pytest.LogCaptureFixture, wrong_id: bool
) -> None:
    FailingRendererLive.wrong_id = wrong_id
    _Scripted.script = lambda messages: _say("ok")
    channel = await open_page(FailingRendererLive)
    page = _page()

    with caplog.at_level(logging.ERROR, logger="tori_py_liveview_kit.chat"):
        await channel.event("chat:send", {"message": "go"})
        await channel.until(lambda: not page.busy)

    assert "could not render a message: page=FailingRendererLive" in caplog.text
    rendered = channel.sent_text(1)
    assert 'id="turn-1-assistant"' in rendered
    assert "Something went wrong." in rendered
    assert "another-id" not in rendered
    assert page.messages[-1] == AssistantMessage("turn-1-assistant", (TextPart("ok"),))
    assert channel.close_code is None


@live_view("/counting")
class CountingLive(_Scripted):
    def __init__(self) -> None:
        self.count = 0

    async def handle_event(self, event: str, value: object):
        if event == "count":
            self.count += 1
            return None
        return await super().handle_event(event, value)

    def render(self):
        return t"<main><output>{self.count}</output>{self.chat_panel()}</main>"


@pytest.mark.asyncio
async def test_a_subclass_adds_events_and_its_own_layout(open_page) -> None:
    _Scripted.script = lambda messages: _say("ok")
    channel = await open_page(CountingLive)
    page = _page()
    assert isinstance(page, CountingLive)

    assert "<main><output>0</output>" in channel.document
    assert 'id="chat-app"' not in channel.document
    assert (await channel.event("count"))["diff"] == {"0": "1"}
    await channel.event("chat:send", {"message": "go"})
    await channel.until(lambda: not page.busy)
    assert page.count == 1
    assert len(page.messages) == 2

    unknown = await channel.event("missing")
    assert unknown == {"reason": "unknown_event"}
    malformed = await channel.event("chat:send", {"text": "no message key"})
    assert malformed == {"reason": "unknown_event"}


@pytest.mark.asyncio
async def test_other_names_go_to_the_base_class() -> None:
    page = ChatLive()

    with pytest.raises(UnknownEventError):
        await page.handle_event("missing", {})
    with pytest.raises(UnknownInfoError):
        await page.handle_info("tick", None)
    with pytest.raises(UnknownAsyncError):
        await page.handle_async("load", AsyncResult(ok=True))


@injectable()
class Greeter:
    def greet(self, name: str) -> str:
        return f"Hello, {name}!"


@module(providers=[Greeter], exports=[Greeter])
class GreeterModule:
    pass


@live_view("/injected")
class InjectedLive(_Scripted):
    def __init__(self, greeter: Annotated[Greeter, Inject(Greeter)]) -> None:
        # No call to the base constructor: the page creates its state itself.
        self.greeter = greeter

    async def respond(self, messages: Sequence[Message]):
        last = messages[-1]
        assert isinstance(last, UserMessage)
        yield self.greeter.greet(last.text)


@pytest.mark.asyncio
async def test_a_page_takes_its_model_client_from_its_constructor(open_page) -> None:
    channel = await open_page(InjectedLive, imports=[GreeterModule])
    page = _page()

    await channel.event("chat:send", {"message": "Tori"})
    await channel.until(lambda: not page.busy)

    assert page.messages[-1] == AssistantMessage(
        "turn-1-assistant", (TextPart("Hello, Tori!"),)
    )


@live_view("/translated")
class TranslatedLive(_Scripted):
    assistant_name = "Помічник"
    welcome = "Чим допомогти?"
    placeholder = "Запитайте що завгодно"
    composer_label = "Повідомлення"
    send_label = "Надіслати"
    stopped_text = "Зупинено."


@pytest.mark.asyncio
async def test_the_visible_text_is_overridable(open_page) -> None:
    _Scripted.script = lambda messages: _say("ok")
    channel = await open_page(TranslatedLive, join=False)

    document = await channel.get()

    for text in (
        ">Помічник</title>",
        "Чим допомогти?",
        'placeholder="Запитайте що завгодно"',
        'aria-label="Надіслати"',
    ):
        assert text in document
    assert "Зупинено." in _markup(
        TranslatedLive().render_assistant_message(
            AssistantMessage("reply", status="stopped")
        )
    )


def test_the_default_reply_markup_names_every_state() -> None:
    page = ChatLive()

    waiting = _markup(
        page.render_assistant_message(AssistantMessage("reply", status="streaming"))
    )
    assert "tori-ui-typing" in waiting
    assert 'aria-busy="true"' not in waiting

    thinking = _markup(
        page.render_assistant_message(
            AssistantMessage("reply", (ReasoningPart("Hm"),), "streaming")
        )
    )
    assert "Thinking" in thinking
    assert "tori-ui-typing" not in thinking

    between = _markup(
        page.render_assistant_message(
            AssistantMessage(
                "reply", (ToolPart("call-1", "search", "{}", "ok"),), "streaming"
            )
        )
    )
    assert "tori-ui-typing" in between

    stopped = _markup(
        page.render_assistant_message(
            AssistantMessage(
                "reply",
                (
                    ReasoningPart("Hm"),
                    ToolPart("call-1", "search"),
                    ToolPart("call-2", "fetch", "", "404", True),
                    TextPart("Half"),
                ),
                "stopped",
            )
        )
    )
    assert "Reasoning" in stopped
    assert "Not finished" in stopped
    assert "tori-ui-tool-call--pending" in stopped
    assert "Failed" in stopped
    assert "tori-ui-tool-call--error" in stopped
    assert "Stopped." in stopped
    assert "tori-ui-message-actions" in stopped

    failed = _markup(
        page.render_assistant_message(
            AssistantMessage("reply", status="error", error="The model is overloaded.")
        )
    )
    assert "tori-ui-alert--danger" in failed
    assert "The model is overloaded." in failed
    assert "tori-ui-message-actions" not in failed

    empty = _markup(page.render_assistant_message(AssistantMessage("reply")))
    assert "The reply is empty." in empty

    user = _markup(page.render_user_message(UserMessage("question", "<b>Hi</b>")))
    assert "&lt;b&gt;Hi&lt;/b&gt;" in user
    assert "tori-ui-chat-message--user" in user

"""A chat that streams from a scripted model, so it needs no API key.

The model task never touches the page. It appends events to a buffer and asks
the page for one flush; the page drains the buffer in `handle_info()`, which
runs with its other callbacks, and renders once for the whole batch.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from string.templatelib import Template

from tori_py_liveview import UnknownEventError, live_view
from tori_py_liveview_ui import (
    avatar,
    chat,
    chat_empty,
    chat_log,
    chat_message,
    composer,
    icon_button,
    markdown,
    message_actions,
    reasoning,
    sources,
    stack,
    suggestions,
    text,
    token_usage,
    tool_call,
    typing_indicator,
)

from examples.tori_py.liveview_ui_gallery.shell import GalleryPage

_LOG = "messages"
_PROMPTS = [
    ("What can you do?", "What can you build with Tori UI?"),
    ("Show me code", "Show me a small LiveView page."),
    "How do streams work?",
]
_ANSWER = """Tori UI gives you **stateless helpers** for LiveView pages:

1. layout, content, and data display;
2. feedback, forms, and navigation;
3. chat and model output, like this message.

```python
@live_view("/hello")
class HelloLive(UiLiveView):
    def render(self) -> Template:
        return container(heading("Hello", level=1))
```

The page owns the state, and the browser owns the scroll position."""

type ModelEvent = tuple[str, str]


async def scripted_model(prompt: str, delay: float) -> AsyncIterator[ModelEvent]:
    """Yield what a model would stream: reasoning, a tool call, then text."""
    await asyncio.sleep(delay * 4)
    for sentence in (
        f"The visitor asked: {prompt!r}. ",
        "A short answer with one example fits best.",
    ):
        yield "reasoning", sentence
        await asyncio.sleep(delay * 4)
    yield "tool", '{"query": "tori ui helpers"}'
    await asyncio.sleep(delay * 8)
    yield "tool_result", '{"matches": 3}'
    for start in range(0, len(_ANSWER), 12):
        await asyncio.sleep(delay)
        yield "text", _ANSWER[start : start + 12]
    yield "done", ""


@dataclass
class Reply:
    """The assistant message that is being written."""

    id: str
    reasoning: str = ""
    thinking: bool = True
    arguments: str | None = None
    result: str | None = None
    answer: str = ""
    done: bool = False
    stopped: bool = False


@live_view("/chat")
class ChatLive(GalleryPage):
    heading = "Chat"
    summary = "A conversation that streams from a scripted model."
    path = "/chat"

    def __init__(self) -> None:
        super().__init__()
        self.turns = 0
        self.reply: Reply | None = None
        self.task: asyncio.Task[None] | None = None
        self.pending: list[ModelEvent] = []
        self.flush_requested = False
        self.delay = 0.03

    @property
    def busy(self) -> bool:
        return self.reply is not None and not self.reply.done

    async def handle_event(self, event: str, value: object) -> None:
        match event, value:
            case "send", {"message": str(prompt)} if prompt.strip():
                self.ask(prompt.strip())
            case "suggest", {"prompt": str(prompt)}:
                self.ask(prompt)
            case "stop", _:
                await self.stop()
            case _:
                raise UnknownEventError(event)

    async def handle_info(self, name: str, value: object) -> None:
        if name != "flush":
            await super().handle_info(name, value)
            return
        self.flush_requested = False
        events, self.pending = self.pending, []
        reply = self.reply
        if reply is None or reply.done:
            return
        for kind, payload in events:
            match kind:
                case "reasoning":
                    reply.reasoning += payload
                case "tool":
                    reply.thinking = False
                    reply.arguments = payload
                case "tool_result":
                    reply.result = payload
                case "text":
                    reply.answer += payload
                case _:
                    reply.done = True
        self.show(reply)

    async def disconnect(self) -> None:
        await self.cancel()

    def ask(self, prompt: str) -> None:
        if self.busy:
            return
        self.turns += 1
        user_id = f"turn-{self.turns}-user"
        self.stream_insert(_LOG, user_id, chat_message(prompt, role="user", id=user_id))
        self.reply = Reply(id=f"turn-{self.turns}-assistant")
        self.show(self.reply)
        self.task = asyncio.create_task(self.generate(prompt))

    async def generate(self, prompt: str) -> None:
        async for event in scripted_model(prompt, self.delay):
            self.pending.append(event)
            # One flush drains every event that has arrived by then.
            if not self.flush_requested:
                self.flush_requested = self.send_info("flush")

    async def stop(self) -> None:
        await self.cancel()
        if self.reply is not None and not self.reply.done:
            self.reply.done = self.reply.stopped = True
            self.reply.thinking = False
            self.show(self.reply)

    async def cancel(self) -> None:
        task, self.task = self.task, None
        self.pending.clear()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def show(self, reply: Reply) -> None:
        self.stream_insert(_LOG, reply.id, self.reply_message(reply))

    def reply_message(self, reply: Reply) -> Template:
        parts: list[object] = []
        if reply.reasoning:
            parts.append(
                reasoning(
                    text(reply.reasoning, size="sm", muted=True),
                    summary="Thinking" if reply.thinking else "Thought it through",
                    streaming=reply.thinking,
                    id=f"{reply.id}-reasoning",
                )
            )
        if reply.arguments is not None:
            parts.append(
                tool_call(
                    "search_docs",
                    status="running" if reply.result is None else "done",
                    status_label="Searching" if reply.result is None else "Done",
                    arguments=reply.arguments,
                    result=reply.result,
                    id=f"{reply.id}-tool",
                )
            )
        if reply.answer:
            parts.append(markdown(reply.answer, highlight=True))
        elif not reply.done:
            parts.append(typing_indicator())
        if reply.stopped:
            parts.append(text("Stopped.", size="sm", muted=True))
        finished = reply.done and not reply.stopped
        footer = (
            stack(
                [
                    sources(
                        [
                            ("LiveView UI guide", "https://example.com/guide"),
                            ("Streams", "https://example.com/streams"),
                        ],
                        id=f"{reply.id}-sources",
                    ),
                    token_usage(input_tokens=1240, output_tokens=312, cost="$0.004"),
                ],
                gap="sm",
                align="start",
            )
            if finished
            else None
        )
        actions = (
            message_actions(
                [icon_button("thumbs-up", label="Good response", size="sm")]
            )
            if finished
            else None
        )
        return chat_message(
            stack(parts, gap="sm"),
            id=reply.id,
            name="Assistant",
            avatar=avatar("Tori Assistant", size="sm"),
            streaming=bool(reply.answer) and not reply.done,
            footer=footer,
            actions=actions,
        )

    def render(self) -> Template:
        if self.turns == 0:
            log: object = chat_empty(
                "What do you want to build?",
                description="This chat answers from a script, so it needs no key.",
                suggestions=suggestions(_PROMPTS, event="suggest"),
            )
        else:
            log = chat_log(self.stream_contents(_LOG), id=_LOG, stream=True)
        form = composer(
            id="composer",
            submit_event="send",
            placeholder="Ask about Tori UI",
            busy=self.busy,
            stop_event="stop",
            hint="Enter sends. Shift+Enter starts a new line.",
        )
        return self.frame(chat(log, form, label="Chat with the scripted model"))

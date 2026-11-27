"""A chat page built with `tori-py-liveview-kit`.

The model is scripted, so the example needs no API key. Replace
`ScriptedModel` with a client for your provider and keep the page as it is.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Sequence
from typing import Annotated

from tori_py import Inject, injectable
from tori_py_liveview import MountContext, live_view
from tori_py_liveview_kit import (
    AssistantMessage,
    ChatEvent,
    ChatLiveView,
    Citation,
    Message,
    ReasoningDelta,
    ToolCall,
    ToolResult,
    Usage,
    create_app,
    run_app,
)

_ANSWER = """Tori Py LiveView Kit turns one generator into a chat:

1. you yield what the model produces;
2. the page keeps the history and streams the reply;
3. stop, errors, and retry come with it.

```python
@live_view("/")
class Assistant(ChatLiveView):
    async def respond(self, messages):
        yield "Hello!"
```

The page owns the conversation, and the browser owns the scroll position."""
_CONVERSATION_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class ModelUnavailable(Exception):
    """What the scripted model raises when a visitor asks it to fail."""


@injectable()
class ScriptedModel:
    """Yields what a model would stream: reasoning, a tool call, then text."""

    delay = 0.03

    async def stream(self, prompt: str) -> AsyncIterator[str | ChatEvent]:
        delay = self.delay
        await asyncio.sleep(delay * 4)
        for sentence in (
            f"The visitor asked: {prompt!r}. ",
            "A short answer with one example fits best.",
        ):
            yield ReasoningDelta(sentence)
            await asyncio.sleep(delay * 4)
        yield ToolCall("call-1", "search_docs", '{"query": "tori py liveview kit"}')
        await asyncio.sleep(delay * 8)
        yield ToolResult("call-1", '{"matches": 3}')
        for start in range(0, len(_ANSWER), 12):
            await asyncio.sleep(delay)
            yield _ANSWER[start : start + 12]
        yield Citation("LiveView Kit guide", "https://example.com/liveview-kit")
        yield Citation("Streams", "https://example.com/streams")
        yield Usage(input_tokens=1240, output_tokens=312, cost="$0.004")


@injectable()
class ConversationStore:
    """Keeps conversations in memory. A real application uses its database."""

    def __init__(self) -> None:
        self._conversations: dict[str, tuple[Message, ...]] = {}

    def load(self, conversation: str) -> tuple[Message, ...]:
        return self._conversations.get(conversation, ())

    def save(self, conversation: str, messages: Sequence[Message]) -> None:
        self._conversations[conversation] = tuple(messages)


@live_view("/")
class AssistantLive(ChatLiveView):
    assistant_name = "Tori Assistant"
    welcome = "What do you want to build?"
    welcome_description = "This assistant answers from a script, so it needs no key."
    placeholder = "Ask about Tori Py"
    composer_hint = "Enter sends. Shift+Enter starts a new line."
    suggestions = (
        ("What can you do?", "What can you build with the LiveView Kit?"),
        ("Show me code", "Show me a small chat page."),
        ("Fail once", "Fail once, then answer on retry."),
    )

    def __init__(
        self,
        model: Annotated[ScriptedModel, Inject(ScriptedModel)],
        store: Annotated[ConversationStore, Inject(ConversationStore)],
    ) -> None:
        self.model = model
        self.store = store
        self.conversation = "default"
        self.failed_once = False

    def render_document(self, live_root: str, client_script: str) -> str:
        document = super().render_document(live_root, client_script)
        # An empty icon keeps browsers from requesting /favicon.ico.
        return document.replace("</head>", '<link rel="icon" href="data:,"></head>', 1)

    async def initial_messages(self, context: MountContext) -> Sequence[Message]:
        # `/?conversation=<name>` opens another conversation.
        requested = context.query_params.get("conversation", "default")
        if _CONVERSATION_ID.fullmatch(requested):
            self.conversation = requested
        return self.store.load(self.conversation)

    async def respond(
        self, messages: Sequence[Message]
    ) -> AsyncIterator[str | ChatEvent]:
        question = messages[-1]
        if "fail" in question.text.lower() and not self.failed_once:
            self.failed_once = True
            yield ReasoningDelta("The visitor asked for a failure. ")
            await asyncio.sleep(self.model.delay * 4)
            raise ModelUnavailable("the scripted model failed on purpose")
        async for event in self.model.stream(question.text):
            yield event

    async def reply_finished(self, message: AssistantMessage) -> None:
        del message
        self.store.save(self.conversation, self.messages)


_PROVIDERS = (ScriptedModel, ConversationStore)

application = create_app(AssistantLive, providers=_PROVIDERS)

if __name__ == "__main__":
    run_app(AssistantLive, providers=_PROVIDERS)

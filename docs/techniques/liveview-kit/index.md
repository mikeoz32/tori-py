# LiveView Kit

`tori-py-liveview-kit` is for prototyping AI applications. You write one async
generator that yields what a model produces, and the kit turns it into a chat
page: it keeps the conversation, streams the reply, and adds a stop button,
error display, and retry.

It builds on [LiveView](../liveview/index.md) and renders with
[LiveView UI](../liveview-ui/index.md). The kit is the layer that owns state;
the UI helpers stay stateless.

```text
uv add tori-py-liveview-kit
```

The optional `highlight` extra colors code blocks in replies:

```text
uv add "tori-py-liveview-kit[highlight]"
```

The kit contains no model client and depends on no provider SDK. You bring the
model call.

## A Chat Page

This is a complete application. `respond()` stands in for a model: replace its
body with a call to your provider.

```python
import asyncio
from collections.abc import AsyncIterator, Sequence

from tori_py_liveview import live_view
from tori_py_liveview_kit import ChatEvent, ChatLiveView, Message, Usage, run_app


@live_view("/")
class AssistantLive(ChatLiveView):
    assistant_name = "Assistant"
    placeholder = "Ask anything"
    suggestions = ("What can you do?", "Show me code")

    async def respond(
        self, messages: Sequence[Message]
    ) -> AsyncIterator[str | ChatEvent]:
        question = messages[-1].text
        for word in f"You asked: **{question}**".split(" "):
            await asyncio.sleep(0.05)
            yield word + " "
        yield Usage(input_tokens=12, output_tokens=8)


if __name__ == "__main__":
    run_app(AssistantLive)
```

Run the file and open `http://127.0.0.1:8000/`.

`respond()` receives the conversation through the visitor's new message and
yields the reply piece by piece. A yielded string is answer text in Markdown.
Everything else on the page comes with the base class.

## What You Yield

A reply is a sequence of events. Each one is a small immutable value:

| Event | Fields | On the page |
| --- | --- | --- |
| `TextDelta` | `text` | Answer text, rendered as Markdown |
| `ReasoningDelta` | `text` | The model's reasoning, folded under one line |
| `ToolCall` | `id`, `name`, `arguments` | A tool call that is running |
| `ToolResult` | `id`, `content`, `is_error` | The result of the call with that `id` |
| `Citation` | `title`, `url` | A numbered source under the answer |
| `Usage` | `input_tokens`, `output_tokens`, `cost` | What the reply consumed |
| `Error` | `message` | Ends the reply as failed and shows the message |

A plain string is a `TextDelta`. Consecutive deltas of one kind join into one
part, and a delta after another kind of part starts a new one, so an agent that
reasons, calls a tool, writes, and calls another tool is shown in that order.

```python
from tori_py_liveview_kit import Citation, ReasoningDelta, ToolCall, ToolResult

async def respond(self, messages):
    yield ReasoningDelta("The question needs a search. ")
    yield ToolCall("call-1", "search_docs", '{"query": "streams"}')
    hits = await self.search("streams")
    yield ToolResult("call-1", f'{{"matches": {len(hits)}}}')
    yield "A stream keeps its items in the browser."
    yield Citation("Streams guide", "https://example.com/streams")
```

`arguments` and `content` are shown as preformatted text, so serialize JSON
before you yield. A second `ToolCall` with the same `id` replaces the first,
which lets you show arguments while they are still arriving. The last `Usage`
of a reply wins.

The kit only displays tool calls. Running the tool and calling the model again
with its result is your code, inside `respond()`.

An event checks its fields when you create it. A `Citation` needs an absolute
`http` or `https` address, because a model chose it.

## The Conversation

`messages` is a sequence of `UserMessage` and `AssistantMessage` values. Both
have `id`, `role`, and `text`. A reply also has:

- `parts`: `TextPart`, `ReasoningPart`, and `ToolPart` values in the order they
  were produced;
- `status`: `streaming`, `done`, `stopped`, or `error`;
- `citations`, `usage`, and, for a failed reply, `error`.

Replies that were stopped or that failed stay in the conversation with what
they produced, so decide what to send to your provider. A reply that failed
before it wrote anything has an empty `text`; most providers reject an empty
turn, so leave it out.

`self.messages` is the conversation without the reply being written, and
`self.busy` tells whether one is being written.

## Stop, Errors, and Retry

The model generator runs in its own task. It never changes the page: it reports
through the events it yields, and the page renders them in batches, at most one
render every 50 ms (`flush_interval`).

| When | The page |
| --- | --- |
| The generator ends | Marks the reply done |
| The visitor presses stop | Keeps what was written, marks the reply stopped, and cancels the generator |
| The generator raises | Shows a generic error on the reply; the exception goes to the log |
| The generator yields `Error("...")` | Shows that message on the reply |
| The visitor presses retry | Runs `respond()` again for the same conversation and replaces the reply |
| The visitor sends while a reply is being written | Ignores the message |
| The connection ends | Cancels the generator |

Cancellation reaches your generator as `asyncio.CancelledError` at its current
`await`, and the kit closes the generator afterwards. Put provider streams in
`async with` or `try`/`finally`, and they are released.

Retry is offered on the last reply while it is stopped or failed. Once the
visitor sends another message, the earlier reply keeps its state and stops
offering retry.

A visitor never sees the text of an exception, because it may hold a key or an
internal address. Override `describe_error()` to say more:

```python
from tori_py_liveview_kit import ChatLiveView


class AssistantLive(ChatLiveView):
    def describe_error(self, error: BaseException) -> str:
        if isinstance(error, TimeoutError):
            return "The model took too long. Try again."
        return super().describe_error(error)
```

## Keeping a Conversation

A page lives as long as its connection. When the browser reconnects after a
network drop or a reload, a new page mounts, and without your help it starts
empty. Two hooks let your application store conversations:

```python
from collections.abc import Sequence

from tori_py_liveview import MountContext
from tori_py_liveview_kit import AssistantMessage, ChatLiveView, Message


class AssistantLive(ChatLiveView):
    async def initial_messages(self, context: MountContext) -> Sequence[Message]:
        self.conversation = context.query_params.get("conversation", "default")
        return await self.store.load(self.conversation)

    async def reply_finished(self, message: AssistantMessage) -> None:
        await self.store.save(self.conversation, self.messages)
```

- `initial_messages()` runs for the first HTTP render and again for every
  connected mount.
- `reply_finished()` runs once for every reply that ends: done, stopped,
  failed, or cut off by a disconnect. A reply that a disconnect cut off arrives
  as `stopped`, with what it had written.

A reply is not resumed after a reconnect. With the hooks above the visitor sees
the part that was written and can retry it.

Where conversations are stored, and which one a visitor may see, is your
application's decision. The example in
`examples/tori_py/liveview_kit/app.py` keeps them in memory.

## Changing the Page

The text a visitor reads or hears is a class attribute. Override it to rename
or translate the page:

```python
from tori_py_liveview_kit import ChatLiveView


class AssistantLive(ChatLiveView):
    assistant_name = "Помічник"
    welcome = "Чим допомогти?"
    placeholder = "Запитайте що завгодно"
    send_label = "Надіслати"
    stop_label = "Зупинити"
    retry_label = "Спробувати ще раз"
    stopped_text = "Зупинено."
    error_text = "Щось пішло не так."
```

`render()` puts the chat in an application shell with a theme switch. To use
your own layout, override it and place `chat_panel()` where the chat belongs:

```python
from string.templatelib import Template

from tori_py_liveview_kit import ChatLiveView
from tori_py_liveview_ui import app_shell, heading


class AssistantLive(ChatLiveView):
    def render(self) -> Template:
        return app_shell(
            self.chat_panel(), id="app", header=heading("Support", level=1)
        )
```

`chat_panel()` must be part of every render, because the messages are a
[stream](../liveview/streams.md): the browser keeps them, and a stream that
leaves the page loses its items. `chat` fills the height of its container, so
give it one.

`render_user_message(message)` and `render_assistant_message(message)` return
one message each and can be overridden. Each must render one root element whose
`id` is `message.id`. `can_retry(message)` tells a custom renderer whether to
offer retry.

A subclass that handles its own events calls `super()` for the rest. The kit
uses the event names `chat:send`, `chat:suggest`, `chat:stop`, and `chat:retry`:

```python
from tori_py_liveview_kit import ChatLiveView


class AssistantLive(ChatLiveView):
    async def handle_event(self, event: str, value: object):
        if event == "clear-draft":
            self.draft = ""
            return None
        return await super().handle_event(event, value)
```

The same holds for `mount()`, `handle_info()`, `handle_async()`, and
`disconnect()`.

## Dependencies in the Page

A page is a provider, so it takes its model client from its constructor. The
kit creates its own state on first use, and the constructor does not call
`super().__init__()`:

```python
from typing import Annotated

from tori_py import Inject, injectable
from tori_py_liveview import live_view
from tori_py_liveview_kit import ChatLiveView, run_app


@injectable()
class Model:
    async def stream(self, prompt: str):
        yield f"You asked: {prompt}"


@live_view("/")
class AssistantLive(ChatLiveView):
    def __init__(self, model: Annotated[Model, Inject(Model)]) -> None:
        self.model = model

    async def respond(self, messages):
        async for piece in self.model.stream(messages[-1].text):
            yield piece


if __name__ == "__main__":
    run_app(AssistantLive, providers=[Model])
```

## Running It

`run_app(*pages, host="127.0.0.1", port=8000, secret=None, providers=(),
imports=())` serves the pages with uvicorn and blocks. It listens on the
loopback interface unless you pass another host.

`create_app(*pages, secret=None, providers=(), imports=())` returns the ASGI
application without serving it. Use it to reload on a code change:

```python
from tori_py_liveview import live_view
from tori_py_liveview_kit import ChatLiveView, create_app


@live_view("/")
class AssistantLive(ChatLiveView):
    async def respond(self, messages):
        yield "Hello!"


application = create_app(AssistantLive)
```

```text
uv run uvicorn app:application --reload
```

Both are development helpers:

- Without a `secret`, one is generated for the process. A browser that
  reconnects after a restart reloads the page.
- They configure no authentication, allowed origins, or live sessions.

When you need those, assemble the modules yourself. It is what the launcher
does:

```python
from tori_py import NestApplication, module
from tori_py.starlette import StarletteAdapter, asgi
from tori_py_liveview import LiveViewModule, LiveViewOptions, live_view
from tori_py_liveview_kit import ChatLiveView
from tori_py_liveview_ui import LiveViewUiModule


@live_view("/")
class AssistantLive(ChatLiveView):
    async def respond(self, messages):
        yield "Hello!"


liveview_module = LiveViewModule.for_root(
    LiveViewOptions(secret="change-me-to-a-long-random-secret"),
    pages=[AssistantLive],
)


@module(imports=[liveview_module, LiveViewUiModule.for_root()])
class AppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule, adapter=StarletteAdapter())


application = asgi(create_application)
```

See [LiveView configuration and security](../liveview/configuration-and-security.md)
for the settings a deployment needs.

## A Real Provider

The repository has two adapters that map a provider's stream to kit events.
They are examples to copy and change, not part of the package:

- `examples/tori_py/liveview_kit/anthropic_adapter.py` for the Anthropic
  Messages API: text, summarized thinking, tool calls, web search results and
  citations, and usage.
- `examples/tori_py/liveview_kit/openai_compatible_adapter.py` for servers
  that speak the Chat Completions streaming format, which is how local model
  servers such as Ollama, vLLM, and LM Studio are usually reached.

Each takes a `run_tool(name, arguments)` function for your own tools. Their
tests feed them stream events in the wire format; they were not run against a
live API in this repository, so try them against your account before you rely
on them.

## Testing

`respond()` is a plain async generator, so a test can call it without a
browser or a connection:

```python
import pytest
from tori_py_liveview_kit import UserMessage


@pytest.mark.asyncio
async def test_the_assistant_repeats_the_question() -> None:
    page = AssistantLive()

    reply = [event async for event in page.respond([UserMessage("q", "Hi")])]

    text = "".join(event for event in reply if isinstance(event, str))
    assert text.startswith("You asked: **Hi**")
```

For the page itself, drive it through a real browser as described in
[Testing LiveView](../liveview/testing.md#browser-tests). The kit's own
scenarios are in `packages/tori-py-liveview-kit/tests/features/`.

## Limits

- One chat panel per page, and one reply at a time.
- A reply that is being written does not survive its connection. Generation
  does not continue in the background.
- Every flush renders the growing reply again and sends it whole, so a very
  long reply costs more per flush than a short one.
- The kit has no conversation store, tool registry, agent loop, or prompt
  templates. It adds no limit on message rate, cost, or content.
- File uploads are not available, because LiveView does not implement them
  yet.
- Model output is treated as untrusted text: reply text goes through
  [`markdown`](../liveview-ui/chat.md#markdown), which shows raw HTML as text
  and leaves images off.

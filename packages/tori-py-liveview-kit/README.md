# ToriPy LiveView Kit

`tori-py-liveview-kit` is a separately installable package for prototyping AI
applications on `tori-py-liveview` and `tori-py-liveview-ui`. You write one
async generator that yields what a model produces, and the kit turns it into a
chat page: it keeps the conversation, streams the reply, and adds a stop
button, error display, and retry.

The kit trusts typed Python events, messages, hooks, and generators. Your type
checker enforces their types; constructors retain semantic checks for names,
IDs, token ranges, and citation URLs. Validate provider responses in your adapter
before constructing events. Untyped calls bypassing these contracts have no
guaranteed runtime validation error.

```bash
uv add tori-py-liveview-kit
```

The optional `highlight` extra colors code blocks in replies:

```bash
uv add "tori-py-liveview-kit[highlight]"
```

## A Chat Page

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

`respond()` receives the conversation through the visitor's new message. A
yielded string is answer text in Markdown; the events `ReasoningDelta`,
`ToolCall`, `ToolResult`, `Citation`, `Usage`, and `Error` show the rest of
what a model produces. Replace the body with a call to your provider.

## What the Kit Does

- The model generator runs in a task its connection owns. It reports through
  the events it yields, and the page renders them in batches.
- Stop keeps what was written and cancels the generator. A disconnect cancels
  it too. The generator is closed either way, so a provider stream opened
  inside it is released.
- A raised exception becomes an error on the reply with a retry control. The
  visitor reads a generic sentence unless `describe_error()` says more; the
  exception goes to the log.
- `initial_messages()` and `reply_finished()` are the hooks for storing
  conversations, so a reload or a reconnect shows the conversation again.
- `create_app()` returns the ASGI application and `run_app()` serves it. Both
  use development defaults: a generated secret and the loopback interface.

## What Stays Yours

The package contains no model client and depends on no provider SDK. The model
call, tool execution and the agent loop, the choice of what to send to the
model, conversation storage, and authentication are the application's. The
repository has example adapters for the Anthropic Messages API and for
OpenAI-compatible servers in `examples/tori_py/liveview_kit/`.

The package ships no stylesheet, script, or hook of its own: it renders with
`tori-py-liveview-ui` helpers on the unchanged official Phoenix LiveView
client.

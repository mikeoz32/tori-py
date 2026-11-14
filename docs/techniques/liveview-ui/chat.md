# Chat and AI

Chat helpers render a conversation and what a language model produces:
messages, reasoning, tool calls, sources, and Markdown. They are stateless like
every other helper. Your page owns the conversation and the model call; the
browser owns the scroll position.

```text
uv add "tori-py-liveview-ui[markdown,highlight]"
```

The `markdown` and `highlight` extras are optional. Everything else on this page
works without them.

## A Streaming Chat

This page streams a reply into a conversation. `reply_to()` stands in for a
model client: replace it with a call to your provider.

```python
import asyncio
from collections.abc import AsyncIterator
from string.templatelib import Template

from tori_py_liveview import LiveView, UnknownEventError, live_view
from tori_py_liveview_ui import (
    UiLiveView,
    chat,
    chat_log,
    chat_message,
    composer,
    markdown,
    typing_indicator,
)


async def reply_to(prompt: str) -> AsyncIterator[str]:
    for word in f"You said: **{prompt}**".split(" "):
        await asyncio.sleep(0.05)
        yield word + " "


@live_view("/chat")
class ChatLive(UiLiveView):
    def __init__(self) -> None:
        self.turns = 0
        self.answer = ""
        self.busy = False
        self.pending: list[str] = []
        self.flush_requested = False
        self.task: asyncio.Task[None] | None = None

    async def handle_event(self, event: str, value: object) -> None:
        match event, value:
            case "send", {"message": str(prompt)} if prompt.strip() and not self.busy:
                self.turns += 1
                self.answer, self.busy = "", True
                user_id = f"turn-{self.turns}-user"
                self.stream_insert(
                    "messages", user_id, chat_message(prompt, role="user", id=user_id)
                )
                self.show_reply()
                self.task = asyncio.create_task(self.generate(prompt))
            case "stop", _:
                await self.cancel()
                self.busy = False
                self.show_reply()
            case _:
                raise UnknownEventError(event)

    async def generate(self, prompt: str) -> None:
        async for chunk in reply_to(prompt):
            self.pending.append(chunk)
            if not self.flush_requested:
                self.flush_requested = self.send_info("flush")
        self.pending.append("")
        self.flush_requested = self.flush_requested or self.send_info("flush")

    async def handle_info(self, name: str, value: object) -> None:
        if name != "flush":
            await super().handle_info(name, value)
            return
        self.flush_requested = False
        chunks, self.pending = self.pending, []
        self.answer += "".join(chunks)
        self.busy = "" not in chunks
        self.show_reply()

    def show_reply(self) -> None:
        reply_id = f"turn-{self.turns}-assistant"
        body = markdown(self.answer) if self.answer else typing_indicator()
        self.stream_insert(
            "messages",
            reply_id,
            chat_message(body, id=reply_id, name="Assistant", streaming=self.busy),
        )

    async def cancel(self) -> None:
        task, self.task = self.task, None
        self.pending.clear()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def disconnect(self) -> None:
        await self.cancel()

    def render(self) -> Template:
        log = chat_log(self.stream_contents("messages"), id="messages", stream=True)
        form = composer(
            id="composer", submit_event="send", busy=self.busy, stop_event="stop"
        )
        return chat(log, form)
```

Three things in it matter for every chat:

- **The messages are a [stream](../liveview/streams.md).** The browser keeps the
  rendered conversation, so the page holds only the reply that is being
  written. Inserting a message again under the same ID updates it in place,
  which is how the reply grows.
- **The model task never touches the page.** It appends chunks to a buffer and
  asks for one flush with `send_info()`. `handle_info()` runs with the page's
  other callbacks, drains everything that has arrived, and renders once. A fast
  model then costs one render per batch, not one per token, and no chunk is
  lost when messages queue up.
- **The page stops the task** when the visitor presses stop and when the page
  goes away.

The gallery's chat adds reasoning, a tool call, sources, and token usage to the
same structure: `examples/tori_py/liveview_ui_gallery/chat.py`.

## Conversation Layout

| Helper | Output |
| --- | --- |
| `chat(log, composer, *, label, header)` | A column: optional header, the log, the composer at the bottom |
| `chat_log(content, *, id, label, stream)` | The scrolling list of messages |
| `chat_message(content, *, role, id, name, avatar, time, streaming, footer, actions)` | One message |
| `composer(*, id, submit_event, ...)` | The form a message is written in |
| `chat_empty(title, *, description, icon, suggestions)` | The welcome shown before the first message |
| `suggestions(items, *, event)` | Prompts the visitor sends with one click |
| `typing_indicator(*, label)` | Three dots while a reply has not started |
| `conversation_list(items, *, label, action)` | Earlier conversations as navigation |

`chat` fills the height of its container, so put it in something with a height:
the main area of an [`app_shell`](layout.md#app-shell), or a container you size
yourself.

### The Log

`chat_log` follows new content while the visitor is at the bottom. Once they
scroll up to read, it stays where they are and shows a button that jumps back to
the latest message. The log is a `role="log"` region, so screen readers announce
new messages.

With `stream=True`, `content` is `self.stream_contents(id)` and every item is a
`chat_message()` whose `id` is the stream item ID. Without it, pass the messages
you render yourself.

### Messages

`role` is `user`, `assistant`, `system`, or `tool` and selects the look: a
visitor's message sits in a bubble at the far side, and a model's message runs
the width of the log.

`streaming=True` marks a message that is still being written. It shows a caret,
and it sets `aria-busy`, so a screen reader waits for the finished message
instead of reading every fragment.

`footer` holds what belongs to the answer, such as `sources()` and
`token_usage()`. `actions` holds a `message_actions()` row:

```python
from tori_py_liveview_ui import icon_button, message_actions

actions = message_actions(
    [icon_button("refresh", label="Try again", size="sm", event="retry")]
)
```

`message_actions` starts with a button that copies the message body; pass
`copy=False` to leave it out.

### The Composer

`composer(*, id, submit_event, name, value, placeholder, change_event, busy,
stop_event, max_rows, actions, hint, ...)` renders a form with one growing text
field.

- Enter sends and Shift+Enter starts a new line. An empty message is not sent.
- The submit event carries the text under `name`, `"message"` by default:
  `{"message": "Hello"}`.
- The field empties itself once the message is sent.
- While `busy` is true the form does not submit. With a `stop_event`, the send
  button becomes a stop button for that time.
- `actions` holds extra controls beside the send button, and `hint` a line of
  text under the field.

`label`, `submit_label`, and `stop_label` are accessible names; translate them
with the rest of your interface.

## Model Output

| Helper | Shows |
| --- | --- |
| `reasoning(content, *, summary, streaming, open, id)` | The model's thinking, folded under one line |
| `tool_call(name, *, status, status_label, arguments, result, ...)` | A tool the model called |
| `agent_steps(items)`, `agent_step(title, *, status, ...)` | The plan of an agent, step by step |
| `sources(items, *, label, id)` | The sources an answer cites, numbered |
| `citation(number, *, href, title)` | An inline reference to a source |
| `attachment(name, *, meta, icon, href, remove_event)` | A file that belongs to a message |
| `token_usage(*, input_tokens, output_tokens, cost)` | What a response consumed |
| `response_branch(*, current, total, previous_event, next_event)` | A switch between alternative responses |
| `artifact_panel(content, *, title, id, ...)` | A document or program the model produced |

```python
from tori_py_liveview_ui import (
    citation,
    reasoning,
    sources,
    stack,
    text,
    token_usage,
    tool_call,
)

answer = stack(
    [
        reasoning(text("The question is about streams."), summary="Thought for 2 s"),
        tool_call(
            "search_docs",
            status="done",
            status_label="Done",
            arguments='{"query": "streams"}',
            result='{"matches": 3}',
        ),
        text(t"A stream keeps its items in the browser.{citation(1, href='#refs-1')}"),
        sources([("Streams guide", "https://example.com/streams")], id="refs"),
        token_usage(input_tokens=1240, output_tokens=312, cost="$0.004"),
    ],
    gap="sm",
)
```

`reasoning` and `tool_call` are native `<details>` elements. `open` is only the
state they start in; afterwards the browser keeps the visitor's choice, also
while the message around them is re-rendered. Give them an `id` when they sit in
a message that streams.

A `status` is `pending`, `running`, `done`, or `error`. `status_label` is the
status in words for the visitor; without it the status name is shown. In
`tool_call`, string `arguments` and `result` are shown as preformatted text, so
serialize JSON before you pass it.

`sources` takes `(title, href)` pairs and opens them in a new tab. With an `id`,
entry *n* gets the ID `<id>-<n>`, which `citation(n, href="#<id>-<n>")` links
to.

## Markdown

`markdown(source, *, highlight, images)` renders CommonMark with tables and
strikethrough inside a [`prose`](content.md#prose) block. It needs the
`markdown` extra.

```python
from tori_py_liveview_ui import markdown

body = markdown("Use **streams** for long lists.\n\n- cheap\n- ordered")
```

The source is treated as untrusted text, because a model writes it:

- Raw HTML is shown as text, not rendered.
- Links with a `javascript:`, `vbscript:`, `file:`, or non-image `data:` target
  are not made links.
- Links to other sites open in a new tab without access to the opener.
- Images are off by default. With image syntax in a model's answer, a page
  would fetch an address the text chose, which can leak what the model saw.
  The syntax renders as a plain link instead; pass `images=True` only for
  sources you trust.

Fenced code becomes a [`code_block`](content.md#code) with a copy button.
`highlight=True` colors it and needs the `highlight` extra; the colors come from
the theme.

A reply that is still streaming may end in the middle of a construct, such as an
unclosed code fence. That renders as what it is so far and settles when the rest
arrives, so you can call `markdown()` on every flush.

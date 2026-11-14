# ToriPy LiveView Kit Architecture

## 1. Purpose

`tori-py-liveview-kit` is an optional, separately installable package for
prototyping AI applications on `tori-py-liveview` and `tori-py-liveview-ui`. It
is the layer that owns state, which the UI package deliberately does not: a chat
page that keeps a conversation, a provider-neutral model event stream, a
streaming runtime that owns the model task, and a launcher that assembles an
application with development defaults.

The application writes one async generator that yields what a model produces.
The package turns it into a conversation with history, streaming, a stop
button, error display, and retry.

## 2. Package Boundary

```text
tori-py-liveview-kit -> tori-py-framework[cli], tori-py-liveview, tori-py-liveview-ui[markdown]
tori-py-framework    -X-> tori-py-liveview-kit
tori-py-liveview     -X-> tori-py-liveview-kit
tori-py-liveview-ui  -X-> tori-py-liveview-kit
```

The package is typed and has no dependency on a model provider SDK, an HTTP
client, or a validation library. The `cli` extra of the framework carries the
ASGI server the launcher runs, and the `markdown` extra of the UI package
renders model text. The optional `highlight` extra adds
`tori-py-liveview-ui[highlight]` for colored code blocks.

The package ships no stylesheet, script, or Phoenix hook. It renders only with
`tori-py-liveview-ui` helpers, and a visual need that no helper covers is added
to the UI package, not here. It uses only the public `tori-py-liveview` page
API: streams, `send_info` and `handle_info`, `start_async`, `cancel_async` and
`handle_async`, and `disconnect`.

## 3. Public Surface

The public facade is the flat `tori_py_liveview_kit` namespace:

- `ChatLiveView`, the chat page base class;
- the events `TextDelta`, `ReasoningDelta`, `ToolCall`, `ToolResult`,
  `Citation`, `Usage`, and `Error`, and their union `ChatEvent`;
- the conversation values `UserMessage`, `AssistantMessage`, their union
  `Message`, the parts `TextPart`, `ReasoningPart`, and `ToolPart`, their union
  `MessagePart`, and the `ReplyStatus` literal;
- `create_app(*pages, ...)` and `run_app(*pages, ...)`.

The implementation modules behind the facade are private, including the
streaming runtime. Applications import names from `tori_py_liveview_kit` only.

## 4. Events

An event is an immutable standard-library dataclass. Its constructor validates
its fields, so a malformed event fails in the model task, where the failure
becomes an error reply, and never in a page callback.

| Event | Fields | Effect on the reply |
| --- | --- | --- |
| `TextDelta` | `text` | Appends to the open text part, or opens one |
| `ReasoningDelta` | `text` | Appends to the open reasoning part, or opens one |
| `ToolCall` | non-empty `id` and `name`, `arguments` | Adds a tool part; the same `id` again replaces its name and arguments in place |
| `ToolResult` | non-empty `id`, `content`, `is_error` | Completes the tool part with that `id`; an unknown `id` adds a completed part named `tool` |
| `Citation` | non-empty `title`, `url` | Adds a source; a repeated `url` is ignored |
| `Usage` | non-negative `input_tokens` and `output_tokens`, optional `cost` | Replaces the reply's usage; the last one wins |
| `Error` | non-empty `message` | Ends the reply as an error with that message |

`arguments` and `content` are text the page shows preformatted, so an adapter
serializes JSON before it yields. `Citation.url` must be an absolute `http` or
`https` URL, because a model chooses it. A generator may also yield a plain
`str`, which is a `TextDelta`.

A text delta after a reasoning or tool part opens a new text part, so the parts
of a reply keep the order in which an agent produced them. `Error` is terminal:
the runtime stops reading the generator after it.

## 5. Messages

`UserMessage(id, text)` and `AssistantMessage(id, parts, status, citations,
usage, error)` are immutable. A reply's `status` is `streaming`, `done`,
`stopped`, or `error`; `error` holds the text shown for a failed reply.
`AssistantMessage.text` joins the text parts. Both messages expose `role`.

Folding a batch of events into a reply is a pure function without LiveView. It
joins the deltas of a batch once, so the cost of a long reply grows with the
number of flushes, not the number of tokens.

## 6. Chat Page

`ChatLiveView` extends `UiLiveView`. A subclass implements one method:

```python
async def respond(
    self, messages: Sequence[Message]
) -> AsyncIterator[str | ChatEvent]: ...
```

`messages` is the conversation up to and including the visitor's new message,
without the reply being written. Earlier replies that were stopped or failed
are included with their status and whatever they produced; mapping them to a
provider's format is the application's choice.

### 6.1 State

The page holds the conversation in `messages`, the reply being written, and the
run that produces it. It initializes this state on first use, so a subclass
constructor is free for dependency injection and does not call
`super().__init__()`. `busy` is true while a reply is being written.

The rendered conversation is a LiveView stream, so the browser keeps the
messages and the server sends only the message that changes. Message IDs are
`turn-<n>-user` and `turn-<n>-assistant`; they are DOM IDs and stream item IDs.

### 6.2 Browser Events

| Event | Value | Behavior |
| --- | --- | --- |
| `chat:send` | `{"message": str}` | Starts a turn; ignored while busy or when the text is blank |
| `chat:suggest` | `{"prompt": str}` | Starts a turn with a suggested prompt |
| `chat:stop` | - | Stops the reply being written |
| `chat:retry` | - | Replaces the last reply when it was stopped or failed |

The page also reserves the info name `tori-kit:flush` and the async name
`tori-kit:reply`. Every other event, info, and async name goes to `super()`, so
a subclass that overrides `handle_event`, `handle_info`, `handle_async`,
`mount`, or `disconnect` calls `super()` for what it does not handle itself.

### 6.3 Hooks

- `initial_messages(context)` returns the conversation a mount starts with. It
  runs for the disconnected render and for every connected mount. A restored
  reply whose status is `streaming` is shown as `stopped`.
- `reply_finished(message)` runs once for every reply that ends: done, stopped,
  failed, or cut off by a disconnect. An exception it raises is logged and does
  not end the connection.
- `describe_error(error)` returns the text a visitor sees when `respond`
  raises. The default is a generic sentence; the exception itself goes to the
  log only, because its text may hold a credential or an internal address.

### 6.4 Rendering

`render()` returns `chat_panel()`, which composes `chat`, `chat_log` or
`chat_empty` with `suggestions`, and `composer`. A subclass may override
`render()` and place `chat_panel()` in its own layout; the panel must be part
of every render, because a stream container that leaves the page loses its
items. `render_user_message(message)` and `render_assistant_message(message)`
return the stream items and may be overridden; each must render one root
element whose `id` is the message ID.

The default reply renders its parts in order: `reasoning` for a reasoning part,
`tool_call` for a tool part, and `markdown` for a text part, with code
highlighting when Pygments is installed. A reply without parts shows
`typing_indicator` while it streams. A finished reply shows `sources` and
`token_usage` in its footer and a copy action. A stopped or failed reply that
is still the last message offers retry.

Visible text and accessible names are class attributes, such as
`assistant_name`, `placeholder`, `welcome`, `suggestions`, `stopped_text`,
`error_text`, and `retry_label`, so an application translates them with the
rest of its interface.

## 7. Streaming Runtime

### 7.1 The Model Task

A turn starts the generator with `start_async("tori-kit:reply", ...)`. The task
never touches the page's rendered state. It appends each event to the buffer of
its run and asks for a flush. LiveView cancels the task before `disconnect()`
runs and bounds the wait with `LiveViewOptions.async_cancel_timeout_seconds`.
The runtime closes the generator with `aclose()` on every exit, so a provider
stream opened inside it is released.

Each run has its own buffer. Events from a run that was stopped or replaced
land in a buffer nobody reads, so they cannot reach a later reply.

### 7.2 Flushing

A flush is one `send_info("tori-kit:flush")`. `handle_info` drains the buffer,
folds the batch into the reply, and re-inserts the reply into the stream, which
is one render for the whole batch. At most one flush is queued at a time, and
flushes are at least `flush_interval` apart (50 ms by default); a timer
delivers the batch that arrives inside the interval.

`send_info` is bounded and returns `False` when its queue is full. The runtime
then retries after the interval and on the next event. The completion of the
task reaches `handle_async` on a path that is not subject to that bound, and
`handle_async` drains whatever is left, so the end of a reply is never lost.

Every callback the package adds catches its own failures. An exception from
`handle_info` or `handle_async` would close the connection, so a reply that
cannot be folded or rendered becomes an error reply instead.

### 7.3 Outcomes

| Situation | Behavior |
| --- | --- |
| The generator ends | The rest of the buffer is rendered and the reply is `done` |
| The generator yields `Error` | The reply is `error` with that message; the generator is closed |
| The generator raises | LiveView logs the exception; the reply is `error` with `describe_error(error)`; the connection stays open |
| The generator yields a value that is not an event or a string | Treated as a raised `TypeError` |
| The visitor presses stop | What has arrived is rendered, the reply is `stopped`, and the task is cancelled |
| The visitor retries | The last reply is replaced in place and `respond` runs again with the same conversation |
| The visitor sends while busy | Ignored |
| The connection ends | LiveView cancels the task; the reply is `stopped` and reported to `reply_finished`; nothing is rendered |
| The browser reconnects | A new page mounts with `initial_messages(context)`; an interrupted reply is not resumed |

A generator that ignores cancellation keeps running until it ends by itself;
its events are discarded, and at disconnect LiveView waits for it no longer
than its cancel deadline.

## 8. Launcher

`create_app(*pages, secret=None, providers=(), imports=())` returns the ASGI
application: a root module that imports `LiveViewModule.for_root(...)` with the
given pages and `LiveViewUiModule.for_root()`. Pages keep their explicit
`@live_view(path)` declarations. `providers` become available to the pages for
constructor injection, and `imports` are modules whose exports the pages need.

Without a `secret` the launcher generates one for the process. Mount tokens
then end with the process, and a browser that reconnects after a restart
reloads the page.

`run_app(*pages, host="127.0.0.1", port=8000, ...)` serves that application
with uvicorn and blocks. It binds the loopback interface unless the caller
passes another host. It has no reload mode; an application that wants one
exposes `create_app(...)` as a module attribute and runs its ASGI server
itself. Authentication, allowed origins, live sessions, and other production
settings are outside the launcher: an application that needs them assembles
its modules explicitly.

## 9. Safety

Model output is untrusted text. Reply text renders through `markdown`, which
shows raw HTML as text, refuses executable link schemes, and leaves images off.
Tool names, arguments, and results render as escaped text. Citation URLs are
restricted to `http` and `https` when the event is created. A raised
exception's text is not shown to the visitor by default.

A visitor's message arrives inside one LiveView frame and is bounded by
`LiveViewOptions.max_message_bytes`. The package adds no other limit; rate,
cost, and content limits are the application's.

## 10. Application Responsibilities

- the model client, its credentials, and the choice of model;
- tool execution and the agent loop; the package only displays tool calls;
- what part of the conversation is sent to the model;
- storing conversations and deciding which one a visitor sees;
- authentication, authorization, rate and cost limits, and moderation.

## 11. Non-Goals

This package does not provide:

- a model client or a provider adapter; adapters for real providers are
  examples in the repository;
- a tool registry, an agent loop, prompt templates, or context-window
  management;
- a conversation store, or generation that continues after the connection
  ends;
- reload, deployment, or production configuration in the launcher;
- file uploads, until LiveView implements the Phoenix upload contract;
- its own stylesheet, script, hooks, client runtime, or protocol.

## 12. Acceptance

- Unit tests fold events into replies without LiveView.
- Runtime tests drive a page over Phoenix V2 Channel frames with generators
  gated by events, not by sleeping: batching, a full info queue, stop, a raised
  exception, an `Error` event, retry, disconnect, and restoring a conversation.
- Launcher tests serve a page and its assets from `create_app` and check the
  server arguments of `run_app`.
- A browser test exercises the example application through the official
  Phoenix client: sending, a streamed reply with reasoning, a tool call,
  sources, and usage, stop, an error followed by a successful retry, and a
  reload that restores the conversation, with no console errors.
- The package passes the family Ruff, formatter, Ty, test, build, artifact, and
  strict documentation gates.

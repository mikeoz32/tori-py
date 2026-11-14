# ToriPy LiveView Kit Specification

This directory records the executable contract for `tori-py-liveview-kit`. The
architecture is maintained in
[`TORI_PY_LIVEVIEW_KIT_ARCHITECTURE.md`](../../TORI_PY_LIVEVIEW_KIT_ARCHITECTURE.md).

1. The package is optional, typed, and separately distributed. It depends on
   `tori-py-framework[cli]`, `tori-py-liveview`, and
   `tori-py-liveview-ui[markdown]`; none of them imports it. It depends on no
   model provider SDK, HTTP client, or validation library.
2. Its public facade is the flat `tori_py_liveview_kit` namespace:
   `ChatLiveView`; the events `TextDelta`, `ReasoningDelta`, `ToolCall`,
   `ToolResult`, `Citation`, `Usage`, `Error`, and `ChatEvent`; the values
   `UserMessage`, `AssistantMessage`, `Message`, `TextPart`, `ReasoningPart`,
   `ToolPart`, `MessagePart`, and `ReplyStatus`; and `create_app` and
   `run_app`. Its implementation modules are private.
3. The package ships no stylesheet, script, or hook. It renders with
   `tori-py-liveview-ui` helpers and uses only the public LiveView page API.
4. Events are immutable and validate their fields when created. Tool IDs and
   names, citation titles, and error messages are non-empty; token counts are
   non-negative integers; a citation URL is an absolute `http` or `https` URL.
5. Folding events into a reply is pure. Consecutive deltas of one kind merge
   into one part, and a delta after a part of another kind opens a new part. A
   `ToolCall` with a known `id` replaces that part's name and arguments in
   place; a `ToolResult` completes the part with its `id`, or adds a completed
   part named `tool` for an unknown `id`. A repeated citation URL is ignored,
   the last `Usage` wins, and nothing after an `Error` changes the reply.
6. A reply's status is `streaming`, `done`, `stopped`, or `error`.
   `AssistantMessage.text` joins its text parts.
7. `ChatLiveView.respond(messages)` returns an async iterator of events or
   strings; a string is a `TextDelta`. `messages` is the conversation through
   the visitor's new message, without the reply being written.
8. The page handles `chat:send` with a string `message`, `chat:suggest` with a
   string `prompt`, `chat:stop`, and `chat:retry`. A blank message and a send
   while busy are ignored. Other events, info names, and async names go to
   `super()`.
9. The conversation renders as a LiveView stream. Message IDs are
   `turn-<n>-user` and `turn-<n>-assistant` and never repeat within a page,
   also after `initial_messages` restores messages with IDs of their own.
10. The model generator runs through `start_async` and never changes rendered
    page state. It appends events to the buffer of its run. The runtime closes
    the generator on every exit.
11. At most one flush is queued, flushes are at least `flush_interval` apart,
    and one flush renders once for the whole batch. A `send_info` that is
    refused is retried. Task completion drains the buffer through
    `handle_async`, independent of the info queue.
12. No callback the package adds raises. A raised exception, an invalid yielded
    value, an `Error` event, and a reply that cannot be rendered all become an
    error reply, and the connection stays open.
13. Stop renders what has arrived, marks the reply `stopped`, and cancels the
    task. Events of a stopped or replaced run never reach a later reply.
14. `chat:retry` applies only when the page is idle and the last message is a
    stopped or failed reply. It replaces that reply in place and calls
    `respond` with the same conversation. A reply stops offering retry once a
    later turn starts.
15. `describe_error(error)` supplies the visitor's text for a raised exception
    and defaults to a generic sentence; the exception text is logged, not
    shown. An `Error` event's message is shown as given.
16. `initial_messages(context)` supplies the conversation of a mount.
    `reply_finished(message)` runs once per ended reply, including a reply cut
    off by a disconnect, which is `stopped`. Its exceptions are logged and do
    not end the connection.
17. A disconnect cancels the model task through LiveView. A reconnect mounts a
    new page; an interrupted reply is not resumed.
18. `render()` returns `chat_panel()`. `render_user_message` and
    `render_assistant_message` return stream items with one root element whose
    `id` is the message ID. Visible text and accessible names are class
    attributes.
19. Reply text renders through `markdown` with its untrusted-source rules. Tool
    names, arguments, and results render as escaped text.
20. `create_app(*pages, secret=None, providers=(), imports=())` returns an ASGI
    application that imports `LiveViewModule` with the pages and
    `LiveViewUiModule`. Without a secret it generates one for the process.
21. `run_app(*pages, host="127.0.0.1", port=8000, ...)` serves that application
    with uvicorn. It has no reload mode and no production configuration.
22. The package contains no model client, provider adapter, tool registry,
    agent loop, conversation store, or generation that outlives its
    connection.

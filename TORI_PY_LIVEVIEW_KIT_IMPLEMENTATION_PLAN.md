# ToriPy LiveView Kit Implementation Plan

## Status

The governing documents are written (LVK0). Every later slice is open.

Architecture:
[`TORI_PY_LIVEVIEW_KIT_ARCHITECTURE.md`](TORI_PY_LIVEVIEW_KIT_ARCHITECTURE.md).

## LVK0: Governing Documents - Complete

- [x] Record the architecture, this plan, and the executable specification.
- [x] Add the package's rules to `AGENTS.md`.

## LVK1: Package Skeleton

- [ ] Add the independently installable typed `tori-py-liveview-kit`
  distribution with its dependencies on the framework `cli` extra, LiveView,
  and the UI `markdown` extra, and its optional `highlight` extra.
- [ ] Register the package in the uv workspace, the development dependency
  group, the Ty command, and the release manifest and its tests.
- [ ] Freeze an empty `tori_py_liveview_kit` facade behind a public API test.

## LVK2: Events and Messages

- [ ] Add the validated immutable events and the `ChatEvent` union.
- [ ] Add `UserMessage`, `AssistantMessage`, the message parts, and
  `ReplyStatus`.
- [ ] Fold a batch of events into a reply as a pure function: merged deltas,
  ordered parts, tool parts replaced and completed by `id`, deduplicated
  citations, last-wins usage, and a terminal `Error`.

## LVK3: Streaming Runtime

- [ ] Run the generator through `start_async`, closing it on every exit, with
  one buffer per run.
- [ ] Coalesce flushes to one queued `send_info` at a time, at least
  `flush_interval` apart, with a retry when the info queue is full.
- [ ] Drain the buffer when the task completes, so the end of a reply does not
  depend on the info queue.
- [ ] Keep every added callback from raising.

## LVK4: Chat Page

- [ ] Add `ChatLiveView` with lazily initialized state, the `chat:send`,
  `chat:suggest`, and `chat:stop` events, and `busy`.
- [ ] Render the conversation as a stream with the UI helpers: reasoning, tool
  calls, Markdown text, sources, usage, and the typing indicator.
- [ ] Add `chat_panel`, `render_user_message`, `render_assistant_message`, and
  the label attributes.
- [ ] Add `initial_messages` and `reply_finished`, including the reply a
  disconnect cuts off.

## LVK5: Errors and Retry

- [ ] Turn a raised exception, an invalid yielded value, and an `Error` event
  into an error reply without closing the connection.
- [ ] Add `describe_error` with a generic default.
- [ ] Add `chat:retry` for the last stopped or failed reply, and withdraw the
  retry control from a reply once a later turn starts.

## LVK6: Launcher

- [ ] Add `create_app` with a generated development secret, provider
  registration for page constructors, and module imports.
- [ ] Add `run_app` on uvicorn, bound to the loopback interface by default.

## LVK7: Example and Browser Acceptance

- [ ] Add an example application that streams from a scripted model, so it
  needs no API key.
- [ ] Exercise it through the official Phoenix client: sending, a streamed
  reply with reasoning, a tool call, sources, and usage, stop, an error
  followed by a successful retry, and a reload that restores the conversation.

## LVK8: Provider Adapter Example

- [ ] Add an example adapter that maps the Anthropic Messages stream to the
  events, with the SDK in the development dependency group only and tests that
  use recorded stream events without a network.
- [ ] Add an OpenAI-compatible adapter example for local models.

## LVK9: Documentation and Acceptance

- [ ] Add the user guide, the API reference entries, the package table rows,
  and the changelog entry.
- [ ] Close the gaps of the hand-written chat in the UI guide: the tail of a
  reply when the info queue is full, the text a stop discards, and a failing
  generator.
- [ ] Run the full-family test, Ruff, formatter, Ty, build, artifact, and
  strict documentation gates.

## Deferred

- A public runtime for a chat inside an arbitrary page or component, until a
  second consumer shows what it needs.
- A built-in conversation store and a stable browser tab identity.
- Regenerating a finished reply and switching between alternative replies.
- Attachments and uploads, until LiveView implements the Phoenix upload
  contract.
- Other page bases, such as a form-to-result page.

# ToriPy LiveView Kit Implementation Plan

## Status

Every slice is complete: the governing documents (LVK0), the package skeleton
(LVK1), the event and message model (LVK2), the streaming runtime (LVK3), the
chat page (LVK4), errors and retry (LVK5), the launcher (LVK6), the example
with its browser scenarios (LVK7), the provider adapter examples (LVK8), and
the documentation and acceptance (LVK9).

Architecture:
[`TORI_PY_LIVEVIEW_KIT_ARCHITECTURE.md`](TORI_PY_LIVEVIEW_KIT_ARCHITECTURE.md).

## LVK0: Governing Documents - Complete

- [x] Record the architecture, this plan, and the executable specification.
- [x] Add the package's rules to `AGENTS.md`.

## LVK1: Package Skeleton - Complete

- [x] Add the independently installable typed `tori-py-liveview-kit`
  distribution with its dependencies on the framework `cli` extra, LiveView,
  and the UI `markdown` extra, and its optional `highlight` extra.
- [x] Register the package in the uv workspace, the development dependency
  group, the Ty command, and the release manifest and its tests.
- [x] Accept an extra on a family dependency in the release metadata check.
- [x] Freeze an empty `tori_py_liveview_kit` facade behind a public API test.

## LVK2: Events and Messages - Complete

- [x] Add the validated immutable events and the `ChatEvent` union.
- [x] Add `UserMessage`, `AssistantMessage`, the message parts, and
  `ReplyStatus`.
- [x] Fold a batch of events into a reply as a pure function: merged deltas,
  ordered parts, tool parts replaced and completed by `id`, deduplicated
  citations, last-wins usage, and a terminal `Error`.

## LVK3: Streaming Runtime - Complete

- [x] Run the generator through `start_async`, closing it on every exit, with
  one buffer per run.
- [x] Coalesce flushes to one queued `send_info` at a time, at least
  `flush_interval` apart, with a retry when the info queue is full.
- [x] Drain the buffer when the task completes, so the end of a reply does not
  depend on the info queue.
- [x] Keep every added callback from raising.

## LVK4: Chat Page - Complete

- [x] Add `ChatLiveView` with lazily initialized state, the `chat:send`,
  `chat:suggest`, and `chat:stop` events, and `busy`.
- [x] Render the conversation as a stream with the UI helpers: reasoning, tool
  calls, Markdown text, sources, usage, and the typing indicator.
- [x] Add `chat_panel`, `render_user_message`, `render_assistant_message`, and
  the label attributes.
- [x] Add `initial_messages` and `reply_finished`, including the reply a
  disconnect cuts off.

## LVK5: Errors and Retry - Complete

- [x] Turn a raised exception, an invalid yielded value, and an `Error` event
  into an error reply without closing the connection.
- [x] Add `describe_error` with a generic default.
- [x] Add `chat:retry` for the last stopped or failed reply, and withdraw the
  retry control from a reply once a later turn starts.

## LVK6: Launcher - Complete

- [x] Add `create_app` with a generated development secret, provider
  registration for page constructors, and module imports.
- [x] Add `run_app` on uvicorn, bound to the loopback interface by default.

## LVK7: Example and Browser Acceptance - Complete

- [x] Add an example application that streams from a scripted model, so it
  needs no API key, and keeps its conversations through `initial_messages` and
  `reply_finished`.
- [x] Exercise it over Channel frames without a browser.
- [x] Exercise it through the official Phoenix client as pytest-bdd scenarios in
  the package's tests: sending, a streamed reply with reasoning, a tool call,
  sources, and usage, stop, an error followed by a successful retry, a reload
  that restores the conversation, and a dropped connection.

## LVK8: Provider Adapter Examples - Complete

- [x] Add an example adapter that maps the Anthropic Messages stream to the
  events: text, summarized thinking, tool calls with the application's tool
  loop, web search results and citations, usage, and declined or cut-off
  replies.
- [x] Add an example adapter for OpenAI-compatible Chat Completions servers,
  which is how local models are usually reached.
- [x] Keep both SDKs in the development dependency group only, and test the
  adapters without a network on stream events written in the wire format and
  validated by each SDK's own models. Neither adapter has run against a live
  API.

## LVK9: Documentation and Acceptance - Complete

- [x] Add the user guide, the API reference entries, the package table rows,
  the example reference, and the changelog entry.
- [x] Name the limits of the hand-written chat in the UI guide and point it at
  this package: the tail of a reply when the info queue is full, the text a
  stop discards, and a failing generator. The UI guide's example and the
  gallery chat are unchanged.
- [x] Run the full-family test, Ruff, formatter, Ty, build, artifact, and
  strict documentation gates.

## Deferred

- A public runtime for a chat inside an arbitrary page or component, until a
  second consumer shows what it needs.
- A built-in conversation store and a stable browser tab identity.
- Regenerating a finished reply and switching between alternative replies.
- Attachments and uploads, until LiveView implements the Phoenix upload
  contract.
- Other page bases, such as a form-to-result page.

# Phase 2: Registration and Dispatch

## Purpose

Connect message types to class/function handlers through explicit metadata and a validated registry. Implement the bus facade and builder, but leave queue mechanics to Phase 3.

## Entry Criteria

- Phase 1 types and exception contracts are complete.
- A fake transport can be used in tests, or a minimal test double can be defined locally.
- No global registry or package scanner exists.

## Registration Metadata

Class decorators MUST attach registration metadata to the decorated class without registering it globally.

Required class decorators:

- `@CommandHandler(CommandType)`;
- `@QueryHandler(QueryType)`;
- `@EventsHandler(EventType)`.

Function handlers use a separate decorator, initially `@handles(MessageType)`. The decorator MUST attach the same logical registration metadata as the class decorators.

Metadata SHOULD include:

- message category;
- message class;
- handler symbol/class name for diagnostics;
- handler style: class or function;
- optional explicit context requirement for functions.

Decorators MUST preserve the decorated object and MUST NOT instantiate classes, create tasks, mutate a global registry, or import modules.

## Handler Forms

The builder/registry must support these inputs:

1. ready handler instance;
2. handler class with registration metadata;
3. provider/factory callable that yields a handler through the provider protocol;
4. decorated function handler.

The implementation MUST not guess whether an arbitrary callable is a handler factory or a message handler. Registration APIs should make the role explicit, and ambiguous inputs must raise `InvalidHandlerRegistration`.

## Registry Rules

The registry is mutable during builder configuration and immutable after `build()`.

Validation rules:

1. A command message type has exactly one registration.
2. A query message type has exactly one registration.
3. An event message type may have zero or many registrations.
4. Duplicate command/query registrations fail during `build()`.
5. Duplicate event registrations are allowed only when they are distinct handler registrations; identical registrations should fail to prevent accidental double delivery.
6. A registration message type must be a matching `Command`, `Query`, or `Event` class.
7. A class handler must expose an async `handle` method.
8. A function handler must be async and match the supported function signature.
9. A registration must not be changed after the registry is passed to a running bus.

## Function Handler Signature

The first implementation should choose one explicit shape rather than support arbitrary signature introspection. The proposed shape is:

```text
async def handler(message: MessageT, context: HandlerContext) -> ResultT
```

If a function does not need context, a separate registration flag or adapter wrapper may provide a message-only form. Do not silently swallow a missing or extra argument.

`HandlerContext` is a core protocol/value that may expose:

- message ID;
- correlation ID when present;
- causation ID when present;
- string headers;
- command, query, and event bus handles.

Application repositories/services are not automatically resolved by core.

## Dispatcher

The dispatcher is the transport consumer supplied by each bus.

For a command/query request it MUST:

1. validate the envelope category and message type;
2. find the single registered handler;
3. obtain a handler callable from the provider context manager;
4. invoke `handle(message)` or the explicit function shape;
5. return a reply envelope with the same correlation ID;
6. convert a handler exception into an error reply for the transport;
7. allow the bus facade to re-raise the original or mapped typed exception.

For an event it MUST:

1. find all registered handlers;
2. pass the event work to EventBus task management;
3. return `None` to the transport consumer once event tasks are tracked.

The dispatcher MUST NOT perform database transactions, serialization, retries, or outbox writes.

## Bus Facades

Public methods:

- `CommandBus.execute(command) -> ResultT`;
- `QueryBus.execute(query) -> ResultT`;
- `EventBus.publish(event) -> DeliveryReceipt`.

Command and query execution MUST create a request envelope, call transport `request`, validate the reply correlation ID, and return the typed result or raise a typed exception.

Event publication MUST create an event envelope and call transport `publish`. It returns after transport enqueue and does not wait for handlers.

The bus MUST reject execute/publish before transport startup with a typed lifecycle exception.

## Builder

Use a mutable configure-then-build API. The builder should provide explicit methods equivalent to:

```text
add_command_handler(registration)
add_query_handler(registration)
add_event_handler(registration)
with_command_transport(transport)
with_query_transport(transport)
with_event_transport(transport)
with_handler_provider(provider)
build()
```

The exact names may change, but configuration must remain explicit and readable. The builder MUST require all three transports unless a documented test-only builder is used.

`build()` MUST validate all registrations before returning any bus. A failed build must not start workers or leave background tasks.

## Lifecycle Ownership

The core builder creates bus objects but does not start transports automatically. The host, later the FastAPI adapter, owns startup and shutdown ordering.

The builder MAY expose a convenience lifecycle coordinator in the future, but it is not required for the first core slice.

## Phase 2 Tests

Tests MUST cover:

1. each decorator stores metadata without global side effects;
2. class handlers receive only message objects;
3. function handlers receive the declared context shape;
4. instance, class, and provider registrations are accepted explicitly;
5. ambiguous callable registrations fail;
6. duplicate command/query handlers fail at build;
7. multiple event handlers are retained in deterministic registration order;
8. missing handlers produce typed errors;
9. command/query results return through the bus facade;
10. handler errors become replies and are re-raised by the facade;
11. event publication delegates enqueue-only semantics to the transport; concrete non-blocking handler execution is verified in Phase 4;
12. building does not start transports or create background tasks.

## Exit Criteria

Phase 2 is complete when a fake transport can exercise all bus facades and registry rules without an asyncio queue implementation. Phase 3 may then replace the fake transport with `InMemoryTransport` without changing message or handler registration APIs.

## Implemented Artifacts

The current implementation is split into these core modules:

- `tori_py_cqrs_core.registrations`: handler kinds, styles, target modes, decorator metadata, `@CommandHandler`, `@QueryHandler`, `@EventsHandler`, and `@handles`;
- `tori_py_cqrs_core.registry`: immutable command/query/event handler mappings and duplicate validation;
- `tori_py_cqrs_core.provider`: explicit instance/class/function/factory materialization without constructor inspection;
- `tori_py_cqrs_core.context`: function-handler context and late-bound bus handles;
- `tori_py_cqrs_core.dispatch`: request reply creation, error conversion, class/function invocation, and event routing;
- `tori_py_cqrs_core.buses`: `CommandBus`, `QueryBus`, and `EventBus` facades;
- `tori_py_cqrs_core.builder`: mutable configure-then-build composition API and `CqrsBuses` result.

The builder supports:

- decorated classes/functions passed explicitly;
- explicit `(message_type, handler)` instance/function registration;
- explicit handler factories;
- one transport per bus;
- an optional custom `HandlerProvider`, with `DefaultHandlerProvider` as the no-DI default.

The registry validates async handler shape at build time. Ready instances are allowed even though they are not themselves callable; class and factory targets must be callable, and function targets must be async callables.

The event dispatcher currently invokes handlers sequentially after the transport consumer receives an event. Phase 4 owns the transition to tracked fire-and-forget task management and must preserve the public `EventBus.publish()` contract.

## Verified Results

Phase 2 was verified through the locked `uv` environment:

```text
uv run ruff check .
uv run ruff format --check .
uv run ty check packages/tori-py-cqrs-core/src packages/tori-py-cqrs-core/tests packages/tori-py-cqrs-fastapi/src packages/tori-py-cqrs-fastapi/tests
uv run pytest
```

Observed results:

- Ruff lint: successful;
- Ruff format check: successful;
- ty type check: successful;
- root workspace suite: `40 passed`;
- core has no relative imports;
- command, query, event, builder, registry, provider, and error paths are covered by tests.

## Review Verdict

Phase 2 received a multi-axis review covering correctness, readability, architecture, security, performance, and test coverage. Required findings were fixed and regression-tested:

- buses now reject work before startup, during lifecycle transitions, and after shutdown;
- each bus requires a distinct transport instance because one transport owns one consumer;
- function handlers are validated as async functions with the exact `(message, context)` shape;
- class decorators and `@handles` enforce their distinct class/function roles;
- decorator metadata is direct-only, preventing inherited registrations from silently changing routing;
- request routing validates message category and turns missing handlers into correlated error replies;
- registration validates concrete message types and exhaustive enum values.

No required Phase 2 findings remain. The concrete queue, worker, reply-future, backpressure, cancellation-isolation, and shutdown-drain behavior belongs to Phase 3. Fire-and-forget event tasks, error hooks, non-blocking event-handler proof, and event draining belong to Phase 4.

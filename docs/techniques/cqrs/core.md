# CQRS Core

`tori-py-cqrs-core` is the framework-neutral CQRS layer. Its runtime dependency
set is the Python standard library, and it does not import ToriPy, FastAPI,
Pydantic, SQLAlchemy, or a DI framework.

## Installation

```text
uv add tori-py-cqrs-core
```

The package requires Python 3.14.

## Complete Standalone Example

This example uses public facade imports, explicit handler registration, and one
in-memory transport per bus:

```python
import asyncio
from dataclasses import dataclass

from tori_py_cqrs_core import (
    Command,
    CommandHandler,
    CqrsBuilder,
    Event,
    EventsHandler,
    InMemoryTransport,
    Query,
    QueryHandler,
)


@dataclass(frozen=True, slots=True)
class Add(Command[int]):
    left: int
    right: int


@dataclass(frozen=True, slots=True)
class ReadTotal(Query[int]):
    pass


@dataclass(frozen=True, slots=True)
class Added(Event):
    value: int


total = 0
event_observed = asyncio.Event()


@CommandHandler(Add)
class AddHandler:
    async def handle(self, command: Add) -> int:
        global total
        total += command.left + command.right
        return total


@QueryHandler(ReadTotal)
class ReadTotalHandler:
    async def handle(self, query: ReadTotal) -> int:
        del query
        return total


@EventsHandler(Added)
class AddedHandler:
    async def handle(self, event: Added) -> None:
        print(f"observed {event.value}")
        event_observed.set()


async def main() -> None:
    buses = (
        CqrsBuilder()
        .add_command_handler(AddHandler)
        .add_query_handler(ReadTotalHandler)
        .add_event_handler(AddedHandler)
        .with_command_transport(InMemoryTransport(name="commands"))
        .with_query_transport(InMemoryTransport(name="queries"))
        .with_event_transport(InMemoryTransport(name="events"))
        .build()
    )

    await buses.event_bus.start()
    await buses.query_bus.start()
    await buses.command_bus.start()
    try:
        result = await buses.command_bus.execute(Add(2, 3), timeout=1)
        assert result == 5
        assert await buses.query_bus.execute(ReadTotal(), timeout=1) == 5

        receipt = await buses.event_bus.publish(Added(result), timeout=1)
        assert receipt.message_id

        # publish() confirms enqueue only. Wait for an application signal before
        # using drain() as proof that already-scheduled handler work completed.
        await asyncio.wait_for(event_observed.wait(), timeout=1)
        await buses.event_bus.drain(timeout=1)
    finally:
        # This order lets accepted commands finish queries/publications before
        # their downstream buses stop.
        await buses.command_bus.shutdown(timeout=1)
        await buses.query_bus.shutdown(timeout=1)
        await buses.event_bus.shutdown(timeout=1)


asyncio.run(main())
```

The example starts events and queries before commands and shuts down commands,
queries, then events. Standalone core does not impose a cross-bus coordinator;
the application owns that order.

## Handler Registration

Decorators attach metadata only. They do not add a handler to a process-global
registry, import a module, or scan a package. The builder must receive each
handler explicitly.

### Decorated classes

```python
from tori_py_cqrs_core import CommandHandler


@CommandHandler(Add)
class AddHandler:
    async def handle(self, command: Add) -> int:
        return command.left + command.right


builder.add_command_handler(AddHandler)
```

Use `CommandHandler`, `QueryHandler`, and `EventsHandler` for classes. A class
handler must expose `async handle(message)`. The core passes only the message;
constructor dependencies are the provider's responsibility.

Metadata is direct, not inherited. A subclass of a decorated handler must be
decorated itself or registered with an explicit message type.

### Function handlers

```python
from tori_py_cqrs_core import HandlerContext, handles


@handles(ReadTotal)
async def read_total(query: ReadTotal, context: HandlerContext) -> int:
    del query
    print(context.envelope.message_id)
    return 0


builder.add_query_handler(read_total)
```

A function handler must be an async function accepting exactly two required
positional parameters: `(message, context)`. `HandlerContext` exposes the
current immutable `Envelope` and command, query, and event bus handles. ToriPy's
integration deliberately supports class handlers only; function handlers are a
standalone core feature.

### Explicit instances and classes

Pass the message type when the target has no decorator metadata:

```python
builder.add_command_handler(Add, AddHandler())
builder.add_query_handler(ReadTotal, ReadTotalHandler)
builder.add_event_handler(Added, AddedHandler())
```

With the default provider, a registered instance is reused. A registered class
is constructed without arguments for each invocation.

### Factories

```python
def make_add_handler() -> AddHandler:
    return AddHandler()


builder.add_command_handler_factory(Add, make_add_handler)
```

The default provider calls a factory without arguments for each dispatch and
awaits its result if needed. The factory must return a class-style handler with
an async `handle()` method.

### Registration rules

- Message types are matched by exact concrete Python type.
- A command type has exactly one registered handler.
- A query type has exactly one registered handler.
- An event type may have zero or more registered handlers.
- Duplicate command/query handlers fail in `build()`.
- Registering the same event target twice for one event fails in `build()`.
- Event registrations retain registration order, although handlers execute
  concurrently and have no start or completion ordering guarantee.
- Every builder requires three different transport objects, even if one bus has
  no handlers.

Dispatching a command or query with no matching handler raises
`MissingHandlerError` at the caller after it travels through the correlated
reply path. Publishing an event with no handlers is valid.

## Dispatch Semantics

### Commands and queries

`execute()` validates the category, creates an `Envelope`, and calls the bus's
transport `request()` method. The envelope has:

- a fresh message UUID;
- a fresh request correlation UUID;
- `causation_id=None`;
- immutable empty headers;
- a fresh delivery UUID, UTC enqueue time, and attempt `1`;
- `message_type` equal to the message class's fully qualified Python path.

The dispatcher selects the handler, opens the provider context manager, invokes
the async handler, closes the provider scope, and returns a `ReplyEnvelope`.
Handler exceptions are placed in that reply and re-raised by `execute()`. The
bus validates reply correlation before returning a result or raising an error.

The public bus convenience methods do not accept custom envelope headers,
correlation IDs, or causation IDs. A custom transport can observe envelopes, but
stable serialization and metadata propagation require an adapter contract
beyond the included in-process convenience path.

### Function-handler context

Function handlers can dispatch queries and events through `context.query_bus`
and `context.event_bus`. They can also inspect IDs, delivery metadata, and
headers through `context.envelope`.

The context includes `context.command_bus`, but same-bus command reentrancy is
guarded as described below. It is not a general service container; application
repositories do not appear in core context automatically.

### Events

`EventBus.publish()` calls the event transport's `publish()` and returns its
`DeliveryReceipt` after acceptance. When the transport later invokes the event
consumer, the bus creates one task per matching handler. Matching handlers for
the same event run independently and concurrently.

An event-handler error:

- does not retroactively fail `publish()`;
- is logged with message and handler identity;
- is delivered to the configured sync or async `EventErrorHandler`;
- is observed so it does not become an unhandled task exception;
- does not kill the in-memory transport worker.

Configure the hook before `build()`:

```python
from tori_py_cqrs_core import EventHandlerFailure


async def report(failure: EventHandlerFailure) -> None:
    print(
        failure.message_id,
        failure.event_type,
        failure.handler,
        failure.handler_id,
        failure.error,
    )


builder.with_event_error_handler(report)
```

If the hook fails, that error is logged and contained. The core does not retry,
requeue, compensate, or dead-letter the failed event.

## Event Drain

`await event_bus.drain(timeout=...)` waits for the generations of handler and
error-observer tasks tracked when drain begins. If the timeout expires, the bus
requests cancellation of those remaining tasks and waits only within its
available cancellation budget. It returns rather than raising `TimeoutError`.
A cancellation-resistant handler can therefore remain active until it
cooperates or finishes.

Drain is not a transport-queue barrier. Immediately after `publish()` returns,
the event may still be queued and no handler task may be tracked yet. Events
submitted concurrently while a drain is in progress are not included
automatically. For deterministic tests:

1. Publish the event.
2. Wait on a bounded application signal proving the relevant handler started or
   produced its effect.
3. Call `drain()` with a sufficient budget to await tracked work for that
   delivery.

With `InMemoryTransport`, `EventBus.shutdown()` is stronger as an admission and
queue boundary: it first shuts down and drains the transport, then drains
tracked handler and error-observer tasks with the remaining timeout. A forced
timeout requests cancellation, cancellation-resistant work may require separate
supervision, and a process crash can lose queued or running events.

The public `Transport` protocol does not itself require a queue-draining shutdown.
A custom transport must define whether accepted work is drained, rejected, or
abandoned during shutdown; `EventBus` cannot strengthen that adapter guarantee.

## Command Reentrancy

A command handler must not call `execute()` through the same active
`CommandBus`. The in-memory command transport has one worker; allowing this
cycle could deadlock and could execute the inner command later after the outer
caller timed out.

The dispatcher marks the active bus while provider setup, handler execution,
and provider cleanup run. A same-bus nested call raises
`NestedCommandDispatchError` before `Transport.request()` and therefore before
enqueue:

```python
from tori_py_cqrs_core import HandlerContext, handles


@handles(Add)
async def invalid_nested_command(
    command: Add,
    context: HandlerContext,
) -> int:
    return await context.command_bus.execute(Add(command.left, command.right))
```

The guard applies to class handlers, function handlers, and custom provider
scopes. It is cleared after success, failure, or cancellation. Top-level
commands remain concurrent from the callers' perspective, although one
`InMemoryTransport` worker processes them FIFO.

Allowed operations include:

- a command handler executing a query through the graph's `QueryBus`;
- a command handler publishing through the graph's `EventBus`;
- dispatch through a different `CommandBus` instance;
- a retained child task dispatching only after the outer handler has completed.

The last case is allowed by the core guard but still requires application-owned
task and shutdown management. It never shares an implicit transaction.

## In-Memory Transport

`InMemoryTransport` is the semantic in-process implementation:

```python
transport = InMemoryTransport(
    max_queue_size=1024,
    default_timeout=2.0,
    error_handler=None,
    name="commands",
)
```

It has one bounded `asyncio` queue and one worker. Requests and publications are
dequeued FIFO. Queue capacity is released when the worker dequeues an item, not
when the handler completes.

Timeout behavior is intentionally specific:

- queue admission waits until capacity or the effective timeout;
- a full queue raises `QueueCapacityError` rather than dropping work;
- a request timeout raises `RequestTimeoutError` to the caller;
- caller timeout or cancellation does not cancel a handler that already started;
- that handler can still finish and mutate state after the caller stopped
  waiting;
- `default_timeout` applies to submissions, not to shutdown unless a shutdown
  timeout is supplied explicitly.

Delivery is process-local, non-durable, and at-most-once. There are no retries,
acknowledgements, requeues, dead letters, or persistence guarantees.

## Bus and Transport Lifecycle

Each bus and `InMemoryTransport` is single-use:

| State | Behavior |
| --- | --- |
| New | Work raises `TransportNotStartedError` |
| Starting or stopping | Work raises `InvalidLifecycleTransitionError` |
| Running | Work is accepted subject to queue/timeouts |
| Stopped | Work raises `TransportStoppedError` |

Calling `start()` twice is invalid. Shutdown is idempotent and permanently stops
the bus. A cancelled or failed shutdown does not resume dispatch.

Normal transport shutdown stops intake, waits for queued/running work to the
deadline, then cancels the worker and fails pending requests if necessary.
Concurrent shutdown calls coordinate; a later bounded shutdown can force an
earlier unbounded drain to complete.

## Custom Providers

Implement the public `HandlerProvider` protocol when handler creation requires
DI or scoped cleanup. `provide(registration, context)` returns an async context
manager. It is entered once per command handler, query handler, or individual
event handler invocation.

The provider receives a `HandlerRegistration` exposing the message type and a
`DispatchContext` exposing the current envelope. It must yield the callable
function or class-style handler represented by the registration and must clean
up in `__aexit__`, including error and cancellation paths.

Provider scope is the right place to implement constructor injection, request
resources, transaction contexts, or handler caching. It must not change routing
semantics. The ToriPy and FastAPI packages are concrete provider adapters.

## Custom Transports

A transport implements the public `Transport` protocol:

```python
from tori_py_cqrs_core import Transport


assert isinstance(my_transport, Transport)
```

It must provide async `start(consumer)`, `request(envelope, timeout=None)`,
`publish(envelope, timeout=None)`, and `shutdown(timeout=None)`. The transport
delivers envelopes to the consumer supplied at start; the bus dispatcher, not
the transport, owns handler routing.

Request transports must return a valid correlated `ReplyEnvelope`.
Publication transports return a `DeliveryReceipt` after acceptance. A serialized
transport must define its own stable message aliases, serialization, remote
error representation, delivery guarantee, retry policy, and acknowledgement
semantics rather than treating Python exception objects or class paths as a
wire contract.

## Failure Checklist

| Failure | Meaning |
| --- | --- |
| `DuplicateCommandHandlerError` / `DuplicateQueryHandlerError` | Invalid graph found during build |
| `MissingHandlerError` | No exact command/query handler at dispatch |
| `InvalidHandlerRegistrationError` | Wrong category, target shape, function signature, or async contract |
| `TransportNotStartedError` / `TransportStoppedError` | Work submitted outside running lifecycle |
| `QueueCapacityError` | Submission was not accepted before capacity timeout |
| `RequestTimeoutError` | Caller stopped waiting; execution may already have started |
| `InvalidReplyCorrelationError` | Transport returned a reply for another correlation |
| `NestedCommandDispatchError` | Same active command bus was called recursively before enqueue |

Do not turn `RequestTimeoutError` into an automatic command retry without an
application idempotency contract.

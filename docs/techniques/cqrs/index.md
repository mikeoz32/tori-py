# CQRS

Command Query Responsibility Segregation (CQRS) separates requests that decide
and change state from requests that read state. In Tori Py, the same message
model can be used at three different integration levels:

| Need | Package | Guide |
| --- | --- | --- |
| Framework-neutral messages, handlers, buses, and in-memory transport | `tori-py-cqrs-core` | [CQRS Core](core.md) |
| ToriPy modules, DI scopes, discovery, and interceptors | `tori-py-cqrs` | [CQRS with ToriPy](tori-py.md) |
| FastAPI lifespan and dependency helpers without ToriPy | `tori-py-cqrs-fastapi` | [CQRS with FastAPI](fastapi.md) |
| Event-sourced write models | `tori-py-cqrs-event-sourcing-core` or `tori-py-cqrs-event-sourcing` | [Event Sourcing](../event-sourcing/index.md) |

All packages require Python 3.14. Install only the integration boundary the
application needs:

```text
uv add tori-py-cqrs-core
uv add tori-py-cqrs
uv add tori-py-cqrs-fastapi
```

`tori-py-cqrs` and `tori-py-cqrs-fastapi` already depend on the core package.
They are alternative adapters; a FastAPI application does not need the ToriPy
integration unless it is also a ToriPy application.

## Message Categories

The core exposes three typed marker classes:

```python
from dataclasses import dataclass

from tori_py_cqrs_core import Command, Event, Query


@dataclass(frozen=True, slots=True)
class CreateProfile(Command[int]):
    username: str


@dataclass(frozen=True, slots=True)
class GetProfile(Query[dict[str, object] | None]):
    profile_id: int


@dataclass(frozen=True, slots=True)
class ProfileCreated(Event):
    profile_id: int
```

The generic argument on `Command[ResultT]` and `Query[ResultT]` describes the
result returned by `execute()`. `Event` has no result.

| Category | Routing | Caller operation | Completion means |
| --- | --- | --- | --- |
| Command | Exactly one handler must be registered | `CommandBus.execute()` | The request transport returned the handler result |
| Query | Exactly one handler must be registered | `QueryBus.execute()` | The request transport returned the handler result |
| Event | Zero or more handlers may be registered | `EventBus.publish()` | The transport accepted the event, not that handlers completed |

"Exactly one handler" is a routing rule, not an exactly-once execution
guarantee. A caller can time out after a command has started, and a durable
transport may define delivery guarantees that differ from the included
in-memory transport.

Immutable slotted dataclasses are the recommended message shape, but the core
requires only concrete subclasses of the appropriate marker. It does not
require Pydantic, msgspec, or a serializer.

## The Basic Flow

A typical request crosses explicit boundaries:

```text
HTTP/controller/consumer
  -> construct a command or query
  -> execute it through the matching bus
  -> transport delivers an envelope
  -> registry selects the exact message-type handler
  -> provider opens a handler scope
  -> handler performs application work
  -> provider closes the scope
  -> request transport returns a correlated reply
```

An event follows a different completion model:

```text
publisher
  -> EventBus.publish(event)
  -> transport accepts an event envelope
       |-> publish returns DeliveryReceipt without waiting for handlers
       `-> independently, transport dequeues before or after that return
             -> EventBus schedules every matching handler independently
             -> failures are logged and sent to the event error hook
```

Commands should express intent, queries should not change domain state, and
events should describe facts. The framework enforces routing and lifecycle
rules, but it does not inspect a handler to enforce those modeling conventions.

## Choosing a Composition Model

### Standalone core

Use `tori-py-cqrs-core` when the application owns composition itself. Register
every handler on `CqrsBuilder`, provide three distinct transports, start the
buses, and shut them down explicitly. The default provider supports ready
instances, no-argument classes, functions, and sync or async no-argument
factories. See [CQRS Core](core.md).

### ToriPy

Use `tori-py-cqrs` when handlers need ToriPy constructor injection, provider
visibility, singleton/request/transient scopes, managed resources, discovery,
or invocation interceptors. Handler classes remain ordinary providers and are
discovered from the compiled module graph. See [CQRS with ToriPy](tori-py.md).

### FastAPI without ToriPy

Use `tori-py-cqrs-fastapi` when FastAPI owns application lifespan and route
dependency injection. `FastAPIAdapter` stores one CQRS graph in `app.state`, and
the public dependency helpers expose its buses to routes. Handler dependencies
are explicit and separate from FastAPI's route dependency solver. See
[CQRS with FastAPI](fastapi.md).

## Transport and Persistence Boundaries

CQRS buses do not persist application state. The included
`InMemoryTransport` is:

- process-local and non-durable;
- bounded and FIFO, with one worker per transport;
- at-most-once, with no retry, acknowledgement, requeue, or dead-letter policy;
- request/reply for commands and queries;
- enqueue-and-return for events.

`DeliveryReceipt` proves only that the transport accepted an envelope. It is not
proof of event-handler completion, database commit, broker durability, or read
model convergence.

Likewise, CQRS events and event-sourced domain events are related concepts but
not an atomic mechanism. The event-sourcing packages never publish persisted
events automatically. See [Event Sourcing](../event-sourcing/index.md) before
combining the two techniques.

## Design Guidance

- Keep controllers and transport consumers thin: translate input, dispatch, and
  translate output or errors.
- Put command decisions in application/domain services or aggregates, not in
  transport adapters.
- Build query models for the read use case rather than returning write-model
  internals by default.
- Publish an event explicitly only when asynchronous fan-out is acceptable.
- Treat in-process event projections as potentially behind the command result.
- Configure finite request and shutdown timeouts according to the surrounding
  application lifecycle.
- Make command idempotency, retries, transaction boundaries, and outbox behavior
  explicit application or adapter concerns.
- Test handler effects only after an application-level completion signal; then
  use `EventBus.drain()` to wait for tracked handler work within a sufficient
  budget.

## Current Boundaries

The CQRS packages do not provide generated routes, package scanning, sagas,
process managers, retries, brokers, persistence, an outbox, or exactly-once
execution. The core routing identity is the fully qualified Python class path;
it is suitable for the typed in-process envelope but is not a stable serialized
broker contract.

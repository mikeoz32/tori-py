# Phase 1: Core Types and Protocols

## Purpose

Define the stable, framework-agnostic vocabulary used by every later phase. This phase must not implement routing, queue workers, FastAPI integration, or dependency resolution.

## Entry Criteria

- Phase 0 exit criteria are met.
- The core package can be imported through the workspace.
- Tests run through `uv`.

## Public Concepts

The core public API consists of:

- message marker classes;
- immutable envelope and delivery metadata;
- request reply and publish receipt types;
- typed transport and consumer protocols;
- handler and provider protocols;
- lifecycle and dispatch exception types;
- message type identity helper.

The module layout SHOULD separate message contracts, transport contracts, errors, and typing helpers. Avoid a single implementation module that becomes a hidden god object.

## Message Marker Classes

The core MUST provide generic marker classes equivalent to:

```python
class Message:
    ...


class Command(Message, Generic[ResultT]):
    ...


class Query(Message, Generic[ResultT]):
    ...


class Event(Message):
    ...
```

Requirements:

1. `Command[T]` describes the result returned by its one handler.
2. `Query[T]` describes the result returned by its one handler.
3. `Event` has no bus result and is published one-way.
4. Marker classes MUST NOT validate, serialize, persist, or resolve dependencies.
5. The core SHOULD allow frozen slotted dataclasses to inherit from the markers.
6. The core MUST NOT require every application message to be a Pydantic model.

Example:

```python
@dataclass(frozen=True, slots=True)
class CreateProfile(Command[ProfileId]):
    username: str


@dataclass(frozen=True, slots=True)
class ProfileCreated(Event):
    profile_id: ProfileId
```

## Message Type Identity

Provide one helper that returns the fully qualified Python path for a message class. The helper MUST be deterministic for a given import path and MUST NOT import modules or scan packages.

The helper SHOULD reject non-message values when used to create an envelope. The first slice does not promise that the value remains stable after a module or class rename.

## Envelope

Use immutable, slotted dataclasses for the envelope and its nested delivery metadata.

Required envelope data:

```text
message: MessageT
message_type: str
message_id: UUID
correlation_id: UUID | None
causation_id: UUID | None
headers: Mapping[str, str]
delivery: DeliveryMetadata
```

Required delivery data:

```text
delivery_id: UUID
enqueued_at: datetime
attempt: int
```

Validation rules:

1. `message_type` MUST match the message class identity when the envelope is created by a bus.
2. IDs MUST be UUID values.
3. `attempt` MUST be at least 1.
4. `enqueued_at` SHOULD be timezone-aware.
5. Headers MUST be treated as read-only by the envelope API.
6. Events MAY have `correlation_id=None` and `causation_id=None`.
7. Command/query request envelopes MUST carry the correlation ID required to match a reply.

The core does not serialize envelopes. A future adapter may map the immutable object to bytes or broker-specific headers.

## Reply Envelope

The request transport returns a reply envelope with:

- a reply ID;
- the request correlation ID;
- either a result value or an exception object.

`None` is a valid successful result, so success MUST be determined by the absence of an error, not by checking whether the result is non-`None`.

The in-memory implementation MAY carry the original Python exception object. A serialized transport is responsible for its own error representation and is outside this phase.

## Delivery Receipt

`publish()` returns a receipt containing at least:

- original message ID;
- transport delivery ID;
- enqueue timestamp.

The receipt means that the transport accepted the envelope into its queue. It MUST NOT mean that an event handler completed.

## Protocols

### Transport consumer

The consumer protocol receives an envelope from the transport worker and returns:

- a reply envelope for command/query request work;
- `None` for event publish work.

The transport MUST treat the consumer as an opaque callback. It MUST NOT inspect handler metadata or route by message type.

### Transport

The protocol MUST expose:

```text
start(consumer) -> None
request(envelope, timeout=None) -> ReplyEnvelope
publish(envelope, timeout=None) -> DeliveryReceipt
shutdown(timeout=None) -> None
```

All operations are asynchronous. `start` is explicit. A transport is not ready until `start` completes.

### Handler provider

The core defines a provider protocol but does not implement a DI container. The provider receives a handler registration and dispatch context, then returns an async context manager that yields the callable handler. The context manager is responsible for cleanup.

The provider owns caching and scope policy. Core MUST NOT assume singleton, request, or transient behavior.

### Handler protocols

Class handlers expose an async `handle(message)` method and receive only the typed message. Function handlers are async callables and may receive a typed context as a second argument. Exact function-context introspection belongs to Phase 2 and must be explicit rather than inferred from arbitrary signatures.

## Exception Types

Define distinct exception types for at least:

- transport not started;
- transport stopped;
- queue capacity timeout/full;
- request timeout;
- duplicate command registration;
- duplicate query registration;
- missing handler;
- invalid handler registration;
- invalid reply correlation;
- invalid lifecycle transition.

Exceptions SHOULD carry stable attributes useful to tests and logging, such as message type, message ID, and correlation ID. Do not expose internal queue objects in exception attributes.

## Phase 1 Tests

Tests MUST cover:

1. marker classes support generic result annotations;
2. frozen slotted message instances cannot be mutated;
3. message type identity is deterministic;
4. envelope fields are preserved exactly;
5. invalid attempts and missing IDs fail clearly;
6. headers are exposed as a read-only mapping contract;
7. reply envelopes distinguish successful `None` from an error;
8. protocol implementations can be type-checked/imported without FastAPI;
9. forbidden third-party imports are absent from core runtime code.

## Exit Criteria

Phase 1 is complete when all public types and protocols are documented, imported from deliberate package exports, covered by focused tests, and contain no routing or framework-specific behavior.

## Implemented Artifacts

The current implementation is split into these core modules:

- `tori_py_cqrs_core.messages`: `Message`, `Command`, `Query`, and `Event` markers;
- `tori_py_cqrs_core.identity`: fully qualified message type identity helper;
- `tori_py_cqrs_core.envelope`: delivery metadata, envelope, reply envelope, and delivery receipt;
- `tori_py_cqrs_core.errors`: validation, lifecycle, transport, registration, and reply errors;
- `tori_py_cqrs_core.protocols`: async handler, registration, dispatch context, provider, consumer, and transport protocols.

The package root exports the deliberate public API through `__all__`. It does not import FastAPI, Pydantic, SQLAlchemy, or broker clients.

## Verified Results

Phase 1 was verified through the locked `uv` environment:

```text
uv lock --check
uv run --locked pytest packages/tori-py-cqrs-core/tests
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked ty check packages/tori-py-cqrs-core/src packages/tori-py-cqrs-core/tests packages/tori-py-cqrs-fastapi/src packages/tori-py-cqrs-fastapi/tests
uv run --locked python -m compileall -q packages/tori-py-cqrs-core/src/tori_py_cqrs_core packages/tori-py-cqrs-core/tests
```

Observed results:

- core focused suite: `16 passed`;
- root workspace suite: `17 passed`;
- Ruff lint: successful;
- Ruff format check: successful;
- ty type check: successful;
- compile check: successful;
- core runtime dependency tree: `tori-py-cqrs-core` only;
- public envelope and protocol type hints resolve successfully.

The provider and function-handler protocols intentionally remain minimal. Phase 2 must define registration metadata, the concrete function context shape, and the explicit builder API before tightening those contracts.

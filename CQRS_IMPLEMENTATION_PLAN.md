# CQRS Library Implementation Plan

Status: Phases 0-7 complete.

The executable phase specifications are in [`spec/README.md`](spec/README.md). Each phase document defines entry criteria, required artifacts, contracts, failure behavior, tests, and exit criteria. Update the relevant specification before changing an agreed behavior in code.

## 1. Goal

Build a reusable CQRS library for Python 3.14 in a `uv` workspace. The library is inspired by the concepts of NestJS CQRS, but its API and internals must be Python-native rather than a mechanical port.

The first application-facing demonstration is a FastAPI profile flow:

1. A route executes a `CreateProfile` command.
2. A command handler creates a profile in an in-memory repository.
3. The handler explicitly publishes a `ProfileCreated` event.
4. The event is delivered through the in-memory transport without blocking the command caller.
5. A query returns the created profile.

## 2. Workspace Boundaries

The initial `uv` workspace should contain two packages:

- `tori-py-cqrs-core`: framework-agnostic messages, envelopes, buses, registries, transport protocols, builder, and in-memory transport.
- `tori-py-cqrs-fastapi`: FastAPI lifecycle, bus dependency helpers, and a FastAPI-specific handler provider implementation.

The core package must have Python standard library runtime dependencies only. The FastAPI package may depend on `tori-py-cqrs-core` and FastAPI. SQLAlchemy, Pydantic, RabbitMQ, Redis/Dragonfly, PostgreSQL, Citus, retry systems, and outbox persistence are later adapters or application concerns.

The workspace targets Python 3.14. Every Python dependency, environment, command, test, and tool invocation must go through `uv`.

## 3. Core Message Model

Use typed marker base classes:

- `Command[ResultT]`: request/response operation with exactly one handler.
- `Query[ResultT]`: read operation with exactly one handler.
- `Event`: one-way notification with zero or more handlers.

The default message style is `@dataclass(frozen=True, slots=True)`. Applications may use other typed subclasses only if the core contract permits them; the core must not require Pydantic.

Message routing identity in the MVP is the fully qualified Python class path (`module.ClassName`). This is intentionally not a stable broker contract. Explicit aliases and versions belong to the later serialization/broker adapter.

## 4. Handler API

Class-based handlers are canonical for the first acceptance flow:

```python
@CommandHandler(CreateProfileCommand)
class CreateProfileHandler:
    def __init__(self, profiles: ProfileRepository, events: EventBus):
        self.profiles = profiles
        self.events = events

    async def handle(self, message: CreateProfileCommand) -> ProfileId:
        profile_id = self.profiles.create(message.username)
        await self.events.publish(ProfileCreated(profile_id))
        return profile_id
```

Use Nest-like class decorator names:

- `@CommandHandler(MessageType)`
- `@QueryHandler(MessageType)`
- `@EventsHandler(MessageType)`

Class handlers receive only the typed message in `handle(message)`. Dependencies are supplied through explicit constructor injection; core does not resolve constructors itself.

Function handlers are a supported secondary API. They use a separate function decorator such as `@handles(MessageType)` and may receive a typed `HandlerContext` in addition to the message. The context may expose envelope metadata and bus handles. Application repositories/services are not part of the core function context MVP.

Decorators only attach registration metadata. The builder receives decorated symbols explicitly. Do not use global registration, automatic import scanning, or implicit module discovery.

## 5. Envelope and Reply Contracts

An envelope is a typed object in the core MVP, not bytes. It should contain:

- message object;
- fully qualified `message_type` string;
- `message_id`;
- optional `correlation_id`;
- optional `causation_id`;
- `Mapping[str, str]` headers;
- delivery metadata: delivery ID, enqueue timestamp, and attempt number.

`message_id` and delivery metadata apply to every message. `correlation_id` and `causation_id` are request/reply metadata for command/query flows; fire-and-forget events do not require them.

Command/query transport requests return a reply envelope containing the correlation ID plus either a typed result or a Python exception object. InMemory transport may carry the exception object directly. A future serialized transport must map it to its own error DTO.

## 6. Transport Protocol

Transport is a delivery abstraction. It must not know handler registries or perform message routing. The bus/dispatcher owns routing and supplies a consumer callback when the transport starts.

The core protocol needs these operations:

- `start(consumer)`: explicitly start the worker; dispatch before startup is a typed error.
- `request(envelope, timeout=None)`: enqueue a command/query envelope and await a reply envelope.
- `publish(envelope, timeout=None)`: enqueue a one-way event and return a delivery receipt after enqueue.
- `shutdown(timeout=None)`: stop accepting new messages, drain to the deadline, then cancel remaining work.

Caller timeout/cancellation cancels waiting for a reply but must not forcibly cancel a handler that has already started. A bounded queue waits for capacity up to the configured timeout; it must not silently drop messages.

## 7. InMemoryTransport

The first transport implementation has these semantics:

- one transport instance per bus;
- an `asyncio` queue and one worker per transport/bus;
- FIFO processing by default;
- transport worker invokes the bus dispatcher consumer;
- request/reply futures are resolved by correlation ID;
- event publishing is fire-and-forget from the caller perspective;
- event handler tasks are tracked by `EventBus`, not awaited by `publish()`;
- delivery is at-most-once and non-durable;
- no retry, acknowledgement, requeue, dead-letter, or persistence behavior;
- events may be lost on process crash or an undrained shutdown;
- normal shutdown drains queued/running work until its deadline.

The transport should expose typed lifecycle, queue-full, not-started, timeout, and stopped errors where applicable.

## 8. Buses and Routing

The application-facing bus API is intentionally Nest-like:

- `CommandBus.execute(command) -> ResultT`;
- `QueryBus.execute(query) -> ResultT`;
- `EventBus.publish(event) -> DeliveryReceipt`.

All three buses use a transport. Commands and queries use `request`; events use `publish`.

Routing rules are strict:

- one command type maps to exactly one handler;
- one query type maps to exactly one handler;
- one event type maps to zero or more handlers;
- duplicate command/query registration is a build-time error;
- missing handler is a typed dispatch error;
- command/query handler exceptions propagate to the caller through typed exceptions;
- event handler exceptions do not fail `publish()`, but are sent to a configured error hook and logging.

`EventBus` tracks event handler tasks and exposes drain/shutdown behavior. `publish()` completes after enqueue, not after event handler completion.

## 9. Registry and Builder

Use a mutable configure-then-build API. The application explicitly supplies:

- command, query, and event handler registrations;
- one transport for each bus;
- the provider implementation used to create handler scopes.

The builder validates registration metadata and duplicates in `build()`. It must accept the supported handler forms: ready instances, handler classes, and provider/factory callables. The provider owns whether a handler is cached as a singleton or created per dispatch.

There is no core DI container or resolver. The core only defines the provider protocol needed by the dispatcher. A provider should expose handler creation/cleanup as an async context manager so resource cleanup is guaranteed.

## 10. FastAPI Adapter

The FastAPI package owns application lifecycle. It should:

- start all transports during FastAPI lifespan startup;
- stop and drain them during lifespan shutdown;
- expose buses through `app.state` and typed `Depends` helpers;
- keep bus objects lazy-singleton at the adapter boundary;
- implement the provider protocol for handler dependency graphs;
- avoid depending on FastAPI private `solve_dependencies` internals in the initial design;
- keep request/app scope policy inside the adapter provider rather than core.

The core must remain usable without FastAPI. The adapter may grow deeper FastAPI integration later, but that integration must not leak FastAPI types into core protocols.

## 11. Implementation Order

### Phase 0: Workspace and tooling

Detailed specification: [`spec/phase-00-workspace-and-tooling.md`](spec/phase-00-workspace-and-tooling.md)

1. Verify `uv` is installed and available.
2. Create root workspace metadata targeting Python 3.14.
3. Add `tori-py-cqrs-core` and `tori-py-cqrs-fastapi` package metadata.
4. Add test tooling and the repository's formatting/linting configuration.
5. Run the first dependency sync through `uv`.

### Phase 1: Core types

Detailed specification: [`spec/phase-01-core-types-and-protocols.md`](spec/phase-01-core-types-and-protocols.md)

1. Add marker message classes and generic result typing.
2. Add immutable envelope, delivery metadata, reply envelope, and delivery receipt types.
3. Add typed lifecycle, transport, consumer, provider, and handler protocols.
4. Add message type identity helper using fully qualified class paths.
5. Add focused unit tests for immutable messages and envelope construction.

### Phase 2: Registration and dispatch

Detailed specification: [`spec/phase-02-registration-and-dispatch.md`](spec/phase-02-registration-and-dispatch.md)

1. Implement class and function handler decorators as metadata only.
2. Implement explicit registry registration for instances, classes, and providers.
3. Implement duplicate and missing-handler validation.
4. Implement command/query/event dispatcher routing.
5. Implement typed dispatch errors and reply conversion.
6. Implement mutable builder and bus facades.

### Phase 3: InMemoryTransport

Detailed specification: [`spec/phase-03-inmemory-transport.md`](spec/phase-03-inmemory-transport.md)

1. Implement explicit start/stop state transitions.
2. Implement bounded FIFO queue and capacity timeout behavior.
3. Implement one worker loop per transport.
4. Implement request/reply futures and correlation validation.
5. Implement publish receipts and at-most-once delivery.
6. Implement shutdown drain deadline and cancellation behavior.
7. Add transport lifecycle, cancellation, queue, ordering, and error tests.

### Phase 4: Event task management

Detailed specification: [`spec/phase-04-event-task-management.md`](spec/phase-04-event-task-management.md)

1. Make EventBus schedule and track event handler tasks.
2. Add error hook and logging behavior.
3. Add `drain()` and shutdown integration.
4. Test that event publish does not await handlers, errors do not escape publish, and shutdown drains within a deadline.

### Phase 5: FastAPI adapter

Detailed specification: [`spec/phase-05-fastapi-adapter.md`](spec/phase-05-fastapi-adapter.md)

1. Add FastAPI package dependency on core.
2. Implement app-state bus accessors and `Depends` helpers.
3. Implement lifespan startup/shutdown orchestration.
4. Implement the adapter-owned async-context-manager handler provider.
5. Add a profile acceptance app using an in-memory repository.
6. Keep the first acceptance flow class-handler based; add a separate function-handler test.

### Phase 6: Review and hardening

Detailed specification: [`spec/phase-06-review-and-hardening.md`](spec/phase-06-review-and-hardening.md)

1. Run focused tests, then the complete test suite through `uv`.
2. Review public exports and error messages.
3. Check that core has no FastAPI/Pydantic/SQLAlchemy runtime dependency.
4. Check cancellation, shutdown, duplicate registration, and event error behavior.
5. Update this plan and `AGENTS.md` when implementation decisions diverge from the agreed design.

### Phase 7: Command reentrancy guard

Detailed specification:
[`spec/phase-07-command-reentrancy.md`](spec/phase-07-command-reentrancy.md)

1. Mark the active command-bus identity while a handler runs.
2. Reject same-bus nested `execute()` before transport enqueue.
3. Preserve independent buses, nested queries, and event publication behavior.
4. Verify no rejected nested command can execute later after timeout/cancellation.

## 12. Verification Targets

Once workspace tooling exists, the normal verification path should be defined and run through `uv`, at minimum:

```text
uv sync
uv run pytest
```

Focused verification should include the core package tests and the FastAPI profile acceptance test. Do not add RabbitMQ, Dragonfly/Redis, PostgreSQL/Citus, SQLAlchemy, migrations, or outbox behavior until the in-process contracts and lifecycle tests are stable.

## 13. Explicit Non-Goals for the First Slice

- No production social-network domain model beyond the profile demo.
- No database integration or transaction/Unit of Work abstraction.
- No RabbitMQ, Redis/Dragonfly, broker serialization, stable message aliases, or version negotiation.
- No retries, durable events, acknowledgements, dead letters, or outbox.
- No automatic module/import scanning.
- No core DI container.
- No generated FastAPI routes.

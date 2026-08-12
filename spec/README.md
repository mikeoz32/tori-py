# CQRS Specifications

The Kinker product has a separate domain vision, ubiquitous language, context
map, cross-context policies, and bounded-context specifications under
[`spec/kinker/README.md`](kinker/README.md). Those documents govern product
business behavior and do not change the reusable CQRS package contracts below.

Nestpy has a separate architecture and phase map under
[`spec/nestpy/README.md`](nestpy/README.md). Its implemented N0-N8 phases do not
create a CQRS dependency. The optional bridge has implemented C0-C3 under
[`spec/nestpy-cqrs/README.md`](nestpy-cqrs/README.md).
The implemented optional event-sourcing package has a separate phase map under
[`spec/cqrs-event-sourcing/README.md`](cqrs-event-sourcing/README.md); it extends
the library without changing the first-slice contracts below.
The planned Nestpy-native bridge between those two optional packages is governed
by [`spec/nestpy-cqrs-event-sourcing/README.md`](nestpy-cqrs-event-sourcing/README.md).
The planned framework-neutral append-only persistent log is governed separately
by [`spec/persistent-streams/README.md`](persistent-streams/README.md); it has no
CQRS, Nestpy, broker, database, or serializer dependency.

These documents turn `CQRS_IMPLEMENTATION_PLAN.md` into executable implementation specifications. They are the source of truth for the first CQRS slice until code and tests establish a more precise behavior.

## How To Read

The specifications use these terms:

- **MUST**: required for the first slice.
- **MUST NOT**: prohibited for the first slice.
- **SHOULD**: default unless an implementation reason is documented.
- **MAY**: optional and must not weaken the required contracts.

Read the phases in order. Each phase has explicit entry criteria, deliverables, invariants, tests, and exit criteria. Do not start a later phase while an earlier phase has unresolved contract failures.

## Phase Map

| Phase | Specification | Depends on | Main result |
| --- | --- | --- | --- |
| 0 | [Workspace and tooling](phase-00-workspace-and-tooling.md) | None | Reproducible `uv` workspace |
| 1 | [Core types and protocols](phase-01-core-types-and-protocols.md) | 0 | Stable message, envelope, error, and protocol types |
| 2 | [Registration and dispatch](phase-02-registration-and-dispatch.md) | 1 | Explicit registry, decorators, builder, and bus facades |
| 3 | [In-memory transport](phase-03-inmemory-transport.md) | 1, 2 | Queue-backed request/publish delivery |
| 4 | [Event task management](phase-04-event-task-management.md) | 2, 3 | Tracked fire-and-forget event handling |
| 5 | [FastAPI adapter](phase-05-fastapi-adapter.md) | 0-4 | Lifecycle, bus dependencies, provider adapter, profile demo |
| 6 | [Review and hardening](phase-06-review-and-hardening.md) | 0-5 | Verified first slice and documented residual risks |
| 7 | [Command reentrancy guard](phase-07-command-reentrancy.md) | 0-6 | Same-bus nested commands rejected before enqueue |

## Cross-Phase Invariants

These constraints apply to every implementation phase:

1. Python target is 3.14.
2. All Python environments, dependency changes, commands, tests, and tooling use `uv` exclusively.
3. `cqrs-core` MUST remain importable without FastAPI, Pydantic, SQLAlchemy, RabbitMQ, Redis, or a DI framework installed.
4. The core MUST be async-first. Public bus and transport operations are asynchronous.
5. Commands and queries have exactly one handler. Events have zero or more handlers.
6. Routing is explicit. Decorators do not mutate a global registry and packages are never scanned automatically.
7. Transport does not know handler registries or routing rules. The bus/dispatcher owns those concerns.
8. The first transport is non-durable, at-most-once, queue-backed, and in-memory.
9. Command/query handler failures propagate as typed exceptions. Event handler failures go to an error hook and do not fail `publish()`.
10. The first slice has no transaction, persistence, retry, outbox, broker serialization, or stable message versioning contract.

## Change Control

When an implementation needs to change an agreed behavior:

1. Update the affected phase specification first.
2. Update `CQRS_IMPLEMENTATION_PLAN.md` if phase order, scope, or non-goals change.
3. Update `AGENTS.md` only for durable repository guidance that future agents must see immediately.
4. Add or update a test that demonstrates the changed behavior.

Do not resolve an open design question by silently choosing behavior in code.

## Current Open Decisions

The CQRS phases have no unresolved implementation decisions. The implemented
framework-neutral event-sourcing slice is recorded in
[`CQRS_EVENT_SOURCING_IMPLEMENTATION_PLAN.md`](../CQRS_EVENT_SOURCING_IMPLEMENTATION_PLAN.md).
Its detailed phase specifications govern the completed implementation. Durable
database adapters, transport retry, outbox delivery, and projection runners still
require separate specifications. The planned Nestpy event-sourcing integration is
recorded in
[`NESTPY_CQRS_EVENT_SOURCING_ARCHITECTURE.md`](../NESTPY_CQRS_EVENT_SOURCING_ARCHITECTURE.md).

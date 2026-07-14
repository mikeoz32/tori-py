# Phase 5: FastAPI Adapter

## Purpose

Integrate the core buses with FastAPI without placing FastAPI types or dependency behavior into `cqrs-core`. The adapter is responsible for application lifecycle, app state access, and its own handler provider implementation.

## Entry Criteria

- Phases 0-4 pass their focused tests.
- Core buses and transports have explicit start/shutdown operations.
- The exact function-handler context and provider protocol have been finalized enough for an adapter implementation.

## Adapter Responsibilities

The FastAPI package MUST provide:

- app-state registration for configured buses;
- typed dependency helpers for command, query, and event buses;
- lifespan startup orchestration;
- lifespan shutdown/drain orchestration;
- an adapter-owned handler provider implementing the core provider protocol;
- a minimal profile acceptance application/test fixture.

It MUST NOT:

- generate routes from command/query metadata;
- add FastAPI imports to core;
- use a global singleton unrelated to the FastAPI application instance;
- silently create a different CQRS graph for each route;
- depend on FastAPI private dependency solver internals in the initial implementation.

## Application State

The adapter SHOULD store the configured CQRS graph or individual bus handles in `app.state`.

Dependency helpers SHOULD:

1. receive the current `Request` or application object through FastAPI's public dependency mechanism;
2. retrieve the configured bus from that app instance;
3. fail with a clear configuration error if the application was not initialized;
4. return the same configured bus instance for the application lifetime.

The bus object is a lazy singleton at the adapter boundary. Lazy construction MUST still be synchronized so concurrent first requests cannot create duplicate graphs.

## Lifespan Ordering

Startup:

1. Build or obtain the configured core graph.
2. Create the provider and transport instances.
3. Start command, query, and event transports.
4. Store ready bus handles in `app.state`.
5. Mark the adapter ready.

If any startup step fails, previously started transports must be shut down before the exception escapes application startup.

Shutdown:

1. Stop accepting new work through the adapter.
2. Drain command/query/event transports and event tasks according to the configured deadline.
3. Release provider-managed resources.
4. Clear or mark app-state handles unavailable.
5. Preserve the first shutdown failure while still attempting cleanup of all components.

The adapter must not close resources before in-flight handler work has completed or been cancelled.

## Provider API

The adapter provider implements the core async-context-manager provider contract. It owns:

- app-scoped caching;
- request/dispatch scope decisions;
- construction of handler classes and callable providers;
- cleanup of resources created for a handler scope.

The initial adapter provider MUST expose an explicit API instead of attempting to invoke FastAPI's private `solve_dependencies` machinery. If a future integration uses `Depends` metadata inside handlers, it must be isolated behind this provider and covered by adapter-specific compatibility tests.

The provider MUST make the following distinction explicit:

- a singleton bus does not imply singleton handlers;
- a request-scoped dependency must not be retained by a long-lived event task;
- event handlers that outlive a route request need app-safe dependencies or an explicit event scope;
- a provider scope ends only after handler cleanup completes.

## Profile Acceptance Flow

The acceptance fixture should contain only enough domain code to prove the infrastructure:

- immutable `CreateProfile` command;
- immutable `ProfileCreated` event;
- immutable `GetProfile` query;
- in-memory profile repository;
- class-based command handler;
- class-based query handler;
- at least one event handler with observable test output;
- three configured buses and three in-memory transports;
- FastAPI routes that obtain buses through adapter dependency helpers.

Expected flow:

1. `POST` route obtains `CommandBus`.
2. Route calls `profile_id = await command_bus.execute(command)`.
3. Command handler writes to the in-memory repository and calls `await event_bus.publish(event)`.
4. Command execution returns the typed `profile_id` after event enqueue, not event handler completion.
5. `GET` route obtains `QueryBus` and returns the profile from the query handler.
6. Test explicitly drains events before asserting event-handler side effects.

The fixture must not introduce SQLAlchemy, a real broker, authentication, or production social-network domain behavior.

## FastAPI Tests

Tests MUST cover:

1. bus helpers retrieve the configured app-state buses;
2. uninitialized app state fails clearly;
3. lifespan starts all transports;
4. lifespan shutdown drains and stops all transports;
5. startup failure cleans up earlier transports;
6. concurrent first access does not create duplicate singleton buses;
7. profile command returns a typed profile ID;
8. profile query returns the created profile;
9. event side effects require explicit drain in tests;
10. provider cleanup runs after handler scope completion;
11. core package remains importable without importing FastAPI.

## Exit Criteria

Phase 5 is complete when the profile acceptance flow passes through a real FastAPI lifespan and route dependency graph, while core tests remain framework-independent and no adapter implementation detail leaks into core types.

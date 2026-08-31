# CQRS with FastAPI

`tori-py-cqrs-fastapi` integrates the framework-neutral CQRS graph with a
FastAPI application's lifespan and route dependencies. It does not use ToriPy,
and it does not call FastAPI's private dependency solver for handler
construction.

## Installation

```text
uv add tori-py-cqrs-fastapi
```

This installs FastAPI and `tori-py-cqrs-core`. The package requires Python 3.14.

## Complete Application

The adapter owns registration, graph construction, bus startup, readiness, and
shutdown. Route dependencies retrieve the same application-scoped buses from
`app.state`.

```python
import asyncio
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, FastAPI
from tori_py_cqrs_core import (
    Command,
    CommandBus,
    CqrsBuses,
    Event,
    EventBus,
    Query,
    QueryBus,
)
from tori_py_cqrs_fastapi import (
    FastAPIAdapter,
    FastAPIHandlerProvider,
    get_command_bus,
    get_event_bus,
    get_query_bus,
)


@dataclass(frozen=True, slots=True)
class CreateProfile(Command[int]):
    username: str


@dataclass(frozen=True, slots=True)
class GetProfile(Query[dict[str, object] | None]):
    profile_id: int


@dataclass(frozen=True, slots=True)
class ProfileCreated(Event):
    profile_id: int


class ProfileServices:
    def __init__(self) -> None:
        self.profiles: dict[int, dict[str, object]] = {}
        self.observed: list[int] = []
        self.event_seen = asyncio.Event()
        self.events: EventBus | None = None


services = ProfileServices()
provider = FastAPIHandlerProvider({ProfileServices: services})


def connect_buses(buses: CqrsBuses) -> None:
    services.events = buses.event_bus


adapter = FastAPIAdapter(
    provider=provider,
    on_buses_built=connect_buses,
    shutdown_timeout=5,
)


@adapter.command_handler(CreateProfile)
class CreateProfileHandler:
    def __init__(self, dependencies: ProfileServices) -> None:
        self._services = dependencies

    async def handle(self, command: CreateProfile) -> int:
        profile_id = len(self._services.profiles) + 1
        self._services.profiles[profile_id] = {
            "id": profile_id,
            "username": command.username,
        }
        if self._services.events is None:
            raise RuntimeError("event bus is not initialized")
        await self._services.events.publish(ProfileCreated(profile_id))
        return profile_id


@adapter.query_handler(GetProfile)
class GetProfileHandler:
    def __init__(self, dependencies: ProfileServices) -> None:
        self._services = dependencies

    async def handle(self, query: GetProfile) -> dict[str, object] | None:
        return self._services.profiles.get(query.profile_id)


@adapter.event_handler(ProfileCreated)
class ObserveProfileCreated:
    def __init__(self, dependencies: ProfileServices) -> None:
        self._services = dependencies

    async def handle(self, event: ProfileCreated) -> None:
        self._services.observed.append(event.profile_id)
        self._services.event_seen.set()


app = FastAPI(lifespan=adapter.lifespan)


@app.post("/profiles")
async def create_profile(
    username: str,
    commands: Annotated[CommandBus, Depends(get_command_bus)],
) -> dict[str, int]:
    return {"profile_id": await commands.execute(CreateProfile(username))}


@app.get("/profiles/{profile_id}")
async def get_profile(
    profile_id: int,
    queries: Annotated[QueryBus, Depends(get_query_bus)],
) -> dict[str, object] | None:
    return await queries.execute(GetProfile(profile_id))


@app.post("/events/wait-tracked")
async def wait_for_tracked_event_handlers(
    events: Annotated[EventBus, Depends(get_event_bus)],
) -> None:
    # This waits only for handler tasks that are already tracked. It is not a
    # barrier for accepted events that are still in the transport queue.
    await events.drain(timeout=1)
```

`on_buses_built` runs once after graph construction and before bus startup. It
may be sync or async. It is useful when an explicitly supplied application
service needs a bus handle; handlers themselves can also receive such a service
through the provider.

## Handler Registration

The adapter registration decorators are instance-specific:

```python
adapter.command_handler(MessageType)(HandlerClassOrInstance)
adapter.query_handler(MessageType)(HandlerClassOrInstance)
adapter.event_handler(MessageType)(HandlerClassOrInstance)
```

They add targets to this adapter's core builder and return the target unchanged.
No module scan or global registration occurs. The usual core routing rules
apply: one command handler, one query handler, and zero or more event handlers.

Factory decorators register explicit no-argument factories:

```python
@adapter.command_handler_factory(CreateProfile)
def create_handler() -> CreateProfileHandler:
    return CreateProfileHandler(services)
```

Equivalent query and event factory decorators are available. A factory may
return an awaitable. Factory-produced handlers are dispatch-scoped and owned by
`FastAPIHandlerProvider` when that provider is configured.

The registration target need not carry core handler decorator metadata because
the adapter receives the message type explicitly.

## FastAPI Lifespan

Always install `adapter.lifespan` as the FastAPI lifespan, or compose it inside
the application's one lifespan context:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with adapter.lifespan(app):
        # Other resources that require ready CQRS buses may enter here.
        yield


app = FastAPI(lifespan=lifespan)
```

For one adapter instance, lifespan is single-use and cannot be active twice.
Create one adapter per application instance.

Startup behavior is:

1. Lazily build or reuse one `CqrsBuses` graph for the app.
2. Store it as `app.state.cqrs_buses` and internal readiness state.
3. Bind the app to the configured handler provider when it supports `bind_app`.
4. Start command, query, then event buses.
5. Set `app.state.cqrs_ready = True` and admit requests.

If a start fails, attempted buses are shut down in reverse order. Lifespan setup
also attempts to close all buses and provider resources before re-raising the
original failure.

Shutdown behavior is:

1. Mark the graph not ready so dependency helpers reject new route work.
2. Shut down command, query, then event buses with one decreasing
   `shutdown_timeout` budget.
3. Let event shutdown drain its transport and tracked event tasks.
4. Close provider-managed app resources with the remaining budget.
5. Preserve the first cleanup error while still attempting every component.

The adapter does not clear `app.state.cqrs_buses`; readiness determines whether
route dependencies may use it. Buses are single-use and stopped after lifespan.

## Lazy Graph and Readiness

`await adapter.get_buses(app)` is synchronized and returns the same graph to
concurrent callers. It builds but does not start the buses and does not mark them
ready. This can support setup hooks, but routes should use dependency helpers.

The public helpers are:

```text
get_command_bus(request) -> CommandBus
get_query_bus(request) -> QueryBus
get_event_bus(request) -> EventBus
```

They read the current request's app, return that app's configured singleton bus,
and raise `FastAPIConfigurationError` before startup, after shutdown, or when the
adapter was not installed as lifespan. They never create a graph per route.

## Handler Provider

Without a provider, the core `DefaultHandlerProvider` is used. It constructs
registered classes and calls factories without arguments, so it is appropriate
only for handlers with no constructor dependencies or for prebuilt instances.

`FastAPIHandlerProvider` adds explicit constructor dependencies and cleanup:

```python
provider = FastAPIHandlerProvider(
    {
        ProfileServices: services,
        "settings": settings,
    }
)
```

For a registered class, it resolves constructor parameters by evaluated type
annotation from this mapping. A parameter default remains usable when no
explicit dependency exists. Missing required dependencies raise `TypeError`
during dispatch; the command/query caller receives that failure through the
normal reply path.

This is intentionally not FastAPI `Depends` resolution. Handler constructors do
not receive route request scope, `Request`, dependency overrides, or yield
dependencies automatically. Put app-safe dependencies in the explicit mapping
or register app resources.

### Dispatch-scoped ownership

Registered classes and factory results are created for each handler invocation.
After `handle()` completes or fails, the provider calls `aclose()` when present,
otherwise `close()`, and awaits the result if necessary. A registered ready
instance is externally owned and is not closed per dispatch.

Each event handler invocation has its own provider scope. It can outlive the HTTP
route that published the event, so handler dependencies must be app-safe or
owned by that event dispatch scope, never borrowed from a route dependency.

### App resources

Register long-lived resources before lifespan starts:

```python
provider.register_app_resource(DatabaseClient, database)
```

The key is available as a constructor annotation identity for a required
parameter. App resources do not override a parameter that already has a default;
put the resource in the constructor dependency mapping when that override is
required. If a registered handler target itself is used as an app-resource key,
the provider returns that resource as the handler and does not close it per
dispatch.

At provider shutdown, app resources close in reverse registration order through
`aclose()` or `close()`. Every resource is attempted, and the first ordinary
failure is re-raised. The provider first waits for active handler scopes. If the
deadline expires or shutdown is cancelled, the provider becomes closed and
schedules deferred cleanup after active scopes finish; new scopes and
registrations are rejected.

One provider can bind to only one app object.

## Event Completion in Routes and Tests

The command in the complete example returns after `ProfileCreated` is enqueued,
not after `ObserveProfileCreated` runs. The route can therefore return before
`services.observed` changes.

`EventBus.drain()` waits for tracked handler tasks within its budget, but it is
not a barrier for events still waiting in the transport queue. On timeout it
requests cancellation and returns rather than raising `TimeoutError`; resistant
handlers can remain active. A deterministic async test should wait for an
application signal first:

```python
await asyncio.wait_for(services.event_seen.wait(), timeout=1)
await app.state.cqrs_buses.event_bus.drain(timeout=1)
assert services.observed == [1]
```

FastAPI's test client must enter application lifespan. For example, the public
`TestClient` context starts and stops it:

```text
uv add --dev httpx
```

```python
from fastapi.testclient import TestClient


def test_profile_route() -> None:
    with TestClient(app) as client:
        response = client.post("/profiles", params={"username": "alice"})
        assert response.status_code == 200
```

For async HTTP clients, use a lifespan manager or explicitly enter the
application lifespan around the client; HTTPX's ASGI transport alone does not
start FastAPI lifespan.

## Transport Customization

Pass three distinct public `Transport` implementations to the adapter:

```python
adapter = FastAPIAdapter(
    command_transport=command_transport,
    query_transport=query_transport,
    event_transport=event_transport,
    provider=provider,
    event_error_handler=report_event_failure,
    shutdown_timeout=10,
)
```

Omitted transports become separate `InMemoryTransport` instances. The core
requires distinct identities. The event error hook can be sync or async and has
the same `EventHandlerFailure` contract as standalone core.

Transport timeouts passed to `execute()` or `publish()` retain core semantics.
In particular, a request timeout means the caller stopped waiting; a handler
that already started is not cancelled and can still change state.

## Boundaries

The FastAPI adapter does not generate routes, scan packages, solve FastAPI
dependencies for handlers, persist state, retry messages, propagate route
request scope into event tasks, or provide durable event delivery. Its included
transport remains process-local and at-most-once. Transactions, idempotency,
outbox publication, and production broker guarantees remain explicit
application or adapter concerns.

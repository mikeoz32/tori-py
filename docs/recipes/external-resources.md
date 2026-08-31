# External Resources

Use normal Python context-manager protocols to tell Tori Py who opens and closes
an external resource. Provider scope decides the owner: the application owns
singleton resources, while one request or work scope owns request and transient
resources resolved inside it.

## Singleton client resource

This example represents an external SDK client without tying the recipe to a
particular library:

```python
from types import TracebackType
from typing import Protocol, Self

from tori_py import ClassProvider, module


class RemoteClient(Protocol):
    async def fetch(self, key: str) -> bytes: ...


class ManagedRemoteClient:
    def __init__(self) -> None:
        self._opened = False

    async def __aenter__(self) -> Self:
        # Open the SDK connection or pool here.
        self._opened = True
        return self

    async def __aexit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # Close it even when startup later fails.
        self._opened = False

    async def fetch(self, key: str) -> bytes:
        if not self._opened:
            raise RuntimeError("client is closed")
        return key.encode()


@module(
    providers=[ClassProvider(RemoteClient, ManagedRemoteClient)],
    exports=[RemoteClient],
)
class RemoteClientModule:
    pass
```

`ClassProvider` and `FactoryProvider` use `manage=True` by default. When their
value is a sync or async context manager, Tori Py enters it before injection and
injects the value returned by `__enter__` or `__aenter__`. The manager object is
retained privately for cleanup.

Singleton providers are eagerly constructed during application startup. The
client therefore opens before request admission, and a failure prevents
readiness. It closes during startup rollback or normal shutdown in reverse
resource-acquisition order.

## Request-owned operation resource

Use a request-scoped factory when every HTTP, CQRS, message, or explicit work
scope needs an independent operation resource:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from tori_py import FactoryProvider, Scope, module


class OperationSession:
    def __init__(self, client: RemoteClient) -> None:
        self.client = client
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@asynccontextmanager
async def operation_session(
    client: RemoteClient,
) -> AsyncIterator[OperationSession]:
    session = OperationSession(client)
    try:
        yield session
    finally:
        await session.close()


@module(
    imports=[RemoteClientModule],
    providers=[
        FactoryProvider(
            OperationSession,
            operation_session,
            scope=Scope.REQUEST,
        )
    ],
    exports=[OperationSession],
)
class OperationModule:
    pass
```

The factory is invoked only if the scope resolves `OperationSession`. Within one
scope the request-scoped value is cached; a later scope gets another value. The
session closes after the complete pipeline and response execution for that
request. For CQRS, microservices, and stream handlers, it closes before the
integration reports invocation success, settlement, or checkpoint eligibility.

A singleton must not inject `OperationSession`; graph compilation rejects the
scope path. If a singleton coordinates non-request work, inject
`WorkScopeFactory` and resolve `OperationSession` inside `run()`.

## Existing external values

`ValueProvider` is externally owned by default:

```python
from tori_py import ValueProvider


existing_client = ManagedRemoteClient()
provider = ValueProvider(RemoteClient, existing_client)
```

Tori Py will neither enter nor close this value. The code that created it must
coordinate startup and shutdown. Use `manage=True` only when transferring
ownership to this application is deliberate:

```python
provider = ValueProvider(RemoteClient, existing_client, manage=True)
```

Do not register the same resource as managed through more than one token. Use an
`AliasProvider` for another token; aliases never own cleanup independently.

## Lifecycle details

- `NestApplication.create()` compiles declarations but opens no resources.
- `application.start()` constructs singleton providers, enters resources, runs
  hooks, and opens admission in deterministic order.
- Partial acquisition failure immediately unwinds resources already entered by
  that scope.
- Async context managers execute in the event loop. Sync `__enter__` and
  `__exit__` execute in a framework-owned executor so they do not block the event
  loop.
- Sync resource thread affinity is not guaranteed. Wrap thread-affine libraries
  in an application-owned async adapter.
- Resource exits receive the active body exception. A truthy suppression result
  is invalid; managed providers do not suppress failures.
- All exits are attempted. `ScopeFinalizationError` or
  `ScopeCancellationError` retains primary and cleanup failures.
- Shutdown has a shared finite deadline. A resource that ignores cancellation
  can remain open and be reported as lingering; Tori Py does not start unbounded
  cleanup after the deadline.

## SQLAlchemy boundary

Use `SqlAlchemyModule.for_root()` when the integration should create and dispose
an engine. Use `for_engine()` for an external engine; the integration will not
dispose it. Both forms provide one singleton session factory and one singleton
`EntityManager`, but no `AsyncSession` provider.

Each standalone manager or repository operation opens, commits or rolls back,
and closes its own session. An explicit same-task `EntityManager.transaction()`
provides a narrow atomic boundary and same-task nesting uses savepoints. Child
tasks are rejected rather than sharing an inherited unsafe session. The
application still owns its async driver, models, migrations, and database policy.

## Testing resources

Test both ownership and behavior:

- Replace the exported `RemoteClient` token with `use_value(fake)` for an
  externally owned fake and assert application behavior without expecting enter
  or exit calls.
- Compile with a managed recording implementation when testing startup,
  rollback, reverse cleanup order, or cancellation.
- Issue multiple requests to prove each request-owned resource is distinct and
  closes once after response completion.
- Force a later singleton startup failure and assert an earlier client closed.
- Always close `TestingApplication` in `finally`; its HTTP client does not own
  application lifespan.

Real infrastructure tests remain necessary for connection limits, TLS,
credentials, driver cancellation, server outages, and cleanup under network
failure. A managed fake proves the Tori Py ownership contract, not the external
system's behavior.

# CQRS with ToriPy

`tori-py-cqrs` integrates the framework-neutral buses with ToriPy modules,
constructor injection, provider visibility, scopes, managed resources,
application lifecycle, discovery, and invocation interceptors.

## Installation

```text
uv add tori-py-cqrs
```

This installs `tori-py-cqrs-core` and `tori-py-framework` as dependencies. The
integration itself does not depend on Starlette, FastAPI, Pydantic, SQLAlchemy,
or a persistence package.

## Discovered Handler Setup

ToriPy-native handler decorators combine CQRS metadata with ToriPy injectable
metadata. Register the decorated classes once as providers; `CqrsModule` finds
them in the compiled graph.

```python
import asyncio
from dataclasses import dataclass

from tori_py import Scope, injectable, module
from tori_py_cqrs import CqrsModule, command_handler, event_handler, query_handler
from tori_py_cqrs_core import Command, CommandBus, Event, EventBus, Query, QueryBus


@dataclass(frozen=True, slots=True)
class Increment(Command[int]):
    amount: int


@dataclass(frozen=True, slots=True)
class CurrentTotal(Query[int]):
    pass


@dataclass(frozen=True, slots=True)
class Incremented(Event):
    amount: int


@injectable()
class Counter:
    def __init__(self) -> None:
        self.total = 0
        self.observed: list[int] = []
        self.event_seen = asyncio.Event()


@command_handler(Increment, scope=Scope.REQUEST)
class IncrementHandler:
    def __init__(self, counter: Counter, events: EventBus) -> None:
        self._counter = counter
        self._events = events

    async def handle(self, command: Increment) -> int:
        self._counter.total += command.amount
        await self._events.publish(Incremented(command.amount))
        return self._counter.total


@query_handler(CurrentTotal, scope=Scope.TRANSIENT)
class CurrentTotalHandler:
    def __init__(self, counter: Counter) -> None:
        self._counter = counter

    async def handle(self, query: CurrentTotal) -> int:
        del query
        return self._counter.total


@event_handler(Incremented, scope=Scope.REQUEST)
class RecordIncrement:
    def __init__(self, counter: Counter) -> None:
        self._counter = counter

    async def handle(self, event: Incremented) -> None:
        self._counter.observed.append(event.amount)
        self._counter.event_seen.set()


@module(
    providers=[
        Counter,
        IncrementHandler,
        CurrentTotalHandler,
        RecordIncrement,
    ]
)
class CounterModule:
    pass


cqrs_module = CqrsModule.for_root(global_=True)


@module(imports=[cqrs_module, CounterModule])
class AppModule:
    pass
```

The handlers remain private to `CounterModule`; discovery examines providers in
the complete compiled graph, so they do not need to be exported to the CQRS
module. Decorators never add provider declarations by themselves, and discovery
never scans Python packages.

Resolve or inject the exported buses normally:

```python
commands = await application.resolve(CommandBus)
queries = await application.resolve(QueryBus)
events = await application.resolve(EventBus)

assert await commands.execute(Increment(3)) == 3
assert await queries.execute(CurrentTotal()) == 3
```

`CqrsModule.for_root()` exports `CqrsBuses`, `CommandBus`, `QueryBus`, and
`EventBus`. It is not global unless `global_=True` is selected. Without global
visibility, import the CQRS descriptor into every module that needs its exports
according to normal ToriPy visibility rules.

## Handler Decorators and Scopes

The public decorators are:

```text
@command_handler(MessageType, scope=Scope.SINGLETON, manage=True)
@query_handler(MessageType, scope=Scope.SINGLETON, manage=True)
@event_handler(MessageType, scope=Scope.SINGLETON, manage=True)
```

Their default is a managed singleton because that is ToriPy's provider default.
Choose a scope deliberately:

| Scope | CQRS behavior |
| --- | --- |
| `Scope.SINGLETON` | One application instance is reused across invocation work scopes |
| `Scope.REQUEST` | One instance is created in each CQRS handler invocation scope |
| `Scope.TRANSIENT` | A new instance is created for each resolution in that invocation |

"Request" means a ToriPy work scope for one CQRS invocation. It is not the
surrounding HTTP request. The integration runs each dispatch in a fresh
context-variable context; ambient HTTP request context is not propagated.

Every command handler and query handler gets one independent work scope. Every
individual event handler gets its own independent work scope, even when several
handlers receive the same event. Request and transient resources close after the
handler and interceptors finish, including failure and cancellation paths.

A class handler must expose `async handle(message)`. Function handlers from the
core `@handles` API are not supported by the ToriPy integration.

## Discovery Rules

At application composition, `CqrsModule` uses ToriPy's compiled provider views:

- directly decorated class and value provider implementations are eligible;
- private providers are eligible;
- aliases of one canonical provider do not create duplicate event deliveries;
- keyed dynamic-module providers remain distinct by canonical provider identity;
- testing overrides are evaluated from the final compiled implementation;
- a factory provider with no statically known decorated implementation is not
  auto-discovered;
- an explicit binding suppresses discovery of the same canonical provider.

Commands and queries still permit one exact handler. Multiple discovered
providers for the same command or query fail graph assembly. Events preserve
compiled registration/scheduling order, but each handler is scheduled
independently and start/completion order is not guaranteed.

## Explicit Bindings

Explicit bindings are the escape hatch for undecorated providers, factory
providers, string tokens, or deliberate selection:

```python
from tori_py import ClassProvider, Scope, module
from tori_py_cqrs import CqrsModule, bind_command_handler


class IncrementHandler:
    async def handle(self, command: Increment) -> int:
        return command.amount


@module(
    providers=[ClassProvider("increment-handler", IncrementHandler, scope=Scope.REQUEST)],
    exports=["increment-handler"],
)
class HandlerModule:
    pass


cqrs_module = CqrsModule.for_root(
    imports=[HandlerModule],
    handlers=[bind_command_handler(Increment, "increment-handler")],
    key="counter",
)
```

The configured token must be visible from the CQRS dynamic module, so a provider
owned by an imported module must be exported. The integration creates a private
alias but resolves the canonical provider in its exact owner module, preserving
the provider's original scope and resource ownership.

Use `bind_query_handler()` and `bind_event_handler()` for the other categories.
Multiple event bindings are invoked in declaration order for scheduling.
Binding the same event and provider identity twice is rejected.

`key` qualifies the dynamic module identity. When several CQRS graphs are
present, resolve buses with the exact module descriptor rather than relying on
an ambiguous unqualified token.

## Handler Invocation Pipeline

ToriPy CQRS interceptors wrap one handler invocation without adding HTTP or
persistence semantics to the core integration.

```python
from tori_py import Scope, injectable
from tori_py_cqrs import CqrsInvocationContext, CqrsNext, use_cqrs_interceptors


@injectable(scope=Scope.REQUEST)
class TraceInvocation:
    async def intercept(
        self,
        context: CqrsInvocationContext,
        next: CqrsNext,
    ) -> object:
        print(context.handler_kind, context.envelope.message_id)
        result = await next()
        print("completed", context.metadata["handler"])
        return result


@use_cqrs_interceptors(TraceInvocation)
@command_handler(Increment, scope=Scope.REQUEST)
class TracedIncrementHandler:
    async def handle(self, command: Increment) -> int:
        return command.amount
```

Provider-backed interceptors resolve lazily in the same work scope and through
the exact handler-owner module's visibility. List their provider declarations in
that module. A direct interceptor instance is externally owned: ToriPy does not
inject into it or manage its lifecycle.

`CqrsInvocationContext` implements ToriPy `ExecutionContext` and exposes:

- `execution_kind == "cqrs"`;
- application and string module identities;
- `route_id=None` and `request_id=None`;
- the exact `owner_module` and canonical `handler_ref`;
- the current message, envelope, handler kind, and dispatch context;
- the invocation's `ScopedResolver`;
- immutable logging metadata;
- invocation completion and handler-exit registration APIs.

It deliberately has no HTTP request or request ID.

### Ordering and phases

An interceptor binding has `OUTER`, `GRAPH`, or `HANDLER` phase:

```python
from tori_py_cqrs import CqrsInterceptorBinding, CqrsInterceptorPhase
from tori_py_cqrs_core import HandlerKind


binding = CqrsInterceptorBinding(
    TraceInvocation,
    CqrsInterceptorPhase.OUTER,
    handler_kinds=(HandlerKind.COMMAND,),
)
```

For one handler, execution order is:

1. Handler-declared or explicit-binding `OUTER` interceptors.
2. Graph interceptors from the matching `CqrsModuleOptions` list.
3. Handler-declared or explicit-binding `GRAPH` interceptors.
4. Handler-declared or explicit-binding `HANDLER` interceptors.
5. The handler terminal.

Unwinding occurs in reverse. `use_cqrs_interceptors()` defaults to `HANDLER`.
`CqrsModuleOptions.command_interceptors`, `query_interceptors`, and
`event_interceptors` accept graph-phase bindings or shorthand tokens/instances.
An optional `handler_kinds` restriction is validated during graph assembly.

Every `next` callback is one-shot. Calling it twice raises
`CqrsPipelineStateError`, even if the first call already ran the handler. An
interceptor may short-circuit by returning without calling `next()`; later
interceptors and the handler remain unresolved.

### Handler exit and post-scope completion

`context.on_handler_exit(callback)` registers a synchronous callback for the
exact handler terminal boundary. Callbacks run in reverse order immediately
after handler invocation or failure and before inner interceptors resume. All
callbacks are attempted; callback failures are retained without losing a
handler failure, and cancellation remains cancellation.

Advanced integrations can register a synchronous mapper through
`context.completion.register(key, mapper)`. Mappers run in reverse registration
order only after all scoped resources close. Each receives `CqrsScopeCompletion`
with result availability, handler/body error, and any ToriPy scope finalization
error. A mapper may transform an error or introduce a post-scope error, but it
cannot suppress an existing error, be async, register twice under one key, or
register after the pipeline freezes.

Most applications should use ordinary interceptors. The completion contract
exists so packages such as `tori-py-cqrs-event-sourcing` can preserve a confirmed
commit when later resource cleanup fails.

## Transport Configuration

Defaults are three distinct `InMemoryTransport` instances. Override them with
sync or async factories:

```python
from tori_py_cqrs import CqrsModule, CqrsModuleOptions
from tori_py_cqrs_core import InMemoryTransport


options = CqrsModuleOptions(
    command_transport_factory=lambda: InMemoryTransport(name="app-command"),
    query_transport_factory=lambda: InMemoryTransport(name="app-query"),
    event_transport_factory=lambda: InMemoryTransport(name="app-event"),
    event_error_handler=report_event_failure,
)

cqrs_module = CqrsModule.for_root(options=options, global_=True)
```

Every factory must return an object satisfying the public core `Transport`
protocol. The three returned identities must be distinct. The runtime owns them
as soon as they are acquired and closes acquired transports if a later factory,
registry build, or application bootstrap fails.

The event error hook receives application-facing provider identity. Explicit
bindings report the configured token; discovered handlers report a
module-qualified canonical provider identity rather than a private bridge
marker.

## Application Lifecycle

The CQRS runtime is an eager singleton lifecycle participant.

Startup order is deliberate:

1. Build the registry and acquire three transports.
2. Start event delivery.
3. Start query delivery.
4. Start command delivery.
5. Allow normal application request admission.

If startup fails, every attempted bus is shut down in reverse order. Acquired
but unstarted transports are also closed by managed-resource cleanup. Repeated
factory returns of one transport identity are closed once on assembly failure,
although sharing identities still causes the core builder to reject the graph.

During application quiescence, normal request admission is already closed but
work scopes remain available. The runtime uses one decreasing shutdown budget:

1. Stop and drain commands.
2. Stop and drain queries.
3. Stop and drain events and tracked event tasks.

With the default in-memory transports, this permits an accepted command to query
or publish before downstream buses stop, and permits an accepted query to
publish. It does not guarantee arbitrary nested dispatch cycles once a target
bus starts stopping.

That downstream-dispatch allowance depends on every configured transport
draining accepted work during shutdown. A custom `Transport` whose shutdown
abandons accepted work cannot provide the same guarantee.

## Dispatch from Handlers

Constructor injection can provide `QueryBus` and `EventBus` to command handlers.
Nested queries execute independently. Event publication is asynchronous and
non-durable; the command result does not imply event-handler completion.

Injecting `CommandBus` does not permit same-bus recursion. The core raises
`NestedCommandDispatchError` before enqueue while a handler from that bus is
active. A different command-bus instance remains independent and never shares
an implicit scope or transaction.

## Testing

`TestingModule.compile()` starts application lifecycle, so resolved buses are
ready:

```python
import asyncio

import pytest
from tori_py.testing import TestingModule
from tori_py_cqrs_core import CommandBus, EventBus


@pytest.mark.asyncio
async def test_increment() -> None:
    application = await TestingModule.create(AppModule).compile()
    try:
        commands = await application.resolve(CommandBus)
        events = await application.resolve(EventBus)
        counter = await application.resolve(Counter, module=CounterModule)

        assert await commands.execute(Increment(2)) == 2
        await asyncio.wait_for(counter.event_seen.wait(), timeout=1)
        await events.drain(timeout=1)
        assert counter.observed == [2]
    finally:
        await application.close()
```

`EventBus.drain()` is not a queue barrier. If the assertion depends on an event
effect, first await a bounded signal from the projection or handler proving the
transport dequeued the event, then drain tracked work with a sufficient budget.
The drain timeout requests cancellation and returns; it does not raise a timeout
or guarantee that cancellation-resistant code has stopped.

## Boundaries

The integration owns handler registration mapping, scope execution, interceptor
composition, and bus lifecycle coordination. ToriPy owns providers and resource
cleanup; CQRS core owns envelopes, routing, transport behavior, task tracking,
and reentrancy. Persistence, retries, brokers, outbox delivery, sagas, and HTTP
request-context propagation remain outside this package.

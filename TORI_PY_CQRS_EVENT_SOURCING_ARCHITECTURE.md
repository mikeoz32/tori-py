# ToriPy CQRS Event-Sourcing Integration Architecture

Status: NES0-NES5 implemented. Executable requirements are split into
`spec/tori-py-cqrs-event-sourcing/phase-nes0-*.md` through `phase-nes5-*.md`.

## 1. Purpose

`tori-py-cqrs-event-sourcing` is the optional integration layer that makes
`tori-py-cqrs-event-sourcing-core` feel native inside a ToriPy CQRS application. It removes
transaction control from command handlers while preserving the exact commit,
rollback, cancellation, cleanup, and indeterminate-outcome guarantees owned by
the framework-neutral event-sourcing package.

Repositories are explicit integration-layer classes:

```python
@aggregate_repository(Group, category="group", id_encoder=str)
class GroupRepository(EventSourcedRepository[int, Group]):
    pass
```

The intended command handler contains only application orchestration:

```python
@use_event_sourcing(key="community")
@command_handler(CreateGroup, scope=Scope.REQUEST)
class CreateGroupHandler:
    def __init__(
        self,
        groups: Annotated[
            GroupRepository,
            aggregate_repository(GroupRepository),
        ],
    ) -> None:
        self._groups = groups

    async def handle(self, command: CreateGroup) -> GroupView:
        group = Group(command.group_id)
        group.create(
            owner_id=command.actor_id,
            name=command.name,
            access=command.access,
        )
        self._groups.save(group)
        return GroupView.from_aggregate(group)
```

The handler does not inject `EventSourcingUnitOfWork`, call `commit()`, or own
transaction cleanup. The command result is not released by `CommandBus` until
the integration confirms persistence and closes the command work scope.

## 2. Goals

The first integration slice MUST provide:

- a standalone `tori-py-cqrs-event-sourcing` distribution;
- ToriPy dynamic-module configuration with `for_root()` and `for_feature()`;
- explicit, keyed EventStore, schema, repository, transaction-accessor, and
  synchronization providers with a coordinator-owned private UoW;
- request-scoped repositories bound to exactly one command transaction;
- a ToriPy-style CQRS invocation-interceptor extension point;
- explicit handler opt-in through `@use_event_sourcing()`;
- automatic commit after a successful command handler;
- explicit rollback after handler/provider failure before commit;
- typed preservation of confirmed commit, confirmed non-commit, and
  indeterminate outcomes;
- transaction synchronization callbacks for external side effects;
- exact ToriPy module visibility, provider scope, resource ownership, keyed
  graph, discovery, and testing-override semantics;
- migration of the large community example away from handler-owned UoW control.

## 3. Non-Goals

The first integration slice MUST NOT provide:

- an EventStore implementation other than consuming configured adapters;
- SQLAlchemy, PostgreSQL, Citus, Redis, RabbitMQ, FastAPI, Starlette, Pydantic,
  or serializer dependencies;
- package scanning or automatic provider declarations;
- a mutable process-global schema, aggregate, or repository registry;
- automatic commit for undecorated command handlers;
- automatic transactions for query or event handlers;
- transaction sharing across nested command dispatches;
- automatic publication of persisted events to `EventBus`;
- an outbox, inbox, command retry, command idempotency, saga, process manager,
  snapshot, or durable projection implementation;
- distributed transactions or transactional coordination with arbitrary
  external services;
- HTTP request-scope or identity propagation into CQRS work scopes.

## 4. Package Boundary

The dependency graph is one-way:

```text
tori-py-cqrs-event-sourcing -> tori-py-cqrs, tori_py,
                              tori-py-cqrs-event-sourcing-core, tori-py-cqrs-core
tori-py-cqrs                -> tori_py, tori-py-cqrs-core
tori-py-cqrs-event-sourcing-core        -> tori-py-cqrs-core
tori_py                     -> no CQRS or event-sourcing package
tori-py-cqrs-core                  -> no framework or event-sourcing package
```

Distribution and import names are:

```text
distribution: tori-py-cqrs-event-sourcing
import:       tori_py_cqrs_event_sourcing
```

The integration package owns composition only. Aggregate lifecycle, codecs,
repository behavior, EventStore protocols, exact expected versions, and commit
classification remain owned by `tori-py-cqrs-event-sourcing-core`. Handler routing,
discovery, transports, and bus lifecycle remain owned by `tori-py-cqrs` and
`tori-py-cqrs-core`. Provider visibility, scopes, resources, and application lifecycle
remain owned by ToriPy.

## 5. Required Foundation Changes

The integration MUST be built on public contracts rather than private imports.
Four prerequisite extensions are required.

### 5.1 ToriPy resource unwinding

ToriPy request-resource cleanup MUST become exception-aware. The current
resource stack calls every `__aexit__()` with `(None, None, None)` and can replace
an active handler error with an unrelated cleanup error. The required contract
is:

- the active body exception is supplied while resources unwind in LIFO order;
- `CancelledError`, `KeyboardInterrupt`, and `SystemExit` remain control-flow
  failures and are never converted to ordinary errors;
- every resource cleanup is attempted;
- cleanup failures are retained without losing the primary body exception;
- the work-scope owner can observe body and collected cleanup failures after all
  command-scoped resources close;
- cleanup after a confirmed commit can be reported as confirmed-commit
  finalization failure rather than as a retryable rollback.

Managed provider resources do not suppress body exceptions: a truthy
`__aexit__()` result is an invalid resource result. Every exit receives the
original body exception tuple. Ordinary cleanup failures are collected while all
remaining exits run. ToriPy then raises `ScopeFinalizationError`, carrying the
original ordinary body error when present plus an ordered tuple of cleanup
errors. If the primary failure is `CancelledError`, ToriPy raises
`ScopeCancellationError`, a `CancelledError` subtype carrying the original
cancellation and cleanup errors. `KeyboardInterrupt` and `SystemExit` remain the
same objects; cleanup failures are logged and attached as notes.

### 5.2 ToriPy CQRS invocation interceptors

`tori-py-cqrs` MUST expose a driver-neutral invocation pipeline. Its shape follows
ToriPy interceptors without reusing HTTP `PipelineResult`:

```python
type CqrsNext = Callable[[], Awaitable[object]]


class CqrsInvocationInterceptor(Protocol):
    async def intercept(
        self,
        context: CqrsInvocationContext,
        next: CqrsNext,
    ) -> object: ...
```

`CqrsInvocationContext` MUST implement ToriPy `ExecutionContext` and expose:

- `execution_kind == "cqrs"`;
- `application_id` from the ToriPy application kernel;
- the handler-owner string label as `module_id`;
- `route_id is None` and `request_id is None`;
- the exact `DispatchContext`, message, envelope, and `HandlerKind`;
- separate exact `handler_ref: ProviderRef` and `owner_module: ModuleId`
  properties without overloading the string `module_id` contract;
- the invocation `ScopedResolver`;
- the invocation's `completion: CqrsInvocationCompletion`;
- immutable metadata suitable for logging and tracing;
- no HTTP request object or ambient HTTP context.

The `next` callback is one-shot. Calling it twice raises a typed
`CqrsPipelineStateError`. Provider-backed interceptors resolve in the same work
scope and exact owner-module visibility context as the handler. Direct
interceptor instances are externally owned and receive no DI or lifecycle
management.

Interceptor order is:

1. outer/system handler bindings such as `@use_event_sourcing()`;
2. CQRS-graph command/query/event interceptors;
3. normal handler-class interceptors in declaration order;
4. the handler terminal.

Unwinding occurs in reverse order. Every provider-backed interceptor is resolved
lazily immediately before its own invocation; the handler terminal is also
resolved lazily. The event-sourcing transaction resource therefore enters before
graph interceptors, handler interceptors, handler construction, and all of their
request-scoped dependencies.

`tori-py-cqrs` MUST preserve an invocation completion record across work-scope
closure. This permits an interceptor to classify a later scoped-resource cleanup
failure using an already confirmed persistence outcome without coupling
`tori-py-cqrs` to event sourcing.

The public handoff is:

```python
type CqrsCompletionMapper = Callable[
    [CqrsScopeCompletion, BaseException | None],
    BaseException | None,
]


class CqrsInvocationCompletion:
    def register(self, key: str, mapper: CqrsCompletionMapper) -> None: ...
```

`CqrsScopeCompletion` is an immutable value with `result: object | None`,
`result_available: bool`, `body_error: BaseException | None`, and
`scope_error: ScopeFinalizationError | ScopeCancellationError | None`.
Registration keys are
unique, registration is allowed only before the interceptor chain returns, and
the record then freezes. Mappers are synchronous, externally pure callbacks;
they cannot resolve providers or perform cleanup. The work-scope owner invokes
them in reverse registration order after every resource has closed. The initial
current error is `scope_error` when present, otherwise `body_error`. Each mapper
receives that current error and returns the error passed to the next mapper. It
MUST NOT return `None` when its input error is non-None; completion mappers cannot
suppress failures. A mapper may return a new error when the current error is
`None`, such as for a transaction finalization failure. The event-sourcing
interceptor registers one mapper before `next()` and
captures a mutable transaction outcome record that it finalizes before scope
closure.

Interceptor bindings use explicit phases:

```python
class CqrsInterceptorPhase(StrEnum):
    OUTER = "outer"
    GRAPH = "graph"
    HANDLER = "handler"


@dataclass(frozen=True, slots=True)
class CqrsInterceptorBinding:
    interceptor: Token | CqrsInvocationInterceptor
    phase: CqrsInterceptorPhase
    handler_kinds: tuple[HandlerKind, ...] | None = None
```

`CqrsModuleOptions.command_interceptors`, `query_interceptors`, and
`event_interceptors` accept graph-phase bindings. `use_cqrs_interceptors(*items,
phase=HANDLER)` composes repeated direct decorators in visible decorator order;
argument order within one decorator is execution order. A binding with
`handler_kinds` is rejected during graph assembly when attached to another
handler kind, before any interceptor provider or UoW is resolved. Explicit
`bind_command_handler(..., interceptors=...)` accepts bindings with any phase, which
is how a factory handler selects the event-sourcing `OUTER` binding.

`CqrsInvocationContext.on_handler_exit(callback)` registers synchronous terminal
callbacks. The terminal invokes them in reverse registration order immediately
after handler construction/invocation returns or fails, before inner interceptors
resume. Every callback is attempted. Callback failures are retained as secondary
errors; they never replace a primary handler failure, and callback cancellation
remains cancellation.

Factory-produced handlers have no statically inspectable class metadata.
Transactional factory handlers MUST use an explicit CQRS binding with interceptor
metadata, for example `bind_command_handler(..., interceptors=[CqrsInterceptorBinding(
transaction_token, CqrsInterceptorPhase.OUTER,
handler_kinds=(HandlerKind.COMMAND,))])`. The event-sourcing package exposes this
as `event_sourcing_transaction(key=...)`.
Class decorator metadata is supported only when the final compiled class provider
has a statically known implementation.

### 5.3 Event-sourcing outcome inspection

`EventSourcingUnitOfWork` MUST expose a read-only typed outcome after finalization:

```python
type UnitOfWorkOutcome = (
    ConfirmedCommit
    | ConfirmedNonCommit
    | IndeterminateCommit
)
```

`ConfirmedCommit` carries `CommitResult`. `ConfirmedNonCommit` carries the cause
when one exists. `IndeterminateCommit` carries the original cause. Active,
committing, and not-yet-finalized states are not successful outcomes and cannot
be mistaken for one.

The integration MUST use this contract rather than infer durable outcome from a
catch-all exception list. Malformed commit results and unknown failures after
commit begins are indeterminate. A validated `CommitResult` remains confirmed
even if synchronization or cleanup later fails.

`EventSourcedRepository` additionally accepts an optional framework-neutral
operation lease. Every public load/save operation checks that lease before using
its retained UoW. The integration lease permits access only from the owning
handler task while the handler body is active. Child tasks, callbacks, escaped
repository instances, queries, events, and code running after handler return fail
with `CommandTransactionUnavailableError`.

### 5.4 Command reentrancy

`tori-py-cqrs-core` MUST reject same-bus nested command execution before transport
enqueue. The dispatcher marks the active command-bus identity in invocation-local
context; `CommandBus.execute()` compares its own identity and raises core-owned
`NestedCommandDispatchError`. Function and class handlers observe the same rule.
Different command buses do not share transactions and remain independent.

## 6. Dynamic Module API

### 6.1 Root configuration

```python
@dataclass(frozen=True, slots=True)
class CqrsEventSourcingOptions:
    store: Token
    schemas: EventSchemaRegistry
    unit_of_work_factory: UnitOfWorkFactory = default_unit_of_work_factory


class CqrsEventSourcingModule:
    @classmethod
    def for_root(
        cls,
        options: CqrsEventSourcingOptions,
        *,
        imports: Iterable[ModuleImport] = (),
        key: str = "default",
    ) -> DeferredModule: ...
```

The configured `store` is a visible ToriPy provider token, not an object opened
by the dynamic-module materializer. This permits normal settings, pool,
lifecycle, and testing-override composition. `schemas` is already explicit and
frozen; `for_root()` rejects an unfrozen registry during graph materialization.

`UnitOfWorkFactory` is exactly a sync-or-async callable receiving the resolved
`EventStore` and returning one unentered `EventSourcingUnitOfWork`:

```python
type UnitOfWorkFactory = Callable[
    [EventStore],
    EventSourcingUnitOfWork | Awaitable[EventSourcingUnitOfWork],
]
```

It is immutable module configuration, not an injectable provider. The
transaction coordinator invokes it once per decorated command, validates the
result, and owns enter/exit. Tests configure a root descriptor with a fake
factory before compilation or override the exported EventStore provider.

The root is global by design, analogous to NestJS TypeORM's global core module.
Application/root composition imports each configured keyed root exactly once.
Submodules do not import it. Root exports only keyed infrastructure tokens, so
multiple roots cannot introduce unqualified global ambiguity.

One root module owns:

- direct framework-neutral `EventStore` resolution or a local alias to the
  configured store token when the tokens differ;
- one frozen schema registry;
- one request-scoped command transaction coordinator;
- one request-scoped private transaction accessor exported only for feature
  provider construction;
- one request-scoped `CommandSynchronization` provider;
- one event-sourcing CQRS interceptor provider;
- deterministic keyed aliases and exports.

The UoW is created inside the coordinator and is never a ToriPy provider or DI
token. The transaction coordinator token is a private implementation detail and
is not exported for application injection.

When `options.store` is the root's keyed store token, root re-exports that
imported provider without creating an alias. When it is `EventStore`, root adds
only the keyed alias. For any other token it creates the local
`EventStore -> options.store -> keyed store` chain. This avoids valid-token
self-alias cycles while preserving deterministic keyed exports.

### 6.2 Feature configuration

```python
community_repositories = CqrsEventSourcingModule.for_feature(
    [
        MemberRepository,
        GroupRepository,
        PostRepository,
    ],
    root_key="community",
    key="community-model",
)
```

`for_feature()` follows the TypeORM feature-module shape: it never receives or
imports the root `DeferredModule`. It selects globally visible infrastructure
only through deterministic tokens qualified by `root_key`. The resulting module
contains repository providers and repository exports only. If the selected root
is not present in the compiled application graph, repository dependencies fail
normal graph compilation as unresolved providers.

```python
class CqrsEventSourcingModule:
    @classmethod
    def for_feature(
        cls,
        repositories: Iterable[type[EventSourcedRepository]],
        *,
        root_key: str = "default",
        key: str | None = None,
    ) -> DeferredModule: ...
```

Each `for_feature()` call creates a fresh private feature-module class. This is the
ToriPy-native equivalent of NestJS dynamic-module metadata identity: independent
submodules may call `for_feature()` with identical repository sets without
descriptor conflicts or a mutable registry. `root_key` and optional `key` remain
diagnostic labels; provider linkage uses only deterministic keyed root tokens.

Feature registration is explicit. There is no package scan and no integration
decorator on domain aggregate classes. Keeping aggregates free of ToriPy imports
is more important than copying an ORM-style `@Entity` decorator. Repository
classes belong to the integration/infrastructure layer and carry their own
declaration metadata:

```python
@aggregate_repository(
    Member,
    category="member",
    id_encoder=str,
    aggregate_factory=Member,
    page_size=None,
)
class MemberRepository(EventSourcedRepository[int, Member]):
    async def find_by_handle(self, handle: str) -> Member | None:
        ...
```

The decorator requires a concrete `EventSourcedRepository` subclass and attaches
immutable direct metadata through ToriPy reflection. It supplies
`id_encoder=str` and `aggregate_factory=aggregate_type` by default. It does not
register the class as a provider; `for_feature()` performs explicit registration.
`for_feature()` reads this metadata through ToriPy `Reflector` while creating the
provider declarations. Inherited metadata is not accepted silently. Duplicate
repository classes or provider tokens within one feature module fail before
compilation. Discovery may validate the resulting compiled provider graph, but
cannot create repository providers after compilation.

### 6.3 Tokens and injection

Runtime generic specialization is not a valid DI token. The package exposes
deterministic token helpers:

```python
get_event_store_token(key="default")
get_schema_registry_token(key="default")
get_command_synchronization_token(key="default")
get_transaction_interceptor_token(key="default")
```

`aggregate_repository()` is deliberately overloaded for the two related ToriPy
declaration sites:

```python
@aggregate_repository(Member, category="member")
class MemberRepository(EventSourcedRepository[int, Member]):
    pass


members: Annotated[
    MemberRepository,
    aggregate_repository(MemberRepository),
]
```

When called with an aggregate plus repository options, it returns the class
decorator. When called with an already decorated repository class and no options,
it returns the standard ToriPy `Inject(MemberRepository)` marker. It is not a
second injection system. Passing an undecorated class or mixing the two call
forms is an immediate configuration error.

The repository class itself is the provider token. ToriPy module qualification
keeps the same token in different feature modules distinct. A handler that needs
two configurations of one logical repository declares two repository subclasses
instead of relying on a hidden key lookup.

The core repository checks its lease on every base load/save operation. A custom
repository method MUST either compose only those guarded base operations or call
the protected `self._require_operation_lease()` before touching retained
transaction/aggregate state. The decorator does not dynamically wrap arbitrary
methods. Violating this rule is an application repository bug and is covered by
custom-repository contract tests.

For example:

```python
members: Annotated[
    MemberRepository,
    aggregate_repository(MemberRepository),
]
```

Repository class tokens and generated keyed root tokens are exported so
`TestingModule.override_provider()` can target the exact root or feature
dynamic-module descriptor. Root infrastructure is never exported globally under
unqualified EventStore, schema-registry, or synchronization tokens.

Repository providers do not inject the private UoW token directly. They resolve
an invocation-local transaction accessor which is activated by the outer
event-sourcing interceptor before the handler terminal. The accessor returns the
current UoW only while that decorated command is active. Consequently, resolving
a repository from a query, event handler, undecorated command, or background task
fails without opening an implicit transaction.

## 7. Transactional Handler API

### 7.1 Explicit opt-in

```python
@use_event_sourcing(key="community")
@command_handler(PublishPost, scope=Scope.REQUEST)
class PublishPostHandler:
    ...
```

`@use_event_sourcing()` is a convenience over the public
`@use_cqrs_interceptors()` metadata API. It attaches the keyed transaction
interceptor token in the outer/system phase and does not register a provider.
Applying it to a query or event handler is a bootstrap-time
`CqrsEventSourcingConfigurationError`.

Undecorated command handlers retain current `tori-py-cqrs` behavior. Manual UoW
injection is not a compatibility mode offered by this package; an application
that requires manual control can use `tori-py-cqrs-event-sourcing-core` directly.

### 7.2 Command synchronization

Handlers that create an external side effect before EventStore commit can inject
`CommandSynchronization`:

```python
content_ref = content.put(command.body)
synchronization.after_confirmed_non_commit(
    lambda: content.erase(content_ref)
)
posts.save(post)
```

The public protocol is:

```python
type Finalizer = Callable[[], Awaitable[None] | None]
type CommitCallback = Callable[[CommitResult], Awaitable[None] | None]
type IndeterminateCallback = Callable[[BaseException], Awaitable[None] | None]


class CommandSynchronization(Protocol):
    def after_commit(self, callback: CommitCallback) -> None: ...
    def after_confirmed_non_commit(self, callback: Finalizer) -> None: ...
    def after_indeterminate(self, callback: IndeterminateCallback) -> None: ...
```

Confirmed-non-commit callbacks are compensations and run in reverse registration
order. Commit and indeterminate callbacks are notifications and run in
registration order. Every callback that raises an ordinary `Exception` is
recorded and the remaining callbacks are attempted. A control-flow exception
stops callback execution immediately. Callback registration closes
as soon as the handler returns or raises; late registration from a child task
raises `CommandSynchronizationStateError`.

Indeterminate callbacks MUST NOT perform destructive rollback compensation. They
schedule or record reconciliation only. The package cannot make arbitrary
external side effects atomic; production publication still requires a
transactional outbox.

## 8. Invocation Lifecycle

For one decorated command, execution is exactly:

```text
CommandBus transport delivery
  -> select exact canonical handler
  -> open one fresh ToriPy CQRS work scope
  -> resolve transaction interceptor in handler-owner visibility
  -> enter transaction coordinator and EventSourcingUnitOfWork
  -> install invocation-local synchronization state
  -> resolve handler and request-scoped repositories
  -> await handler.handle(command)
  -> close synchronization registration
  -> await UnitOfWork.commit()
  -> classify typed UnitOfWork outcome
  -> run matching synchronization callbacks
  -> retain the exact handler result
  -> unwind handler resources in LIFO order
  -> exit transaction coordinator and UnitOfWork last
  -> return the retained result from CommandBus
```

The transaction coordinator is entered before handler construction. Therefore
the UoW is the outermost command-scoped managed resource and closes after
handler dependencies. All repositories and the interceptor resolve the same
request-scoped UoW instance.

The UoW does not need to reinterpret arbitrary inner resource failures itself.
The work-scope owner closes every resource, then combines its
`ScopeFinalizationError`/`ScopeCancellationError` with the transaction completion
record retained by the coordinator. That final mapping produces the public
outcome-preserving command error after the complete scope has closed.

A handler returning normally means only that its decision completed. The command
does not succeed until commit, synchronization, and scope finalization complete.

## 9. Outcome Matrix

| Situation | Persistence outcome | Synchronization | Caller-visible result |
| --- | --- | --- | --- |
| Handler succeeds with staged events | Confirmed commit | `after_commit` | Exact handler result |
| Handler succeeds with no events | Confirmed empty commit | `after_commit` | Exact handler result |
| Handler/provider fails before commit | Confirmed non-commit after rollback | Compensation | Original error |
| Optimistic conflict | Confirmed non-commit | Compensation | Original conflict |
| Duplicate event ID | Confirmed non-commit | Compensation | Original duplicate error |
| Adapter-confirmed commit rejection | Confirmed non-commit | Compensation | Original error |
| Raw cancellation classified by store as rollback | Confirmed non-commit | Compensation | Cancellation |
| Ambiguous cancellation | Indeterminate | Reconciliation notification | Indeterminate error |
| Unknown failure after commit begins | Indeterminate | Reconciliation notification | Indeterminate error |
| Malformed commit result | Indeterminate | Reconciliation notification | Result mismatch error |
| Commit succeeds, callback fails | Confirmed commit | Remaining callbacks attempted | Confirmed finalization error |
| Commit succeeds, scoped cleanup fails | Confirmed commit | Already completed | Confirmed cleanup error |
| Handler fails and compensation fails | Confirmed non-commit | Remaining callbacks attempted | Outcome-preserving finalization error |

`ConfirmedCommandFinalizationError` has `commit_result`, `handler_result`,
`phase`, `primary_error`, and `secondary_errors`. The corresponding non-commit
and indeterminate errors have `outcome`, `primary_error`, `phase`, and
`secondary_errors`. All are ordinary `Exception` subclasses chained from the
primary ordinary failure. `CommandCancellationError` is a `CancelledError`
subtype carrying the typed persistence outcome, original cancellation, phase,
and secondary errors. A confirmed commit MUST never be surfaced as a plain
retryable rollback.

`phase` is `CommandFinalizationPhase`, with `HANDLER_ROLLBACK`,
`HANDLER_FINALIZATION`, `COMMIT`, `SYNCHRONIZATION`, `SCOPE_CLEANUP`, and
`UOW_CLEANUP` values.
`secondary_errors` is an occurrence-ordered `tuple[BaseException, ...]`.
`KeyboardInterrupt` and `SystemExit` are re-raised unchanged; the transaction
outcome and secondary failures are logged structurally and attached as notes,
because replacing process-control identity with an adapter type is prohibited.

## 10. Cancellation and Shutdown

Caller cancellation and handler cancellation are different facts.

After an in-memory transport accepts a command, cancellation or timeout of
`CommandBus.execute()` does not cancel the worker-owned handler. The handler may
still commit. The adapter MUST NOT interpret caller cancellation as rollback
evidence.

Handler cancellation before commit causes explicit rollback and confirmed
non-commit compensation. Cancellation during durable commit is classified only
by the EventStore/UoW contract: adapter-confirmed rollback remains a confirmed
non-commit; ambiguous acknowledgement becomes indeterminate.

The adapter owns no worker or independent shutdown hook. `tori-py-cqrs` stops
command intake and drains accepted work while ToriPy work scopes remain open. A
shutdown deadline cannot turn an unknown commit into a confirmed rollback.

## 11. Nested Dispatch

Nested query dispatch remains allowed but observes committed state only; it
cannot see the outer command's pending events. Event publication remains
non-transactional unless deferred through `after_commit`, and even then it is
not durable or atomic.

Dispatching another command through the same active `CommandBus` is rejected
before enqueue with core-owned `NestedCommandDispatchError`. The current single-worker
in-memory transport can otherwise deadlock and later execute a timed-out nested
command. A nested command never joins or shares the outer UoW. Cross-bus and
distributed transaction propagation are outside the first slice.

## 12. Scope and Visibility Rules

- Every decorated command invocation receives one fresh request-scoped UoW.
- Queries, event handlers, and undecorated commands create no automatic UoW.
- Repository resolution outside an active decorated command raises
  `CommandTransactionUnavailableError`.
- A singleton handler cannot inject a request-scoped repository; ToriPy's normal
  scope-path validation rejects it. Transactional handlers using repositories
  should be request-scoped.
- Different event handlers continue to use independent work scopes.
- Different keyed roots have independent provider identities, UoWs,
  synchronization state, repositories, and interceptors. Applications may
  deliberately configure the same immutable registry or store object for more
  than one root.
- Private handlers remain discoverable, but their repository and interceptor
  tokens must be visible from the exact owner module.
- Testing overrides are evaluated against the final compiled provider graph.

## 13. Failure Types

The integration package defines only integration failures:

- `CqrsEventSourcingError`;
- `CqrsEventSourcingConfigurationError`;
- `CommandTransactionUnavailableError`;
- `CommandSynchronizationStateError`;
- `ConfirmedCommandFinalizationError`;
- `ConfirmedNonCommitFinalizationError`;
- `IndeterminateCommandFinalizationError`;
- `CommandCancellationError`.

Optimistic concurrency, duplicate IDs, codec failures, aggregate lifecycle
failures, commit mismatch, and indeterminate commit errors retain their original
`tori-py-cqrs-event-sourcing-core` types when no secondary finalization failure requires an
outcome-preserving wrapper. Control-flow exceptions are never converted to
ordinary adapter errors.

Configuration errors are detected before request admission whenever the final
provider declarations are statically knowable. This includes duplicate
repositories within one feature, invisible store/interceptor tokens, unfrozen
schemas, invalid handler kind, dynamic-module identity conflicts, scope
violations, and ambiguous unqualified exports.

## 14. Event Publication

EventStore persistence and `EventBus` delivery remain separate. The integration
MUST NOT publish `CommitResult.events` automatically.

Direct `EventBus.publish()` from a command can happen before persistence and is
therefore explicitly non-transactional. `after_commit` may enqueue an in-process
event only after confirmed commit, but a process crash can still lose delivery.
Production reliable delivery requires an outbox written by the EventStore
adapter in the same database transaction and a separate relay.

## 15. Complete Composition Example

```python
schemas = build_schemas()


@aggregate_repository(Member, category="member", id_encoder=str)
class MemberRepository(EventSourcedRepository[int, Member]):
    pass


@aggregate_repository(Group, category="group", id_encoder=str)
class GroupRepository(EventSourcedRepository[int, Group]):
    pass


@aggregate_repository(Post, category="post", id_encoder=str)
class PostRepository(EventSourcedRepository[int, Post]):
    pass


@module(
    providers=[ClassProvider(InMemoryEventStore)],
    exports=[InMemoryEventStore],
)
class PersistenceModule:
    pass


community_es = CqrsEventSourcingModule.for_root(
    CqrsEventSourcingOptions(
        store=InMemoryEventStore,
        schemas=schemas,
    ),
    imports=[PersistenceModule],
    key="community",
)

community_repositories = CqrsEventSourcingModule.for_feature(
    [
        MemberRepository,
        GroupRepository,
        PostRepository,
    ],
    root_key="community",
    key="community-model",
)


@module(
    imports=[community_repositories],
    providers=[
        CreateGroupHandler,
        PublishPostHandler,
    ],
)
class CommunityModule:
    pass


cqrs = CqrsModule.for_root(key="community", global_=True)


@module(imports=[community_es, CommunityModule, cqrs])
class AppModule:
    pass
```

The root descriptor is imported once by `AppModule`; `CommunityModule` imports
only its feature descriptor. Root descriptors still follow ToriPy's exact
identity/reuse rule. Feature registrations are independently composable because
each call owns a fresh private module identity.

## 16. Testing Contract

The package MUST verify:

- public API and dependency boundaries;
- wheel and source-distribution isolation;
- exact dynamic-module reuse, keys, imports, exports, and ambiguity behavior;
- root-once/submodule-feature composition and feature descriptors with no root
  import;
- independent feature modules for one root, missing-root compilation failure,
  and repeated identical feature registrations;
- decorated repository class tokens and testing overrides;
- one UoW enter/commit/exit per decorated command;
- no UoW for queries, events, or undecorated commands;
- single- and multi-aggregate atomic commits;
- exact handler-result retention after commit;
- no-op commit;
- provider/handler failure, cancellation, conflict, duplicate ID, malformed
  result, unknown commit failure, and indeterminate cancellation;
- callback ordering, callback failure, late registration, and compensation;
- cleanup failures before and after confirmed commit;
- caller cancellation while an accepted command later commits;
- same-bus nested command rejection before enqueue;
- nested query committed-state visibility;
- no automatic EventBus publication;
- private handler discovery, scope validation, multiple keyed roots, and no
  transaction state leakage under concurrent dispatch;
- migration of the large community example with unchanged privacy, moderation,
  projection, and concurrency behavior.

## 17. Implementation Order

1. NES0 establishes package boundaries and prerequisite public contracts.
2. NES1 verifies and consumes N8/C3/ES6/CQRS7 upstream foundations.
3. NES2 adds keyed root/feature modules and repository injection.
4. NES3 adds automatic command transactions and exact outcome handling.
5. NES4 adds synchronization, cancellation, nesting, and finalization hardening.
6. NES5 migrates the community example and completes release verification.

The executable phase contracts are under
`spec/tori-py-cqrs-event-sourcing/README.md`.

# Event Sourcing with ToriPy

`tori-py-cqrs-event-sourcing` adds explicit, opt-in event-store transactions to
ToriPy CQRS command handlers. It composes public ToriPy, CQRS, and framework-
neutral event-sourcing contracts; it does not add a database driver, serializer,
broker, or HTTP dependency.

## Installation

```text
uv add tori-py-cqrs-event-sourcing
```

The package requires Python 3.14 and installs its CQRS, event-sourcing core, and
ToriPy dependencies.

## What the Integration Owns

For an opted-in command, the integration:

- creates and enters one fresh `EventSourcingUnitOfWork`;
- makes request-scoped repositories resolve that exact transaction;
- commits automatically after a successful handler result;
- rolls back after provider or handler failure before commit;
- runs callbacks selected by the typed persistence outcome;
- closes handler resources and the UoW in the correct order;
- returns the exact handler result only after commit, synchronization, and scope
  finalization succeed;
- preserves confirmed, non-commit, indeterminate, cancellation, and cleanup
  facts in typed errors.

Queries, event handlers, and undecorated commands do not receive automatic
transactions. Handlers cannot inject the private transaction coordinator or
integration-owned UoW and do not call `commit()` themselves.

## Define a Repository

Aggregates remain framework-neutral. Repository classes belong to the ToriPy
infrastructure layer and carry explicit declaration metadata:

```python
from uuid import UUID

from tori_py_cqrs_event_sourcing import aggregate_repository
from tori_py_cqrs_event_sourcing_core import EventSourcedRepository


@aggregate_repository(
    Profile,
    category="profile",
    id_encoder=str,
)
class ProfileRepository(EventSourcedRepository[UUID, Profile]):
    pass
```

The declaration form accepts:

- one concrete `AggregateRoot` subclass;
- a stable non-empty category;
- an ID encoder, defaulting to `str`;
- an aggregate factory, defaulting to the aggregate class;
- an optional positive repository page size.

The decorated target must be a concrete `EventSourcedRepository` subclass. The
decorator attaches direct ToriPy reflection metadata but does not register a
provider. Inherited repository metadata is deliberately rejected. A subclass of
an already decorated repository cannot be redecorated as another repository;
derive each registered repository from `EventSourcedRepository` or from an
undecorated application base so that it owns its declaration metadata directly.

The same helper has an injection form for an already decorated repository:

```python
from typing import Annotated


profiles: Annotated[
    ProfileRepository,
    aggregate_repository(ProfileRepository),
]
```

This returns ToriPy's standard `Inject(ProfileRepository)` marker. It is not a
second dependency-injection system.

## Compose Root and Feature Modules

One keyed root owns store/schema infrastructure and transaction coordination.
Feature modules own explicit repository providers.

```python
from tori_py import ClassProvider, Scope, module
from tori_py_cqrs import CqrsModule
from tori_py_cqrs_event_sourcing import (
    CqrsEventSourcingModule,
    CqrsEventSourcingOptions,
)
from tori_py_cqrs_event_sourcing_core import InMemoryEventStore


@module(
    providers=[ClassProvider(InMemoryEventStore)],
    exports=[InMemoryEventStore],
)
class PersistenceModule:
    pass


event_sourcing_root = CqrsEventSourcingModule.for_root(
    CqrsEventSourcingOptions(
        store=InMemoryEventStore,
        schemas=schemas,
    ),
    imports=[PersistenceModule],
    key="profiles",
)


profile_repositories = CqrsEventSourcingModule.for_feature(
    [ProfileRepository],
    root_key="profiles",
    key="profile-model",
)


cqrs_module = CqrsModule.for_root(global_=True)
```

`schemas` must be frozen before graph compilation. `store` is a visible ToriPy
provider token, not a store object created by the module descriptor. This keeps
store lifecycle, settings, pooling, and test overrides with the provider that
owns them.

Import the root descriptor exactly once in application/root composition. It is
global by design but exports only deterministic key-qualified infrastructure
tokens. A feature descriptor does not receive or import the root; it selects
global infrastructure by `root_key` and exports only its listed repository
classes.

Every `for_feature()` call creates a fresh private module identity. Independent
feature modules can register the same repository set without descriptor reuse or
a mutable global registry. An absent selected root fails normal ToriPy graph
compilation.

## Transactional Command Handler

Decorator order matters: `@command_handler` must run first so
`@use_event_sourcing` can validate command metadata. In source, put
`@use_event_sourcing` above it:

```python
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from tori_py import Scope, module
from tori_py_cqrs import command_handler
from tori_py_cqrs_core import Command
from tori_py_cqrs_event_sourcing import aggregate_repository, use_event_sourcing


@dataclass(frozen=True, slots=True)
class OpenProfile(Command[Profile]):
    profile_id: UUID
    display_name: str


@use_event_sourcing(key="profiles")
@command_handler(OpenProfile, scope=Scope.REQUEST)
class OpenProfileHandler:
    def __init__(
        self,
        profiles: Annotated[
            ProfileRepository,
            aggregate_repository(ProfileRepository),
        ],
    ) -> None:
        self._profiles = profiles

    async def handle(self, command: OpenProfile) -> Profile:
        profile = Profile(command.profile_id)
        profile.open(command.display_name)
        self._profiles.save(profile)
        return profile


@module(
    imports=[profile_repositories],
    providers=[OpenProfileHandler],
)
class ProfilesModule:
    pass


@module(
    imports=[
        event_sourcing_root,
        cqrs_module,
        ProfilesModule,
    ]
)
class AppModule:
    pass
```

`OpenProfileHandler` contains application orchestration only. It does not inject
`EventSourcingUnitOfWork`, call `commit()`, or own rollback. The returned
`Profile` object is retained; after confirmed commit its version is advanced and
its pending events are cleared before `CommandBus.execute()` returns it.

Use request scope for handlers that inject repositories. ToriPy's normal scope
validation rejects a singleton dependency path to a request-scoped repository.

`@use_event_sourcing()` accepts only an already decorated command handler.
Attaching its interceptor to a query or event is a configuration error before
request admission.

## Exact Invocation Lifecycle

For one decorated command, execution is:

1. The command transport selects the exact canonical handler.
2. `tori-py-cqrs` opens one fresh handler-owner work scope.
3. The outer transaction interceptor resolves in handler-owner visibility.
4. The transaction coordinator creates and enters one UoW.
5. The integration activates repository and synchronization access for the
   owning handler task.
6. Graph and normal handler interceptors resolve.
7. The handler and request-scoped dependencies resolve.
8. `handler.handle(command)` runs.
9. At the exact terminal boundary, repository use and synchronization
   registration close before inner interceptors resume.
10. A successful handler triggers `unit_of_work.commit()` even when no event was
    staged.
11. A failed provider/handler triggers explicit rollback.
12. The integration reads the typed UoW outcome and runs matching
    synchronization callbacks.
13. Handler/interceptor resources unwind in LIFO order.
14. The outer transaction coordinator exits the UoW last.
15. After every scope resource closes, the completion mapper preserves the
    persistence outcome through cleanup failures.
16. The command result or typed failure returns through the CQRS reply path.

The UoW enters before handler construction and exits after handler dependencies.
All repositories in one command use that one transaction. Concurrent commands
receive independent work scopes, repositories, synchronization state, and UoWs.

A handler returning normally means its decision completed, not that the command
succeeded. The caller sees the result only after commit, synchronization, and
scope finalization.

## Repository Lease

Generated feature repositories receive the core operation-lease hook. Access is
allowed only from the exact task running the active command handler body.

These uses raise `CommandTransactionUnavailableError`:

- resolving a repository without an active decorated command;
- injecting/resolving it from a query, event handler, or undecorated command;
- returning a repository and using it after `handle()` returns;
- using it from a child task, even while the parent awaits that task;
- using it from an interceptor after the handler terminal;
- using it from a synchronization callback.

This prevents retained request-scoped repository state from escaping the
transaction decision boundary. Custom repository methods that touch retained
state directly must call `_require_operation_lease()` first; methods composing
only `load()`, `get()`, and `save()` inherit their checks.

Queries should read a projection. When a query genuinely needs aggregate replay,
inject the keyed public `EventStore` token and use the framework-neutral explicit
UoW rather than an integration-managed feature repository:

```python
from typing import Annotated

from tori_py import Inject
from tori_py_cqrs_event_sourcing import get_event_store_token
from tori_py_cqrs_event_sourcing_core import EventStore, EventSourcingUnitOfWork


class ReadProfileHandler:
    def __init__(
        self,
        store: Annotated[
            EventStore,
            Inject(get_event_store_token(key="profiles")),
        ],
    ) -> None:
        self._store = store

    async def handle(self, query) -> object:
        async with EventSourcingUnitOfWork(self._store) as unit_of_work:
            repository = ProfileRepository(
                unit_of_work,
                category="profile",
                aggregate_factory=Profile,
                aggregate_type=Profile,
                id_encoder=str,
                schemas=schemas,
            )
            return await repository.load(query.profile_id)
```

This query UoW is explicit and is not committed unless application code asks it
to; context exit rolls it back harmlessly after reads.

## Factory-Produced Handlers

A factory provider has no statically inspectable class metadata. Bind it
explicitly and attach the public outer transaction binding:

```python
from tori_py import FactoryProvider, Scope, module
from tori_py_cqrs import CqrsModule, bind_command_handler
from tori_py_cqrs_event_sourcing import event_sourcing_transaction


@module(
    imports=[profile_repositories],
    providers=[
        FactoryProvider(
            "open-profile-handler",
            make_open_profile_handler,
            scope=Scope.REQUEST,
        )
    ],
    exports=["open-profile-handler"],
)
class FactoryHandlersModule:
    pass


cqrs_module = CqrsModule.for_root(
    imports=[FactoryHandlersModule],
    handlers=[
        bind_command_handler(
            OpenProfile,
            "open-profile-handler",
            interceptors=[event_sourcing_transaction(key="profiles")],
        )
    ],
    global_=True,
)
```

The binding is command-only and `OUTER`, so invalid attachment to a query/event
or missing root interceptor visibility fails graph assembly before a UoW is
created.

## Custom Unit-of-Work Factory

Root options accept a sync or async callable receiving the resolved store and
returning one unentered `EventSourcingUnitOfWork`:

```python
from tori_py_cqrs_event_sourcing_core import EventSourcingUnitOfWork, EventStore


def create_unit_of_work(store: EventStore) -> EventSourcingUnitOfWork:
    return ObservedUnitOfWork(store, metrics)


options = CqrsEventSourcingOptions(
    store=InMemoryEventStore,
    schemas=schemas,
    unit_of_work_factory=create_unit_of_work,
)
```

The factory is immutable module configuration, not a provider token. It runs
once per opted-in command. The integration validates that it returns an
unentered UoW whose context returns itself.

## Command Synchronization

Use `CommandSynchronization` for outcome-specific coordination with an external
side effect that cannot join the event-store transaction:

```python
from typing import Annotated

from tori_py import Inject
from tori_py_cqrs_event_sourcing import (
    CommandSynchronization,
    aggregate_repository,
    get_command_synchronization_token,
)


class PublishPostHandler:
    def __init__(
        self,
        synchronization: Annotated[
            CommandSynchronization,
            Inject(get_command_synchronization_token(key="community")),
        ],
        posts: Annotated[
            PostRepository,
            aggregate_repository(PostRepository),
        ],
        content: ContentVault,
        reconciliation: ReconciliationLog,
    ) -> None:
        self._synchronization = synchronization
        self._posts = posts
        self._content = content
        self._reconciliation = reconciliation

    async def handle(self, command) -> object:
        content_ref = self._content.put(command.body)

        self._synchronization.after_confirmed_non_commit(
            lambda: self._content.erase(content_ref)
        )
        self._synchronization.after_indeterminate(
            lambda error: self._reconciliation.record(content_ref, error)
        )
        self._synchronization.after_commit(
            lambda result: self._reconciliation.confirm(content_ref, result)
        )

        post = Post(command.post_id)
        post.publish(content_ref=content_ref)
        self._posts.save(post)
        return post
```

Callbacks may be sync or return an awaitable. Registration is accepted only from
the owning task while the handler body is active; late or child-task
registration raises `CommandSynchronizationStateError`.

Callback selection and order are exact:

| Outcome | Callback | Order | Intended use |
| --- | --- | --- | --- |
| `ConfirmedCommit` | `after_commit(result)` | Registration order | Notification after proven commit |
| `ConfirmedNonCommit` | `after_confirmed_non_commit()` | Reverse registration order | Compensation for proven rollback |
| `IndeterminateCommit` | `after_indeterminate(cause)` | Registration order | Record/schedule reconciliation |

An indeterminate callback must not destructively compensate as if rollback were
known. Storage may already contain the event.

Ordinary callback exceptions are recorded and remaining callbacks are attempted.
A `CancelledError`, `KeyboardInterrupt`, or `SystemExit` stops callback execution
and remains control flow. Callback failures never change the persistence
classification.

## Finalization Errors

When no secondary finalization failure exists, original domain, handler,
optimistic-concurrency, duplicate-ID, codec, confirmed-rejection, and
indeterminate errors pass through unchanged.

Additional synchronization or cleanup failures require wrappers that retain the
outcome:

| Error | Persistence fact and data |
| --- | --- |
| `ConfirmedCommandFinalizationError` | Commit is confirmed; carries `commit_result`, retained `handler_result`, phase, primary error, and secondary errors |
| `ConfirmedNonCommitFinalizationError` | Non-commit is confirmed; carries `outcome`, phase, original primary error, and secondary errors |
| `IndeterminateCommandFinalizationError` | Commit remains indeterminate; carries `outcome`, phase, primary error, and secondary errors |
| `CommandCancellationError` | `CancelledError` subtype carrying exact UoW outcome, original cancellation, phase, and secondary errors |

`CommandFinalizationPhase` identifies `HANDLER_ROLLBACK`,
`HANDLER_FINALIZATION`, `COMMIT`, `SYNCHRONIZATION`, `SCOPE_CLEANUP`, or
`UOW_CLEANUP`.

A confirmed commit followed by a callback or managed-resource cleanup failure is
not retryable rollback. Inspect `commit_result`, reconcile finalization, and do
not repeat the command blindly. A compensation failure does not erase the
confirmed non-commit or original handler failure. An indeterminate callback
failure does not turn ambiguity into rollback proof.

`KeyboardInterrupt` and `SystemExit` retain object identity, and secondary
failures are attached as notes rather than replacing process-control flow with
an ordinary error. The current integration does not attach the typed Unit of
Work outcome to those original process-control objects and does not emit it from
this mapper. If recovery depends on the persistence result, record it through
application/store telemetry and reconcile from authoritative storage; do not
infer rollback from the absence of an outcome on the exception.

## Cancellation and Caller Timeouts

Caller cancellation and handler cancellation are different:

- after an in-memory command transport accepts work, cancelling or timing out
  `CommandBus.execute()` stops that caller from waiting but does not cancel the
  worker-owned handler;
- the command can still commit after the caller receives cancellation or
  `RequestTimeoutError`;
- handler cancellation before commit triggers explicit rollback and confirmed
  non-commit compensation;
- cancellation during commit is classified only by the store/UoW contract;
- ambiguous adapter cancellation must become an indeterminate outcome.

Applications need stable command IDs and persisted idempotency before retrying a
timed-out command. A shutdown deadline cannot invent proof that an unknown
commit rolled back.

## Nested Dispatch

Same-bus nested command execution is rejected by CQRS core with
`NestedCommandDispatchError` before transport enqueue. The inner command never
joins the outer UoW and cannot execute later from the rejected call.

A nested query remains allowed but runs in an independent CQRS work scope and
does not inherit the outer UoW or its integration-managed feature repositories.
If the query explicitly opens its own EventStore transaction, it sees a
committed EventStore snapshot and cannot see the outer UoW's staged appends.
Visibility through other shared providers, in-memory state, or external stores
is application-defined and is not made "committed only" by CQRS. A different
`CommandBus` also remains independent and does not share the transaction.

## Persistence and EventBus Publication

The integration never publishes `CommitResult.events` to `EventBus`. A persisted
domain event and an in-process CQRS event delivery are separate facts.

Direct publication in the handler occurs before event-store commit:

```python
await events.publish(ProfileOpenedNotification(profile.id))
profiles.save(profile)
```

The notification can run even if persistence later rolls back.

An `after_commit` callback moves enqueue after confirmed commit:

```python
async def notify_after_commit(result) -> None:
    await events.publish(ProfileOpenedNotification(profile.id))


synchronization.after_commit(notify_after_commit)
```

This is still non-durable. A process can crash after commit and before enqueue,
and the CQRS envelope does not automatically preserve stored event metadata.
Reliable publication requires a transactional outbox written by the EventStore
adapter in the same database transaction and a separate relay.

Committed projections can instead consume the keyed store's bounded
`read_all()` feed with durable checkpoints. The integration does not provide the
runner, checkpoint store, poison-event policy, or idempotency.

## Keyed Infrastructure and Testing

Public helpers return deterministic tokens:

```python
from tori_py_cqrs_event_sourcing import (
    get_command_synchronization_token,
    get_event_store_token,
    get_schema_registry_token,
    get_transaction_interceptor_token,
)
```

Different root keys produce independent provider identities, coordinators,
repositories, and synchronization state. They may intentionally point at the
same store or immutable registry object, but no transaction is shared
implicitly.

Override the exact keyed provider on the root descriptor in tests:

```python
replacement = InMemoryEventStore()
builder = TestingModule.create(AppModule)
builder.override_provider(
    get_event_store_token(key="profiles"),
    module=event_sourcing_root,
).use_value(replacement)
application = await builder.compile()
```

`TestingModule.compile()` starts CQRS lifecycle. Resolve the command bus, execute
the command, and inspect the keyed store through public APIs. Close the
application so bus drains and work-scope cleanup complete.

## Boundaries

The integration does not provide an EventStore adapter, SQLAlchemy, migrations,
FastAPI, RabbitMQ, retries, an outbox, inbox, command idempotency, sagas,
snapshots, durable projectors, distributed transactions, or automatic event
publication. Its role is exact ToriPy composition and command transaction
lifecycle while the core package retains aggregate, schema, repository, and
commit-classification semantics.

# tori-py-cqrs-event-sourcing-core

`tori-py-cqrs-event-sourcing-core` provides framework-neutral event-sourcing primitives for
`tori-py-cqrs-core`:

- synchronous `AggregateRoot` event recording and replay;
- stable explicit event schemas, bytes codecs, and contiguous upcasters;
- asynchronous EventStore and transaction protocols;
- atomic `InMemoryEventStore` reference semantics;
- event-sourced repositories and explicit Unit of Work ownership;
- immutable confirmed-commit, confirmed-non-commit, and indeterminate outcomes;
- optional synchronous repository operation leases for framework integrations.

The package has no framework, database, DI, or serializer dependency. The
in-memory store is a semantic reference and test fixture, not durable storage.

Typical command-side flow:

```python
async with EventSourcingUnitOfWork(store) as unit_of_work:
    profiles = EventSourcedRepository(
        unit_of_work,
        category="profile",
        aggregate_factory=Profile,
        aggregate_type=Profile,
        id_encoder=str,
        schemas=schemas,
    )
    profile = await profiles.get(profile_id)
    profile.rename("Alicia")
    profiles.save(profile)
    await unit_of_work.commit()
```

After commit or rollback finalization, `unit_of_work.outcome` exposes the exact
persistence classification as `ConfirmedCommit`, `ConfirmedNonCommit`, or
`IndeterminateCommit`. Access before classification raises
`UnitOfWorkLifecycleError`.

Framework integrations may pass `operation_lease=callable` when constructing a
repository. The callable runs before every base `load()`, `get()`, or `save()`
operation and may reject retained repository access by raising its own error.
Custom repository methods that directly use retained transaction or aggregate
state must call `_require_operation_lease()` first. Omitting the lease preserves
standalone repository behavior.

Aggregates never publish through `EventBus`. Production adapters must coordinate
event rows and an outbox in one database transaction, then relay committed events
separately. The package does not claim exactly-once command execution, durable
projection checkpoints, automatic publication, or snapshot support.

The complete architecture and phase contracts are available in the
[implementation plan](https://github.com/mikeoz32/tori-py/blob/main/TORI_PY_CQRS_EVENT_SOURCING_CORE_IMPLEMENTATION_PLAN.md)
and [specification](https://github.com/mikeoz32/tori-py/blob/main/spec/tori-py-cqrs-event-sourcing-core/README.md).

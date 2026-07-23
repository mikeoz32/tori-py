# NES0: Workspace and Public Contracts

## Entry Criteria

- Nestpy N0-N7, `nestpy-cqrs` C0-C2, and `cqrs-event-sourcing` ES0-ES5 pass.
- The architecture document has no unresolved first-slice decisions.

## Deliverables

- Workspace package `packages/nestpy-cqrs-event-sourcing`.
- Distribution/import names and dependency boundaries.
- `py.typed`, package metadata, wheel, and source-distribution configuration.
- Public option, module, decorator, token, synchronization, and error contracts.
- Import-boundary tests that install only declared runtime dependencies.

## Public Surface

The initial package exports:

- `CqrsEventSourcingModule`;
- `CqrsEventSourcingOptions`;
- `aggregate_repository`;
- `event_sourcing_transaction`;
- `use_event_sourcing`;
- `CommandSynchronization`;
- `CommandFinalizationPhase`;
- keyed root token helpers;
- integration configuration, transaction availability, synchronization state,
  outcome-preserving finalization errors, and a `CancelledError`-derived command
  cancellation error.

The package MUST NOT publicly re-export the complete APIs of Nestpy,
`nestpy-cqrs`, or `cqrs-event-sourcing`.

## Repository Declaration Contract

```python
@aggregate_repository(Member, category="member", id_encoder=str)
class MemberRepository(EventSourcedRepository[int, Member]):
    pass
```

- The aggregate is a concrete `AggregateRoot` subtype.
- The repository is a concrete `EventSourcedRepository` subtype.
- Category, ID encoder, aggregate factory, and optional page size are immutable
  direct metadata.
- ID encoder defaults to `str`.
- Aggregate factory defaults to the aggregate type.
- The decorator does not register a provider.
- Re-decoration and inherited-only metadata are rejected.
- `aggregate_repository(MemberRepository)` returns `Inject(MemberRepository)`.
- Passing an undecorated repository to the injection form is rejected.
- Mixing declaration options into the injection form is rejected.
- `UnitOfWorkFactory` is a sync-or-async callable from resolved `EventStore` to
  one unentered `EventSourcingUnitOfWork`; it is immutable module configuration,
  not a DI provider.

## Invariants

- Importing the package performs no registration, discovery, I/O, or global
  mutation.
- Public declarations have stable type annotations and useful repr/equality where
  value semantics apply.
- Core aggregate, schema, store, repository, and UoW contracts are reused rather
  than copied.
- Package code does not import private names from any dependency.

## Tests

- Public API allowlist and `py.typed`.
- Dependency/import graph checks.
- Decorator declaration/injection overloads and invalid combinations.
- Metadata is direct, immutable, and absent from undecorated/inherited classes.
- Wheel and source artifact contents and isolated imports.

## Exit Criteria

- Public contracts are frozen before lifecycle implementation begins.
- Artifacts install with only declared dependencies.

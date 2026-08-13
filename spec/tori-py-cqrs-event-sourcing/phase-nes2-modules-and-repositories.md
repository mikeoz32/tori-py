# NES2: Dynamic Modules and Repositories

## Entry Criteria

- NES0-NES1 pass.

## Deliverables

- `CqrsEventSourcingModule.for_root()`.
- `CqrsEventSourcingModule.for_feature()`.
- Keyed public store/schema/synchronization/interceptor tokens and a private
  transaction-coordinator token.
- Decorated repository provider factories and exports.
- Testing overrides for root and feature providers.

## Root Contract

- `for_root()` accepts options, imports, and a root key.
- Every configured root is global by design and is imported once by the
  application/root composition module.
- The configured store is a visible ToriPy provider token.
- A store configured with the root's keyed store token is re-exported directly;
  `store=EventStore` receives only a keyed alias; other tokens receive a local
  `EventStore` alias followed by the keyed alias.
- The schema registry is explicit and frozen before graph compilation succeeds.
- Root aliases the framework-neutral EventStore token locally only for a distinct
  configured token, preventing self-alias cycles for both public store tokens.
- Transaction coordinator and synchronization providers are request-scoped.
- A private keyed request-scoped transaction accessor is exported globally from
  root only for feature provider construction and is not re-exported by feature
  modules.
- The UoW is created by immutable module configuration inside the coordinator;
  it is not a ToriPy provider or token.
- The transaction coordinator token is not exported for application handler
  injection.
- The EventStore and schema registry retain their configured provider ownership.
- Root dynamic identity is `(CqrsEventSourcingModule, key)`.
- Reuse requires the same deferred descriptor object.
- Root exports only deterministic keyed infrastructure tokens. It does not
  globally export unqualified EventStore, schema, or synchronization aliases.

## Feature Contract

- `for_feature(repositories, *, root_key="default", key=None)` receives
  repositories positionally and never receives or imports a root descriptor.
- `root_key` selects the keyed global root infrastructure used by every generated
  repository factory.
- Every feature registration uses a fresh private internal module class, allowing
  independent submodules to register identical repository sets without ToriPy
  descriptor conflicts. Optional key values are diagnostic labels.
- `repositories` contains only directly decorated repository classes, and
  metadata is read through ToriPy `Reflector` before provider creation.
- Every repository provider is request-scoped and binds the decorated aggregate,
  category, factory, ID encoder, page size, root transaction accessor, and root
  schemas.
- The repository class is its own provider token and export.
- Feature exports only its generated repository class providers. Keyed root
  transaction/interceptor capabilities are already globally visible.
- Duplicate repository classes/tokens fail during materialization.
- Distinct feature modules for one root may register different or identical
  repository sets without dynamic identity collisions or shared descriptors.

## Scope and Visibility

- A repository obtains the UoW only through the transaction accessor activated by
  its outer interceptor.
- Every repository operation checks an owner-task/body-phase lease; escaped,
  child-task, callback, and post-handler use fails.
- Custom methods either compose guarded base operations or call protected
  `_require_operation_lease()` before retained-state access; the decorator does
  not wrap arbitrary methods dynamically.
- Repository resolution without an active decorated command fails with
  `CommandTransactionUnavailableError`.
- A singleton provider cannot depend on a request repository.
- Private handlers can be discovered but still require normal imported/exported
  repository and interceptor visibility.
- Multiple keyed roots have independent provider identities, repositories, and
  UoWs. Applications may deliberately configure the same store or frozen schema
  registry object for more than one root.
- A feature whose selected root is absent fails normal graph compilation with an
  unresolved keyed provider; runtime discovery does not repair the graph.

## Tests

- Root/feature materialization, keyed root identity reuse, fresh feature
  identities, optional diagnostic keys, and root descriptor conflicts.
- Feature descriptors have no root import; application composition imports root
  once while submodules import features independently.
- Missing/ambiguous store, invalid schema registry, and scope violations.
- Decorated repository construction, load/save, and custom repository methods.
- Same repository token in separately qualified feature modules.
- Multiple independent feature modules selecting one global root.
- Missing selected root fails graph compilation.
- Two roots with distinct stores and schema registries under concurrent commands.
- Exact `TestingModule.override_provider()` for stores and repository classes.
- No package scanning or implicit provider registration.

## Exit Criteria

- A handler can inject a decorated repository with
  `Annotated[Repo, aggregate_repository(Repo)]` and receive the exact command
  transaction instance.

# NPS1: Root and Configuration

## Status

Complete.

## Purpose

Compose one always-global application root with one imported adapter
and immutable stream bindings.

## Public Contracts

- Public runtime-checkable `StreamAdapterFactory` Protocol used as the canonical
  Nestpy provider token by every adapter module.
- `PersistentStreamsOptions`, `PersistentStreamsRuntimeOptions`, and immutable
  stream-binding declarations.
- `PersistentStreamsModule.for_root()` and `for_root_async()`.
- Deterministic binding, named-publisher, and runtime tokens.

## Required Behavior

- Materialized root `ModuleSpec.global_` is always `True`; no public opt-out exists.
- The root accepts adapter and runtime-option dependencies through `imports` and
  directly injects `StreamAdapterFactory`.
- Adapter `for_root()` and `for_root_async()` methods return `DeferredModule`
  directly and provide/export `StreamAdapterFactory`.
- One application has at most one persistent-stream root; the root has no public key.
- One root may configure several unique logical stream aliases.
- `for_root_async(bindings=..., publishers=..., use_factory=..., imports=...)`
  keeps provider-generating inventory static and registers the user
  factory directly for runtime-only settings.
- Sync and async factories resolve normal annotated dependencies and
  `Annotated[..., Inject(token)]` from explicit imports.
- Runtime options expose `owner_id`, `max_concurrency`, `poll_interval`,
  `max_pending_publications`, and `global_pipeline`; every numeric bound is
  finite and positive.
- Async root materialization validates static bindings and publishers without a
  placeholder owner; binding owner limits apply after factory resolution.
- Every binding fixes stream identity, codec, resolver, deterministic router,
  optional named-producer policy, limits, and publisher registrations. Unnamed
  mode requires no publishing-ID source or producer exclusivity.

## Invalid Configurations

- Missing `StreamAdapterFactory` provider or competing imported adapter modules.
- A second root, duplicate binding alias, publisher name, Protocol token, or
  explicit publisher name colliding with an implicit binding publisher token.
- Unknown publisher binding, unsafe alias, mutable options, or non-positive bound.
- User factory invocation during import or descriptor materialization.
- A per-publication override for fixed binding policy.

## Tests

- Root materialization and exact internal import/export inventories.
- One-root diagnostics through direct and transitive duplicate imports.
- Sync/async factory injection, final testing overrides, and factory failures.
- One-adapter success plus standard `provider.unresolved` and
  `provider.ambiguous` diagnostics for missing and competing adapters.
- Immutability, defensive copying, alias validation, and secret-safe repr.

## Exit Criteria

- One imported root resolves several bindings and exactly one adapter through
  standard Nestpy imports without a global registry.

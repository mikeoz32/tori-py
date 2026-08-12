# NPS1: Root and Configuration

## Status

Complete.

## Purpose

Compose one always-global application root with one internally imported adapter
and immutable stream bindings.

## Public Contracts

- `ConfiguredStreamAdapter` reference with `module`, `factory_token`, and kind.
- `PersistentStreamsOptions`, `PersistentStreamsRuntimeOptions`, and immutable
  stream-binding declarations.
- `PersistentStreamsModule.for_root()` and `for_root_async()`.
- Deterministic binding, named-publisher, and runtime tokens.

## Required Behavior

- Materialized root `ModuleSpec.global_` is always `True`; no public opt-out exists.
- The root imports `adapter.module` internally and injects its exact factory token.
- The application imports only the root descriptor, not the adapter descriptor.
- One application has at most one persistent-stream root; the root has no public key.
- One root may configure several unique logical stream aliases.
- `for_root_async(adapter, bindings=..., publishers=..., use_factory=...,
  imports=...)` keeps provider-generating inventory static and registers the user
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

- Missing or structurally invalid adapter reference.
- A second root, duplicate binding alias, publisher name, Protocol token, or
  explicit publisher name colliding with an implicit binding publisher token.
- Unknown publisher binding, unsafe alias, mutable options, or non-positive bound.
- User factory invocation during import or descriptor materialization.
- A per-publication override for fixed binding policy.

## Tests

- Root materialization and exact internal import/export inventories.
- One-root diagnostics through direct and transitive duplicate imports.
- Sync/async factory injection, final testing overrides, and factory failures.
- Adapter module overrides and missing adapter-token diagnostics.
- Immutability, defensive copying, alias validation, and secret-safe repr.

## Exit Criteria

- One imported root resolves several bindings and its adapter without a global
  registry or separate application adapter import.

# N7: Reflection and Discovery

## Purpose

Provide generic framework introspection for integrations without package scans,
provider auto-registration, mutable container access, or ambiguous global
resolution.

## Contract

- `MetadataKey[T]`, `MetadataDecorator[T]`, `metadata()`, and `Reflector`
  attach and read typed metadata on classes and functions.
- `Reflector.get_own()` reads only directly declared metadata.
- `Reflector.get()` may walk class inheritance and accepts either a class or an
  instance. Existing direct-only metadata APIs do not change semantics.
- `ModulesContainer` is an application-scoped, read-only mapping of exact
  `ModuleId` values to immutable `ModuleView` values.
- `ModuleView.providers` and `ModuleView.controllers` contain immutable
  `ProviderView` descriptors in compiled order.
- A provider descriptor includes its exact provider reference, canonical
  reference, declaration, scope, statically known implementation class, and an
  explicit created-state plus singleton instance value when one exists. `None`
  is a valid created value.
- `DiscoveryService` enumerates all compiled modules by default and supports an
  explicit module-class include filter.
- Discovery sees private providers but does not make their tokens normally
  visible to unrelated modules.
- Aliases canonicalize to one provider in default discovery results.
- Exact token lookup preserves an alias declaration and reference while scope,
  implementation, and instance information comes from its canonical provider.
- Metadata filtering checks the declared implementation before a managed
  provider's entered runtime value.
- `ModulesContainer`, `DiscoveryService`, and `Reflector` are reserved framework
  dependencies and cannot be overridden by application providers.
- `WorkScopeFactory.run_in()` resolves through an exact target `ModuleId`; it
  never performs an unqualified global token lookup.
- Reflection and discovery never import `cqrs-core` or application packages.

## Failure Behavior

- Invalid metadata targets, metadata keys, include filters, and unknown module
  identities fail with typed Nestpy errors.
- Discovery never instantiates request or transient providers.
- Factory provider implementation classes remain unknown unless an already
  created singleton instance supplies one.
- Duplicate tokens in different modules remain separate descriptors.
- Cancellation and resource failures during `run_in()` follow normal work-scope
  cleanup semantics.

## Verification

- metadata can be read from classes, methods, and instances;
- direct and inherited lookup semantics differ explicitly;
- all three framework services inject without provider declarations;
- application code cannot redeclare reserved framework tokens;
- private providers are discoverable but not normally resolvable across module
  visibility boundaries;
- aliases do not duplicate canonical providers;
- static and keyed dynamic module identities remain distinct;
- request, transient, and singleton providers are not instantiated by scanning;
- `run_in()` resolves the exact owner when two modules reuse one token;
- import-boundary, Ruff, formatting, type, and full test gates pass.

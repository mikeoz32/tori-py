# NPS2: Discovery and Handler Compiler

## Status

Complete.

## Purpose

Compile direct persistent-stream controller methods across the final ToriPy
application graph into one immutable module-qualified registry.

## Public Contracts

- Direct immutable `@stream_handler(stream=..., consumer_group=...)` metadata.
- `StreamPayload`, `StreamRecordContext`, `StreamHeaders`, `StreamHeader`,
  `StreamPartition`, `StreamOffset`, and `StreamInject` markers.
- Immutable handler identity, parameter plan, and handler registry values.

## Discovery Contract

- Inject public `DiscoveryService` and call `get_controllers()` after testing
  overrides are compiled.
- Inspect only methods directly present in `controller.__dict__`.
- Retain the exact controller `ProviderRef` and owner `ModuleId`.
- Perform no package scan, subclass enumeration, endpoint-module registration,
  scoped provider construction, codec call, checkpoint lookup, or adapter I/O.
- Ignore all `tori-py-microservices` handler and parameter metadata.

## Compilation Rules

- Each handler is async and has explicit `None` return annotation.
- Every non-`self` parameter has exactly one supported stream marker.
- Each handler has exactly one complete `StreamPayload()` parameter.
- Payload and context annotations resolve completely before startup.
- `(stream, consumer_group)` is unique application-wide.
- Referenced stream aliases exist in the root binding registry.

## Tests

- Multi-module global discovery in deterministic compiled order.
- Same controller token in different modules with exact owner preservation.
- Direct versus inherited methods and final testing overrides.
- Duplicate mappings and unknown stream/group diagnostics.
- Missing/duplicate markers, variadics, sync handlers, and bad returns.
- Proof that microservices decorators and markers are independent.

## Exit Criteria

- A final application graph yields one deterministic immutable stream-handler
  registry without opening an adapter or constructing scoped values.

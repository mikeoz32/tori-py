# ES2: Stable Schemas and Codecs

## Entry Criteria

- ES1 exit criteria pass.

## Deliverables

- Stable event schema descriptors and explicit mutable-then-frozen registry.
- Encoded, append, and stored event value objects.
- Deterministic encoder/decoder calls and contiguous byte upcasters.
- Shared finite resource-limit configuration.

## Invariants

- Persisted event aliases never derive from Python class paths.
- One alias maps to one event class and one current positive schema version.
- One event class maps to one alias.
- Upcasters advance exactly one version per step and run without I/O or dynamic
  imports.
- Registry use requires an explicit frozen state.
- Encoding preserves pending occurrence metadata in `AppendEvent`.

## Failure Behavior

- Duplicate aliases/classes, missing upcast steps, unknown aliases, future
  versions, malformed codec output, type mismatches, and resource-limit breaches
  raise typed errors.

## Tests

- Stable alias survives Python class/module identity changes.
- Deterministic encode/decode round trip.
- Multi-step upcast and every invalid chain shape.
- Payload, metadata, and upcast limits.
- Frozen registry rejects later mutation.

## Exit Criteria

- ES2 behavior passes with explicit standard-library test codecs only.

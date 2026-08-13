# RPS2: Topology and Operator Preflight

Status: incomplete. Inspectable kind, partition, and binding facts are covered. Effective
policy remains explicitly operator-owned.

## Requirements

- `CREATE` idempotently creates explicitly configured regular Streams or fixed
  Super Stream partitions and bindings.
- `REQUIRE_EXISTING` creates nothing and requires topology to exist.
- Inspectable regular-versus-Super kind, physical partition set, count, and
  binding conflicts fail startup.
- The adapter never deletes, truncates, recreates, resizes, or repairs topology.
- Creation sends configured retention/segment/replication arguments but does not
  claim their effective values were verified when public native APIs cannot
  inspect them.
- Broker policy, effective retention, permissions, replication, and placement
  are documented operator preflight unless a separately approved management
  capability is added.

## Tests

Real-broker idempotent creation, concurrent races, existing topology, inspectable
conflicts, and explicit unverified-operator-preflight diagnostics.

## Exit Criteria

Only inspectable topology facts are asserted at runtime; no unverifiable setting
is represented as verified.

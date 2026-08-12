# Nestpy Persistent Streams Specifications

Governing documents:

- [`NESTPY_PERSISTENT_STREAMS_ARCHITECTURE.md`](../../NESTPY_PERSISTENT_STREAMS_ARCHITECTURE.md)
- [`NESTPY_PERSISTENT_STREAMS_IMPLEMENTATION_PLAN.md`](../../NESTPY_PERSISTENT_STREAMS_IMPLEMENTATION_PLAN.md)

## Current Status

Architecture is approved. NPS0-NPS6 are complete. The seven stream review
findings and focused NPS7 test, quality, typing, and artifact gates are green;
its repository-wide gate remains blocked by unrelated baseline failures.

## Phase Map

| Phase | Specification | Main result | Status |
| --- | --- | --- | --- |
| NPS0 | [Workspace and contracts](phase-nps0-workspace-and-contracts.md) | Installable typed integration | Complete |
| NPS1 | [Root and configuration](phase-nps1-root-and-configuration.md) | One global internally composed root | Complete |
| NPS2 | [Discovery and compiler](phase-nps2-discovery-and-compiler.md) | Immutable global handler registry | Complete |
| NPS3 | [Pipeline and checkpoints](phase-nps3-pipeline-and-checkpoints.md) | Scoped ordered processing | Complete |
| NPS4 | [Publishers](phase-nps4-publishers.md) | Raw, named, and Protocol publishing | Complete |
| NPS5 | [Runtime and lifecycle](phase-nps5-runtime-and-lifecycle.md) | Ready, bounded partition runtime | Complete |
| NPS6 | [Conformance and hardening](phase-nps6-conformance-and-hardening.md) | Explicit replay-safe failures | Complete |
| NPS7 | [Acceptance and release](phase-nps7-acceptance-and-release.md) | Reviewed releasable artifacts | Baseline blocked |

## Governing Invariants

1. `nestpy-persistent-streams` depends on Nestpy and persistent-stream contracts;
   neither has a reverse dependency.
2. One application imports one always-global persistent-stream root.
3. The root composes exactly one adapter module through standard Nestpy imports.
4. Async configuration uses annotation-driven injectable sync/async factories.
5. Discovery examines direct `@stream_handler` methods on all explicit
   controllers through `DiscoveryService`.
6. Stream markers and metadata are independent of `nestpy-microservices`.
7. Each record is decoded to its declared DTO through the binding's codec.
8. Decode or validation failure stops its physical partition without checkpoint.
9. Each attempt executes in a fresh exact-owner Nestpy work scope.
10. A resume cursor advances only after successful pipeline and scope cleanup;
    filters cannot make a failed attempt eligible.
11. Partition processing is serial; cross-partition concurrency is finite.
12. Root bindings fix stream, codec, resolver, router, and optional named-producer
    policy before startup; unnamed mode remains fully supported.
13. Every publisher form accepts optional explicit `record_id`; generated UUIDs
    are defaults only, and receipts never contain offsets.
14. There is no EventHandler, EventDispatcher, or automatic CQRS bridge.
15. Every dependency, test, build, quality, and service command uses uv.
16. Broker-managed checkpoints are supported only in explicitly configured
    single-instance deployments. A shared external checkpoint store supports
    multi-replica deployments only when every replica uses a replica-unique owner ID
    and the store provides atomic fence replacement and exact-owner save validation.

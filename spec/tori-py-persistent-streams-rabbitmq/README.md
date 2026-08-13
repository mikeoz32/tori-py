# RabbitMQ Persistent Streams Specifications

Status: RPS0-RPS7 incomplete after adversarial review. Focused CPython 3.14.6,
`rstream==1.0.1`, and RabbitMQ 4.1.8 tests cover the revised guarantees, but full
conformance, transparent reconnect, TLS/fault
coverage, Super Stream failover, and release review remain gates.

| Phase | Result |
| --- | --- |
| RPS0 | [Incomplete: feasibility guarantees revised](phase-rps0-workspace-and-driver-contracts.md) |
| RPS1 | [Incomplete: configuration and resources](phase-rps1-configuration-and-resources.md) |
| RPS2 | [Incomplete: topology and operator preflight](phase-rps2-topology-and-retention.md) |
| RPS3 | [Incomplete: envelope and publishing](phase-rps3-publishing-and-deduplication.md) |
| RPS4 | [Incomplete: SAC, starts, and resume cursors](phase-rps4-sac-and-checkpoints.md) |
| RPS5 | [Partial: reconnect, TLS, and backpressure](phase-rps5-reconnect-tls-and-backpressure.md) |
| RPS6 | [Partial: conformance passes; failure matrix remains](phase-rps6-conformance-and-failure-matrix.md) |
| RPS7 | [Conditional: acceptance and release](phase-rps7-acceptance-and-release.md) |

## Invariants

1. Publish returns an offset-free `PublishReceipt`; offsets occur only on consumed
   or read records.
2. Offsets are non-negative and strictly increasing; gaps are valid.
3. Public bounds are unavailable; chunk metadata is never used as a record end.
4. Unnamed mode has no publishing-ID storage or producer exclusivity.
5. Named IDs are monotonic per physical producer and partition.
6. No indeterminate publish is automatically retried.
7. All starts are capability-gated; relative resolves to timestamp and no clamp
   or retention gap is silently accepted.
8. `ResumeCursor` distinguishes initialized start from last successful offset.
9. A definitive failed attempt leaves the prior cursor unchanged; timeout,
   cancellation, or disconnect during store/query is indeterminate and recovery
   may observe either the old or new cursor. Filters cannot recover checkpoint
   eligibility.
10. The versioned AMQP 1.0 envelope is frozen before publishing.
11. Runtime verifies only inspectable kind and partition topology; policy and
    retention are operator preflight unless management capability is approved.
12. PSRM barriers establish exact `END` and finite-read boundaries and never
    surface as application records.
13. Broker-managed checkpoints are supported only in explicitly configured
    single-instance deployments. A shared external checkpoint store supports
    multi-replica deployments only when every replica uses a replica-unique owner ID
    and the store provides atomic fence replacement and exact-owner save validation.

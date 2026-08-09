# Nestpy Microservices Specifications

Governing documents:

- [`NESTPY_MICROSERVICES_ARCHITECTURE.md`](../../NESTPY_MICROSERVICES_ARCHITECTURE.md)
- [`NESTPY_MICROSERVICES_IMPLEMENTATION_PLAN.md`](../../NESTPY_MICROSERVICES_IMPLEMENTATION_PLAN.md)

## Current Status

MS0-MS10 and MS12 capabilities are implemented in the current worktree,
including the MS9
root-owned application-facing `EventDispatcher`, RabbitMQ event routing,
complete real-broker cardinality matrix, offline ephemeral behavior, and
reliable-broadcast restart retention. MS10 failure hardening is implemented and
MS11 release acceptance is not complete; broker application restart, pending-RPC reconnect
behavior, and bounded proxy-injected network blackhole recovery are covered by
the MS10 slice; publisher-confirm cancellation fencing, deleted-reply-route
terminal settlement, poison-event retry/DLX behavior, malformed schema
dead-lettering, handler/reply blackholes, pre-write timeout classification, and
active-RPC forced shutdown are covered as well. The remaining work is complete
observability/security hardening and MS11 release acceptance.

## Phase Map

| Phase | Specification | Main result | Status |
| --- | --- | --- | --- |
| MS0 | [Workspace and contracts](phase-ms0-workspace-and-contracts.md) | Installable typed optional package | Implemented; release artifact gate remains MS11 |
| MS1 | [Service identity and wire protocol](phase-ms1-service-identity-and-wire-protocol.md) | Stable bounded RPC/event envelopes | Implemented |
| MS2 | [Controller discovery and handler compiler](phase-ms2-controller-discovery-and-handler-compiler.md) | Immutable application-wide handler registry | Implemented |
| MS3 | [Invocation pipeline and scopes](phase-ms3-invocation-pipeline-and-scopes.md) | Exact scoped broker invocation | Implemented |
| MS4 | [Transport contract and in-memory broker](phase-ms4-transport-contract-and-inmemory.md) | Executable transport conformance baseline | Implemented |
| MS5 | [Service runtime and lifecycle](phase-ms5-service-runtime-and-lifecycle.md) | Ready and quiescent service runtime | Implemented; examples remain MS11 |
| MS6 | [Cluster client and replies](phase-ms6-cluster-client-and-replies.md) | Shared bounded asynchronous RPC client | Implemented |
| MS7 | [RabbitMQ foundation and topology](phase-ms7-rabbitmq-foundation-and-topology.md) | Owned robust connection and exact topology | Implemented; MS10 owns broker recovery hardening |
| MS8 | [RabbitMQ RPC service cluster](phase-ms8-rabbitmq-rpc-service-cluster.md) | Wildcard-bound competing service replicas | Implemented; full fault matrix pending |
| MS9 | [Clustered event dispatch](phase-ms9-clustered-event-dispatch.md) | SERVICE_POOL, SINGLETON, and BROADCAST | Implemented; exit criteria proven against real RabbitMQ |
| MS10 | [Failure recovery and hardening](phase-ms10-failure-recovery-and-hardening.md) | Bounded explicit distributed failures | Implemented; MS11 release gates remain |
| MS11 | [Acceptance, docs, and release](phase-ms11-acceptance-docs-and-release.md) | Reviewed releasable artifacts | Not complete |
| MS12 | Typed service contracts | Protocol-driven dynamic RPC clients | Implemented |

## Governing Invariants

1. `nestpy-microservices` depends on Nestpy; Nestpy never depends on it.
2. One `NestApplication` exposes at most one logical service identity.
3. Every explicitly registered controller is scanned once during startup; no
   package scan, endpoint module, or process-global handler registry exists.
4. RPC methods use simple stable `@rpc("method")` mappings.
5. RabbitMQ RPC uses one service queue, one service wildcard binding, distinct
   method routing keys, and competing replicas.
6. All RPC calls have finite deadlines; accepted or indeterminate calls are
   never automatically resent.
7. Every delivery attempt receives a fresh exact-owner Nestpy work scope.
8. Reply publication is confirmed and routed before normal RPC ACK; a proven
   deleted reply route is ACKed without intentional requeue, while ACK
   uncertainty may still redeliver.
9. Event delivery modes are consumer metadata and broker topology, not producer
   dispatcher choices.
10. Durable event handlers use explicit stable subscription identities.
11. Settlement occurs only after pipeline and work-scope cleanup; events require
    success, while RPC may return a sanitized wire error.
12. Publisher confirms do not imply consumer handling or transactional
    publication.
13. Outbox/inbox, distributed transactions, and service extraction remain
    separate application architecture decisions.
14. Every development and verification command uses uv.

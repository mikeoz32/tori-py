# NPS6: Conformance and Hardening

## Status

Complete.

## Purpose

Freeze the reusable adapter contract and prove bounded behavior for duplicate,
checkpoint, reconnect, capacity, security, and shutdown failures.

## Conformance Matrix

Core `PersistentLog` conformance proves portable log semantics. Separately, each
Nestpy adapter lifecycle/execution suite proves:

- exact regular and partitioned logical-stream mapping;
- encoded publication with confirmed, rejected, and indeterminate outcomes;
- receipt partition metadata without publish offsets, and consumed record offsets;
- serial delivery within each partition;
- broker and external checkpoint behavior where supported;
- reconnect generation changes and old-callback rejection;
- stop-intake, callback fencing, status, and close semantics;
- native unwrap isolation and no framework ownership leakage.
- RabbitMQ objects map to core conformance through its `PersistentLog` and to
  Nestpy conformance through its configured adapter factory/runtime.

## Required Failure Distinctions

- decode or DTO validation failure;
- handler/pipeline poison failure and partition stop;
- work-scope cleanup failure;
- checkpoint rejection, timeout, and uncertainty;
- checkpoint removed by retention;
- duplicate delivery after uncertain checkpoint;
- publication rejection, timeout, saturation, and uncertainty;
- adapter loss before and after callback handoff;
- shutdown cancellation with active work.

## Hardening

- Bound payloads, metadata, partitions, concurrency, queues, pending
  publications, retries, status listeners, logs, and shutdown waits.
- Redact credentials, native options, payloads, and sensitive headers.
- Use bounded metric labels and stable diagnostic codes.
- Prove stream metadata is not authorization policy.
- Prove HTTP and microservices roots can coexist without marker or dispatcher
  sharing.

## Tests

- Nestpy lifecycle/execution conformance suite against a deterministic fake.
- Fault injection at every decode/scope/checkpoint/publish/lifecycle boundary.
- Saturated queue/semaphore/listener maps and cancellation races.
- Context, task, callback, and generation leakage checks.
- Security/redaction snapshots and bounded-cardinality metric hooks.

## Exit Criteria

- No supported failure advances an unsafe checkpoint, reports uncertainty as
  success, retries publication silently, or leaks unbounded work.

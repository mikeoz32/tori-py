# Persistent Stream Operations

Persistent-stream operations must preserve replay coordinates and uncertainty.
The safest default is to stop and retain evidence rather than skip a record,
clamp a cursor, overlap owners, or resend an indeterminate publication.

This guide applies to the portable and Tori Py contracts. RabbitMQ-specific
preflight is included because the provided durable adapter is provisional.

## Deployment Inventory

Record these values as version-controlled deployment data:

| Contract | Examples |
| --- | --- |
| Logical stream | `member-activity-v1` |
| Application alias | `member-activity` |
| Physical partitions | `member-activity-v1-0..7` |
| Partition count | `8` |
| Router | `sha256-v1` plus compatibility key |
| Partition-key encoding | UTF-8 member ID |
| Consumer groups | `member-card-v1`, `search-v2` |
| Start mode | `Beginning()` or an explicit alternative |
| Checkpoint strategy | Broker-managed or named external store |
| Producer coordinates | Producer name and publishing-ID policy |
| Envelope and codec | PSRM v2 plus application schema version |
| Retention | Effective age, bytes, and segment policy |
| Runtime bounds | Handler concurrency and pending publications |
| Adapter bounds | Credit, callback queue, pending bytes/count, timeouts |

Changing one of these can redirect records, split ordering, replay or skip data,
invalidate producer sequences, or make existing payloads undecodable. Treat the
change as a migration, not an ordinary rolling configuration update.

## RabbitMQ Broker Preflight

Complete this preflight before each environment is admitted:

1. Run RabbitMQ 4.1 and enable `rabbitmq_stream` and
   `rabbitmq_stream_management`.
2. Expose the native stream port, default `5552`; AMQP 0-9-1 port `5672` is not a
   substitute.
3. Configure a stable endpoint or load balancer and make every broker advertised
   host reachable by the application. Set `advertised_host` to that endpoint.
4. Grant read, write, create where applicable, and offset-tracking permissions for
   every logical and physical stream.
5. Prefer `DeclarationMode.REQUIRE_EXISTING` when infrastructure automation owns
   topology.
6. Verify regular versus Super Stream kind, exact partition count, physical
   names, and binding keys `0..N-1`.
7. Verify effective age and byte retention, segment size, replicas, leader
   placement, broker policy, and permissions through operator tooling. Adapter
   startup does not verify those facts.
8. Check disk alarms, free disk, page cache, network paths, and replica health.
9. Validate TLS trust, hostname, certificate/key pairing, expiry, rotation, and
   the selected SASL mechanism with the real certificates.
10. Confirm that Super Streams use `PLAIN`; the pinned driver cannot configure
    `EXTERNAL` for Super Stream declaration and inspection.
11. Confirm `rstream==1.0.1` and Python 3.14 in the built artifact.
12. Verify all documented RabbitMQ provisional gates accepted by the deployment's
    risk owner.

Creating a stream with retention arguments does not prove effective policy. A
broker policy can alter effective behavior, and public adapter preflight reports
retention, replication, placement, policy, and permissions as unverified.

## Ownership Preflight

### Broker-Managed Groups

Broker-managed checkpoints require an explicitly single-instance group:

- Set the adapter's `broker_managed_single_instance=True` where required.
- Set Tori Py `single_instance_consumer_groups=True` to declare the application
  topology.
- Configure the scheduler so old and replacement processes cannot overlap.
- Do not use a normal rolling deployment that starts the replacement first.
- After disconnect, prove the old process has stopped before starting another.

These flags do not implement a distributed lock. The deployment must satisfy the
claim.

### External-Store Groups

For a shared external checkpoint store:

- Give every replica a stable, replica-unique `owner_id`.
- Set `owner_id_is_replica_unique=True`.
- Verify the store atomically replaces fences and accepts saves only from the
  exact current `OwnershipToken`.
- Verify compare-and-create and expected-cursor save are atomic.
- Use finite query and persistence deadlines.
- Preserve cursor tags and reject regression.
- Test owner takeover, process death, timeout, cancellation, and network
  partition against the real store.

SAC or another broker assignment primitive does not replace durable store
fencing. RabbitMQ's complete multi-replica external-store fault matrix remains a
provisional release gate.

## Retention Preflight

Retention must exceed the worst credible recovery interval:

```text
maximum outage
+ detection delay
+ repair and redeploy
+ replay catch-up
+ safety margin
```

Check both age and byte limits. During a traffic spike, the byte policy may remove
history much earlier than the age policy suggests.

Before a planned long outage:

1. Measure each group's progress per partition.
2. Compare progress with the broker's current low watermark through operator
   tooling.
3. Estimate write rate and time until the low watermark reaches the checkpoint.
4. Increase effective retention or keep consumers running before entering the
   unsafe margin.
5. Verify disk and replica capacity for the temporary increase.

RabbitMQ `bounds()` is unavailable, so do not build this alert from the adapter's
public bounds. Use broker operations tooling and treat observations as moving
watermarks.

## Readiness

Tori Py `StreamRuntime.ready` becomes true only after:

- Handler and publisher compilation succeeds.
- Binding components and the adapter factory resolve.
- Streams are declared or verified.
- Every handler partition lease is prepared.
- `adapter.start()` crosses its native readiness barrier.
- Every partition task registers intake entry.
- No partition status is blocked.

`runtime.ready` is the Tori Py runtime/partition signal, not a continuous broker
connection heartbeat. It is computed only from runtime state and blocked
`PartitionStatus` values. Do not route dependent workload merely because the
process is alive, but also do not use `runtime.ready` as the only RabbitMQ
connectivity check.

After RabbitMQ fails an adapter closed, a consumer root becomes unready only when
its partition task observes the stopped lease; this can be delayed by in-flight
handler work. A publisher-only root has no partition task and can remain
`runtime.ready == True` while the adapter rejects every append. The current
integration does not propagate a public adapter connection status through
`StreamRuntime`. Pair `runtime.ready` with broker telemetry or an
application-owned dependency/fail-closed signal, and treat every publication as
its own acceptance boundary.

A standby RabbitMQ SAC registration is ready even though it has not become the
active owner; its task waits for promotion. A later intake, decode, handler, or
checkpoint failure degrades state and makes readiness false after the partition
task observes it.

## Observe the Runtime

The public runtime surfaces bounded status:

```python
from tori_py_persistent_streams import StreamRuntime


def readiness(runtime: StreamRuntime) -> tuple[bool, tuple[object, ...]]:
    return runtime.ready, runtime.statuses
```

Monitor at least:

| Signal | Why |
| --- | --- |
| Runtime state and readiness | Detect global degradation and shutdown |
| Blocked status by alias, group, and partition | Locate fail-stop delivery |
| Running checkpoint offset | Track progress without assuming adjacency |
| Publication outcomes | Separate confirm, pressure, timeout, and uncertainty |
| Confirm and checkpoint latency | Detect approaching deadlines |
| Runtime saturation count | Detect `max_pending_publications` pressure |
| Adapter backpressured receipts | Detect count/byte admission pressure |
| Broker low watermark versus progress | Predict retention gaps |
| Disk alarms, free disk, page cache, replica health | Protect broker availability |
| SAC ownership changes | Detect churn and takeover |
| Connection close/fail-closed events | Trigger replacement procedure |

The packages do not provide a complete metrics backend. Instrument public
receipts, runtime statuses, error diagnostic codes, and broker telemetry without
reaching into adapter private fields.

Keep labels bounded. Do not put payloads, partition keys, member identifiers,
record contents, credentials, or raw headers in metric labels or default logs.
Record UUID and exact offset can be included in restricted incident evidence when
needed for recovery.

## Status Interpretation

`PartitionStatus` includes stream alias, consumer group, physical partition,
state, optional offset, and optional diagnostic code.

| Status | Offset meaning |
| --- | --- |
| `prepared` | Lease exists; no runtime progress reported |
| `running` | Last successfully checkpointed record seen by the runtime, or `None` |
| `blocked` | Failing or uncertain record when known, not proof it checkpointed |

Common diagnostics include:

| Code | Meaning |
| --- | --- |
| `tori_py_persistent_streams.invocation_failed` | Decode or framework invocation failure |
| `tori_py_persistent_streams.partition_failed` | Handler, intake, checkpoint, or adapter error without a narrower code |
| `tori_py_persistent_streams.partition_stopped` | Lease stopped or consumer exited while admission remained open |
| `tori_py_persistent_streams.checkpoint_outcome_unknown` | Cancellation escaped during checkpoint persistence |

`tori_py_persistent_streams.publication_saturated` is the diagnostic code of
`StreamPublicationSaturatedError`. It belongs to publication error telemetry and
never appears in `PartitionStatus` or blocks a consumer partition.

Preserve the original exception and adapter-specific cause in application logs
with secret and payload redaction.

## Incident Classification

Classify before recovery:

| Incident | Cursor fact | Safe default |
| --- | --- | --- |
| Decode, guard, pipe, interceptor, handler, or cleanup failure | Prior cursor unchanged | Preserve record, fix code/dependency, replay |
| Checkpoint rejection proven not to mutate progress | Prior cursor unchanged | Stop, fix store/ownership, replay idempotently |
| Checkpoint timeout, cancellation, or disconnect | Old or new cursor may exist | Stop, inspect under fencing, assume duplicate window |
| Retention gap | Required history is absent | Stop, restore/rebuild/new group; never clamp silently |
| Publish timeout, caller/shutdown cancellation, or indeterminate send | Broker may have accepted | Do not auto-resend; reconcile or exact named retry |
| Runtime saturation | Adapter was not called | Apply caller pressure and bounded retry policy |
| Adapter `BACKPRESSURED` receipt | Adapter rejected local admission | Reduce load or capacity pressure; no send occurred per fact |
| RabbitMQ connection loss | Adapter fails closed | Stop old instance, recover broker, create new adapter |
| Topology conflict | Deployed data contract differs | Stop and migrate; do not repair in place |

## Recover a Blocked Record

1. Capture deployment version, alias, logical and physical stream, group,
   partition, offset, record UUID, status code, and redacted cause.
2. Determine whether failure occurred during decode, application work, cleanup,
   checkpoint, or native intake.
3. Keep the group cursor unchanged. Do not skip to the next record.
4. Determine which effects may already have committed and verify their idempotency
   keys.
5. Correct the codec/handler, restore the dependency, or deploy a compatible
   schema reader.
6. Replace or restart the application. The current Tori Py runtime has no hot
   resume API for a blocked partition.
7. Verify the same record is redelivered or that an already-advanced uncertain
   checkpoint is reconciled.
8. Confirm readiness only after all required partitions return to running.

If the source record is permanently invalid, abandoning it is a governed data-loss
decision. Use a checkpoint migration or new consumer group with an audit record;
there is no poison skip API.

## Recover Checkpoint Uncertainty

When a save, store, or query times out, is cancelled, or loses its connection:

1. Stop every old owner and fence it from further writes.
2. Assume handler effects may have completed.
3. Assume either old or new cursor may be durable.
4. Query the external store under a new exact fence, or use approved broker
   tracking diagnostics.
5. Compare observed progress with the failing record and effect idempotency state.
6. Resume only with a handler safe for redelivery or already-advanced progress.
7. Retain the incident evidence; do not rewrite uncertainty as a definitive
   failure.

For RabbitMQ, broker tracking is `(offset << 1) | kind`. Never inspect or edit it
as a raw application offset. There is no public high-level checkpoint reset API.

## Recover a Retention Gap

1. Stop all owners of the affected group.
2. Record the stale cursor and the current low watermark for every affected
   partition.
3. Quantify the missing range and downstream effects.
4. Restore/replay from an authoritative source into a compatible replacement
   stream when complete history is required.
5. Rebuild disposable projections from their authoritative database when
   possible.
6. If loss is accepted, create a versioned new group using `Beginning()` or
   administratively install a governed initialized cursor in the external store.
7. Preserve the old group/checkpoint for forensics.
8. Increase effective retention or reduce recovery time before resuming normal
   operation.

Do not change the configured start on the old group and expect it to override an
existing stale checkpoint. Existing progress always wins until explicitly
migrated.

## Recover a Publication

### Confirmed

Treat `CONFIRMED` only as the adapter's broker-acceptance fact. Continue using the
record UUID as the downstream idempotency identity.

### Runtime Saturation

`StreamPublicationSaturatedError` means Tori Py rejected admission before adapter
I/O. A bounded caller may retry after capacity returns, but must still use a
finite deadline and must not spin.

### Adapter Backpressure

RabbitMQ `BACKPRESSURED` with `local-admission-rejected` means adapter admission
rejected the call before native send. Reduce ingress, drain accepted work, or
adjust count/byte limits after capacity testing.

### Timed Out, Cancelled, or Indeterminate

Do not automatically resend. Broker acceptance may have happened.

The RabbitMQ adapter currently propagates `CancelledError` without a receipt and
without a public before-send/after-send phase. Treat cancellation conservatively
as acceptance-unknown, including cancellation caused by application shutdown.

An application-owned outbox should retain:

- Record UUID.
- Stream alias and partition key.
- Encoded business operation or reconstructable payload.
- Named producer name and publishing ID when used.
- Last receipt outcome and confirmation facts.
- Reconciliation and retry decision.

An intentional named retry must reuse the same record UUID, producer name,
partition key, and publishing ID. A RabbitMQ restart may still yield
`INDETERMINATE` because broker sequence state does not prove content association.
Unnamed publication has no exact append deduplication; reusing only the UUID can
append another occurrence.

## Recover RabbitMQ Loss

The RabbitMQ adapter disables automatic driver recovery and fails closed on a
producer, tracker, metadata, or consumer connection loss.

1. Remove the failed instance from readiness immediately.
2. Stop or terminate it and prove it cannot resume callbacks or checkpoint writes.
3. Recover broker nodes, routing, DNS/load balancer, certificates, disk alarms,
   and replicas.
4. Complete broker health and topology preflight again.
5. Reconcile in-flight publication and checkpoint uncertainty.
6. Start a fresh application/adapter instance.
7. Watch SAC ownership, cursor resume, duplicate handling, and readiness.

Do not call `start()` again on the failed adapter. Do not overlap a replacement
with an unproven old single-instance process.

## Recover a Topology Conflict

The adapter intentionally does not resize or repair topology.

1. Stop application declaration and intake for the affected logical stream.
2. Compare expected kind, physical partitions, binding keys, router, and key
   encoding with broker facts.
3. Correct accidental empty topology only through approved infrastructure tools.
4. For a real compatibility change, create a versioned logical stream and migrate
   producers, retained data, checkpoints, and consumer groups deliberately.
5. Do not rename only the application alias while silently changing the physical
   contract.

## Shutdown

Normal Tori Py shutdown closes publication admission, calls adapter `quiesce()`,
drains admitted work, then closes resources. Configure an application shutdown
deadline long enough for:

```text
native intake fence
+ longest allowed handler
+ work-scope cleanup
+ checkpoint deadline
+ publication confirm deadline
+ resource close reserve
```

At the deadline, handler cancellation leaves an uncheckpointed record replayable.
Checkpoint cancellation remains indeterminate. Cancellation of an admitted
publication can also leave broker acceptance unknown and may surface as
`CancelledError` without a receipt; recover it through the publication procedure
above. A RabbitMQ quiesce waits for an in-flight delivery to complete before
unsubscribe; forced shutdown must retain a finite outer deadline.

Do not use direct `close()` as a graceful-drain substitute. Direct close cancels
and observes admitted tasks before adapter resource closure.

## Data Safety Limits

- Persistent streams are not a backup. RabbitMQ retention can permanently remove
  history.
- Replication and placement are operator policy, not adapter-verified facts.
- A confirm is not per-message fsync or consumer completion.
- SAC is not a transaction.
- External checkpoints are not atomic with effects or broker ownership.
- Named producer deduplication is append-boundary behavior, not exactly-once
  handling.
- Finite reads add hidden RabbitMQ barrier records and require write permission.
- Public RabbitMQ bounds are unavailable.
- The adapter provides no stream restore, group reset, poison skip, topology
  migration, or administration dashboard.

## Verification Commands

Run the broker-free example and package suites through `uv`:

```console
uv run python -m examples.tori_py.persistent_streams.app
uv run pytest examples/tori_py/persistent_streams
uv run pytest packages/tori-py-persistent-streams-core/tests
uv run pytest packages/tori-py-persistent-streams/tests
uv run pytest packages/tori-py-persistent-streams-rabbitmq/tests
```

RabbitMQ-marked tests are skipped unless `RPS0_RABBITMQ=1`. They use the
repository's disposable RabbitMQ 4.1 Docker Compose environment. In PowerShell:

```powershell
$env:RPS0_RABBITMQ = "1"
uv run pytest packages/tori-py-persistent-streams-rabbitmq/tests
Remove-Item Env:RPS0_RABBITMQ
```

The broker tests can delete test topology, stop and start the broker application,
and clean Docker volumes. Run them only against the disposable environment.

Run focused quality checks with `uv`:

```console
uv run ruff check .
uv run ruff format --check .
uv run ty check packages/tori-py-persistent-streams-core/src packages/tori-py-persistent-streams-core/tests packages/tori-py-persistent-streams/src packages/tori-py-persistent-streams/tests packages/tori-py-persistent-streams-rabbitmq/src packages/tori-py-persistent-streams-rabbitmq/tests examples/tori_py
```

Before an unconditional RabbitMQ release claim, the remaining NACK,
disconnect/checkpoint, blackhole, TLS rotation, external-store fencing, Super
Stream movement, multi-node failover, complete conformance, and residual-risk
gates must also pass.

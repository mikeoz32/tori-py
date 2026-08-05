# MS10: Failure Recovery and Hardening

## Status

In progress; not complete. Current remediation covers typed publication
failures, strict protocol rejection, bounded delayed retry/DLX, deterministic
disconnect fencing, broker application restart with topology/consumer recovery,
generation-fenced stale settlement, bounded recovery listeners, and additional
shutdown cleanup tests. Network blackhole, reconnect at request/reply/ACK
boundaries, forced shutdown, complete observability/security guidance, and
broader fault injection remain unverified or unfinished.

## Purpose

Prove bounded, explicit behavior across network, broker, task, codec, settlement,
and shutdown failures before declaring the transport production-capable.

## Required Failure Distinctions

- Publication rejected before broker acceptance.
- Mandatory unroutable publication.
- Publisher-confirm NACK.
- Publication outcome unknown after connection loss.
- Local timeout before any request bytes are written.
- Timeout/cancellation while a publisher confirm is pending.
- Request accepted but local caller timed out/cancelled.
- Handler failed before any durable effect.
- Handler committed but reply/ACK outcome is unknown.
- Reply published but original request redelivered.
- Delivery permanently rejected or dead-lettered.
- Consumer connection lost with unsettled deliveries.
- Reply consumer lost with pending requests.
- Application shutdown cancelled active work.

These states are not collapsed into a generic timeout or success.

## Reconnect Contract

- Framework consumers and declarations opt out of automatic aio-pika robust
  replay; the recovery coordinator revalidates topology before reopening intake.
- RabbitMQ application restart recovery must preserve the configured broker
  endpoint, redeclare framework topology, and reopen consumers before reporting
  the manager ready.
- Old delivery tags are never settled on replacement channels.
- Unsettled old-channel messages may redeliver with the same message ID.
- Client reply reconnect fails all old pending requests as outcome unknown.
- New client requests wait for a completely ready replacement reply route.
- No accepted/uncertain RPC request is automatically republished.
- Event retry preserves message identity when application policy initiates it.

## Bounds

Configuration must bound:

- payload and encoded envelope size;
- header count, key/value size, and aggregate bytes;
- nesting depth and decoded collection sizes;
- RPC timeout and maximum accepted server deadline;
- service concurrency and prefetch;
- total prefetch/accepted callbacks across all consumers;
- pending RPC request count;
- in-memory queue capacity;
- accepted task count;
- publisher retry attempts before acceptance;
- broker delivery attempts and dead-letter path;
- reconnect backoff and status logging rate;
- graceful shutdown and cancellation waits.

## Shutdown Faults

- Consumer cancellation timeout does not admit new work.
- Handler cancellation remains cancellation through scope cleanup.
- Settlement attempted on a dead channel is not reported as success.
- Lingering tasks/resources are observed and logged with stable diagnostic codes.
- First failure is retained while all bounded cleanup is attempted.
- No cleanup continues unobserved after public shutdown returns.

## Observability

- Structured logs include safe service, message, handler, attempt, and outcome
  fields.
- Metrics use bounded aliases/status classes, never payloads or user identity.
- Status transitions are distinct and deduplicated.
- Correlation/causation and optional validated W3C trace headers propagate
  explicitly.
- Secrets, RabbitMQ credentials, reply tokens, payloads, and remote internal
  errors are redacted.

## Security Hardening

- TLS options and verification failures are typed and safely represented.
- Reply routes are generated/validated and cannot choose arbitrary exchanges.
- JSON decoding rejects unsafe/oversized input before target construction.
- Routing identity is cross-checked against envelope identity.
- Broker metadata is never an authorization decision.
- Documentation defines per-service vhost permissions and least privilege.

## Failure-Injection Tests

- Network disabled before connect, during publish, while waiting for confirm,
  during handler, during reply, and before ACK.
- Downstream/upstream blackhole bounded by heartbeat/deadline.
- Broker restart with queued and in-flight work.
- Consumer channel close and stale delivery tag.
- Reply queue deletion/expiry with pending requests.
- Unroutable reply attempts terminal ACK without intentional requeue; ACK
  uncertainty may still redeliver the request.
- Publisher NACK and mandatory return.
- Poison payload, unknown schema, and repeated retry to DLX.
- Process cancellation at every lifecycle boundary.
- Saturated queue, semaphore, pending map, and shutdown budget.
- Duplicate handler effect demonstrates required application idempotency.

## Exit Criteria

- Every tested failure maps to one documented typed outcome.
- No test depends on unbounded sleeps or silently dropped tasks.
- Indeterminate outcomes are never reported as success or automatically retried.

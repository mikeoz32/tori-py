# MS7: RabbitMQ Foundation and Topology

## Status

Implemented. Lazy configuration, owned connection/channels, deterministic
topology, confirms/returns, and framework recovery coordination are present.
Normal broker paths have Docker-backed coverage; broker restart and blackhole
recovery are not proven and remain MS10 work.

## Purpose

Implement owned aio-pika resources and deterministic topology without yet
coupling RabbitMQ callbacks to RPC or event business handlers.

## Configuration

- Immutable `RabbitMqOptions` with exactly one AMQP URL, connection name,
  heartbeat, TLS, reconnect, channel, and topology defaults.
- Secrets are redacted from representations and diagnostics.
- `RabbitMqModule.for_root(options, key="default")` owns one robust connection.
- Async factory configuration uses normal Nestpy annotation-driven DI.
- `RabbitMqTransport(key=...)` refers to one configured root without carrying
  credentials in handler metadata.
- Initial defaults are RabbitMQ 4.0+, 60-second heartbeat, 10-second connection
  timeout, and aio-pika's fixed bounded 5-second reconnect interval.
- Endpoint rotation/failover across several URLs is deferred because aio-pika
  robust reconnect targets its original URL.

## Resource Ownership

- Connection acquisition occurs during singleton resource startup.
- One robust connection is shared per root.
- Consumer, publisher-confirm, and reply concerns use separate channels.
- Publisher channels enable confirms and mandatory return handling.
- Consumer channels use manual acknowledgement and per-consumer QoS.
- Channel and connection close are idempotent and bounded by Nestpy lifecycle.
- Delivery tags are settled only on their receiving channel.

## Topology Compiler

The compiler produces immutable declarations for:

- durable topic exchanges;
- durable quorum RPC/event queues;
- classic exclusive auto-delete reply and ephemeral broadcast queues;
- exact bindings and queue arguments;
- optional reliable-broadcast queues;
- stable diagnostic labels independent of credentials.

Topology naming follows the governing architecture exactly. Names are bounded
for RabbitMQ limits and reject invalid aliases before connection.

## Declaration Semantics

- Exchanges, queues, and bindings are declared before intake.
- Existing equivalent topology is reused.
- RabbitMQ inequivalent-argument/channel errors fail startup with actionable
  typed diagnostics.
- Queue type is never migrated automatically.
- Delivery limits, dead-letter resources, and delayed retry resources are
  currently declared as deterministic topology; existing broker topology must
  use equivalent arguments.
- Framework declarations and consume registrations opt out of aio-pika robust
  replay with `robust=False`; the framework recovery coordinator re-declares
  the same immutable topology before intake.

## Publication Semantics

- Publisher confirms distinguish broker ACK and NACK.
- Mandatory publication distinguishes returned unroutable messages.
- Connection/channel loss before a definitive result is indeterminate.
- A successful confirm does not claim consumer presence or execution.
- Retry is never implicit after an indeterminate application-visible publish.

## Status and Recovery

- Status reports connecting, ready, reconnecting, failed, quiescing, and closed
  states as appropriate.
- Recovery callbacks are owned and observed.
- Consumers do not resume until topology and application intake are ready.
- Reply recovery always declares a newly generated non-robust queue and route;
  old reply identities are never replayed.
- Native `unwrap()` exposes typed aio-pika objects as an explicit escape hatch.

## Callback Handoff

- Each aio-pika callback enters a short adapter handoff barrier, checks
  admission, transfers an accepted delivery to one runtime-owned processing
  task, then leaves the handoff barrier before awaiting that task.
- Callback tails awaiting processing tasks are counted separately; no callback
  spawns work and returns detached.
- After `Basic.CancelOk`, shutdown crosses an event-loop scheduling fence so all
  callbacks scheduled before cancellation have entered or completed, then waits
  for the short handoff barrier.
- Shutdown drains/cancels processing tasks before waiting for callback tails;
  this ordering cannot deadlock on callbacks awaiting those tasks.

## Tests

- Optional dependency absent/present imports.
- Owned connection/channel acquisition and reverse close.
- Sync/async DI configuration and redacted failures.
- Exact exchange/queue/binding declarations against real RabbitMQ.
- Queue-type and argument mismatch startup failure.
- Confirm ACK/NACK, mandatory return, and connection uncertainty.
- Channel affinity and duplicate settlement rejection.
- Broker restart/reconnect and topology restoration.
- Callback scheduled-before-cancel race, handoff/task/tail drain ordering, and
  no shutdown deadlock.
- Partial startup failure after each acquired resource.
- No leaked RabbitMQ connection after shutdown.

## Exit Criteria

- Real RabbitMQ topology can be prepared and recovered without application
  handler callbacks.
- The generic conformance transport boundary remains intact.

# RabbitMQ Persistent Streams Operations

## Broker Preflight

1. Run RabbitMQ 4.1 with `rabbitmq_stream` and
   `rabbitmq_stream_management` enabled and expose the native stream port.
2. Configure a stable endpoint or load balancer. Broker advertised hosts must be
   reachable by the application; set `advertised_host` to that endpoint.
3. Grant create/read/write and offset-tracking permissions for every logical and
   physical stream. Use `REQUIRE_EXISTING` when applications must not create
   topology.
4. Preflight effective finite age/byte retention, segment size, replicas, leader
   placement, disk alarms, page cache, and free disk through operator tooling.
   Adapter startup does not verify these policy facts.
5. Treat partition count, binding keys, router identity/version, and producer
   names as durable data contracts. Change them only through a migration.

## TLS and SASL

Provide a CA file through `RabbitMqTlsOptions`; contexts always require a trusted
certificate and hostname verification. A client certificate and key must be
provided together. `server_hostname`, when present, must equal the configured
advertised endpoint. Passwords are excluded from option representations and must
come from a secret provider.

The pinned regular producer/consumer API supports PLAIN and EXTERNAL. The pinned
Super Stream producer exposes only its default PLAIN mechanism, so Super Stream
configuration rejects EXTERNAL. Real certificate-chain acceptance, rotation, and
mutual-TLS tests remain environment-specific RPS7 operational gates.

## Recovery

- Never retry a timed-out or indeterminate publication automatically. Retry only
  with the same record ID and named producer coordinate when the caller owns that
  decision.
- Broker tracking values are tagged uint64 cursors, not data offsets. Do not edit
  them as raw offsets.
- A retention gap stops the partition. Restore required history or intentionally
  establish a new group/cursor; the adapter never clamps.
- On broker loss, the adapter fails closed. Driver automatic recovery is disabled
  because it cannot be fenced through cursor preparation. Replace the adapter or
  application instance after recovery. Monitor blocked partition statuses, publish outcomes, confirm
  latency, callback pressure, disk alarms, retention low watermarks, and SAC
  ownership changes.
- Quiesce closes adapter admission before shutdown drain. Forced cancellation
  leaves uncheckpointed records replayable and checkpoint/publish uncertainty
  explicit.

## Deferred Release Gates

Induced NACK classification, disconnect-time checkpoint certainty, blackhole
faults, full Super Stream SAC movement, real TLS certificate acceptance/rotation,
and multi-node placement/failover remain mandatory before unconditional release.

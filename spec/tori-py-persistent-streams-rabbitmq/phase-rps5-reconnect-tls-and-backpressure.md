# RPS5: Reconnect, TLS, and Backpressure

Status: incomplete. Bounded admission/lifecycle, TLS context construction,
generation fencing, and fail-closed broker restart have focused coverage.
Transparent reconnect is unsupported; real certificate acceptance, blackhole
faulting, and disconnect-time outcome hardening remain gates.

## Requirements

- Close affected admission on loss and preserve definitive versus indeterminate
  publish/cursor outcomes.
- Generation-fence deliveries, confirms, consumer updates, stores, queries, and
  close callbacks.
- Driver automatic recovery is disabled. A disconnect fails admission/readiness
  closed and requires a new adapter instance.
- Bound pending publications/bytes, callback tasks, credit, reconnect backoff,
  operation deadlines, blackhole detection, and shutdown.
- Require certificate and hostname verification in production; redact secrets.
- Quiescence closes admission before draining accepted work. Forced shutdown
  leaves uncertain publishes explicit and unprocessed records replayable.

## Exit Criteria

Broker restart, movement, blackholes, TLS failure, saturation, and shutdown cannot
bypass preparation, mutate from stale generations, or grow without bounds.

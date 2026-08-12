# RPS4: SAC, Starts, and Resume Cursors

Status: incomplete. Beginning, barrier-based end, exact-offset, explicitly
single-instance broker checkpoints, and shared-store external takeover have
focused coverage. Timestamp and relative time remain rejected.

## Requirements

- One SAC identity per logical stream, group, and physical partition.
- Delivered offsets are non-negative, strictly increasing, serial, and may have
  gaps; regression or partition mismatch stops intake.
- Beginning, end, and exact offset are enabled. Timestamp and relative time are
  rejected adapter capabilities until exact append-time semantics are proven.
- Native clamp or retention loss raises a typed gap. If it cannot be detected,
  the mode is rejected at startup rather than weakened.
- `ResumeCursor` is either an initialized inclusive start cursor or the last
  successfully processed record offset.
- Broker tracking stores `(offset << 1) | kind`, with initialized `0` and
  last-successful `1`; offsets above `2^63-1` are rejected.
- Broker cursor query/create happens only after active SAC activation. Subscribe
  inclusively and discard offsets `<=` only for last-successful.
- `END` confirms a PSRM barrier, observes its delivered offset, then initializes
  after that control. It never derives an end from chunk metadata.
- External and broker strategies never substitute for one another.
- Decode, pipeline, handler, filter, cleanup, ownership, store/query, timeout,
  disconnect, or retention failure stops the partition and leaves its prior
  cursor unchanged after a definitive failure. Timeout, cancellation, or
  disconnect is indeterminate and may leave either cursor observable. Filters
  never create eligibility from failure.
- Credit and callback queues are finite.

Broker-managed checkpoints are supported only in explicitly configured
single-instance deployments. A shared external checkpoint store supports
multi-replica deployments only when every replica uses a replica-unique owner ID
and the store provides atomic fence replacement and exact-owner save validation.

## Exit Criteria

Multi-replica failover resumes from exact safe tagged cursors with sparse offsets,
at-least-once replay, no silent clamp, and no unsafe start combination.

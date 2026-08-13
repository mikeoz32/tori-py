# PS1: Records, Routing, and Log Contracts

Status: implemented.

## Entry Criteria

- PS0 exit criteria pass.

## Deliverables

- Immutable validated stream definitions, limits, append requests,
  `PublishReceipt`, stored records, optional available bounds, and bounded pages.
- Typed values for beginning, end, exact-offset, timestamp, and relative-time
  starts.
- Deterministic `PartitionRouter` protocol with a hashable `compatibility_key`
  and versioned SHA-256 default router.
- Asynchronous stream declaration, append, optional available-bound, and partition-read
  protocols.
- Optional named producer coordinates and publishing-ID failure types.
- Typed validation, configuration, offset, and retention-gap errors.

## Invariants

- Every record has a UUID, non-empty byte partition key, opaque byte payload,
  and immutable string-to-bytes headers.
- Logical stream names are stable and partition counts are positive and
  immutable after declaration.
- A stream defensively copies and freezes its copyable immutable-value router;
  compatibility includes a snapshot of its identity and compatibility key;
  the default uses the complete SHA-256 digest as an unsigned big-endian integer
  modulo partition count.
- Partition offsets are non-negative, strictly increasing, may contain gaps, and
  order only that partition.
- Append timestamps are aware and non-decreasing within partition offset order.
- Reads are inclusive by offset, finite, partition-local, and ordered.
- Available bounds, where supported, are read cursors and never append evidence.
- Empty reads do not imply end of stream and no API exposes `last_chunk`.
- Named publishing IDs are scoped by producer, logical stream, and selected
  physical partition; unnamed mode stores no publishing IDs.
- Append returns a receipt with `record_id`, selected partition, and confirmation
  facts/outcome, never an offset or stored record.
- Start modes apply only when no checkpoint exists; exact offsets are inclusive.
- A timestamp at or before retained history's time boundary reports a gap after
  trimming; a target beyond removed history resolves normally.
- Relative ages do not exceed `max_relative_age_days`, and resolution cannot leak
  datetime overflow from an aware clock.

## Failure Behavior

- Invalid UUIDs, keys, bytes, headers, timestamps, integers, limits, stream names,
  and partition numbers fail before mutation.
- Incompatible stream redeclaration raises a typed configuration error.
- Reads known to precede retained history raise typed `RetentionGapError` rather
  than clamping.
- Conflicting or stale publishing-ID use raises typed errors without append.
- The public log protocol exposes immutable per-start-mode capabilities.
  Unsupported start modes fail capability validation before ownership or intake;
  timestamp or relative
  starts that could hide removed history report a retention gap and never clamp.

## Tests

- Byte copying, immutable headers, value equality, and validation boundaries.
- Stable routing vectors, caller-mutation snapshots, non-copyable router
  rejection, and keys routed across multiple partitions.
- Sparse offset ordering, available-bound semantics, and finite read validation.
- Every start value, aware-time requirement, timestamp ties, and future target.
- Timestamp resolution at retained and fully trimmed time boundaries.
- Named producer exact retry, mismatched retry, stale ID, allowed ID gaps, and
  producer-scope isolation.
- Public API has no global-position, cross-partition batch, or last-chunk type.

## Exit Criteria

- PS1 values and protocols pass without consumer, in-memory storage, framework,
  or infrastructure dependencies.

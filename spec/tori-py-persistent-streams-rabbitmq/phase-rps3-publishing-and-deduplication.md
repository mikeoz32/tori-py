# RPS3: Envelope, Publishing, and Deduplication

Status: incomplete. Named/unnamed coordinate isolation is covered, while durable
cross-restart content association remains unsupported.

## Canonical Envelope

Freeze version 2 before publication: canonical UUID `message-id`, required content
type, and one deterministic binary body. The body contains `PSRM`, version 2,
record/barrier kind, UUID bytes, length-prefixed partition key,
UTF-8-byte-sorted length-prefixed headers, and the length-prefixed payload.
Barriers cannot surface as records.

Bad magic/version, duplicate or non-canonically ordered names, invalid UTF-8,
truncation, trailing bytes, and limit violations fail decoding. Unknown transport
fields are ignored. All component and total encoded sizes are finite.

## Publishing

- Use the stream's frozen deterministic router; the versioned SHA-256 core router
  is the default, not a universal adapter mandate.
- Realize the selected Super Stream partition through its exact binding key.
- Return `PublishReceipt(record_id, partition, outcome, confirmation facts)` with
  no offset or `StoredRecord`.
- Fully support unnamed mode without ID storage or producer exclusivity.
- Named mode uses one producer per `(physical stream, producer name)` and a
  separate unnamed producer. IDs increase within that coordinate.
- Broker sequence without durable content association is indeterminate after
  restart and is never silently reported as equivalent content.
- All publish surfaces accept explicit `record_id`; configured publishers generate
  a UUID only when omitted.
- No automatic retry. Exact indeterminate retry requires the same `record_id` and
  producer coordinate/handle.
- Bound pending count/bytes, confirms, callback state, deadlines, and shutdown.

Publication does not coordinate all writers, reserve or infer record positions,
or impose a logical cross-partition publishing-ID sequence.

## Exit Criteria

Real-broker named and unnamed publication proves envelope interoperability,
partition routing, receipt facts, exact retry, uncertainty, and bounded pressure.

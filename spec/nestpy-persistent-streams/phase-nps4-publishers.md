# NPS4: Publishers

## Status

Complete.

## Purpose

Expose raw, named configured, and Protocol-token publication without allowing
callers to alter deployment compatibility policy.

## Global Publisher

- Root exports one managed singleton `StreamPublisher` globally.
- `publish(binding_alias, payload, ...)` accepts only configured aliases.
- It accepts optional explicit `record_id`; a UUID is generated only when omitted.
- It uses the binding's codec, partition resolver, producer identity,
  publishing-ID source, metadata limits, and adapter.
- Arbitrary physical stream names, encoded-byte shortcuts, and native options
  are rejected.

## Named Publishers

- A deterministic token resolves one `ConfiguredStreamPublisher[PayloadT]`.
- Stream alias is absent from its publish method.
- Payload annotation is checked against the configured payload contract.
- Named tokens are unique and available through normal global Nestpy visibility.

## Protocol Publishers

- Applications register explicit `typing.Protocol` tokens.
- Every method is async and has explicit `@stream_publish(payload=...)` metadata.
- Payload parameters are required and cannot declare defaults.
- Signatures, payload construction, metadata markers, return annotations, and
  duplicate method aliases compile before startup.
- One dynamic proxy is injected under the Protocol token and delegates to the
  same configured publisher.
- Python method names never infer streams or schemas.

## Outcome Contract

- All APIs return `PublishReceipt`; its typed outcome distinguishes confirmed,
  rejected, timed-out, closed, saturated, and indeterminate publication.
- Receipts contain `record_id`, selected partition, and confirmation facts, not
  an offset or `StoredRecord`.
- Exact retry after an indeterminate outcome requires caller reuse of
  `record_id` and the same producer coordinate/handle.
- No accepted or indeterminate publication is automatically retried.
- Confirmation never claims consumer handling.
- Publication admission closes before runtime quiescence drains accepted calls.
- Admission above `max_pending_publications` raises the typed
  `StreamPublicationSaturatedError` before adapter I/O.

## Tests

- Global, named, and Protocol DI across several modules.
- Unknown alias, payload mismatch, bad Protocol, and token-collision diagnostics.
- Fixed configuration cannot be overridden through any surface.
- Metadata binding and normal Python positional/keyword errors.
- Confirm/reject/timeout/indeterminate mapping through a fake adapter.
- Concurrent admission, close races, and bounded shutdown drain.

## Exit Criteria

- All three publisher forms share one lifecycle-managed runtime and immutable
  binding policy.

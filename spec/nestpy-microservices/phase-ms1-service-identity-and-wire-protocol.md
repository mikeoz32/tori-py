# MS1: Service Identity and Wire Protocol

## Status

Implemented. Immutable identities, bounded envelopes and metadata, typed wire
errors, and the msgspec JSON codec have focused tests in the package suite.

## Purpose

Define stable transport-neutral identities, envelopes, codecs, deadlines, and
remote failures before handlers or transports can depend on ambiguous wire data.

## Public Contracts

- `ServiceIdentity(namespace, name, contract_version)`.
- `RpcTarget(service: ServiceIdentity, method, schema_version)`.
- `EventIdentity(source: ServiceIdentity, event, schema_version)`.
- `MessageMetadata` with message, correlation, causation, timing, and bounded
  header data.
- Immutable `MessageLimits` shared by server and client options.
- `RpcRequestEnvelope`, `RpcResponseEnvelope`, and `EventEnvelope`.
- `RemoteRpcErrorData` and public client-side remote error.
- `MessageCodec` protocol and `MsgspecJsonMessageCodec` default.
- Typed configuration, encoding, decoding, size, deadline, and remote errors.

## Identity Rules

- Namespace, service, RPC method, subscription, and single-segment event aliases
  match `[a-z][a-z0-9_-]{0,62}`.
- Generated instance/reply tokens have separately specified lowercase ASCII
  grammars; user aliases can never contain `.`, `*`, or `#`.
- Every composed exchange, queue, binding, and routing key is at most 255 UTF-8
  bytes and fails locally before broker access when it would exceed that bound.
- Contract and schema versions are positive integers.
- Python module/class paths, object identities, hashes, and inferred function
  names are not published identities.
- IDs use canonical UUID text and UTC timestamps are timezone-aware.
- Equality and hashing depend only on normalized immutable fields.

## RPC Request Contract

The encoded request carries exactly:

```text
message_id, kind, namespace, service, contract_version, method,
schema_version, created_at, deadline_at, correlation_id, causation_id,
reply_to, headers, payload
```

- `kind` is a fixed discriminant.
- `deadline_at` is required and later than `created_at` at creation time.
- Client configuration bounds the maximum accepted deadline.
- `correlation_id` is required for request-response.
- `causation_id` is an optional transport fact.
- `message_id` remains stable across redelivery but is not business idempotency.
- `reply_to` is opaque to application handlers and has the exact generated
  `reply.<32-lowercase-hex>` routing-key form.

## RPC Response Contract

- Response correlation must match one request.
- Exactly one of `result` or `error` is encoded.
- Remote errors expose stable code, sanitized message, retryable flag, and
  bounded safe details.
- Python exception paths, tracebacks, exception objects, and arbitrary arguments
  are prohibited.

## Event Contract

- Event source identity is explicit and immutable.
- Event alias and schema version are independent fields.
- `occurred_at` describes the producer fact time, not broker enqueue time.
- Event metadata permits correlation and causation IDs without requiring them to
  equal HTTP request IDs.
- Consumer delivery attempts are transport metadata and are not persisted into
  the producer envelope.

## Codec Contract

- The default codec is deterministic msgspec JSON encoded as UTF-8 bytes.
- Decoding first validates envelope shape and limits, then decodes payload to the
  compiled target annotation.
- Encoding validates the declared response/event contract.
- Unknown fields, optional fields, and schema evolution follow explicit codec
  policy; they are never silently guessed from Python defaults.
- Payload and header byte limits are checked before expensive typed decoding.
- Pickle and arbitrary object serialization are prohibited.

## Invalid Input

- Missing or duplicate required fields.
- Unknown message kind.
- Invalid aliases or versions.
- Naive, malformed, non-UTC, or impossible timestamps.
- Expired request creation and deadlines beyond configured maximum.
- Invalid UUID, reply route, header type, or header key.
- Oversized body, headers, nesting, or collection count.
- Response containing both or neither result/error.
- Unserializable or annotation-incompatible payload/result.

## Tests

- Identity normalization, equality, hashing, and invalid segment matrix.
- Deterministic request/response/event golden bytes.
- Round trips for supported primitive, dataclass, and msgspec payloads.
- Unknown/malformed/oversized input rejected before target construction.
- Exact result/error exclusivity and safe remote-error rendering.
- Deadline calculations and boundary values.
- Header defensive copies and deep immutability.
- No Python path or sensitive accidental representation in wire failures.

## Exit Criteria

- Wire contracts are stable enough for in-memory and RabbitMQ transports to use
  without transport-specific Python objects.
- No later phase needs to serialize application exceptions or infer durable
  aliases.

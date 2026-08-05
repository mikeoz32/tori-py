# MS8: RabbitMQ RPC Service Cluster

## Status

Implemented. The service queue/wildcard route, competing-consumer endpoint,
deadline admission, confirmed reply-before-ACK flow, and bounded retry/DLX
topology are present. Docker-backed round-trip, redelivery, unroutable publish,
and shared conformance tests exist; crash/restart boundary coverage remains
MS10.

## Purpose

Implement the Nameko-derived service-cluster topology: one wildcard-bound queue
per logical service and one competing consumer per replica.

## Exact Topology

```text
exchange:    nestpy.rpc
type:        topic
queue:       nestpy.rpc.<namespace>.<service>.v<contract_version>
binding:     <namespace>.<service>.v<contract_version>.*
routing key: <namespace>.<service>.v<contract_version>.<rpc_method>
```

- There is exactly one service binding, not one binding per RPC method.
- There is exactly one service queue, not one queue per method or controller.
- Every replica with the same `ServiceIdentity` consumes from that queue.
- Different services and incompatible contract versions use distinct queues.
- RPC method aliases are one topic segment so the wildcard matches exactly.

## Replica Consumer Contract

- One consumer registration per service replica.
- Equal consumer priority.
- No exclusive consumer or single-active-consumer.
- Manual acknowledgements.
- Bounded prefetch allocated from service-wide `max_inflight_deliveries` and no
  more than `max_concurrency` for the RPC consumer.
- One service-wide semaphore covers all RPC methods on the replica.
- A saturated replica cannot exceed its shared inflight/concurrency windows.
- Distribution is described as competing-consumer balancing, not guaranteed
  strict round-robin.

## Request Dispatch

1. RabbitMQ routes the method-specific key through the service wildcard binding.
2. One eligible replica receives the delivery.
3. Transport validates envelope routing identity against native routing key.
4. Runtime rejects expired/malformed requests before a work scope.
5. Runtime finds the explicit `@rpc` alias in its immutable registry.
6. Known method executes through its exact module work scope and pipeline.
7. Unknown method produces a typed `method_not_found` response.

An unknown service/version has no route and mandatory confirmed publication
raises `UnknownServiceError`. A durable stale service queue can remain routable
without consumers; that condition resolves through deadline timeout, not a
false live-membership claim.

## Deadline-Bound Backlog

- Client sets per-message RabbitMQ expiration from the remaining call budget.
- Server compares `deadline_at` before provider/controller resolution.
- Expired requests perform no application work.
- Queue delay reduces the handler's remaining deadline.
- A newly started replica may process only requests whose deadlines remain
  valid.
- Admission of a non-expired request is final: reaching the deadline afterward
  does not cancel its handler or imply rollback.
- Expiry/timeout never invites an automatic retry with a new message or
  idempotency ID.

## Response and Settlement

1. Pipeline produces an encoded result or sanitized error response.
2. Work-scope cleanup completes successfully.
3. Response is published to the validated reply route with `mandatory=True` and
   confirms.
4. Confirmed and routed publication permits ACK of the original request.
5. Publisher NACK or connection/confirm uncertainty leaves the request
   unacknowledged.
6. Mandatory return proves the reply route is gone and attempts terminal ACK
   with a `reply_route_gone` diagnostic instead of intentional requeue; ACK
   uncertainty may still redeliver.

Malformed envelopes, mismatched routing identity, and invalid reply routes reject
without requeue and never execute application work. A structurally valid request
with trusted correlation/reply route but unsupported schema receives a typed
`unsupported_schema` response. Known-method validation failures and ordinary
handler failures become sanitized responses, then follow the response rules
above. Scope-finalization failure overrides any provisional result/error and
leaves the request unsettled with no reply because durable effects may be
indeterminate. A response's `retryable` flag advises the caller; it never causes
broker requeue by itself. Other infrastructure failure before a definitive reply
outcome also leaves a valid request unsettled.

If the request connection closes after work or reply but before ACK, RabbitMQ
may redeliver to the same or another replica. RPC execution is therefore at
least once. Duplicate responses use the original correlation ID and are safely
discarded after the first client completion.

## Idempotency Contract

- Framework message IDs and correlation IDs do not provide exactly-once effects.
- Mutating service contracts decide whether an idempotency key is required.
- Application deduplication and state changes commit atomically where required.
- An indeterminate handler or settlement outcome does not generate a new key.
- Read-only handlers still tolerate duplicate execution where possible.

## Tests

- Exact one queue/one wildcard binding with several RPC methods.
- Two and three replicas consume one queue.
- Calls across methods share service-wide capacity.
- Bounded distribution with equal consumers and saturated replica behavior.
- Distinct services and contract versions never share queues.
- Unknown service versus unknown method.
- No active replicas, queued request, restart before deadline, and expiry after
  deadline.
- Crash before handler, during handler, after scope, after reply confirm, and
  before ACK.
- Redelivery to another replica and stable IDs.
- Duplicate response and late response handling.
- Reply publish NACK and connection uncertainty leave the request unsettled;
  unroutable reply attempts terminal ACK without intentional requeue, while ACK
  uncertainty remains eligible for redelivery.
- Graceful quiesce stops intake and drains accepted RPC calls.

## Exit Criteria

- A real RabbitMQ deployment can add/remove replicas without client-side service
  discovery or topology changes.
- One wildcard-bound service queue remains the sole RPC balancing boundary.

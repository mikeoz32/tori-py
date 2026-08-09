# MS6: ServiceCluster Client and Replies

## Status

Implemented. Keyed client registration, immutable service proxies, finite RPC
deadlines, bounded pending calls, one reply router, and explicit uncertain
outcomes are present with focused tests.

## Purpose

Provide one asynchronous Python-native client for the complete logical service
cluster with shared reply routing, finite deadlines, and explicit uncertain
outcomes.

## Public API

```python
service = cluster.service(
    ServiceIdentity(namespace="kinker", name="members", contract_version=1)
)
result = await service.request(
    "resolve-profile",
    request,
    response_type=ResolveProfileResponse,
    schema_version=1,
    timeout=2.0,
    correlation_id=None,
    causation_id=None,
    headers=None,
)
```

`ClientsModule.register_cluster(transport, options=None, imports=(), key="default")`
registers the keyed singleton. `ServiceClusterOptions` owns finite default and
maximum RPC timeouts, pending-map capacity, immutable wire limits, and optional
default namespace and contract version. Defaults are 5 seconds, 30 seconds, and
1024 pending calls.

- `service("members", version=1)` requires a configured default namespace;
  `cluster["members"]` additionally requires a configured default version. The
  canonical key is a complete `ServiceIdentity`.
- Service proxies are immutable and cached by stable target identity.
- Explicit `request(method, ...)` is primary; arbitrary dynamic method
  attributes are not required.
- `emit()` belongs to the event dispatcher/client contract, not RPC request.

## Pending Request Contract

- Every request has a unique correlation ID.
- One bounded map stores pending waiters for all target services.
- Registration happens before publication so an immediate reply cannot race the
  map entry.
- One synchronized state machine owns publication, reply, timeout, cancellation,
  and close transitions; every transition completes/removes at most once.
- A validated immediate reply wins over a still-pending publisher confirm.
- Definitive pre-acceptance NACK/unroutable publication fails only an unresolved
  entry; confirm uncertainty is an indeterminate outcome.
- Local timeout/cancellation removes the entry but does not claim remote
  cancellation.
- Pending-map exhaustion rejects before publication.
- Completion/removal is exactly once under reply/timeout/cancel/close races.

## Deadline Contract

- Every call has a finite positive timeout bounded by client options.
- One monotonic deadline governs connection wait, publication, and reply wait.
- The encoded request also receives absolute UTC `deadline_at` and broker
  expiration derived from the remaining budget.
- Time spent connecting/publishing reduces reply wait; phases do not each get a
  fresh timeout.
- Timeout/cancellation before any write is local; while awaiting confirm it is
  indeterminate; after confirmed acceptance it is an accepted-request timeout.
- The transport does not model application idempotency; applications place any
  deduplication identity in their own request contracts.

## Reply Router

- One reply consumer is shared across all service proxies.
- Correlation lookup precedes typed result decoding.
- The registered response type controls result decode.
- Remote errors become stable client exceptions without importing server
  exception classes.
- Unknown, late, duplicate, timed-out, and cancelled replies are ACKed and
  discarded after bounded logging.
- Malformed replies complete a known waiter with protocol failure when
  correlation can be trusted, then ACK. Malformed replies with unknown or
  untrusted correlation are also ACKed and discarded. Poison replies are never
  requeued on the exclusive reply route.

## Disconnect and Close

- Reply transport loss completes every pending waiter with
  `RpcOutcomeUnknownError`.
- Pending requests are never automatically republished.
- A replacement reply route becomes ready before new request publication.
- Normal client close stops new calls, fails pending waiters deterministically,
  cancels reply intake, and releases resources.
- Use after close fails locally before publication.

## Nestpy Registration

- Client clusters are ordinary keyed singleton providers.
- Async configuration uses annotation-driven Nestpy factories.
- Managed roots own close; external preconstructed client instances remain
  externally owned unless explicitly registered as managed values.
- Named clusters expose qualified injection tokens; one documented default may
  expose an unqualified alias.

## Tests

- Concurrent calls to one and several services.
- Out-of-order replies and one shared reply consumer.
- Remote success, typed error, malformed response, and decoding failure.
- Timeout before connect, during publish, and during reply wait.
- Caller cancellation before/after broker acceptance.
- Immediate reply race and pending-map capacity.
- Unknown, late, duplicate, and repeated result access behavior.
- Disconnect with pending calls and successful readiness before reuse.
- Close races and exact provider resource ownership.

## Exit Criteria

- In-memory client calls are fully asynchronous, bounded, and reusable across
  services.
- No accepted or uncertain request is silently resent.

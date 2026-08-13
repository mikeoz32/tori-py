# NPS3: Pipeline and Checkpoints

## Status

Complete.

## Purpose

Decode one typed record, execute it in the exact handler-owner ToriPy pipeline
and work scope, and make checkpoint eligibility depend on complete success.

## Execution Contract

```text
bounded codec decode to declared DTO
-> fresh exact-owner work scope
-> guards
-> argument binding and pipes
-> interceptors
-> handler
-> interceptor unwind and filters
-> work-scope cleanup
-> checkpoint-eligible completion
```

- Global, controller, and handler enhancers execute in that order.
- Interceptors unwind in reverse order and `next` is one-shot.
- Provider-backed enhancers resolve lazily from the handler-owner scope.
- Context and resolver leases invalidate after scope closure.
- HTTP and microservices pipeline executors are not used.

## Partition Contract

- Processing is serial by physical partition.
- Different partitions may run concurrently under one finite application bound.
- A later delivered offset does not begin before the current record has a
  definitive cursor outcome; sparse offsets are valid.
- Malformed encoding, unsupported schema, oversized payload, or DTO validation
  stops the partition without checkpoint or skip.
- An ordinary handler or pipeline failure stops the partition immediately at
  the failed offset; reacquisition or restart redelivers that record.

## Checkpoint Contract

- Canonical `ResumeCursor` means an initialized inclusive start cursor or the
  last successfully processed record offset.
- Eligibility requires successful codec, pipeline, handler, interceptor unwind,
  and work-scope finalization.
- Checkpoint persistence happens outside the closed work scope.
- Failure or uncertainty stops the partition and is never guessed successful.
- Cancellation during checkpoint persistence is an unknown outcome unless the
  adapter reports a definitive result; the runtime blocks that partition and
  preserves `CancelledError` for shutdown.
- A retention gap raises a checkpoint-expired outcome; silent clamp is invalid.
- A filter cannot convert decode, pipeline, handler, or cleanup failure into
  checkpoint eligibility.

## Tests

- Exact pipeline and reverse-unwind order.
- Singleton/request/transient provider behavior and module visibility.
- No ambient HTTP, prior-record, or microservices context leakage.
- Body plus cleanup failure and cancellation plus cleanup failure.
- Decode/pipe/guard/interceptor/filter/handler failure classes.
- Serial partition order, finite cross-partition concurrency, and blocked peers.
- Cleanup-before-checkpoint callback ordering and checkpoint uncertainty.
- Immediate poison stop, duplicate replay after reacquisition, and
  effects-before-checkpoint crash.

## Exit Criteria

- A fake encoded record yields a typed completion sufficient for any adapter to
  checkpoint safely without inspecting ToriPy internals.

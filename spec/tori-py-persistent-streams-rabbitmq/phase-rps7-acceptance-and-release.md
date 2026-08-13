# RPS7: Acceptance and Release

Status: conditional after final structural review. Facade, documentation,
ordinary/Super Stream acceptance, repository tests, Ruff, format, Ty, and
artifact verification pass. Deferred RPS5/RPS6 operational and cluster gates
block unconditional release.

## Documentation

Document topology creation versus operator-owned policy/retention preflight,
router/version compatibility, canonical envelope, named and unnamed producers,
explicit record-ID retry, offset-free receipts, sparse consumed offsets, start
capabilities, tagged resume cursors, empty-stream `END` limitations, SAC, replay,
retention gaps, TLS, backpressure, operations, and RabbitMQ data-safety limits.

## Verification

- Run core and ToriPy conformance as separate gates.
- Run all real-cluster and fault-proxy tests through `uv` on Python 3.14.
- Run repository pytest, Ruff, format, ty, documentation, facade, dependency,
  wheel, sdist, and isolated-install checks.
- Complete driver, reliability, concurrency, security, operations, compatibility,
  and public-API review.

## Exit Criteria

Every RPS0 capability and later acceptance criterion passes from built artifacts.
Documentation makes no stronger offset, retry, verification, fsync, failover,
retention, or exactly-once claim than the public driver and broker prove.

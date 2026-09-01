# Changelog

Notable changes to each Tori Py distribution are documented here. Each package
uses independent [Semantic Versioning](https://semver.org/); a version change in
one package does not require the same change in every package.

## [Unreleased]

### Added

- Public package metadata, legal files, security policy, contribution guidance,
  and release documentation.
- Opt-in core `@no_body` route metadata with post-guard actual-stream enforcement
  and compatible trailing route-plan metadata.
- Typed request-lifetime raw HTTP body streaming with direct backpressured ASGI
  receiving, incremental limits, complete-consumption enforcement, and
  provenance-aware disconnect cancellation.
- OpenAPI bound-parameter schema/description refinement plus explicit response
  headers and per-response media types, including header-only 204 responses.
- Explicit singleton `@websocket_gateway` providers with native Starlette
  sockets, marker-only handshake binding, connection-owned request scopes, and
  the full middleware/guard/pipe/interceptor/filter pipeline.
- Separately installable `tori-py-liveview` integration with explicit
  request-scoped pages, signed mounts, Opal protocol-v2 structural diffs, and a
  checksum-pinned common browser client, now including connection-local stateful
  components, targeted component events, and browser-owned bounded streams.

### Fixed

- OpenAPI header parameter identities now follow case-insensitive HTTP semantics,
  and excessively nested annotations fail with typed schema diagnostics.

## [0.1.0] - Unreleased

Coordinated initial beta release train for all 13 distributions. This train
establishes public package boundaries and compatibility ranges; subsequent
releases are versioned independently.

The `tori-py-persistent-streams-rabbitmq` release is provisional and
conditional. Its operational limits, driver and broker requirements, checkpoint
constraints, and remaining deployment gates are documented in its package
README and operations guide.

[Unreleased]: https://github.com/mikeoz32/tori-py/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mikeoz32/tori-py/releases/tag/v0.1.0

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
  request-scoped pages, signed mounts, checksum-pinned official Phoenix and
  Phoenix LiveView clients, Channels/render-tree interoperability,
  connection-local stateful component CIDs, targeted component events, and
  browser-owned bounded streams, plus serialized connection-local server
  updates through `send_info` and `handle_info`.
- Separately installable `tori-py-liveview-ui` foundation with typed stateless
  display, layout, form, and validation-presentation helpers, a
  content-addressed immutable local stylesheet, and `UiLiveView` document
  theming plus editorial/minimal/rounded skinning for Phoenix LiveView pages.

### Fixed

- OpenAPI header parameter identities now follow case-insensitive HTTP semantics,
  and excessively nested annotations fail with typed schema diagnostics.
- Settings secrets wrapped in `Optional`, `| None`, or another union, and secrets
  inside optional nested models, are now protected from `--set` and other
  bootstrap overrides.
- LiveView `redirect()` now cleans its target, rejects non-http(s) schemes such
  as `javascript:`, and keeps redirects on the request host unless the host is
  listed in the new `LiveViewOptions.redirect_hosts`. Live navigation targets
  that browsers read as another host, such as `/\evil.example` or
  `///evil.example`, are no longer treated as same-origin.
- Value and factory providers that expose a class with method interceptors now
  fail instead of silently skipping the interceptors.
- LiveView `attrs()`, Template interpolation, and `rendered()` values, and the
  LiveView UI event options built on them, now reject data that would start or
  appear inside a `phx-*` value beginning with `[`, which the Phoenix client runs
  as JS commands.
- Swagger UI now loads its default CDN assets with pinned Subresource Integrity
  hashes. `SwaggerUiOptions` adds `javascript_integrity` and
  `stylesheet_integrity`, which are required for other absolute HTTPS asset URLs.

## [0.1.0] - Unreleased

Coordinated initial beta release train for all 14 distributions. This train
establishes public package boundaries and compatibility ranges; subsequent
releases are versioned independently.

The `tori-py-persistent-streams-rabbitmq` release is provisional and
conditional. Its operational limits, driver and broker requirements, checkpoint
constraints, and remaining deployment gates are documented in its package
README and operations guide.

[Unreleased]: https://github.com/mikeoz32/tori-py/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mikeoz32/tori-py/releases/tag/v0.1.0

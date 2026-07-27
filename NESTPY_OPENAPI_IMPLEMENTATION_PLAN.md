# Nestpy OpenAPI Implementation Plan

## Status

Implementation status: in progress on `feature/nestpy-openapi`.

Architecture: [`NESTPY_OPENAPI_ARCHITECTURE.md`](NESTPY_OPENAPI_ARCHITECTURE.md).

## Delivery Order

### OA0: Workspace and Nestpy Mapping Contract

- Add the `nestpy-openapi` workspace package and artifact contracts.
- Add `RoutePlan.return_annotation` as a trailing compatible field.
- Extract public `compile_controller_routes()` and make graph compilation reuse
  it.
- Add focused Nestpy mapping tests without changing `StarletteAdapter`.

### OA1: Configuration and Metadata

- Implement immutable options, errors, and direct metadata decorators.
- Freeze the exact package facade and import boundaries.

### OA2: Discovery and Document Compiler

- Inject `DiscoveryService` into a singleton document service.
- Compile discovered controllers through `compile_controller_routes()`.
- Generate and cache strict OpenAPI 3.1 JSON through msgspec.

### OA3: Dynamic Module, Controller, and Kinker

- Implement `OpenApiModule.for_root()` and its generated Nestpy controller.
- Serve cached JSON and Swagger UI through normal Nestpy route mappings.
- Import the descriptor in Kinker and document health operations.

### OA4: Acceptance

- Run full pytest, Ruff, format, ty, strict docs, and artifact smoke gates.
- Complete independent architecture/security/correctness review.

## Deferred Work

- ReDoc, self-hosted assets, YAML, callbacks, webhooks, OAuth flow builders,
  multipart/files, WebSockets, client generation, and parameter examples.

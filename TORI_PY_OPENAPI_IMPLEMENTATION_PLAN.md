# ToriPy OpenAPI Implementation Plan

## Status

Implementation status: OA0-OA4 complete on `main`.

Architecture: [`TORI_PY_OPENAPI_ARCHITECTURE.md`](TORI_PY_OPENAPI_ARCHITECTURE.md).

## Delivery Order

### OA0: Workspace and ToriPy Mapping Contract

- Add the `tori-py-openapi` workspace package and artifact contracts.
- Add `RoutePlan.return_annotation` as a trailing compatible field.
- Extract public `compile_controller_routes()` and make graph compilation reuse
  it.
- Add focused ToriPy mapping tests without changing `StarletteAdapter`.

### OA1: Configuration and Metadata

- Implement immutable options, errors, and direct metadata decorators.
- Add route-only parameter refinement metadata and per-response validated
  headers/media types.
- Freeze the exact package facade and import boundaries.

### OA2: Discovery and Document Compiler

- Inject `DiscoveryService` into a singleton document service.
- Compile discovered controllers through `compile_controller_routes()`.
- Generate and cache strict OpenAPI 3.1 JSON through msgspec.
- Match parameter refinements to compiled bindings and compile response-specific
  content keys and headers, including bodyless 204 responses.

### OA3: Dynamic Module and Controller

- Implement `OpenApiModule.for_root()` and its generated ToriPy controller.
- Serve cached JSON and Swagger UI through normal ToriPy route mappings.
- Demonstrate descriptor import, bearer security, and public health operations.

### OA4: Acceptance

- Run full pytest, Ruff, format, ty, strict docs, and artifact smoke gates.
- Complete independent architecture/security/correctness review.

## Deferred Work

- ReDoc, self-hosted assets, YAML, callbacks, webhooks, OAuth flow builders,
  multipart/files, WebSockets, client generation, and parameter examples.

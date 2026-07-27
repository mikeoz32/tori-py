# Nestpy OpenAPI Specifications

Governing documents:

- [`NESTPY_OPENAPI_ARCHITECTURE.md`](../../NESTPY_OPENAPI_ARCHITECTURE.md)
- [`NESTPY_OPENAPI_IMPLEMENTATION_PLAN.md`](../../NESTPY_OPENAPI_IMPLEMENTATION_PLAN.md)

## Phase Map

| Phase | Specification | Main result |
| --- | --- | --- |
| OA0 | [Workspace and mapping contract](phase-oa0-workspace-and-foundation.md) | Public per-controller route compiler |
| OA1 | [Configuration and metadata](phase-oa1-configuration-and-metadata.md) | Frozen options and decorators |
| OA2 | [Discovery and document compiler](phase-oa2-document-and-schema-compiler.md) | Cached OpenAPI from discovered controllers |
| OA3 | [Dynamic module and Kinker](phase-oa3-swagger-and-kinker.md) | Normal Nestpy docs controller |
| OA4 | [Acceptance](phase-oa4-acceptance-and-release.md) | Quality and artifact gates |

## Invariants

1. `nestpy-openapi` depends on Nestpy; Nestpy never depends on it.
2. Controller discovery uses `DiscoveryService`; no package scan or global
   registry exists.
3. Route mappings use public `compile_controller_routes()`; the package does not
   copy Nestpy path/binding compilation.
4. Documentation endpoints are ordinary Nestpy controller routes.
5. `StarletteAdapter` has no OpenAPI or extension-route API.
6. Generation happens once during singleton startup and fails closed.
7. Guards/errors are never inferred.
8. Runtime binding/encoding behavior is not changed by this package.
9. Every command uses uv.

# OA3: Dynamic Module and Application Integration

## Deliverables

- `OpenApiModule.for_root(options, key="default")`.
- Generated ToriPy controller at configured JSON/UI paths.
- Example module import, bearer component, public health metadata, and
  authenticated operation metadata.

## Invariants

- Dynamic-module identity and reuse follow normal ToriPy rules.
- The controller and service are singleton providers owned by the descriptor.
- JSON/UI requests pass through the normal ToriPy HTTP pipeline.
- Runtime duplicate/overlap/redirect behavior remains ToriPy/Starlette-owned.
- JSON and HTML use cached bytes; requests do no discovery/schema work.
- Swagger HTML safely encodes title, assets, and JSON configuration.

## Tests

- Descriptor shape, identity, options validation, and duplicate route behavior.
- Startup generation failure is fail-closed.
- JSON/UI content, HEAD, request ID, pipeline participation, and caching.
- Public health and authenticated example paths, bearer components, no global
  security, authenticated operation requirements, stable IDs/tags/summaries,
  and no self-doc routes.

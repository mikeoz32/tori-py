# OA3: Dynamic Module and Kinker

## Deliverables

- `OpenApiModule.for_root(options, key="default")`.
- Generated Nestpy controller at configured JSON/UI paths.
- Kinker module import, bearer component, and health metadata.

## Invariants

- Dynamic-module identity and reuse follow normal Nestpy rules.
- The controller and service are singleton providers owned by the descriptor.
- JSON/UI requests pass through the normal Nestpy HTTP pipeline.
- Runtime duplicate/overlap/redirect behavior remains Nestpy/Starlette-owned.
- JSON and HTML use cached bytes; requests do no discovery/schema work.
- Swagger HTML safely encodes title, assets, and JSON configuration.

## Tests

- Descriptor shape, identity, options validation, and duplicate route behavior.
- Startup generation failure is fail-closed.
- JSON/UI content, HEAD, request ID, pipeline participation, and caching.
- Kinker health paths, bearer components, no global security, no self-doc routes.

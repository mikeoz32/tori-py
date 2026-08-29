# OA2: Discovery and Document Compiler

## Deliverables

- Singleton document service over `DiscoveryService` and `OpenApiOptions`.
- Controller views converted with public `compile_controller_routes()`.
- Strict deterministic OpenAPI 3.1 document and cached JSON/HTML bytes.

## Invariants

- Discovery reads only the compiled graph and constructs no scoped provider.
- The generated docs controller is excluded through normal metadata.
- Schema generation uses one msgspec component pass.
- `Any`, unresolved types, invalid mappings, collisions, non-native defaults,
  and unsupported unions fail startup.
- Explicit operation descriptions override cleaned method docstrings; fallback
  descriptions stop at the first `\f`, and summaries are never inferred.
- No adapter or native-route inspection occurs.
- Parameter metadata refines only an existing source/location binding;
  unmatched metadata fails compilation.
- Frozen nested parameter schema metadata materializes recursively back to
  native JSON dictionaries and lists in the compiled overlay.
- Explicit response headers and per-response media types are isolated from
  inferred route headers; bodyless 204/304 responses omit content.

## Tests

- Discovery across multiple modules and exclusion of the docs controller.
- Parameters, body, responses, schemas, tags, security, and operation IDs.
- Static response headers and declared content types on inferred responses.
- Nested parameter overlays, unmatched bindings, explicit response headers/media
  types, and opaque 204 response headers without content.
- Docstring description fallback, explicit precedence, and `\f` truncation.
- Path/collision/shadow diagnostics.
- Strict defaults and unsupported annotation diagnostics.
- Immutable document and one-time generation.

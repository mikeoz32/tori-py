# OA1: Configuration and Metadata

## Deliverables

- Frozen info/server/bearer/Swagger/options values.
- `api_tags`, `api_operation`, `api_parameter`, `api_response`, `api_security`,
  `api_public`, and `api_exclude`.
- Typed configuration, metadata, and schema errors.

## Invariants

- Inputs are validated and defensively frozen.
- Paths are absolute and static.
- Swagger assets are HTTPS or root-relative; document source keys are reserved.
- Metadata is direct, immutable, and performs no registration.
- Route metadata overrides controller defaults according to architecture.
- Parameter schemas are normalized JSON-object overlays and are defensively
  recursively frozen in route-only metadata.
- Cyclic, excessively nested, or otherwise non-encodable parameter schemas
  always fail as `OpenApiMetadataError` without leaking recursion failures.
- Explicit response headers are valid, unique HTTP headers; `Content-Type` uses
  `media_type`, and framework-owned `X-Request-ID` is rejected.
- Per-response media types normalize parameters and semicolon whitespace to one
  OpenAPI content key.

## Tests

- Exact public API and import boundaries.
- Valid/invalid options and defensive copying.
- Decorator identity, order, conflicts, inheritance override, and exclusion.
- Parameter/schema/description and response header/media-type validation,
  including nested immutability, cycles, and excessive depth.

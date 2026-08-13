# OA1: Configuration and Metadata

## Deliverables

- Frozen info/server/bearer/Swagger/options values.
- `api_tags`, `api_operation`, `api_response`, `api_security`, `api_public`, and
  `api_exclude`.
- Typed configuration, metadata, and schema errors.

## Invariants

- Inputs are validated and defensively frozen.
- Paths are absolute and static.
- Swagger assets are HTTPS or root-relative; document source keys are reserved.
- Metadata is direct, immutable, and performs no registration.
- Route metadata overrides controller defaults according to architecture.

## Tests

- Exact public API and import boundaries.
- Valid/invalid options and defensive copying.
- Decorator identity, order, conflicts, inheritance override, and exclusion.

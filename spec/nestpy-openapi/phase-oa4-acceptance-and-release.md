# OA4: Acceptance and Release

## Gates

- Focused Nestpy, package, and Kinker tests.
- Full workspace pytest.
- Ruff check and format check.
- Full configured ty paths including `packages/nestpy-openapi`.
- Strict MkDocs build.
- Wheel/sdist build and isolated smoke for Nestpy and `nestpy-openapi`.
- Dependency inspection proving no FastAPI, Pydantic, `python-openapi`, or second
  schema stack.
- Independent correctness, architecture, and security review.

## Exit Criteria

- Kinker exposes generated OpenAPI and Swagger UI through a normal imported
  Nestpy module.
- No adapter integration or request-time schema generation remains.
- Review has no required findings.

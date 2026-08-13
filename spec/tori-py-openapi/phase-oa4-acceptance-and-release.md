# OA4: Acceptance and Release

## Gates

- Focused ToriPy, package, and integration tests.
- Full workspace pytest.
- Ruff check and format check.
- Full configured ty paths including `packages/tori-py-openapi`.
- Strict MkDocs build.
- Wheel/sdist build and isolated smoke for ToriPy and `tori-py-openapi`.
- Dependency inspection proving no FastAPI, Pydantic, `python-openapi`, or second
  schema stack.
- Independent correctness, architecture, and security review.

## Exit Criteria

- An example application exposes generated OpenAPI and Swagger UI through a
  normal imported ToriPy module.
- No adapter integration or request-time schema generation remains.
- Review has no required findings.

# NPS0: Workspace and Package Contracts

## Status

Complete.

## Purpose

Create an installable typed ToriPy integration with frozen dependency, import,
facade, and artifact boundaries before runtime behavior is added.

## Deliverables

- `packages/tori-py-persistent-streams` as a uv workspace member.
- Runtime import `tori_py_persistent_streams` with `py.typed`.
- Runtime dependencies limited to `tori_py` and `tori-py-persistent-streams-core`.
- Exact root `__all__`, package README, typed base errors, and artifact verifier.
- Repository Ruff, ty, pytest, and documentation paths.

## Required Behavior

- Base import does not load RabbitMQ, `rstream`, `aio_pika`, Starlette,
  SQLAlchemy, CQRS, event sourcing, microservices, Alembic, or application code.
- Import performs no event-loop lookup, module compilation, discovery, provider
  construction, codec call, checkpoint access, task creation, or logging setup.
- Every public symbol is documented and available from exactly one facade.
- Package metadata targets Python `>=3.14,<3.15` and the workspace build backend.

## Invalid Configurations

- A broker or application package as a runtime dependency.
- Private ToriPy imports where a public contract exists.
- Re-exported native-driver, HTTP, microservices, CQRS, or persistence symbols.
- Missing `py.typed`, facade drift, or incomplete wheel/sdist contents.

## Tests

- Isolated subprocess imports with only declared dependencies.
- Forbidden `sys.modules` and AST import assertions.
- Exact dependency, `__all__`, Python-version, wheel, and sdist inventories.
- Isolated artifact install, import, and type smoke tests.

## Exit Criteria

- Empty package artifacts install, import, and type-check in isolation.
- Later phases need no package-boundary repair.

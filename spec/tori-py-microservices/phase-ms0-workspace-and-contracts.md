# MS0: Workspace and Package Contracts

## Status

Implemented. Workspace/package metadata, typed facades, lazy optional RabbitMQ
loading, import-boundary tests, and artifact verification scaffolding are
present; final built-artifact acceptance remains MS11.

## Purpose

Create an installable optional ToriPy integration with frozen dependency,
typing, import, and artifact boundaries before implementing messaging behavior.

## Deliverables

- `packages/tori-py-microservices` as a uv workspace member.
- Runtime package `tori_py_microservices` with `py.typed`.
- Exact root `__all__` and RabbitMQ subpackage `__all__` inventories.
- Base dependencies on `tori_py` and `msgspec` only.
- Optional `rabbitmq` extra containing `aio-pika>=10,<11`.
- Package README and artifact verification script.
- Package unit-test paths in repository Ruff, ty, and pytest commands.

## Required Behavior

- `import tori_py_microservices` succeeds without the RabbitMQ extra.
- Base import does not import `aio_pika`, Starlette, SQLAlchemy, CQRS, event
  sourcing, Alembic, or application code.
- `import tori_py_microservices.rabbitmq` without the extra fails only when a
  RabbitMQ symbol requiring `aio-pika` is used and reports the exact install
  extra.
- Import performs no event-loop lookup, controller discovery, provider
  construction, user factory call, broker connection, or logging setup.
- Every public symbol is available from one documented facade and has a stable
  type annotation.
- Package metadata requires Python `>=3.14,<3.15` and uses the workspace's
  `uv_build` backend.

## Invalid Configurations

- A mandatory runtime dependency on `aio-pika` in the base package.
- Imports from private ToriPy modules or mutable runtime internals.
- Re-exporting Starlette, SQLAlchemy, CQRS, or broker-native types from the base
  root facade.
- Missing `py.typed`, undocumented facade symbols, or files absent from built
  artifacts.

## Tests

- Subprocess imports with only base dependencies installed.
- Subprocess imports with the RabbitMQ extra installed.
- `sys.modules` assertions for forbidden eager imports.
- Exact `__all__`, version, and dependency allowlists.
- AST checks against private dependency imports.
- Wheel and sdist content inspection.
- Isolated artifact install and smoke import.

## Exit Criteria

- The empty package builds, installs, imports, and type-checks in isolation.
- Optional RabbitMQ dependency loading is proven lazy.
- No implementation code is required by later phases to repair package
  boundaries.

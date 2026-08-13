# ES0: Workspace and Contracts

## Entry Criteria

- `TORI_PY_CQRS_EVENT_SOURCING_CORE_IMPLEMENTATION_PLAN.md` is approved.
- The existing `tori-py-cqrs-core` test suite and package boundary are stable.

## Deliverables

- Distribution `tori-py-cqrs-event-sourcing-core` and import package `tori_py_cqrs_event_sourcing_core`.
- Workspace membership, local `tori-py-cqrs-core` dependency, package facade, and
  `py.typed` marker.
- Isolated import-boundary and wheel/source artifact checks.

## Invariants

- Dependency direction is `tori-py-cqrs-event-sourcing-core -> tori-py-cqrs-core` only.
- Runtime dependencies are `tori-py-cqrs-core` and the Python standard library.
- Importing the facade does not require a framework, database, serializer, or DI
  container.
- No behavior from ES1 or later is implemented before its specification exists.

## Failure Behavior

- Missing package artifacts, reverse imports, undeclared dependencies, and
  facade import failures fail verification.

## Tests

- Public facade and `py.typed` are present.
- Import boundaries are checked in an isolated subprocess.
- Wheel and source distributions install with a local `tori-py-cqrs-core` artifact.

## Exit Criteria

- The package imports in the workspace and isolated artifact environments.
- Repository lock, Ruff, formatting, and type checks pass.

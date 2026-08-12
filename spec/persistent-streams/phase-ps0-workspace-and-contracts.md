# PS0: Workspace and Contracts

Status: implemented.

## Entry Criteria

- `PERSISTENT_STREAMS_ARCHITECTURE.md` is approved.
- `PERSISTENT_STREAMS_IMPLEMENTATION_PLAN.md` and this phase map are approved.
- No persistent-streams package implementation exists in the workspace.

## Deliverables

- Distribution `persistent-streams` and import package `persistent_streams`.
- `uv` workspace membership, package facade, `py.typed`, and package metadata.
- Public module skeleton for models, protocols, routing, checkpoints, consumers,
  in-memory reference, errors, and testing helpers.
- Isolated import-boundary and wheel/source artifact smoke checks.

## Invariants

- Runtime dependencies are Python standard library only.
- No workspace package imports `persistent_streams` as part of PS0.
- Importing the facade performs no I/O, starts no worker, and requires no
  framework, broker, database, serializer, or test runner.
- Public protocols are asynchronous where implementations may perform I/O.
- No behavior from PS1 or later is implemented before its executable phase file
  is approved.

## Failure Behavior

- Missing artifacts, undeclared dependencies, forbidden imports, reverse
  dependencies, and facade import failures block PS0.
- Package metadata that claims durability or a production adapter blocks PS0.

## Tests

- Public facade and `py.typed` are present.
- Import boundaries are inspected in the repository and an isolated subprocess.
- Wheel and source distributions install and import without another workspace
  distribution.
- Package metadata targets Python 3.14 and names only intended artifacts.

## Exit Criteria

- The empty package boundary imports in workspace and isolated artifact
  environments.
- Lock, focused tests, Ruff, formatting, and package type checks pass through
  `uv`.

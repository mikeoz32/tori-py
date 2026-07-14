# Phase 0: Workspace and Tooling

## Purpose

Create a reproducible Python 3.14 `uv` workspace that can build and test two package boundaries without introducing application or infrastructure dependencies prematurely.

## Entry Criteria

- `uv --version` works in a fresh shell.
- The repository root is known and writable.
- Python 3.14 can be selected through `uv`.
- `AGENTS.md` and `CQRS_IMPLEMENTATION_PLAN.md` are present.

If `uv` is not available, stop. Do not use system `python`, `pip`, `venv`, `poetry`, or another environment manager as a substitute.

## Target Layout

The first workspace should have this shape:

```text
AGENTS.md
CQRS_IMPLEMENTATION_PLAN.md
pyproject.toml
uv.lock
spec/
  README.md
  phase-00-workspace-and-tooling.md
  phase-01-core-types-and-protocols.md
  phase-02-registration-and-dispatch.md
  phase-03-inmemory-transport.md
  phase-04-event-task-management.md
  phase-05-fastapi-adapter.md
  phase-06-review-and-hardening.md
packages/
  cqrs-core/
    pyproject.toml
    src/cqrs_core/
    tests/
  cqrs-fastapi/
    pyproject.toml
    src/cqrs_fastapi/
    tests/
tests/
  integration/
```

The exact package directory names may change only if package metadata, imports, and this specification are updated together. The intended import names are `cqrs_core` and `cqrs_fastapi`.

## Root Workspace Metadata

According to the official uv workspace model:

- the workspace root is also a workspace member;
- every directory matched by `tool.uv.workspace.members` must contain a `pyproject.toml`;
- the workspace has one shared `uv.lock`;
- `uv sync` and `uv run` operate on the root by default and accept `--package <name>` for a specific member;
- workspace members are installed editable by default when they define a build system;
- a root project without a build system is not installed as a package, even though it remains the workspace root/member.

The authoritative references are:

- <https://docs.astral.sh/uv/concepts/projects/workspaces/>
- <https://docs.astral.sh/uv/concepts/projects/config/>
- <https://docs.astral.sh/uv/concepts/projects/dependencies/>
- <https://docs.astral.sh/uv/concepts/projects/sync/>

The root `pyproject.toml` MUST:

- declare the Python 3.14 requirement;
- declare the workspace members for both packages;
- contain the root project's workspace-level metadata and development configuration;
- omit a build system so the repository root is not installed as a third runtime package;
- not list FastAPI, SQLAlchemy, Pydantic, or broker clients as core dependencies.

The root workspace SHOULD keep package runtime metadata in each package's own `pyproject.toml`. Use workspace references for the local core dependency of the FastAPI package. A workspace dependency must be listed by package name in `project.dependencies` and mapped with `tool.uv.sources.<name> = { workspace = true }`.

## Package Metadata

### Core package

The core package MUST:

- declare Python 3.14 compatibility;
- have no runtime dependencies outside the standard library;
- expose only deliberate public imports from its package root;
- keep test-only dependencies out of runtime dependencies.

### FastAPI package

The FastAPI package MUST:

- depend on the local core package;
- declare FastAPI as its own runtime dependency;
- not add FastAPI dependencies to core through workspace configuration;
- keep adapter-specific types out of core public protocols.

## Development Tools

The root `dev` dependency group MUST contain the test runner, async test support, Ruff, and ty. Their versions MUST be selected and locked through `uv`.

The current tools are:

- `pytest` for tests;
- `pytest-asyncio` for async test support;
- `ruff` for linting and formatting;
- `ty` for type checking.

Ruff is configured in the root `pyproject.toml` for Python 3.14 with import sorting, common correctness rules, and the project formatter. ty is configured there with `tool.ty.environment.python-version = "3.14"`.

The first expected commands, after metadata exists, are:

```text
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check packages/cqrs-core/src packages/cqrs-core/tests packages/cqrs-fastapi/src packages/cqrs-fastapi/tests
```

`uv lock --check` MUST be used when checking that the lockfile matches project metadata. `uv run --locked ...` MAY be used in CI to refuse an implicit lockfile update. `uv sync` performs exact synchronization by default; do not use `--inexact` unless the workflow explicitly needs to retain packages outside the lockfile.

Focused commands SHOULD include:

```text
uv run pytest packages/cqrs-core/tests
uv run pytest packages/cqrs-fastapi/tests
uv run pytest tests/integration
```

The `--package` option selects the workspace member's environment but does not change the shell working directory. When using it from the root, pass root-relative test paths, for example:

```text
uv run --package cqrs-core pytest packages/cqrs-core/tests
uv run --package cqrs-fastapi pytest packages/cqrs-fastapi/tests
```

The exact paths must match the final layout. Never document a command that has not been run successfully once the workspace is available.

## Dependency Rules

1. Add dependencies with `uv add` or the appropriate workspace-aware `uv` command.
2. Update the lockfile through `uv`, never by hand.
3. Keep core runtime dependency inspection in the verification suite.
4. Do not add SQLAlchemy, Pydantic, broker clients, or a DI framework to make the first in-memory tests easier.
5. Keep FastAPI test dependencies in the FastAPI package or test group only.

## Required Phase 0 Tests

Before Phase 1 starts, verify:

- workspace resolution succeeds;
- lockfile generation succeeds;
- root and both package members are present in the workspace metadata;
- core package imports without FastAPI installed in its dependency context;
- FastAPI package resolves the local core package;
- the test runner can discover an empty or smoke test in each package;
- Python reports version 3.14 through the `uv` environment.

## Exit Criteria

Phase 0 is complete only when:

1. `uv sync` succeeds from the repository root.
2. `uv run pytest` succeeds.
3. Both package directories are recognized as workspace members.
4. The core package has no forbidden runtime dependency.
5. The lockfile is present and generated by `uv`.
6. The final commands are recorded in the repository documentation.

## Verified Results

Phase 0 was verified on the current Windows workspace with `uv 0.11.28`:

```text
uv --version
uv python pin 3.14
uv lock --check
uv sync --locked
uv run --locked python --version
uv run --locked pytest
uv run --package cqrs-core pytest packages/cqrs-core/tests
uv run --package cqrs-fastapi pytest packages/cqrs-fastapi/tests
uv tree --locked --package cqrs-core --no-dev --depth 1
uv tree --locked --package cqrs-fastapi --no-dev --depth 1
```

Observed results:

- uv version: `0.11.28`;
- selected Python: `3.14.6`;
- root test suite: `2 passed`;
- core focused suite: `1 passed`;
- FastAPI focused suite: `1 passed`;
- core runtime tree: `cqrs-core` only;
- FastAPI runtime tree: `cqrs-fastapi` with `cqrs-core` and `fastapi`;
- lockfile check and locked sync: successful.

The initial smoke tests intentionally verify only package importability and workspace dependency resolution. CQRS behavior begins in Phase 1.

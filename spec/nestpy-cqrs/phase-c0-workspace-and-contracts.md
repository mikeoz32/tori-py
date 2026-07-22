# C0: Workspace and Contracts

## Purpose

Create the separate `nestpy-cqrs` distribution and freeze its public boundary.

## Contract

- Distribution: `nestpy-cqrs`.
- Import: `nestpy_cqrs`.
- Dependencies: `nestpy` and `cqrs-core` only.
- No reverse dependency from Nestpy or CQRS core.
- No Starlette, FastAPI, Pydantic, package scanning, or process-global registry.
- C0 public registration is explicit through `CqrsHandlerBinding`; C2 adds
  compiled-provider discovery without provider auto-registration.
- CQRS core messages and buses remain imported from `cqrs_core`.

## Verification

- package facade and `py.typed` exist;
- import boundaries are subprocess-tested;
- wheel and source distribution import in isolated `uv` environments;
- `uv run python packages/nestpy-cqrs/scripts/verify_artifacts.py dist/`
  compiles and dispatches through both artifact sets;
- invalid binding categories and tokens fail deterministically.

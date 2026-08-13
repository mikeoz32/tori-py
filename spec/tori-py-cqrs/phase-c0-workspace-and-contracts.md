# C0: Workspace and Contracts

## Purpose

Create the separate `tori-py-cqrs` distribution and freeze its public boundary.

## Contract

- Distribution: `tori-py-cqrs`.
- Import: `tori_py_cqrs`.
- Dependencies: `tori_py` and `tori-py-cqrs-core` only.
- No reverse dependency from ToriPy or CQRS core.
- No Starlette, FastAPI, Pydantic, package scanning, or process-global registry.
- C0 public registration is explicit through `CqrsHandlerBinding`; C2 adds
  compiled-provider discovery without provider auto-registration.
- `command_handler`, `query_handler`, and `event_handler` compose core handler
  metadata with ToriPy injectable metadata for class-provider shorthand.
- `bind_command_handler`, `bind_query_handler`, and `bind_event_handler` create
  explicit `CqrsHandlerBinding` values for custom-token/factory providers.
- CQRS core messages and buses remain imported from `tori_py_cqrs_core`.

## Verification

- package facade and `py.typed` exist;
- import boundaries are subprocess-tested;
- wheel and source distribution import in isolated `uv` environments;
- `uv run python packages/tori-py-cqrs/scripts/verify_artifacts.py dist/`
  compiles and dispatches through both artifact sets;
- invalid binding categories and tokens fail deterministically.

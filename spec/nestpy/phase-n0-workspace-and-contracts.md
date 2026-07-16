# Phase N0: Workspace and Contracts

## Purpose

Create the standalone `nestpy` workspace package, enforce dependency direction,
and define stable declaration/protocol types without implementing module
compilation, resolution, lifecycle, or HTTP serving.

## Entry Criteria

- `NESTPY_ARCHITECTURE.md` is approved.
- Existing CQRS packages and tests pass.
- No Nestpy runtime package exists in the workspace.

## Deliverables

Create:

```text
packages/nestpy/
  pyproject.toml
  src/nestpy/
    __init__.py
    py.typed
    core/
    settings/
    starlette/
    testing/
    cli/
  tests/
```

Add `packages/nestpy` to the `uv` workspace and root dependencies.

## Dependency Contract

Required runtime dependencies:

- `starlette` in the v1 distribution;
- `msgspec` in the v1 distribution.

Optional extras:

- `settings-yaml`: PyYAML;
- `cli`: Uvicorn.

Forbidden dependencies:

- FastAPI;
- Pydantic;
- `dependency_injector`;
- `cqrs-core`;
- OpenTelemetry packages;
- SQLAlchemy or an ORM.

`nestpy.core` MUST import using only the standard library and other
`nestpy.core` modules. Import tests MUST prove that importing `nestpy.core` does
not load Starlette or Uvicorn modules.

## Public Declarations

N0 defines but does not execute:

- `Token = type[object] | str`;
- `Scope` enum or literal with singleton/request/transient;
- `Inject` marker;
- `ValueProvider`, `ClassProvider`, `FactoryProvider`, `AliasProvider`;
- `ProviderDeclaration` union;
- `ModuleSpec`, `DeferredModule`;
- `ApplicationOptions`, `StarletteOptions`;
- `ExecutionContext`, `ScopedResolver` protocols;
- `Middleware`, `Guard`, `Pipe`, `Interceptor`, `ExceptionFilter` protocols;
- `ArgumentMetadata`, `PipelineResult`;
- `Logger`, `Codec`, and `SettingsDecoder` protocols;
- declaration decorators that attach immutable metadata only.

Provider declaration validation in N0 is structural:

- token must be a class or non-empty string;
- provider scope must be supported;
- alias has no independent scope or cleanup;
- a managed value provider must be explicit;
- application and Starlette timeouts/limits cannot be negative.
- cancellation grace plus cleanup reserve cannot exceed shutdown timeout.

## Exception Contract

Define typed public bases:

```text
NestpyError
BootstrapError
ResolutionError
ScopeError
ScopeClosedError
ResourceError
LifecycleError
ApplicationStateError
SettingsError
PipelineStateError
```

HTTP exception declarations and rendering are deferred to N4. N0 defines no
HTTP-status-bearing exception in core.

Define internal diagnostics with stable machine-readable codes:

```text
module.cycle
module.dynamic_conflict
module.static_dynamic_conflict
module.materialization_error
module.invalid_constructor
module.invalid_export
provider.duplicate
provider.invalid_signature
provider.unresolved
provider.ambiguous
provider.cycle
provider.alias_cycle
provider.scope_violation
controller.invalid_declaration
controller.invalid_signature
route.invalid_signature
route.duplicate
route.invalid_binding
route.duplicate_pipeline_decorator
settings.source_error
settings.decode_error
resource.acquire_error
resource.cleanup_error
resource.lingering_worker
resource.lingering_resource
lifecycle.startup_error
lifecycle.shutdown_timeout
lifecycle.lingering_task
application.invalid_state
```

## Metadata Contract

Decorators MUST:

- attach frozen metadata directly to the decorated class or method;
- reject duplicate metadata of the same kind on one target;
- not mutate a global registry;
- not instantiate modules, controllers, providers, or Starlette objects;
- preserve the decorated object identity.

N0 MAY define controller and route metadata dataclasses, but route compilation
belongs to N4.

## Explicit Non-Goals

N0 MUST NOT:

- walk a module graph;
- inspect provider constructor dependencies;
- resolve a provider;
- start lifecycle hooks;
- create a Starlette application;
- parse settings sources;
- implement testing overrides or CLI commands.

## Tests

Tests MUST cover:

1. provider declaration immutability;
2. class and string tokens;
3. invalid scopes/tokens/options;
4. alias declaration restrictions;
5. decorators preserve target identity;
6. duplicate decorator metadata rejection;
7. no global registry side effects;
8. public import facade;
9. package type markers;
10. core import boundary without Starlette/Uvicorn/FastAPI/CQRS/OpenTelemetry;
11. settings imports core/msgspec but not Starlette;
12. Starlette layer depends inward and CLI/server imports remain lazy;
13. optional YAML and CLI imports remain lazy;
14. workspace lock and build metadata.
15. `ExecutionContext` protocol exposes application/module/route IDs, request
    ID, resolver, metadata, and execution kind without driver types.

N0 also runs:

```text
uv build --package nestpy
```

## Exit Criteria

N0 is complete when the Nestpy package builds through `uv`, public declarations
type-check, import boundaries are mechanically tested, and no runtime graph or
HTTP behavior has been introduced.

# Modules

Modules are ToriPy's composition and visibility boundary. A module states which
other modules it imports, which providers and controllers it owns, and which
provider tokens it deliberately exposes. ToriPy never scans a package to fill in
missing declarations.

## Minimal Static Module

This focused example follows the tested Task API's infrastructure/feature split:

```python
from tori_py import ClassProvider, module


class TaskRepository:
    pass


class TaskService:
    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository


@module(
    providers=[ClassProvider(TaskRepository)],
    exports=[TaskRepository],
)
class InfrastructureModule:
    pass


@module(
    imports=[InfrastructureModule],
    providers=[ClassProvider(TaskService)],
    exports=[TaskService],
)
class TasksModule:
    pass


@module(imports=[TasksModule])
class AppModule:
    pass
```

`TaskRepository` is private to `InfrastructureModule` until that module exports
its class token. `TasksModule` can inject it because `InfrastructureModule` is a
direct import. `AppModule` can see `TaskService`, but not `TaskRepository`,
because exports are not automatically transitive.

The complete composition used as the basis for this example is the
[Task API](../reference/task-api.md).

## Module Metadata

`@module()` attaches immutable metadata directly to the decorated class and
preserves class identity.

| Field | Accepted values | Meaning |
| --- | --- | --- |
| `imports` | Module classes or `DeferredModule` descriptors | Adds explicit nodes and visibility edges to the graph |
| `providers` | Provider declarations or directly `@injectable()` classes | Registers module-owned dependency tokens |
| `controllers` | Controller classes | Registers eager singleton controllers owned by the module |
| `exports` | Class or non-empty string tokens | Makes selected local/direct-import providers available to importers |
| `global_` | `bool`, default `False` | Makes explicit exports visible as a final fallback to every compiled module |

Metadata is direct-only. Subclassing a decorated module does not inherit its
module declaration. Applying `@module()` twice to the same class is an error.
The module class must have no required constructor arguments.

At startup, ToriPy instantiates each module class with no arguments. A module
instance exists for lifecycle hooks and graph validation; it is not a DI-managed
provider and receives no constructor injection. Put application behavior in
providers instead.

## Visibility Rules

For one `(module, token)` pair, ToriPy resolves exactly in this order:

1. A provider declared locally by the module.
2. A provider explicitly exported by a direct import.
3. A provider explicitly exported by a compiled global module.

A local provider shadows imported and global providers. A direct imported export
shadows a global export. If more than one provider matches at the selected
level, compilation fails with `provider.ambiguous`; declaration order never
chooses a winner.

### Private providers

A provider absent from `exports` remains private. Importing its module does not
make it injectable elsewhere. Discovery integrations may inspect private
providers, but discovery does not change normal visibility.

### Re-exports

Exports do not flow through multiple imports automatically. A module may
explicitly re-export a token that it can resolve from one of its direct imports:

```python
@module(imports=[InfrastructureModule], exports=[TaskRepository])
class PersistenceModule:
    pass
```

A token visible only because another module is global cannot be re-exported on
that basis. Re-export from a direct import instead.

### Global modules

A global module must still be reachable from the root through normal imports,
and it must still list every public token in `exports`:

```python
@module(
    providers=[ClassProvider(TaskRepository)],
    exports=[TaskRepository],
    global_=True,
)
class GlobalInfrastructureModule:
    pass
```

Global exports are the lowest-priority visibility source. They do not override a
local provider or direct import. Use a global module for genuinely
application-wide infrastructure, not to avoid designing feature boundaries.

## Static Module Identity

A static module's identity is its class. Repeated imports of the same class
reuse one graph node; providers and hooks are not duplicated. Compilation order
is dependency-first, with import declaration order as the deterministic
tie-breaker for independent modules.

A module class cannot appear in both static and dynamic form in one graph. That
would make ownership and configuration ambiguous, so creation fails with
`module.static_dynamic_conflict`.

## Dynamic Modules

A dynamic module defers a `ModuleSpec` until application creation. It is useful
when a reusable integration needs explicit configuration before provider startup.

The following focused declaration mirrors the dynamic-module compiler tests:

```python
from tori_py import DeferredModule, ModuleSpec, ValueProvider


class ConfigurationModule:
    @classmethod
    def for_value(
        cls,
        value: str,
        *,
        key: str = "default",
    ) -> DeferredModule:
        return DeferredModule(
            module=cls,
            key=key,
            factory=lambda: ModuleSpec(
                providers=[ValueProvider("configuration.value", value)],
                exports=["configuration.value"],
            ),
        )


configuration_module = ConfigurationModule.for_value("production")


@module(imports=[configuration_module])
class AppModule:
    pass
```

The descriptor is not a running module. Its zero-argument factory runs during
`NestApplication.create()` and must return `ModuleSpec`; the factory may be
synchronous or asynchronous. It may load and validate configuration, but it
must not open provider resources or run lifecycle hooks.

Dynamic identity is `(module class, key)`:

- The key must be a non-empty string and cannot be `"static"`.
- Reusing the same `DeferredModule` object reuses one node and materializes it
  once.
- A different descriptor object with the same identity is always a conflict,
  even if both factories would return equal specs.
- Different keys create distinct module nodes.
- Different keys do not make same-token exports unambiguous to a module that
  imports both; normal visibility rules still apply.

There is no implicit options hash. Keep a descriptor in one composition variable
and reuse that object wherever the same configured module is required.

## Compilation Semantics

`NestApplication.create()` performs module work before provider runtime work:

1. Materialize each reachable deferred descriptor.
2. Normalize bare `@injectable()` provider classes into `ClassProvider`
   declarations.
3. Detect import cycles and assign dependency-first module order.
4. Validate providers, controllers, exports, aliases, and annotations.
5. Compile local/direct/global visibility.
6. Detect provider cycles and invalid scope paths.
7. Freeze the resulting `CompiledGraph`.

No module instance, provider, controller, or context manager is created during
these stages. This is why composition errors can fail before traffic and before
resource side effects.

## Failure Behavior

| Diagnostic code | Cause |
| --- | --- |
| `module.invalid_declaration` | Invalid import, dynamic key/factory, metadata field, or `global_` value |
| `module.duplicate_metadata` | `@module()` was applied twice to one class |
| `module.invalid_constructor` | A module class requires constructor arguments or cannot be inspected |
| `module.cycle` | The import graph is cyclic |
| `module.dynamic_conflict` | Different descriptors use the same dynamic identity |
| `module.static_dynamic_conflict` | One class appears as both a static and dynamic module |
| `module.materialization_error` | A dynamic factory failed or did not return `ModuleSpec` |
| `module.invalid_export` | An export is neither local nor resolvable from a direct import |
| `provider.ambiguous` | Multiple direct imports or global modules provide the same selected token |
| `provider.unresolved` | A dependency is not visible from its owning module |
| `controller.invalid_declaration` | A controller declaration is invalid or attempts a non-singleton scope |

`BootstrapError.diagnostic_code` is the stable assertion surface. Some errors
also include immutable details such as a module path or dynamic key.

## Testing Modules

`TestingModule` applies overrides before normal graph validation. Provider
overrides are intentionally limited to exported tokens of the selected module;
tests cannot reach through a module boundary to replace private providers.

```python
from tori_py.testing import TestingModule


builder = TestingModule.create(AppModule)
builder.override_provider(
    TaskRepository,
    module=InfrastructureModule,
).use_value(fake_repository)
application = await builder.compile()
try:
    resolved = await application.resolve(
        TaskRepository,
        module=InfrastructureModule,
    )
    assert resolved is fake_repository
finally:
    await application.close()
```

The example resolves from the exact owning module because `AppModule` does not
receive a re-export of `TaskRepository`. The root can resolve the replacement
only when the token is visible from the root. To resolve from another compiled
owner in a test, pass its module class, `ModuleId`, or `(module class, key)` to
`TestingApplication.resolve()`.

Use `replace_module(descriptor, replacement)` to replace a deferred module before
its original factory materializes. Dynamic provider overrides select either the
descriptor or `(ModuleClass, "key")`. The builder seals when `compile()` starts;
late changes fail.

Run focused framework coverage with:

```text
uv run pytest packages/tori-py/tests/test_module_compiler.py
```

## NestJS and FastAPI Differences

For NestJS users, `@module()` serves a familiar composition purpose, but ToriPy
has no `forwardRef()`, runtime module mutation, or constructor injection into
module classes. Dynamic modules return a deferred, explicitly keyed descriptor
rather than a materialized metadata object. Cycles and identity conflicts are
hard bootstrap failures.

For FastAPI users, a ToriPy module is not an `APIRouter`. It can own controllers,
but it also controls provider ownership and visibility. Importing a module is
therefore stronger than including routes, while exporting a provider is separate
from exposing an HTTP endpoint.

## Production Notes

- Keep the root module focused on composition; put behavior in feature providers.
- Export the smallest stable token surface needed by direct consumers.
- Prefer explicit imports over global modules.
- Create one configured descriptor object and reuse it instead of calling a
  `for_root()`-style method repeatedly with the same key.
- Keep dynamic factories bounded and side-effect-light. Provider context managers
  are the resource acquisition boundary.
- Treat a compile failure as fatal; do not serve a reduced or partially compiled
  application.

## Related APIs

- Declarations: `module`, `ModuleMetadata`, `ModuleSpec`, `DeferredModule`
- Types: `ModuleImport`, `ModuleProvider`, `ModuleFactory`, `ModuleId`
- Introspection: `get_module_metadata`, `CompiledGraph`, `ModulePlan`
- Failures: `BootstrapError`, `Diagnostic`
- Testing: `TestingModule.replace_module()`,
  `TestingModule.override_provider()`

## Next Steps

Continue with [Providers and DI](providers-and-di.md) to define module-owned
dependencies, then [Scopes and Resources](scopes-and-resources.md) to assign
lifetime and cleanup ownership. See [Discovery and Reflection](discovery-and-reflection.md)
before building an integration that enumerates modules.

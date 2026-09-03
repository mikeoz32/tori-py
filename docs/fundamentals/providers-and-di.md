# Providers and Dependency Injection

A provider declaration tells ToriPy which token a module owns, how to obtain its
value, which scope controls its lifetime, and whether a context-manager result is
managed. Constructor and factory dependencies are resolved from precompiled
annotations; there is no service locator scan or implicit class construction.

## Provider Forms

| Declaration | Creates or exposes | Default scope | Resource default |
| --- | --- | --- | --- |
| `ValueProvider(token, value)` | One existing value | Singleton only | Unmanaged; opt in with `manage=True` |
| `ClassProvider(token, use_class)` | A class instance | Singleton | Managed with `manage=True` |
| `FactoryProvider(token, factory)` | A sync or async factory result | Singleton | Managed with `manage=True` |
| `AliasProvider(token, target)` | The canonical target value | Target's effective scope | Never owns cleanup separately |
| A directly `@injectable()` class in `providers` | `ClassProvider(Class, Class, ...)` shorthand | Decorator scope | Decorator `manage` value |

Provider declarations are immutable. Explicit `ClassProvider` settings override
any `@injectable()` metadata on the implementation class.

## Tokens

A provider token is either a class or a non-empty string:

```python
TASK_REPOSITORY = "tasks.repository"
```

Class tokens are convenient when the abstraction itself is the public identity.
String tokens are useful when composition must select an implementation without
making the implementation class the contract. Empty strings, instances, typing
objects that are not classes, and arbitrary hashable values are invalid tokens.

Reserved framework tokens such as `WorkScopeFactory`, `ModulesContainer`,
`DiscoveryService`, and `Reflector` are injected intrinsically. Applications
must not declare or override them.

## Class Shorthand

`@injectable()` marks a class for self-token shorthand:

```python
from tori_py import injectable, module


@injectable()
class GreetingService:
    def message(self) -> str:
        return "hello"


@module(providers=[GreetingService], exports=[GreetingService])
class GreetingModule:
    pass
```

The decorator preserves the class object and attaches direct metadata. A bare
class in `providers` is valid only when that exact class has its own
`@injectable()` metadata. Metadata is not inherited by subclasses. Use an
explicit `ClassProvider` when the token, implementation, scope, or ownership is a
composition decision:

```python
from tori_py import ClassProvider, Scope


provider = ClassProvider(
    "tasks.repository",
    SqlTaskRepository,
    scope=Scope.SINGLETON,
)
```

Controllers do not need `@injectable()`. Listing a controller in a module's
`controllers` field creates its mandatory singleton class provider.

## Constructor Injection

ToriPy inspects class constructors and provider factories once during graph
compilation with `typing.get_type_hints(..., include_extras=True)`.

```python
from typing import Annotated

from tori_py import ClassProvider, Inject, module


TASK_REPOSITORY = "tasks.repository"


class TaskRepository:
    pass


class SqlTaskRepository(TaskRepository):
    pass


class TaskService:
    def __init__(
        self,
        repository: Annotated[TaskRepository, Inject(TASK_REPOSITORY)],
        batch_size: int = 100,
    ) -> None:
        self.repository = repository
        self.batch_size = batch_size


@module(
    providers=[
        ClassProvider(TASK_REPOSITORY, SqlTaskRepository),
        ClassProvider(TaskService),
    ],
    exports=[TASK_REPOSITORY, TaskService],
)
class TasksModule:
    pass
```

The rules are exact:

1. A class annotation uses that class as the token.
2. `Annotated[T, Inject(token)]` replaces the annotation-derived token.
3. A required parameter needs a class annotation or one `Inject` marker.
4. A parameter with a default uses its Python default when it has no explicit
   `Inject`, even if a provider matches its annotation.
5. An explicit `Inject` remains a required dependency even when the parameter
   has a default.
6. Variadic `*args` and `**kwargs` parameters are not injectable.
7. More than one `Inject` marker on one parameter is invalid.
8. A class used only as a constructor/factory annotation is never
   auto-registered.
9. Every token resolves using the provider's owning module visibility.

In the example, `batch_size` remains `100`; ToriPy does not try to inject an
`int`. `Inject(TASK_REPOSITORY)` selects the string-token class provider.

Positional-only constructor and factory parameters currently compile when they
otherwise satisfy these rules, but provider invocation passes dependencies by
keyword. Resolution therefore fails with `TypeError` when such a dependency is
constructed. Use positional-or-keyword or keyword-only injectable parameters;
do not declare injectable dependencies before `/`.

There is one compile-time pipeline exception to explicit registration. A guard,
pipe, interceptor, or filter implementation class used directly in compiled
global/controller/route pipeline metadata receives an implicit class provider
when no provider is visible. This fallback is driven by the explicit pipeline
registration, not by annotations. Middleware classes receive no such fallback:
declare a middleware provider explicitly and register its token.

## Factory Providers

A factory may be synchronous or asynchronous and receives dependencies by the
same parameter rules:

```python
from tori_py import FactoryProvider


async def create_client(settings: ClientSettings) -> ApiClient:
    return await ApiClient.connect(settings.endpoint)


client_provider = FactoryProvider(ApiClient, create_client)
```

The return annotation is descriptive Python typing; the provider token comes
from `FactoryProvider(ApiClient, ...)`. If the awaited result is a context
manager and `manage=True`, ToriPy enters it before consumers receive it.

Synchronous constructor and factory bodies run on the event-loop thread. Only
synchronous context-manager `__enter__` and `__exit__` calls are executor-backed,
so constructors and sync factories must not perform blocking I/O.

## Value and Alias Providers

Use a value provider for a preconstructed immutable value or an externally owned
object:

```python
from tori_py import ValueProvider


settings_provider = ValueProvider("app.settings", AppSettings(debug=False))
```

The first argument is the provider token. In most applications a class token is
clearer when the value has a stable type:

```python
settings = AppSettings(debug=False)
settings_provider = ValueProvider(AppSettings, settings)
```

Values are singleton-only. By default ToriPy does not enter or close a value,
because the object existed before the container owned it. Set `manage=True` only
when application composition deliberately transfers context-manager ownership.

An alias exposes an already visible provider under another token:

```python
from tori_py import AliasProvider


reader_alias = AliasProvider(TaskReader, TASK_REPOSITORY)
```

Aliases create no second instance or resource record. They canonicalize to the
target's identity, cache, effective scope, and cleanup ownership. Alias chains
are allowed when acyclic and fully visible; alias-only and mixed dependency
cycles fail compilation.

## Resolution Semantics

The compiler turns every dependency into a module-qualified `ProviderRef`.
Runtime construction follows that frozen plan instead of inspecting annotations
or repeating unqualified visibility lookup.

Singleton providers and controllers are resolved eagerly during application
startup in topological dependency order. Request providers are created on first
use in each request/work scope. Transient providers are created for each
resolution. A request/work scope belongs to the task that enters it, so its
provider cache is accessed sequentially and does not need construction locks.
Using its resolver from another task raises `ScopeError`, even if the requested
provider is already cached.

See [Modules](modules.md) for local/direct/global visibility and
[Scopes and Resources](scopes-and-resources.md) for lifetime rules.

## Failure Behavior

Most graph failures are `BootstrapError` values raised by
`NestApplication.create()`:

| Diagnostic code | Cause |
| --- | --- |
| `provider.invalid_token` | Token is not a class or non-empty string |
| `provider.invalid_scope` | Scope name is unsupported or a value provider is not singleton |
| `provider.invalid_declaration` | Bare class lacks direct `@injectable()` metadata or provider fields are invalid |
| `provider.invalid_signature` | Annotation resolution, required/default, `Inject`, or variadic rules are violated |
| `provider.duplicate` | One module declares the same token more than once |
| `provider.unresolved` | A dependency or alias target is not visible |
| `provider.ambiguous` | More than one provider matches at the selected visibility level |
| `provider.cycle` | Constructor/factory dependency graph is cyclic |
| `provider.alias_cycle` | An alias-only or mixed alias dependency cycle exists |
| `provider.scope_violation` | A singleton reaches a request provider through any path |
| `provider.reserved_token` | Application code tries to own a framework intrinsic |

Constructor, factory, or managed-resource entry failures occur when that provider
is created. The original failure propagates after already acquired resources in
the affected scope segment are rolled back. A singleton failure makes startup
fail and triggers application rollback.

## Testing Providers

Override an exported token before compilation, not a live container cache:

```python
from tori_py.testing import TestingModule


builder = TestingModule.create(AppModule)
builder.override_provider(
    TASK_REPOSITORY,
    module=TasksModule,
).use_value(FakeTaskRepository())

application = await builder.compile()
try:
    service = await application.resolve(TaskService, module=TasksModule)
    assert isinstance(service, TaskService)
finally:
    await application.close()
```

The selected token must be exported by `TasksModule`. Supported replacement
forms are `use_value()`, `use_class()`, `use_factory()`, and `use_alias()`.
Overrides are compiled through the same annotation, scope, cycle, visibility,
startup, and cleanup rules as production declarations.

Run focused coverage with:

```text
uv run pytest packages/tori-py/tests/test_module_compiler.py packages/tori-py/tests/test_logging_and_testing.py
```

## NestJS and FastAPI Differences

For NestJS users, the four explicit provider classes correspond closely to
`useValue`, `useClass`, `useFactory`, and `useExisting`. ToriPy uses Python
`Annotated` rather than parameter decorators and has no property injection,
implicit provider discovery, or runtime `ModuleRef` mutation. Scope-invalid
graphs fail before startup instead of relying on request proxies.

For FastAPI users, a provider is not an arbitrary callable passed to `Depends`.
It is an application-graph declaration with module visibility, scope, lifecycle,
and resource ownership. Function/class annotations alone do not register or run
dependencies. HTTP handler injection uses ToriPy's explicit `Inject` binding and
the current request scope, not FastAPI dependency solving.

## Production Notes

- Prefer class tokens for stable application abstractions and namespaced strings
  for composition-owned implementation choices.
- Keep singleton providers safe for concurrent use; one instance serves the
  whole application.
- Keep constructors cheap and non-blocking. Put asynchronous acquisition in an
  async factory or async context manager.
- Do not hide request-scoped state behind a singleton. Use `WorkScopeFactory` or
  inject the scoped value into an HTTP handler.
- Use aliases for another view of one provider, not for decoration that needs a
  second lifecycle owner.
- Treat unresolved, ambiguous, cyclic, and scope-invalid graphs as design errors,
  not recoverable runtime configuration.

## Related APIs

- Provider declarations: `ValueProvider`, `ClassProvider`, `FactoryProvider`,
  `AliasProvider`, `ProviderDeclaration`
- Tokens and injection: `Token`, `Inject`, `injectable`,
  `get_injectable_metadata`
- Scope: `Scope`, `normalize_scope`
- Utilities: `provider_token`, `validate_token`
- Compiled plans: `ProviderRef`, `ProviderPlan`, `DependencyPlan`
- Failures: `BootstrapError`, `ScopeError`, `ResourceError`

## Next Steps

Read [Scopes and Resources](scopes-and-resources.md) before selecting
`Scope.REQUEST`, `Scope.TRANSIENT`, or `manage=True`. Return to
[Modules](modules.md) when a dependency is private, unresolved, or ambiguous.

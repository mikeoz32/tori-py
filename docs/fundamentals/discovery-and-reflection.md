# Discovery and Reflection

Reflection attaches typed metadata to explicitly declared Python classes and
functions. Discovery reads immutable views of one application's already compiled
modules, providers, and controllers. Together they support integrations such as
OpenAPI, CQRS, and transports without package scanning, provider
auto-registration, mutable container access, or process-global registries.

These APIs are privileged introspection tools for infrastructure authors. Normal
application services should prefer explicit constructor dependencies.

## Typed Metadata

Create a unique typed decorator with `Reflector.create_decorator()`, or create a
`MetadataKey` and use `metadata()` directly:

```python
from tori_py import MetadataDecorator, MetadataKey, Reflector, metadata


ROLES: MetadataDecorator[tuple[str, ...]] = Reflector.create_decorator("roles")
METHOD_LABEL = MetadataKey[str]("method-label")


@ROLES(("admin",))
class BaseHandler:
    @metadata(METHOD_LABEL, "run")
    def run(self) -> None:
        pass


class ChildHandler(BaseHandler):
    pass


reflector = Reflector()

assert reflector.get(ROLES, ChildHandler) == ("admin",)
assert reflector.get_own(ROLES, ChildHandler) is None
assert reflector.get(METHOD_LABEL, ChildHandler().run) == "run"
assert ROLES.KEY is ROLES.key
```

This focused example follows the framework reflection tests. Metadata values are
attached directly to the target class or function in an immutable mapping. The
decorator returns the original target.

### Keys use identity, not names

Every `MetadataKey` has a unique identity. Two calls to
`Reflector.create_decorator("roles")` produce different keys even though their
diagnostic names match. Define a decorator once in the package that owns the
contract and import that public decorator wherever metadata is declared or read.

### Valid targets

Metadata may be attached to a class or Python function. It cannot be attached
directly to an arbitrary instance. Lookup accepts classes, functions, bound
methods, and instances; an instance lookup uses its class.

Declaring the same key twice on one target fails with
`reflection.duplicate_metadata`. Different keys may coexist.

## Reflector Lookup Semantics

| Method | Behavior |
| --- | --- |
| `get_own(key, target)` | Return only metadata directly declared on the target's class or function |
| `has_own(key, target)` | Distinguish directly declared metadata from absence |
| `get(key, target)` | Return direct metadata or the nearest value in class MRO order |
| `has(key, target)` | Check direct or inherited class metadata |
| `get_all_and_override(key, targets)` | Return the first present value from the caller's ordered targets |

Metadata may deliberately contain `None`. In that case, `get()` returning `None`
does not distinguish a stored value from absence; call `has()` or `has_own()`.
`get_all_and_override()` also respects an explicitly stored `None` as the first
present override.

Existing framework metadata APIs keep their own direct-only semantics. Generic
`Reflector.get()` inheritance does not make `@module()`, `@injectable()`,
controller, or route metadata inheritable where their public accessor reads only
direct declarations.

## Runtime Discovery Services

`ModulesContainer`, `DiscoveryService`, and the application-owned `Reflector`
are intrinsic constructor dependencies. Do not add them to `providers` or
`exports`:

```python
from tori_py import (
    ClassProvider,
    DiscoveryService,
    MetadataDecorator,
    ModulesContainer,
    ProviderView,
    Reflector,
    Scope,
    ScopedResolver,
    WorkScopeFactory,
    module,
)


HANDLER: MetadataDecorator[str] = Reflector.create_decorator("example.handler")


@HANDLER("billing")
class BillingHandler:
    pass


class HandlerRegistry:
    def __init__(
        self,
        modules: ModulesContainer,
        discovery: DiscoveryService,
        reflector: Reflector,
        scopes: WorkScopeFactory,
    ) -> None:
        self.modules = modules
        self.discovery = discovery
        self.reflector = reflector
        self.scopes = scopes
        self.handlers: tuple[ProviderView, ...] = ()

    async def on_application_bootstrap(self) -> None:
        self.handlers = self.discovery.get_providers(metadata=HANDLER)

    async def resolve(self, provider: ProviderView) -> object:
        async def operation(resolver: ScopedResolver) -> object:
            return await resolver.resolve(provider.token)

        return await self.scopes.run_in(provider.ref.module_id, operation)


@module(
    providers=[
        ClassProvider(BillingHandler, scope=Scope.REQUEST),
        ClassProvider(HandlerRegistry),
    ],
)
class BillingModule:
    pass
```

Discovery finds `BillingHandler` from its explicit provider declaration and
metadata. It does not instantiate the request-scoped handler. `run_in()` later
opens one application-tracked work scope from the handler's exact owning module,
so normal module visibility, request caching, cancellation, and resource cleanup
apply.

## ModulesContainer

`ModulesContainer` is a read-only application view keyed by exact `ModuleId`:

| Operation | Result |
| --- | --- |
| `len(modules)` | Number of compiled static and dynamic module identities |
| `for module_id in modules` | Exact identities in dependency-first compiled order |
| `modules[module_id]` | An immutable `ModuleView` for one exact identity |
| `modules.values()` | All `ModuleView` snapshots in compiled order |
| `modules.provider(module_id, token)` | The provider visible for that exact module/token, or `None` |

`ModuleView` contains:

- `module_id`: exact static or `(class, key)` dynamic identity;
- `module`: the module class;
- `providers`: canonical module-owned provider views, excluding controllers;
- `controllers`: canonical module-owned controller views.

The provider collections show ownership, not every token visible through
imports/globals. Use `modules.provider(module_id, token)` to ask what a specific
module can resolve. An unknown module identity raises `ScopeError`; a known
module with no visible token returns `None`.

## ProviderView

Each immutable provider snapshot exposes enough identity for deterministic
integration work:

| Field | Meaning |
| --- | --- |
| `ref` | Exact declaration reference, including owning `ModuleId` and token |
| `canonical` | Canonical provider reference after alias resolution |
| `token` | Class or string token represented by `ref` |
| `declaration` | Frozen value/class/factory/alias provider declaration |
| `scope` | Effective canonical scope |
| `implementation` | Statically known implementation type, or runtime type for an already created factory value |
| `instance_created` | Whether the application singleton cache contains the canonical provider |
| `instance` | Cached singleton entered value, including valid `None`, when created |

Class provider implementations are statically known. Value provider
implementations are the value type. A factory implementation remains `None`
until a singleton result has already been created; discovery never runs a
factory merely to learn its type. Request and transient instances are never
reported from request caches.

Managed providers may expose an entered value whose type differs from the
declared manager class. `implementation` retains the declared `ClassProvider`
class when available, while `instance` is the actual entered singleton value.

Default provider/controller enumeration canonicalizes aliases and does not emit
duplicate alias entries. Exact `ModulesContainer.provider()` lookup by an alias
token preserves the alias `ref` and declaration while reporting canonical scope,
implementation, and instance information.

## DiscoveryService

`DiscoveryService` enumerates provider or controller views in deterministic
compiled order:

```python
all_providers = discovery.get_providers()
billing_providers = discovery.get_providers(include=[BillingModule])
handlers = discovery.get_providers(metadata=HANDLER)
controllers = discovery.get_controllers()
```

The filters are explicit:

- `include` accepts an iterable of module classes. It does not import or scan
  those classes.
- A class include matches every compiled dynamic identity using that class; use
  each returned view's `ref.module_id` to retain its key.
- `metadata` accepts a `MetadataKey` or `MetadataDecorator` and checks the
  declared implementation before an already created entered singleton value.
- `get_metadata_by_decorator(decorator, provider)` returns metadata from those
  same provider targets.

Discovery includes private providers from every compiled module by default.
That is introspection privilege, not dependency visibility: an unrelated module
still cannot resolve a private token through its resolver.

## Executing Discovered Providers

Global discovery must not lead to unqualified global resolution. Two modules may
legitimately own the same token, especially two keyed dynamic modules. Keep the
`ProviderView` and execute from `provider.ref.module_id`:

```python
async def resolve_discovered(
    scopes: WorkScopeFactory,
    provider: ProviderView,
) -> object:
    async def operation(resolver: ScopedResolver) -> object:
        return await resolver.resolve(provider.token)

    return await scopes.run_in(provider.ref.module_id, operation)
```

`run_in()` validates that the `ModuleId` belongs to the current application and
opens a fresh isolated work scope. Duplicate same-token providers remain
separate and deterministic. Scoped construction and cleanup failures follow the
normal rules in [Scopes and Resources](scopes-and-resources.md).

An integration should normally discover during
`on_application_bootstrap()`: all singleton providers have been eagerly created,
the adapter is bound, and work scopes are available. Stop integration intake in
`on_application_quiesce()` before work admission closes. See
[Lifecycle](lifecycle.md).

## Failure Behavior

| Diagnostic/error | Cause |
| --- | --- |
| `reflection.invalid_metadata` | Empty key name, invalid target, invalid metadata storage, or invalid lookup key |
| `reflection.duplicate_metadata` | The same metadata key is declared twice on one target |
| `discovery.invalid_filter` | `include` is not iterable or contains a non-class value |
| `provider.reserved_token` | Application provider tries to own `ModulesContainer`, `DiscoveryService`, `Reflector`, or another intrinsic |
| `ScopeError` | `ModulesContainer` or `run_in()` receives an unknown compiled module identity |

Discovery itself never constructs request/transient providers, opens resources,
or changes application state. Metadata and returned views are immutable; there
is no public cache/resource stack mutation API.

## Testing Discovery

Resolve the integration provider after `TestingModule.compile()` has run normal
startup and bootstrap hooks:

```python
from tori_py.testing import TestingModule


application = await TestingModule.create(BillingModule).compile()
try:
    registry = await application.resolve(HandlerRegistry)
    assert isinstance(registry, HandlerRegistry)
    assert [view.token for view in registry.handlers] == [BillingHandler]
    assert registry.handlers[0].instance_created is False

    handler = await registry.resolve(registry.handlers[0])
    assert isinstance(handler, BillingHandler)
finally:
    await application.close()
```

Useful tests assert exact module keys, canonical alias identity, private-provider
non-resolution from the root, no scoped construction during discovery, and work
scope cleanup after `run_in()`.

```text
uv run pytest packages/tori-py/tests/test_framework_discovery.py
```

## NestJS and FastAPI Differences

For NestJS users, the names `Reflector`, `DiscoveryService`, and
`ModulesContainer` are intentionally familiar. ToriPy's metadata is
Python-native and typed rather than based on JavaScript `reflect-metadata`.
Discovery returns frozen snapshots and offers no `ModuleRef` mutation, package
scanner, or provider registration path.

For FastAPI users, this is not route/dependency-callable inspection. ToriPy
discovery starts from explicit compiled modules and can enumerate controllers,
but it does not inspect arbitrary `Depends` callables, Pydantic models, or
Starlette adapter internals. The optional [OpenAPI integration](../openapi/index.md)
combines controller discovery with ToriPy's public route compiler.

## Production Notes

- Give public metadata decorators stable names, but rely on imported key identity
  rather than reconstructing a key by name.
- Discover once during bootstrap and keep exact `ProviderView` identities when
  dispatch will occur later.
- Never treat discovery of a private provider as permission for root/global
  resolution.
- Use `run_in()` for scoped invocation and do not retain the resolver or scoped
  value after the operation returns.
- Avoid storing mutable application state in metadata; metadata values are shared
  declarations attached to Python targets.
- Keep integrations lifecycle-managed and cancellation-cooperative.

## Related APIs

- Reflection: `MetadataKey`, `MetadataDecorator`, `metadata`, `Reflector`
- Discovery protocols: `ModulesContainer`, `DiscoveryService`
- Views: `ModuleView`, `ProviderView`
- Exact identities: `ModuleId`, `ProviderRef`
- Scoped execution: `WorkScopeFactory`, `ScopedResolver`
- Failures: `BootstrapError`, `ScopeError`

## Next Steps

Return to the [Concepts Map](../concepts-map.md) for the full architecture view.
Read [Modules](modules.md) for exact dynamic identity and provider visibility,
and [Lifecycle](lifecycle.md) before starting discovery-driven subsystem work.

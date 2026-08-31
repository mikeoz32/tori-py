# Testing Applications

`TestingModule` changes a module graph before compilation and then uses the same
container, adapter, startup, request scopes, and bounded shutdown as a production
application. It does not maintain a separate test runtime.

Install the optional HTTP client for an application project:

```text
uv add --dev 'tori-py-framework[testing]'
```

Run tests through the project environment:

```text
uv run pytest
```

## Basic Workflow

The Getting Started example demonstrates an exported provider override and an
HTTP request:

```python
--8<-- "examples/tori_py/getting_started/first_test/test_example.py"
```

The required lifecycle is:

1. Create a mutable builder with `TestingModule.create(root)`.
2. Record module and provider overrides.
3. Call `compile()`. This seals the builder, compiles the production graph, and starts the application.
4. Exercise providers or HTTP.
5. Always await `TestingApplication.close()` in `finally`.

A builder remains sealed even if compilation fails. Create a new builder for a
different graph or another attempt.

## Provider Overrides

Targeted provider overrides require both a token and a module identity:

```python
builder.override_provider(Repository, module=FeatureModule).use_value(fake)
```

The fluent terminal operations are:

| Operation | Resulting declaration |
| --- | --- |
| `.use_value(value)` | `ValueProvider(token, value)` |
| `.use_class(implementation)` | `ClassProvider(token, implementation)` |
| `.use_factory(factory)` | `FactoryProvider(token, factory)` |
| `.use_alias(target)` | `AliasProvider(token, target)` |

Value, class, and factory replacements use their provider declaration's default
singleton scope. An alias replacement has no scope of its own and inherits its
canonical target's effective scope. There is no fluent scope argument. If a
value, class, or factory replacement must retain request-scope behavior, replace
the containing deferred module with a test module that declares the required
provider scope instead of silently changing the production boundary.
`.use_value()` also creates an unmanaged value provider; `close()` will not call
resource methods on that externally supplied object. Class and factory
replacements retain their declarations' normal managed-resource behavior.

Only a token exported by the selected module can be overridden. A same-token
private provider is rejected with `testing.private_provider`. The replacement
is compiled normally, so constructor/factory injection, alias visibility,
dependency cycles, and scope rules are revalidated.

Use `override_global(token)` only for a token exported by an explicitly global
module:

```python
builder.override_global(Clock).use_value(fixed_clock)
```

It does not make an ordinary module global and is not a shortcut around exports.

An absent target module or otherwise unmatched override fails compilation with
`testing.invalid_override`; it is never silently ignored.

## Module Identity And Replacement

Static modules are selected by class:

```python
builder.override_provider(Repository, module=FeatureModule)
```

Keyed dynamic modules are selected by their descriptor or exact identity tuple:

```python
builder.override_provider(
    SettingsModel,
    module=(SettingsModule, "tenant-a"),
)
```

Passing only the dynamic module class selects the static identity and does not
match keyed descriptors.

`replace_module(target, replacement)` replaces a deferred descriptor before the
original descriptor materializes. The target is either the original
`DeferredModule` or its `(module_class, key)` tuple; the replacement is a static
module class or another deferred descriptor. This is the correct tool when a
test must avoid opening, parsing, or otherwise materializing the production
dynamic module at all.

## Resolving Providers

`TestingApplication.resolve(token)` resolves from the compiled root module.
Pass a static class, `(class, key)`, or public `ModuleId` to resolve from another
module identity:

```python
value = await application.resolve(
    Repository,
    module=FeatureModule,
)
```

Resolution follows that module's normal visibility and can be used for focused
lifecycle assertions. The facade intentionally does not expose mutable provider
caches, resource stacks, or container mutation.

## HTTP Testing

Compile with a fresh `StarletteAdapter`, then use the async client context:

```python
application = await builder.compile(adapter=StarletteAdapter())
try:
    async with application.http_client() as client:
        response = await client.get("/health")
finally:
    await application.close()
```

`TestingApplication.http_client()` and the standalone `http_client()` helper use
`httpx.ASGITransport`. Options are:

| Option | Default | Meaning |
| --- | --- | --- |
| `base_url` | `http://testserver` | Base URL used by HTTPX. |
| `raise_app_exceptions` | `False` | Whether transport-level application exceptions escape instead of becoming a response where possible. |
| `client_address` | `("testclient", 50000)` | Client address placed in the ASGI scope. |

The helper requires an already-started application using `StarletteAdapter`.
It rejects compiled-but-unstarted and stopped applications. It also reports an
actionable `testing.httpx_unavailable` error if the testing extra is absent.

Create a new adapter for each application. A `StarletteAdapter` is owned by one
compiled application and cannot be reused.

## Lifespan Testing

There are two distinct test paths:

| Goal | Correct path |
| --- | --- |
| Test graph overrides, providers, routes, and production startup/shutdown | `TestingModule.compile()`, HTTP client, then `close()` |
| Test the exported `asgi(create_application)` factory and ASGI lifespan protocol itself | Drive `lifespan.startup` and `lifespan.shutdown` against the exported wrapper |

HTTPX `ASGITransport` does not initiate ASGI lifespan. Do not put a second
lifespan manager around a `TestingApplication`: `compile()` has already started
it, and its HTTP client intentionally performs no lifespan actions.

For an exported-wrapper test, start one lifespan task, send
`lifespan.startup`, wait for `lifespan.startup.complete`, make HTTP requests
against the wrapper, send `lifespan.shutdown`, and await
`lifespan.shutdown.complete`. This verifies that the async factory is awaited in
the server event loop and that the wrapper owns exact startup and shutdown. The
executable repository example is
`packages/tori-py/tests/docs/test_getting_started_examples.py::test_asgi_wrapper_examples_serve_after_lifespan`.

The wrapper is one-shot. Do not restart the same wrapper in another test; import
or construct a fresh wrapper and application instance.

## Lifecycle And Failure Tests

`compile()` starts eager singletons, managed resources, hooks, and the adapter.
`close()` runs the production shutdown path, including quiescence, request/work
drain, hooks, adapter close, and LIFO resource cleanup. This makes it suitable
for asserting:

- startup failures roll back already-acquired resources;
- deferred settings failures happen before application resources and hooks;
- request-scoped resources close after the complete response;
- singleton resources close only when the testing application closes;
- lifecycle hooks run in production order;
- shutdown failures and configured deadlines propagate to the test.

When `compile()` raises, startup rollback is automatic and there is no
`TestingApplication` to close. When compilation succeeds, use `try/finally` even
if an assertion or HTTP call fails.

For deterministic settings tests, pass an explicit `environment` mapping to
`SettingsOptions`, replace the settings dynamic module before materialization,
or establish a `BootstrapContext` around the factory/compile operation. Do not
depend on the developer machine's process environment.

## Boundaries

- Private provider overrides are intentionally unsupported.
- Overrides do not mutate an already compiled application.
- The builder has no reset or unseal operation.
- The standard client is async; no synchronous test client is provided.
- The HTTP helper tests in-process ASGI behavior, not sockets, proxy headers, TLS, Uvicorn configuration, or multi-process deployment.
- `raise_app_exceptions=False` is useful for response assertions, but tests for cancellation or failures after response transmission may need lower-level ASGI assertions.
- Production authorization and security boundaries must still be tested through public behavior; a private-provider shortcut is not a valid substitute.

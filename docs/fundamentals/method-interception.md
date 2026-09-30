# Method Interception

Method interception is an opt-in way to apply cross-cutting behavior to
application provider methods. It is useful for extension packages that want to
offer decorators such as `@transactional` without coupling the ToriPy core to a
database or authorization library.

## Opt In Per Provider

The default provider remains the original instance. Enable a proxy with either
the `@injectable()` shorthand or an explicit `ClassProvider`:

```python
from tori_py import ClassProvider, Scope, injectable, module


@injectable(scope=Scope.SINGLETON, proxy=True)
class PaymentService:
    ...


class BillingService:
    ...


@module(
    providers=[
        PaymentService,
        ClassProvider(BillingService, proxy=True),
    ]
)
class ServicesModule:
    pass
```

The proxy preserves provider scope, constructor injection, managed-resource
cleanup, and `isinstance(proxy, ProviderClass)`. Proxying does not make a
singleton request-scoped; its target and proxy remain shared across callers.

## Attach Method Interceptors

Use `@use_method_interceptors()` to attach provider tokens or direct interceptor
instances to an async method:

```python
from typing import Annotated

from tori_py import (
    ClassProvider,
    MethodInvocationContext,
    injectable,
    module,
    use_method_interceptors,
)


events: list[str] = []


class AuditInterceptor:
    async def intercept(
        self,
        context: MethodInvocationContext,
        next,
    ) -> object:
        events.append(f"start:{context.provider_ref.token}:{context.method_name}")
        result = await next()
        events.append(f"success:{context.method_name}")
        return result


@injectable(proxy=True)
class PaymentService:
    @use_method_interceptors(AuditInterceptor)
    async def charge(self, payment_id: str) -> str:
        return payment_id


@module(providers=[PaymentService, ClassProvider(AuditInterceptor)])
class PaymentsModule:
    pass
```

An interceptor provider token is resolved from the active request or work scope
on each intercepted call, so a request-scoped interceptor is never captured by
a singleton proxy. The interceptor context includes the provider reference,
method name, immutable keyword-argument mapping, positional arguments, and a
qualified resolver for the provider's module. That resolver is invalidated with
its request/work scope; do not retain it for later calls. A direct interceptor
instance is shared as declared and must be safe for concurrent calls; use a
provider token for scope-managed state.

Unadvised public async methods are forwarded by the proxy without creating an
interceptor context. Synchronous methods are not intercepted in this version;
declaring interceptors on one fails graph compilation. Method interceptor
metadata on a provider requires `proxy=True`.

## Write Decorator Sugar

Extension packages can make a focused decorator by attaching their interceptor
token:

```python
from tori_py import use_method_interceptor


def transactional(method):
    return use_method_interceptor(TransactionInterceptor)(method)
```

The package supplies `TransactionInterceptor` and its provider registration;
the core only supplies proxying and the method-interceptor contract. Application
decorators such as `@requires_policy(...)` can use the same mechanism while
keeping the policy implementation application-owned. The interceptor token must
be visible from the provider's owning module.

Stacked method-interceptor decorators run outermost first on entry and unwind in
reverse order. Each interceptor may await `next()` at most once or short-circuit
with its own result. Calls made from an intercepted target to `self.other()` run
on the target instance and bypass the proxy; call through an injected proxy when
the nested method also needs interception.

## Scope and Concurrency

An intercepted call requires an active ToriPy request or work scope. Calls made
outside one fail with `ScopeError`; the proxy never retains a scoped resolver.
Scoped interceptors resolve under the active scope and inherit its task-owner
checks, so a child task cannot use the parent invocation's request-scoped
dependencies.

Keep tenant, actor, and other per-invocation state in scoped providers or pass
immutable context explicitly. Do not store it on a singleton provider or the
proxy. For example, an HTTP request and a LiveView page work scope are distinct
scopes; each must establish its own caller context.

The [method-interception example](../reference/examples.md#framework-overview)
shows a small bearer-authenticated HTTP entry point and an in-process
work-scoped caller invoking the same permission-protected service without an
HTTP round trip. Its fixed bearer tokens are demonstration credentials only.

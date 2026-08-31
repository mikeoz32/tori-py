# Authorization and Errors

Tori Py supplies guard and filter extension points, not an authentication or
authorization product. Keep trusted identity extraction in an application or
edge adapter, make policy a provider, let a guard decide whether execution may
continue, and disclose only explicitly approved errors.

## Policy provider and guard

This educational policy checks a header. A production policy must receive a
validated principal, not trust an arbitrary header directly.

```python
from typing import Protocol

from tori_py import ClassProvider, controller, module, post, use_filter, use_guard
from tori_py.starlette import RequestContext


class WritePolicy(Protocol):
    async def allows(self, context: RequestContext) -> bool: ...


class HeaderWritePolicy:
    async def allows(self, context: RequestContext) -> bool:
        return context.headers.get("x-write-policy") == "allow"


class WriteGuard:
    def __init__(self, policy: WritePolicy) -> None:
        self._policy = policy

    async def can_activate(self, context: RequestContext) -> bool:
        return await self._policy.allows(context)
```

A `False` guard result becomes the framework's standard 403 Problem Details
response. Raise `HttpException(403, "approved public detail")` instead only when
the application intentionally owns a different public detail or headers.

The guard uses `RequestContext` because it intentionally depends on Starlette
headers. A transport-neutral policy should accept `ExecutionContext` or an
application principal instead. Do not pass the complete native request into the
domain model.

## Map owned domain failures

Filters should handle only errors they own and re-raise everything else. A
portable `HttpResponse` can return a stable Problem Details body without a
Starlette response type:

```python
import json

from tori_py import HttpResponse, PipelineResult


class TaskNotFound(Exception):
    pass


class TaskErrorFilter:
    async def catch(self, error: Exception, context) -> PipelineResult:
        if not isinstance(error, TaskNotFound):
            raise error
        content = json.dumps(
            {
                "type": "about:blank",
                "title": "Not Found",
                "status": 404,
                "detail": "Task was not found.",
            },
            separators=(",", ":"),
        ).encode()
        return PipelineResult.from_response(
            HttpResponse(
                content,
                status_code=404,
                headers={"Content-Type": "application/problem+json"},
            )
        )
```

The detail is constant and deliberately public. Do not include the original
exception text, a database key, credential, policy rule, stack trace, or object
representation. The Starlette adapter supplies the framework-owned request ID
header on the explicit response.

Register the policy, guard, and filter as providers so constructor injection and
lifecycle ownership are explicit:

```python
@controller("/tasks")
class TaskController:
    @post("")
    @use_guard(WriteGuard)
    @use_filter(TaskErrorFilter)
    async def create(self) -> dict[str, bool]:
        return {"created": True}


@module(
    providers=[
        ClassProvider(WritePolicy, HeaderWritePolicy),
        ClassProvider(WriteGuard),
        ClassProvider(TaskErrorFilter),
    ],
    controllers=[TaskController],
    exports=[WritePolicy],
)
class TasksModule:
    pass
```

Pipeline order matters: middleware runs before guards; argument binding and
pipes run only after guards; interceptors wrap the handler; filters form the
ordinary-exception boundary. Filters are tried route, controller, then global.
They do not catch `asyncio.CancelledError`, `KeyboardInterrupt`, `SystemExit`, or
another `BaseException`.

Unmatched 404 and 405 errors have only global filters because no controller or
route matched. Errors during or after response transmission cannot safely be
re-rendered.

## Authentication boundary

A guard receives request metadata; that does not make it an authenticator. A
production flow normally separates:

1. Validate a credential using an application-owned verifier.
2. Construct a minimized, trusted principal.
3. Make that principal available only for the current scope.
4. Ask a policy provider about the requested action and resource.
5. Enforce domain invariants again where state changes occur.

Request IDs, path parameters, message routing keys, broker headers, and stream
partition keys are observability or transport facts, never authorization facts.
For inaccessible private resources, a generic 404 may disclose less than a 403;
that is application policy, not a framework default.

## Testing

Replace the exported policy token, not the guard or a private repository, when
testing authorization outcomes:

```python
from tori_py.starlette import StarletteAdapter
from tori_py.testing import TestingModule


class AllowAllWrites:
    async def allows(self, context: RequestContext) -> bool:
        return True


testing = TestingModule.create(TasksModule)
testing.override_provider(WritePolicy, module=TasksModule).use_value(
    AllowAllWrites()
)
application = await testing.compile(adapter=StarletteAdapter())
try:
    async with application.http_client() as client:
        response = await client.post("/tasks")
        assert response.status_code == 200
finally:
    await application.close()
```

Also test the denied path without replacement, domain-error mapping, filter
fallthrough for an unowned exception, and that a 500 response omits sensitive
exception text. `TestingModule.compile()` starts the application; always close
it, and do not add another lifespan manager around its HTTP client.

## Other transports

Microservices and persistent streams reuse transport-neutral guards, pipes,
interceptors, and filters in their own invocation pipelines, but do not reuse the
HTTP executor or HTTP middleware. `MessageAuthorizationError` is a typed message
failure. A public RPC error must be an explicit `PublicRpcError`; unexpected
exceptions are sanitized before crossing the wire. Stream filters can observe
an ordinary failure but cannot turn a failed record into a checkpoint-eligible
success.

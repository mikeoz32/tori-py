# Advanced OpenAPI Usage

## Startup and Caching

`OpenApiModule` generates the document when its singleton document service is
constructed during application startup. It discovers every compiled controller,
including the generated documentation controller, which is marked excluded.

Generation does not happen during `NestApplication.create()` and does not happen
per request. JSON and Swagger HTML bytes are reused for every request.

Consequences:

- OpenAPI-specific invalid schemas fail startup before traffic is accepted;
- runtime route mutation is unsupported and cannot update the document;
- request-time documentation cost is a cached response plus the normal pipeline;
- no scoped or transient controller provider is constructed for discovery.

## Path Normalization

Starlette converter syntax is normalized through its public path compiler:

```text
/members/{member_id:int} -> /members/{member_id}
```

The following fail startup:

- same method and normalized path;
- canonically equivalent templates such as `/items/{id}` and `/items/{name}`;
- an earlier same-effective-method template shadowing a later concrete path;
- an earlier excluded equivalent template shadowing a documented template;
- missing, extra, or duplicate path bindings.

GET is treated as including HEAD for selected shadow checks. Exact route
duplicates and documentation endpoint conflicts remain normal ToriPy bootstrap
errors.

## Operation and Component Identity

Prefer stable explicit operation IDs for public client-generation contracts:

```python
@api_operation(operation_id="members_read")
async def read(self) -> MemberView:
    raise NotImplementedError
```

Otherwise the generated ID derives from `{Controller.__qualname__}_{method}`.
Every included operation ID must be unique.

Schema component names come from msgspec. Two distinct models producing the same
component name fail startup. Give public models stable, unique class names.

## Understanding Diagnostics

Route-specific `OpenApiSchemaError` diagnostics normally include:

```python
{
    "method": "GET",
    "path": "/members/{member_id:int}",
    "handler": "MembersController.read",
}
```

Depending on the error, details may also include:

- `annotation` for schema failures;
- `parameter`, `missing`, or `extra` for bindings;
- `normalized_path` and `conflicting_path` for collisions;
- `shadowing_method` and `shadowing_path` for route order;
- schema annotations and the underlying msgspec cause.

Configuration and metadata errors can occur while options and decorators are
constructed. ToriPy route signature, annotation-resolution, and exact duplicate
errors can occur during `NestApplication.create()`. The OpenAPI diagnostics in
this section occur during `application.start()`. Do not catch any of them to
serve a partial schema.

## Testing Documentation

Test the generated endpoint through the application rather than calling compiler
internals:

```python
import httpx
import pytest
from tori_py.starlette import StarletteAdapter

from myapp import create_application


@pytest.mark.asyncio
async def test_openapi_document() -> None:
    application = await create_application()
    await application.start()
    transport = httpx.ASGITransport(
        app=application.get_adapter(StarletteAdapter).app
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    document = response.json()
    assert document["openapi"] == "3.1.0"
    assert "/members/{handle}" in document["paths"]
    await application.shutdown()
```

Useful assertions include operation IDs, public/security overrides, requiredness,
response models, static headers, and absence of excluded/internal docstring text.

The runnable guide example has an integration test at
`examples/tori_py/openapi/test_openapi_example.py`.

## Multiple Module Keys

`OpenApiModule.for_root(options, key="default")` participates in normal ToriPy
dynamic-module identity. Use distinct keys only when an application intentionally
owns multiple independently configured module instances. Each instance performs
its own discovery and owns its own generated routes, so paths must also be
distinct to avoid normal route conflicts.

Most applications should configure exactly one root instance.

## Current Non-goals

The current package deliberately does not provide:

- FastAPI or Pydantic integration;
- package scanning or global registries;
- guard, filter, or handler-body inference;
- runtime response validation;
- multipart, form, file, streaming, callback, webhook, or WebSocket schemas;
- OAuth flow builders;
- ReDoc, bundled assets, YAML output, or client generation;
- parameter descriptions, examples, or styles;
- server variables;
- per-response media types beyond inferred static `Content-Type` metadata;
- automatic documentation for native Starlette response behavior.

Use `HttpResponse` plus explicit `api_response` metadata for portable opaque
responses. Exclude driver-specific escape-hatch routes when their contract cannot
be expressed accurately.

## Troubleshooting

| Symptom | Likely cause | Resolution |
| --- | --- | --- |
| Startup fails with unconstrained schema | `Any`, `object`, or unsupported annotation | Replace it with a concrete model |
| Opaque response requires explicit responses | `HttpResponse` or `PipelineResult` annotation | Add model-free or modeled `api_response` entries |
| Unknown security scheme | `api_security()` name is not configured | Add the matching bearer scheme or correct the name |
| `/docs` conflicts at bootstrap | Application already owns the path | Configure another `docs_path` or disable UI |
| Swagger page loads without styling/scripts | CSP/network blocks assets or inline bootstrap code | Permit assets and configure hashes/nonces/inline policy, or transform the page |
| Template shadow diagnostic | Earlier route captures a later documented path | Reorder or redesign routes to remove ambiguity |
| Static header missing from explicit response docs | Explicit primary responses do not inherit inference | Document that response explicitly; use inferred response when appropriate |

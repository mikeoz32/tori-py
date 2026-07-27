# Nestpy OpenAPI Architecture

Status: approved revised architecture. Executable requirements are split across
`spec/nestpy-openapi/phase-oa0-*.md` through `phase-oa4-*.md`.

## 1. Purpose

`nestpy-openapi` is an optional Nestpy dynamic module that generates an OpenAPI
3.1 document from the controllers and HTTP mappings in one compiled Nestpy
application. It exposes the cached JSON document and Swagger UI through normal
Nestpy controller routes.

The package integrates at the Nestpy application-model boundary:

```text
compiled modules
  -> DiscoveryService controller views
  -> public Nestpy controller-route mapping compiler
  -> OpenAPI document compiler
  -> OpenApiModule controller
  -> normal Nestpy HTTP pipeline
```

It does not inspect or extend `StarletteAdapter`. The adapter remains concerned
only with binding Nestpy route plans to Starlette.

## 2. Application API

Applications configure one descriptor and import it normally:

```python
openapi_module = OpenApiModule.for_root(
    OpenApiOptions(
        info=OpenApiInfo(title="Kinker API", version="0.1.0"),
        docs_path="/docs",
        openapi_path="/openapi.json",
    )
)


@module(imports=[openapi_module, MembersModule, HealthModule])
class AppModule:
    pass
```

`for_root()` returns one `DeferredModule` keyed by `(OpenApiModule, key)`. Its
materialized `ModuleSpec` owns:

- the immutable `OpenApiOptions` value provider;
- one singleton document service;
- one generated singleton Nestpy controller whose paths come from the options.

There is no post-compilation `setup()` call and no application or adapter
mutation.

## 3. Goals

The first slice MUST provide:

- distribution `nestpy-openapi` and import `nestpy_openapi`;
- `OpenApiModule.for_root()` dynamic-module composition;
- OpenAPI 3.1.0 generated from compiled-module controller declarations;
- request parameter/body and response schemas from Nestpy route mappings and
  resolved annotations;
- explicit tags, operation metadata, responses, bearer security, public
  overrides, and exclusion;
- cached `/openapi.json` and Swagger UI routes at configured paths;
- immediate Kinker integration;
- fail-fast startup diagnostics for an invalid document.

## 4. Non-Goals

The first slice MUST NOT provide:

- FastAPI, Pydantic, `python-openapi`, or a second request runtime;
- adapter route access, adapter extension routes, or native route registration;
- package scanning or a process-global controller registry;
- inference of security from guards or errors from filters/handler bodies;
- response validation or serialization changes;
- multipart, form, files, streaming, WebSockets, callbacks, or webhooks;
- ReDoc, bundled Swagger assets, YAML output, or client generation.

## 5. Package Boundary

```text
nestpy-openapi -> nestpy, msgspec, starlette
nestpy         -X-> nestpy-openapi
```

The direct Starlette dependency is limited to its public route-template
compiler. Documentation responses use Nestpy's transport-neutral
`HttpResponse`; controller discovery, route mapping, lifecycle, pipeline
execution, and request scopes remain Nestpy-owned.

`python-openapi` 0.3.0 remains rejected. Its generator rescans classes with
different method/source/default/media-type conventions, while its lower-level
mutable models add `json_strong_typing` and `jsonschema` without replacing the
Nestpy-specific controller mapping step.

## 6. Required Nestpy Contract

Nestpy HTTP exposes one transport-neutral helper:

```python
def compile_controller_routes(
    module_id: ModuleId,
    controller: type[object],
) -> tuple[RoutePlan, ...]: ...
```

The helper is the canonical compiler for one declared controller. It:

- reads `@controller`, route, status, pipeline, and binding metadata;
- joins controller and method paths exactly as runtime compilation does;
- resolves parameter and return annotations once for that invocation;
- returns immutable unbound `RoutePlan` values;
- rejects invalid declarations with normal Nestpy bootstrap diagnostics.

`compile_routes(graph)` MUST delegate each controller to this helper and retain
graph-wide exact duplicate validation. The helper is public so integrations do
not copy Nestpy private path/binding logic.

`RoutePlan.return_annotation` is appended with
`inspect.Signature.empty` as its default to preserve existing construction and
positional compatibility. Runtime response handling does not use it.

No `StarletteAdapter` API changes and no unrelated body/status behavior changes
belong to this feature.

## 7. Controller Discovery

The singleton document service injects the public `DiscoveryService` intrinsic
and `OpenApiOptions`. During singleton startup it calls
`DiscoveryService.get_controllers()` and, for every view:

1. obtains the controller implementation class and exact `ModuleId` from the
   immutable provider view;
2. calls `compile_controller_routes(view.ref.module_id, controller)`;
3. merges package-owned documentation metadata from the controller and unbound
   handler;
4. compiles included route plans into one document.

Discovery inspects only the already compiled module graph. It performs no module
or package scan and does not instantiate request/transient providers.

The generated documentation controller is marked `api_exclude()`. It is visible
to normal discovery and routing but absent from the generated document.

## 8. Documentation Controller

`for_root()` creates a private controller class and applies normal Nestpy
metadata programmatically:

- `@controller()`;
- `@get(openapi_path)` on the JSON method;
- optional `@get(docs_path)` on the Swagger method;
- `@api_exclude()` on the class.

The controller injects the singleton document service and returns Nestpy
`HttpResponse` values containing precomputed bytes and content-type headers.

These endpoints are ordinary Nestpy routes. They:

- participate in normal duplicate-route compilation;
- run through global/controller/route middleware, guards, pipes, interceptors,
  filters, request scopes, and request IDs;
- follow normal Starlette ordering, overlap, redirect, and HEAD behavior;
- require no special route conflict matcher in the OpenAPI package.

Applications that secure documentation do so with normal Nestpy pipeline policy.

## 9. Configuration and Metadata

The first slice exposes immutable `OpenApiInfo`, `OpenApiServer`,
`BearerSecurityScheme`, `SwaggerUiOptions`, and `OpenApiOptions` values.
Documentation paths are absolute static paths. Swagger assets are absolute HTTPS
or root-relative URLs, and UI parameters cannot override `url`, `urls`, `spec`,
or `dom_id`.

Metadata decorators attach immutable direct metadata without registration:

- `api_tags(*tags)`;
- `api_operation(...)`;
- repeatable `api_response(status_code, ...)`;
- repeatable `api_security(name, scopes=())`, represented as OR alternatives;
- `api_public()` to clear inherited controller security;
- `api_exclude()`.

Guards and filters are opaque. Security and error responses are documented only
when explicitly declared.

## 10. Operation and Schema Compilation

The document compiler consumes only discovered `RoutePlan` values,
`OpenApiOptions`, and package metadata. It does not inspect application adapters.

It MUST:

- emit OpenAPI `3.1.0`;
- support GET, PUT, POST, DELETE, OPTIONS, HEAD, PATCH, and TRACE;
- normalize Starlette converters through Starlette's public path compiler;
- reject invalid path bindings, normalized operation collisions, equivalent
  templated paths, duplicate operation IDs, and concrete paths shadowed by an
  earlier same-effective-method template;
- document Path/Query/Header/Cookie requiredness from Python defaults;
- document static response `@header` metadata on inferred encoded responses;
- document one `Body` mapping as `application/json` using current Nestpy body
  presence semantics;
- omit `Context` and `Inject`;
- infer ordinary success responses from route status and return annotation;
- require explicit responses for `HttpResponse`/`PipelineResult` annotations;
- omit content for explicitly documented 204/304 and reject models on them.

Schemas use one `msgspec.json.schema_components()` call with references under
`#/components/schemas/`. `Any` is rejected recursively. The supported union
subset is scalar unions, nullable models, and tagged `msgspec.Struct` unions;
unsupported untagged multi-object unions fail startup.

Route defaults are documented only when already strict native JSON values:
`None`, booleans, integers, finite floats, strings, lists, and string-keyed
dictionaries recursively containing those values.

The compiler assembles a plain dictionary/list graph, encodes it once, then
deep-freezes the same graph for internal read-only access.

Operation descriptions default to the cleaned route method docstring when
`api_operation(description=...)` is absent. Only text before the first form-feed
(`\f`) is public, matching Python documentation tooling conventions; explicit
metadata always wins, and summaries remain explicit-only.

## 11. Swagger UI

The service precomputes responsive Swagger UI HTML using one pinned exact asset
version. Titles and URLs are HTML escaped. UI configuration is JSON encoded and
`<`, `>`, and `&` are escaped before embedding in script content. The configured
OpenAPI URL and DOM ID are package-owned.

Assets are not downloaded or bundled. Deployment documentation MUST mention
external asset/CSP requirements.

## 12. Kinker Integration

Kinker adds `nestpy-openapi==0.1.0`, creates one `openapi_module` descriptor, and
imports it from `AppModule`. It serves `/openapi.json` and `/docs`, declares an
`oidcBearer` JWT scheme in components, and adds explicit health tags/summaries.
Authenticated Members and Profiles routes declare the bearer requirement,
stable operation IDs, summaries, and a shared tag. No root security requirement
is applied, so health remains public.

## 13. Errors and Lifecycle

Configuration/metadata errors fail eagerly when values/decorators are created.
Controller discovery and schema errors fail application startup while singleton
providers initialize. No partially generated document is served.

The document and HTML are generated once per dynamic-module instance and reused
for every request. Shutdown owns no additional resource.

## 14. Change Control

1. Update this architecture before changing integration ownership.
2. Update the affected OA phase before behavior changes.
3. Update Nestpy N4 before changing the public controller route compiler.
4. Add behavioral tests for each changed invariant.
5. Do not introduce adapter coupling or duplicate Nestpy mapping logic.

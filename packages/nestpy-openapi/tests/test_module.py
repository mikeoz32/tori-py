import json
import re
from typing import Any, cast

import httpx
import nestpy_openapi.module as module_impl
import pytest
from nestpy import (
    BootstrapError,
    ExecutionContext,
    ModuleId,
    ModuleSpec,
    NestApplication,
    controller,
    get,
    get_controller_metadata,
    get_route_metadata,
    module,
)
from nestpy.http import RoutePlan
from nestpy.starlette import StarletteAdapter
from nestpy_openapi import (
    OpenApiConfigurationError,
    OpenApiInfo,
    OpenApiModule,
    OpenApiOptions,
    OpenApiSchemaError,
    SwaggerUiOptions,
)
from nestpy_openapi.compiler import CompiledOpenApiDocument
from nestpy_openapi.metadata import get_direct_metadata


def _options(**changes: object) -> OpenApiOptions:
    values: dict[str, object] = {"info": OpenApiInfo("Example API", "1.0.0")}
    values.update(changes)
    return OpenApiOptions(**cast(Any, values))


async def _request(
    application: NestApplication,
    method: str,
    path: str,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=application.get_adapter(StarletteAdapter).app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.request(method, path)


def test_for_root_validates_options_and_materializes_normal_nestpy_controller() -> None:
    with pytest.raises(OpenApiConfigurationError, match="OpenApiOptions"):
        OpenApiModule.for_root(cast(Any, object()))

    descriptor = OpenApiModule.for_root(
        _options(openapi_path="/schema.json", docs_path="/reference")
    )
    spec = cast(ModuleSpec, descriptor.factory())
    assert descriptor.module is OpenApiModule
    assert descriptor.key == "default"
    controllers = tuple(spec.controllers)
    assert len(controllers) == 1
    docs_controller = controllers[0]
    assert get_controller_metadata(docs_controller) is not None
    openapi_mapping = get_route_metadata(cast(Any, docs_controller).openapi)
    swagger_mapping = get_route_metadata(cast(Any, docs_controller).swagger)
    assert openapi_mapping is not None
    assert swagger_mapping is not None
    assert openapi_mapping.path == "/schema.json"
    assert swagger_mapping.path == "/reference"
    assert get_direct_metadata(docs_controller).excluded
    assert len(tuple(spec.providers)) == 2
    assert spec.exports == ()


def test_docs_none_materializes_only_the_json_mapping() -> None:
    descriptor = OpenApiModule.for_root(_options(docs_path=None), key="internal")
    spec = cast(ModuleSpec, descriptor.factory())
    controller_type = tuple(spec.controllers)[0]
    assert get_route_metadata(cast(Any, controller_type).openapi) is not None
    assert get_route_metadata(cast(Any, controller_type).swagger) is None


@pytest.mark.asyncio
async def test_document_is_discovered_once_and_docs_controller_is_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @controller()
    class HealthController:
        @get("/health")
        async def health(self) -> dict[str, str]:
            return {"status": "ok"}

    openapi_module = OpenApiModule.for_root(_options())

    @module(imports=[openapi_module], controllers=[HealthController])
    class Root:
        pass

    route_compilations = 0
    document_compilations = 0
    original_routes = module_impl.compile_controller_routes
    original_document = module_impl.compile_openapi_document

    def count_routes(
        module_id: ModuleId,
        controller_type: type[object],
    ) -> tuple[RoutePlan, ...]:
        nonlocal route_compilations
        route_compilations += 1
        return original_routes(module_id, controller_type)

    def count_document(
        plans: tuple[RoutePlan, ...],
        options: OpenApiOptions,
    ) -> CompiledOpenApiDocument:
        nonlocal document_compilations
        document_compilations += 1
        return original_document(plans, options)

    monkeypatch.setattr(module_impl, "compile_controller_routes", count_routes)
    monkeypatch.setattr(module_impl, "compile_openapi_document", count_document)
    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    assert route_compilations == document_compilations == 0
    await application.start()
    assert route_compilations == 2
    assert document_compilations == 1

    first = await _request(application, "GET", "/openapi.json")
    second = await _request(application, "GET", "/openapi.json")
    head = await _request(application, "HEAD", "/openapi.json")
    assert first.status_code == second.status_code == head.status_code == 200
    assert first.content == second.content
    assert head.content == b""
    assert first.headers["content-type"] == "application/json; charset=utf-8"
    assert "x-request-id" in first.headers
    document = first.json()
    assert set(document["paths"]) == {"/health"}
    assert route_compilations == 2
    assert document_compilations == 1
    await application.shutdown()


@pytest.mark.asyncio
async def test_swagger_html_is_cached_and_safely_encoded() -> None:
    malicious = "</script><script>alert('&')</script>"
    openapi_module = OpenApiModule.for_root(
        _options(
            info=OpenApiInfo('<Example & "API">', "1.0.0"),
            openapi_path="/schema.json",
            swagger_ui=SwaggerUiOptions(
                javascript_url='https://cdn.example.test/swagger.js?value=">&',
                stylesheet_url='/swagger.css?value=">&',
                parameters={"layout": malicious, "deepLinking": True},
            ),
        )
    )

    @module(imports=[openapi_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    response = await _request(application, "GET", "/docs")
    body = response.text
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert '<meta name="viewport"' in body
    assert "<noscript>" in body
    assert "&lt;Example &amp; &quot;API&quot;&gt;" in body
    assert malicious not in body
    assert "\\u003c/script\\u003e" in body
    assert "\\u0026" in body
    match = re.search(r"SwaggerUIBundle\((\{.*\})\);", body)
    assert match is not None
    assert json.loads(match.group(1)) == {
        "layout": malicious,
        "deepLinking": True,
        "url": "/schema.json",
        "dom_id": "#swagger-ui",
    }
    await application.shutdown()


@pytest.mark.asyncio
async def test_documentation_routes_participate_in_global_guard_pipeline() -> None:
    calls: list[str | None] = []

    class DenyGuard:
        async def can_activate(self, context: ExecutionContext) -> bool:
            calls.append(context.route_id)
            return False

    openapi_module = OpenApiModule.for_root(_options())

    @module(imports=[openapi_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    application.use_global_guard(DenyGuard())
    await application.start()
    openapi = await _request(application, "GET", "/openapi.json")
    docs = await _request(application, "GET", "/docs")
    assert openapi.status_code == docs.status_code == 403
    assert calls == ["GET /openapi.json", "GET /docs"]
    await application.shutdown()


@pytest.mark.asyncio
async def test_invalid_discovered_schema_fails_application_startup() -> None:
    @controller()
    class InvalidController:
        @get("/invalid")
        async def invalid(self) -> object:
            return object()

    openapi_module = OpenApiModule.for_root(_options())

    @module(imports=[openapi_module], controllers=[InvalidController])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    with pytest.raises(OpenApiSchemaError, match="unconstrained schema"):
        await application.start()


@pytest.mark.asyncio
async def test_docs_mapping_uses_normal_duplicate_route_validation() -> None:
    @controller()
    class ConflictController:
        @get("/docs")
        async def docs(self) -> str:
            return "conflict"

    openapi_module = OpenApiModule.for_root(_options())

    @module(imports=[openapi_module], controllers=[ConflictController])
    class Root:
        pass

    with pytest.raises(BootstrapError, match="duplicate controller route"):
        await NestApplication.create(Root, adapter=StarletteAdapter())

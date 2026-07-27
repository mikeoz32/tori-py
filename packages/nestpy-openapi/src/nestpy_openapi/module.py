"""Dynamic module, discovered document service, and Nestpy docs controller."""

from __future__ import annotations

import html
from collections.abc import Mapping

import msgspec
from nestpy import (
    ClassProvider,
    DeferredModule,
    DiscoveryService,
    ModuleSpec,
    ValueProvider,
    controller,
    get,
)
from nestpy.http import HttpResponse, compile_controller_routes

from nestpy_openapi.compiler import CompiledOpenApiDocument, compile_openapi_document
from nestpy_openapi.errors import OpenApiConfigurationError
from nestpy_openapi.metadata import api_exclude
from nestpy_openapi.options import OpenApiOptions

_DOM_ID = "#swagger-ui"


class _OpenApiDocumentService:
    def __init__(
        self,
        discovery: DiscoveryService,
        options: OpenApiOptions,
    ) -> None:
        plans = []
        for view in discovery.get_controllers():
            controller_type = view.implementation
            if controller_type is None:
                raise OpenApiConfigurationError(
                    "discovered controller has no implementation type"
                )
            plans.extend(compile_controller_routes(view.ref.module_id, controller_type))
        self.compiled: CompiledOpenApiDocument = compile_openapi_document(
            tuple(plans), options
        )
        self.swagger_html = (
            None if options.docs_path is None else _compile_swagger_html(options)
        )

    def openapi_response(self) -> HttpResponse:
        return HttpResponse(
            self.compiled.json_bytes,
            headers={"content-type": "application/json; charset=utf-8"},
        )

    def swagger_response(self) -> HttpResponse:
        if self.swagger_html is None:
            raise OpenApiConfigurationError("Swagger UI is disabled")
        return HttpResponse(
            self.swagger_html,
            headers={"content-type": "text/html; charset=utf-8"},
        )


def _controller_type(options: OpenApiOptions) -> type[object]:
    class OpenApiController:
        def __init__(self, documents: _OpenApiDocumentService) -> None:
            self._documents = documents

        async def openapi(self) -> HttpResponse:
            return self._documents.openapi_response()

        async def swagger(self) -> HttpResponse:
            return self._documents.swagger_response()

    OpenApiController.__module__ = __name__
    get(options.openapi_path)(OpenApiController.openapi)
    if options.docs_path is not None:
        get(options.docs_path)(OpenApiController.swagger)
    decorated = controller()(OpenApiController)
    return api_exclude()(decorated)


class OpenApiModule:
    """Compose generated OpenAPI documentation as ordinary Nestpy routes."""

    @classmethod
    def for_root(
        cls,
        options: OpenApiOptions,
        *,
        key: str = "default",
    ) -> DeferredModule:
        if not isinstance(options, OpenApiOptions):
            raise OpenApiConfigurationError(
                "options must be an OpenApiOptions instance"
            )
        docs_controller = _controller_type(options)

        def materialize() -> ModuleSpec:
            return ModuleSpec(
                providers=(
                    ValueProvider(OpenApiOptions, options),
                    ClassProvider(_OpenApiDocumentService),
                ),
                controllers=(docs_controller,),
            )

        return DeferredModule(cls, key, materialize)


def _compile_swagger_html(options: OpenApiOptions) -> bytes:
    config = {
        key: _thaw_json(value) for key, value in options.swagger_ui.parameters.items()
    }
    config["url"] = options.openapi_path
    config["dom_id"] = _DOM_ID
    encoded_config = msgspec.json.encode(config)
    encoded_config = (
        encoded_config.replace(b"&", b"\\u0026")
        .replace(b"<", b"\\u003c")
        .replace(b">", b"\\u003e")
    )
    title = html.escape(options.info.title, quote=True)
    stylesheet_url = html.escape(options.swagger_ui.stylesheet_url, quote=True)
    javascript_url = html.escape(options.swagger_ui.javascript_url, quote=True)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n"
        f'<link rel="stylesheet" href="{stylesheet_url}">\n'
        "<style>html{box-sizing:border-box;overflow-y:scroll}"
        "*,*:before,*:after{box-sizing:inherit}body{margin:0;background:#fafafa}"
        "#swagger-ui{min-height:100vh}</style>\n"
        "</head>\n"
        "<body>\n"
        "<noscript>Swagger UI requires JavaScript.</noscript>\n"
        '<div id="swagger-ui"></div>\n'
        f'<script src="{javascript_url}"></script>\n'
        "<script>\n"
        'window.addEventListener("load",function(){\n'
        f"window.ui=SwaggerUIBundle({encoded_config.decode('utf-8')});\n"
        "});\n"
        "</script>\n"
        "</body>\n"
        "</html>\n"
    ).encode()


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


__all__ = ["OpenApiModule"]

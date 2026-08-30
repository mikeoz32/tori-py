import inspect
import math
from dataclasses import dataclass, make_dataclass
from datetime import timedelta
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Annotated, Any, Literal, TypedDict, cast

import msgspec
import pytest
from tori_py.core import BodyStream, ModuleId, PipelineResult, controller, post
from tori_py.core.pipeline import PipelineBindings
from tori_py.http import (
    HttpBodyStream,
    HttpResponse,
    ParameterPlan,
    ResponseHeaderMetadata,
    RoutePlan,
    compile_controller_routes,
)
from tori_py_openapi import (
    BearerSecurityScheme,
    OpenApiInfo,
    OpenApiOptions,
    OpenApiSchemaError,
    OpenApiServer,
    api_exclude,
    api_operation,
    api_parameter,
    api_public,
    api_response,
    api_security,
    api_tags,
)
from tori_py_openapi.compiler import compile_openapi_document


class TestModule:
    pass


def _parameter(
    name: str,
    annotation: object,
    kind: str,
    source: str | None = None,
    *,
    default: object = inspect.Parameter.empty,
) -> ParameterPlan:
    return ParameterPlan(
        name=name,
        annotation=annotation,
        kind=kind,
        source=source,
        token=None,
        default=default,
        has_default=default is not inspect.Parameter.empty,
    )


def _plan(
    controller: type[object],
    method_name: str,
    *,
    method: str = "GET",
    path: str = "/items",
    status_code: int = 200,
    return_annotation: object = inspect.Signature.empty,
    parameters: tuple[ParameterPlan, ...] = (),
    response_headers: tuple[ResponseHeaderMetadata, ...] = (),
) -> RoutePlan:
    controller.__qualname__ = controller.__name__
    handler = controller.__dict__[method_name]
    return RoutePlan(
        module_id=ModuleId(TestModule),
        controller=controller,
        method_name=method_name,
        handler=handler,
        return_annotation=return_annotation,
        method=method,
        path=path,
        route_id=f"{method} {path}",
        status_code=status_code,
        parameters=parameters,
        controller_pipeline=PipelineBindings(),
        route_pipeline=PipelineBindings(),
        response_headers=response_headers,
    )


def _json(result: object) -> dict[str, Any]:
    return msgspec.json.decode(cast(Any, result).json_bytes)


def test_minimal_document_and_json_are_exact_and_stable() -> None:
    class Controller:
        async def health(self) -> object:
            raise NotImplementedError

    plan = _plan(Controller, "health", path="/health")
    options = OpenApiOptions(OpenApiInfo("Example", "1.0"))

    first = compile_openapi_document((plan,), options)
    second = compile_openapi_document((plan,), options)

    assert first.json_bytes == second.json_bytes
    assert _json(first) == {
        "openapi": "3.1.0",
        "info": {"title": "Example", "version": "1.0"},
        "paths": {
            "/health": {
                "get": {
                    "operationId": "Controller_health",
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }


def test_root_info_servers_schemas_and_bearer_schemes_preserve_order() -> None:
    class Result(msgspec.Struct):
        value: int

    class Controller:
        @api_security("oidc", ("read",))
        @api_security("service")
        async def read(self) -> object:
            raise NotImplementedError

    options = OpenApiOptions(
        OpenApiInfo("Example", "1.0", "Description"),
        servers=(
            OpenApiServer("https://one.example", "One"),
            OpenApiServer("https://two.example"),
        ),
        security_schemes=(
            BearerSecurityScheme("oidc", "JWT", "Members"),
            BearerSecurityScheme("service", None),
        ),
    )
    document = _json(
        compile_openapi_document(
            (_plan(Controller, "read", return_annotation=Result),), options
        )
    )

    assert document["info"] == {
        "title": "Example",
        "version": "1.0",
        "description": "Description",
    }
    assert document["servers"] == [
        {"url": "https://one.example", "description": "One"},
        {"url": "https://two.example"},
    ]
    assert list(document["components"]) == ["schemas", "securitySchemes"]
    assert document["components"]["securitySchemes"] == {
        "oidc": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Members",
        },
        "service": {"type": "http", "scheme": "bearer"},
    }
    assert document["paths"]["/items"]["get"]["security"] == [
        {"oidc": ["read"]},
        {"service": []},
    ]


def test_converter_normalization_and_all_parameter_presence_semantics() -> None:
    class Controller:
        async def read(self) -> object:
            raise NotImplementedError

    parameters = (
        _parameter("member_id", int, "path", "member_id", default=7),
        _parameter("search", str | None, "query", "q"),
        _parameter("limit", int, "query", "limit", default=20),
        _parameter("request_id", str, "header", "x-request-id"),
        _parameter("session", str, "cookie", "session", default=None),
        _parameter("context", object, "context"),
        _parameter("service", object, "inject"),
    )
    document = _json(
        compile_openapi_document(
            (
                _plan(
                    Controller,
                    "read",
                    path="/members/{member_id:int}",
                    parameters=parameters,
                ),
            ),
            OpenApiOptions(OpenApiInfo("Example", "1.0")),
        )
    )
    operation = document["paths"]["/members/{member_id}"]["get"]

    assert operation["parameters"] == [
        {
            "name": "member_id",
            "in": "path",
            "required": True,
            "schema": {"type": "integer", "default": 7},
        },
        {
            "name": "q",
            "in": "query",
            "required": True,
            "schema": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        {
            "name": "limit",
            "in": "query",
            "required": False,
            "schema": {"type": "integer", "default": 20},
        },
        {
            "name": "x-request-id",
            "in": "header",
            "required": True,
            "schema": {"type": "string"},
        },
        {
            "name": "session",
            "in": "cookie",
            "required": False,
            "schema": {"type": "string", "default": None},
        },
    ]


def test_body_uses_only_application_json_and_python_default_requiredness() -> None:
    @dataclass
    class CreateItem:
        name: str

    class Controller:
        async def create(self) -> object:
            raise NotImplementedError

    document = _json(
        compile_openapi_document(
            (
                _plan(
                    Controller,
                    "create",
                    method="POST",
                    parameters=(_parameter("body", CreateItem, "body", default=None),),
                ),
            ),
            OpenApiOptions(OpenApiInfo("Example", "1.0")),
        )
    )

    assert document["paths"]["/items"]["post"]["requestBody"] == {
        "required": True,
        "content": {
            "application/json": {"schema": {"$ref": "#/components/schemas/CreateItem"}}
        },
    }


def test_body_stream_is_documented_as_binary_octet_stream() -> None:
    @controller()
    class Controller:
        @post("/items")
        async def upload(
            self,
            body: Annotated[HttpBodyStream, BodyStream(max_bytes=20 * 1024 * 1024)],
        ) -> None:
            async for _ in body:
                pass

    document = _json(
        compile_openapi_document(
            compile_controller_routes(ModuleId(Controller), Controller),
            OpenApiOptions(OpenApiInfo("Example", "1.0")),
        )
    )

    assert document["paths"]["/items"]["post"]["requestBody"] == {
        "required": True,
        "content": {
            "application/octet-stream": {
                "schema": {"type": "string", "format": "binary"}
            }
        },
    }


@pytest.mark.parametrize(
    ("parameters", "match"),
    [
        ((), "exactly match"),
        ((_parameter("other", int, "path", "other"),), "exactly match"),
        (
            (
                _parameter("first", int, "path", "member_id"),
                _parameter("second", int, "path", "member_id"),
            ),
            "duplicate Path",
        ),
    ],
)
def test_path_markers_must_match_each_template_exactly(
    parameters: tuple[ParameterPlan, ...], match: str
) -> None:
    class Controller:
        async def read(self) -> object:
            raise NotImplementedError

    with pytest.raises(OpenApiSchemaError, match=match) as captured:
        compile_openapi_document(
            (
                _plan(
                    Controller,
                    "read",
                    path="/members/{member_id:int}",
                    parameters=parameters,
                ),
            ),
            OpenApiOptions(OpenApiInfo("Example", "1.0")),
        )
    assert captured.value.diagnostic.details["method"] == "GET"
    assert captured.value.diagnostic.details["path"] == "/members/{member_id:int}"


def test_normalized_duplicate_and_canonical_equivalent_paths_fail() -> None:
    class Controller:
        async def first(self) -> object:
            raise NotImplementedError

        async def second(self) -> object:
            raise NotImplementedError

    options = OpenApiOptions(OpenApiInfo("Example", "1.0"))
    first = _plan(
        Controller,
        "first",
        path="/items/{item_id:int}",
        parameters=(_parameter("item_id", int, "path", "item_id"),),
    )
    duplicate = _plan(
        Controller,
        "second",
        path="/items/{item_id}",
        parameters=(_parameter("item_id", str, "path", "item_id"),),
    )
    equivalent = _plan(
        Controller,
        "second",
        path="/items/{name}",
        parameters=(_parameter("name", str, "path", "name"),),
    )

    with pytest.raises(OpenApiSchemaError, match="duplicate normalized"):
        compile_openapi_document((first, duplicate), options)
    with pytest.raises(OpenApiSchemaError, match="canonically equivalent"):
        compile_openapi_document((first, equivalent), options)


def test_earlier_effective_method_template_cannot_shadow_concrete_path() -> None:
    class Controller:
        async def template(self) -> object:
            raise NotImplementedError

        async def concrete(self) -> object:
            raise NotImplementedError

    template = _plan(
        Controller,
        "template",
        path="/items/{name}",
        parameters=(_parameter("name", str, "path", "name"),),
    )
    concrete = _plan(Controller, "concrete", method="HEAD", path="/items/special")

    with pytest.raises(OpenApiSchemaError, match="shadows concrete"):
        compile_openapi_document(
            (template, concrete), OpenApiOptions(OpenApiInfo("Example", "1.0"))
        )


def test_excluded_template_still_participates_in_runtime_shadow_detection() -> None:
    @api_exclude()
    class HiddenController:
        async def template(self) -> object:
            raise NotImplementedError

    class Controller:
        async def concrete(self) -> object:
            raise NotImplementedError

    hidden = _plan(
        HiddenController,
        "template",
        path="/items/{name}",
        parameters=(_parameter("name", str, "path", "name"),),
    )
    concrete = _plan(Controller, "concrete", path="/items/special")

    with pytest.raises(OpenApiSchemaError, match="shadows concrete"):
        compile_openapi_document(
            (hidden, concrete), OpenApiOptions(OpenApiInfo("Example", "1.0"))
        )


def test_excluded_equivalent_template_cannot_shadow_documented_template() -> None:
    @api_exclude()
    class HiddenController:
        async def template(self) -> object:
            raise NotImplementedError

    class Controller:
        async def documented(self) -> object:
            raise NotImplementedError

    hidden = _plan(
        HiddenController,
        "template",
        path="/items/{item_id}",
        parameters=(_parameter("item_id", str, "path", "item_id"),),
    )
    documented = _plan(
        Controller,
        "documented",
        path="/items/{name}",
        parameters=(_parameter("name", str, "path", "name"),),
    )

    with pytest.raises(OpenApiSchemaError, match="excluded template shadows"):
        compile_openapi_document(
            (hidden, documented), OpenApiOptions(OpenApiInfo("Example", "1.0"))
        )


def test_supported_methods_share_path_in_compilation_order_and_others_fail() -> None:
    class Controller:
        async def get(self) -> object:
            raise NotImplementedError

        async def post(self) -> object:
            raise NotImplementedError

    options = OpenApiOptions(OpenApiInfo("Example", "1.0"))
    document = _json(
        compile_openapi_document(
            (
                _plan(Controller, "get"),
                _plan(Controller, "post", method="POST"),
            ),
            options,
        )
    )
    assert list(document["paths"]["/items"]) == ["get", "post"]

    with pytest.raises(OpenApiSchemaError, match="unsupported OpenAPI method"):
        compile_openapi_document((_plan(Controller, "get", method="CONNECT"),), options)


def test_operation_metadata_tags_exclusion_and_unique_ids() -> None:
    @api_tags("controller", "shared")
    class Controller:
        @api_tags("shared", "route")
        @api_operation(
            summary="Read",
            description="Read one",
            operation_id="read_item",
            deprecated=True,
        )
        async def read(self) -> object:
            raise NotImplementedError

        @api_exclude()
        async def hidden(self) -> object:
            raise NotImplementedError

        @api_operation(operation_id="read_item")
        async def duplicate(self) -> object:
            raise NotImplementedError

    options = OpenApiOptions(OpenApiInfo("Example", "1.0"))
    document = _json(
        compile_openapi_document(
            (
                _plan(Controller, "read"),
                _plan(Controller, "hidden", path="/hidden"),
            ),
            options,
        )
    )
    operation = document["paths"]["/items"]["get"]
    assert operation["operationId"] == "read_item"
    assert operation["tags"] == ["controller", "shared", "route"]
    assert operation["summary"] == "Read"
    assert operation["description"] == "Read one"
    assert operation["deprecated"] is True
    assert "/hidden" not in document["paths"]

    with pytest.raises(OpenApiSchemaError, match="duplicate OpenAPI operation ID"):
        compile_openapi_document(
            (
                _plan(Controller, "read"),
                _plan(Controller, "duplicate", method="POST"),
            ),
            options,
        )


def test_method_docstring_is_the_default_operation_description() -> None:
    class Controller:
        async def inferred(self) -> object:
            """Read one public item.

            This paragraph is also public.

            \f
            Internal implementation details are not public.
            """
            raise NotImplementedError

        @api_operation(summary="Explicit summary", description="Explicit description")
        async def explicit(self) -> object:
            """This docstring must not override explicit metadata."""
            raise NotImplementedError

        async def internal_only(self) -> object:
            """\f
            Internal-only documentation.
            """
            raise NotImplementedError

    document = _json(
        compile_openapi_document(
            (
                _plan(Controller, "inferred", path="/inferred"),
                _plan(Controller, "explicit", path="/explicit"),
                _plan(Controller, "internal_only", path="/internal"),
            ),
            OpenApiOptions(OpenApiInfo("Example", "1.0")),
        )
    )
    inferred = document["paths"]["/inferred"]["get"]
    assert inferred["description"] == (
        "Read one public item.\n\nThis paragraph is also public."
    )
    assert "summary" not in inferred
    explicit = document["paths"]["/explicit"]["get"]
    assert explicit["summary"] == "Explicit summary"
    assert explicit["description"] == "Explicit description"
    assert "description" not in document["paths"]["/internal"]["get"]


def test_default_response_explicit_override_and_additional_response() -> None:
    class Result(msgspec.Struct):
        value: int

    class Error(msgspec.Struct):
        message: str

    class Controller:
        @api_response(201, description="Explicit success")
        @api_response(409, model=Error)
        async def create(self) -> object:
            raise NotImplementedError

    document = _json(
        compile_openapi_document(
            (
                _plan(
                    Controller,
                    "create",
                    method="POST",
                    status_code=201,
                    return_annotation=Result,
                    response_headers=(
                        ResponseHeaderMetadata("Cache-Control", "no-store"),
                    ),
                ),
            ),
            OpenApiOptions(OpenApiInfo("Example", "1.0")),
        )
    )
    responses = document["paths"]["/items"]["post"]["responses"]
    assert responses == {
        "201": {"description": "Explicit success"},
        "409": {
            "description": "Conflict",
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
            },
        },
    }
    assert set(document["components"]["schemas"]) == {"Error"}


def test_static_response_headers_and_content_type_are_documented() -> None:
    class Controller:
        async def read(self) -> object:
            raise NotImplementedError

    response_headers = (
        ResponseHeaderMetadata("Cache-Control", "no-store"),
        ResponseHeaderMetadata(
            "Content-Type", "application/vnd.test+json; charset=utf-8"
        ),
        ResponseHeaderMetadata("X-Request-ID", "overridden"),
    )
    document = _json(
        compile_openapi_document(
            (
                _plan(
                    Controller,
                    "read",
                    return_annotation=dict[str, str],
                    response_headers=response_headers,
                ),
            ),
            OpenApiOptions(OpenApiInfo("Example", "1.0")),
        )
    )
    response = document["paths"]["/items"]["get"]["responses"]["200"]
    assert set(response["content"]) == {"application/vnd.test+json"}
    assert response["headers"] == {
        "Cache-Control": {
            "schema": {"type": "string"},
            "example": "no-store",
        }
    }


def test_explicit_response_does_not_inherit_static_header_metadata() -> None:
    class Result(msgspec.Struct):
        value: int

    class Controller:
        @api_response(200, model=Result)
        async def read(self) -> object:
            raise NotImplementedError

    document = _json(
        compile_openapi_document(
            (
                _plan(
                    Controller,
                    "read",
                    return_annotation=Result,
                    response_headers=(
                        ResponseHeaderMetadata("Cache-Control", "no-store"),
                        ResponseHeaderMetadata("Content-Type", "text/plain"),
                    ),
                ),
            ),
            OpenApiOptions(OpenApiInfo("Example", "1.0")),
        )
    )
    response = document["paths"]["/items"]["get"]["responses"]["200"]
    assert set(response["content"]) == {"application/json"}
    assert "headers" not in response


def test_parameter_metadata_overlays_bound_schema_and_description() -> None:
    class Controller:
        @api_parameter(
            "cursor",
            location="query",
            schema={
                "maxLength": 512,
                "examples": [{"cursor": ["next"]}],
            },
            description="Opaque continuation token",
        )
        async def read(self) -> object:
            raise NotImplementedError

    document = _json(
        compile_openapi_document(
            (
                _plan(
                    Controller,
                    "read",
                    parameters=(
                        _parameter(
                            "cursor", str | None, "query", "cursor", default=None
                        ),
                    ),
                ),
            ),
            OpenApiOptions(OpenApiInfo("Example", "1.0")),
        )
    )

    assert document["paths"]["/items"]["get"]["parameters"] == [
        {
            "name": "cursor",
            "in": "query",
            "required": False,
            "description": "Opaque continuation token",
            "schema": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "maxLength": 512,
                "examples": [{"cursor": ["next"]}],
            },
        }
    ]


def test_parameter_metadata_requires_an_existing_matching_route_binding() -> None:
    class Controller:
        @api_parameter("missing", location="header", schema={"maxLength": 10})
        async def read(self) -> object:
            raise NotImplementedError

    with pytest.raises(OpenApiSchemaError, match="no matching route binding") as raised:
        compile_openapi_document(
            (
                _plan(
                    Controller,
                    "read",
                    parameters=(_parameter("missing", str, "query", "missing"),),
                ),
            ),
            OpenApiOptions(OpenApiInfo("Example", "1.0")),
        )

    assert raised.value.diagnostic.details["parameters"] == (("missing", "header"),)


def test_explicit_response_supports_per_response_media_type_and_headers() -> None:
    class Problem(msgspec.Struct):
        detail: str

    class Controller:
        @api_response(
            422,
            model=Problem,
            media_type="application/problem+json ; charset=utf-8",
            headers={"Retry-After": "30"},
        )
        async def read(self) -> object:
            raise NotImplementedError

    document = _json(
        compile_openapi_document(
            (_plan(Controller, "read", return_annotation=dict[str, str]),),
            OpenApiOptions(OpenApiInfo("Example", "1.0")),
        )
    )

    assert document["paths"]["/items"]["get"]["responses"]["422"] == {
        "description": "Unprocessable Content",
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/Problem"}
            }
        },
        "headers": {"Retry-After": {"schema": {"type": "string"}, "example": "30"}},
    }


def test_bodyless_204_opaque_response_can_document_headers_without_content() -> None:
    class Controller:
        @api_response(204, headers={"Cache-Control": "no-store"})
        async def delete(self) -> object:
            raise NotImplementedError

    document = _json(
        compile_openapi_document(
            (
                _plan(
                    Controller,
                    "delete",
                    method="DELETE",
                    status_code=204,
                    return_annotation=HttpResponse,
                ),
            ),
            OpenApiOptions(OpenApiInfo("Example", "1.0")),
        )
    )

    response = document["paths"]["/items"]["delete"]["responses"]["204"]
    assert response == {
        "description": "No Content",
        "headers": {
            "Cache-Control": {
                "schema": {"type": "string"},
                "example": "no-store",
            }
        },
    }
    assert "content" not in response


@pytest.mark.parametrize("status_code", [204, 304])
def test_no_content_status_requires_native_response_and_rejects_explicit_model(
    status_code: int,
) -> None:
    class Controller:
        async def empty(self) -> object:
            raise NotImplementedError

        @api_response(status_code, model=str)
        async def invalid(self) -> object:
            raise NotImplementedError

    options = OpenApiOptions(OpenApiInfo("Example", "1.0"))
    with pytest.raises(OpenApiSchemaError, match="explicit HttpResponse annotation"):
        compile_openapi_document(
            (
                _plan(
                    Controller,
                    "empty",
                    status_code=status_code,
                    return_annotation=dict[str, Any],
                ),
            ),
            options,
        )
    with pytest.raises(OpenApiSchemaError, match="cannot declare a model"):
        compile_openapi_document(
            (
                _plan(
                    Controller,
                    "invalid",
                    status_code=status_code,
                    return_annotation=HttpResponse,
                ),
            ),
            options,
        )


@pytest.mark.parametrize("annotation", [HttpResponse, PipelineResult])
def test_opaque_response_annotations_require_complete_explicit_responses(
    annotation: object,
) -> None:
    class Controller:
        async def missing(self) -> object:
            raise NotImplementedError

        @api_response(202, description="Accepted response")
        async def documented(self) -> object:
            raise NotImplementedError

    options = OpenApiOptions(OpenApiInfo("Example", "1.0"))
    with pytest.raises(OpenApiSchemaError, match="require explicit responses"):
        compile_openapi_document(
            (_plan(Controller, "missing", return_annotation=annotation),), options
        )
    document = _json(
        compile_openapi_document(
            (_plan(Controller, "documented", return_annotation=annotation),), options
        )
    )
    assert document["paths"]["/items"]["get"]["responses"] == {
        "202": {"description": "Accepted response"}
    }


def test_api_public_emits_empty_security_and_unknown_scheme_fails() -> None:
    @api_security("oidc")
    class Controller:
        @api_public()
        async def public(self) -> object:
            raise NotImplementedError

        @api_security("missing")
        async def invalid(self) -> object:
            raise NotImplementedError

    options = OpenApiOptions(
        OpenApiInfo("Example", "1.0"),
        security_schemes=(BearerSecurityScheme("oidc"),),
    )
    document = _json(compile_openapi_document((_plan(Controller, "public"),), options))
    assert document["paths"]["/items"]["get"]["security"] == []
    assert "security" not in document

    with pytest.raises(OpenApiSchemaError, match="unknown OpenAPI security scheme"):
        compile_openapi_document((_plan(Controller, "invalid"),), options)


class Kind(Enum):
    ONE = "one"


class Payload(TypedDict):
    name: str
    enabled: bool


@dataclass
class Detail:
    kind: Kind
    payload: Payload


class Envelope(msgspec.Struct):
    detail: Detail


def test_msgspec_schema_matrix_and_shared_components() -> None:
    class Controller:
        @api_response(400, model=Payload)
        async def read(self) -> object:
            raise NotImplementedError

    parameters = (
        _parameter("literal", Literal["a", "b"], "query", "literal"),
        _parameter("values", list[int], "query", "values"),
        _parameter("mapping", dict[str, float], "query", "mapping"),
        _parameter("union", int | str | None, "query", "union"),
        _parameter("body", Envelope, "body"),
    )
    document = _json(
        compile_openapi_document(
            (
                _plan(
                    Controller,
                    "read",
                    parameters=parameters,
                    return_annotation=Envelope,
                ),
            ),
            OpenApiOptions(OpenApiInfo("Example", "1.0")),
        )
    )
    components = document["components"]["schemas"]
    assert set(components) == {"Detail", "Envelope", "Kind", "Payload"}
    assert components["Envelope"]["properties"]["detail"] == {
        "$ref": "#/components/schemas/Detail"
    }
    assert document["paths"]["/items"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/Envelope"}


def test_duplicate_non_path_parameter_identity_fails() -> None:
    class Controller:
        async def read(self) -> object:
            raise NotImplementedError

    parameters = (
        _parameter("first", str, "query", "filter"),
        _parameter("second", str, "query", "filter"),
    )
    with pytest.raises(OpenApiSchemaError, match="duplicate Query binding"):
        compile_openapi_document(
            (_plan(Controller, "read", parameters=parameters),),
            OpenApiOptions(OpenApiInfo("Example", "1.0")),
        )


def test_tagged_struct_union_is_supported_and_untagged_object_union_fails() -> None:
    class Cat(msgspec.Struct, tag="cat"):
        lives: int

    class Dog(msgspec.Struct, tag="dog"):
        bark: bool

    class PlainCat(msgspec.Struct):
        lives: int

    class PlainDog(msgspec.Struct):
        bark: bool

    class Controller:
        async def tagged(self) -> object:
            raise NotImplementedError

        async def untagged(self) -> object:
            raise NotImplementedError

    options = OpenApiOptions(OpenApiInfo("Example", "1.0"))
    document = _json(
        compile_openapi_document(
            (_plan(Controller, "tagged", return_annotation=Cat | Dog),), options
        )
    )
    schema = document["paths"]["/items"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert schema["discriminator"]["propertyName"] == "type"
    assert schema["anyOf"] == [
        {"$ref": "#/components/schemas/Cat"},
        {"$ref": "#/components/schemas/Dog"},
    ]

    with pytest.raises(OpenApiSchemaError, match="unresolved or unsupported"):
        compile_openapi_document(
            (
                _plan(
                    Controller,
                    "untagged",
                    return_annotation=PlainCat | PlainDog,
                ),
            ),
            options,
        )


def test_nullable_model_is_supported_and_mixed_unions_fail() -> None:
    class Model(msgspec.Struct):
        value: str

    class Controller:
        async def read(self) -> object:
            raise NotImplementedError

    options = OpenApiOptions(OpenApiInfo("Example", "1.0"))
    compile_openapi_document(
        (_plan(Controller, "read", return_annotation=Model | None),), options
    )
    for annotation in (int | Model, list[int] | Model):
        with pytest.raises(OpenApiSchemaError, match="unresolved or unsupported"):
            compile_openapi_document(
                (_plan(Controller, "read", return_annotation=annotation),), options
            )


def test_type_aliases_are_validated_recursively_and_scalar_aliases_work() -> None:
    class Model(msgspec.Struct):
        value: str

    type Scalar = Decimal | int
    type ScalarBase = int | str
    type ExtendedScalar = ScalarBase | float
    type OptionalModel = Model | None
    type Mixed = int | Model
    type NestedAny = list[Any]

    class Controller:
        async def read(self) -> object:
            raise NotImplementedError

    options = OpenApiOptions(OpenApiInfo("Example", "1.0"))
    for annotation in (Scalar, ExtendedScalar, timedelta | float, OptionalModel):
        compile_openapi_document(
            (_plan(Controller, "read", return_annotation=annotation),), options
        )
    for annotation in (Mixed, NestedAny):
        with pytest.raises(OpenApiSchemaError, match="unresolved or unsupported"):
            compile_openapi_document(
                (_plan(Controller, "read", return_annotation=annotation),), options
            )


def test_any_is_rejected_at_root_and_recursively_in_models() -> None:
    @dataclass
    class NestedAny:
        values: list[dict[str, Any]]

    class Controller:
        async def read(self) -> object:
            raise NotImplementedError

    options = OpenApiOptions(OpenApiInfo("Example", "1.0"))
    for annotation in (Any, list[Any], NestedAny):
        with pytest.raises(OpenApiSchemaError, match="unresolved or unsupported"):
            compile_openapi_document(
                (_plan(Controller, "read", return_annotation=annotation),), options
            )


def test_unconstrained_root_schema_and_component_collision_are_typed() -> None:
    first = make_dataclass("Same", [("first", int)])
    second = make_dataclass("Same", [("second", str)])

    class Controller:
        @api_response(400, model=second)
        async def read(self) -> object:
            raise NotImplementedError

    options = OpenApiOptions(OpenApiInfo("Example", "1.0"))
    with pytest.raises(OpenApiSchemaError, match="unconstrained schema"):
        compile_openapi_document(
            (_plan(Controller, "read", return_annotation=object),), options
        )
    with pytest.raises(OpenApiSchemaError, match="component schema names collide"):
        compile_openapi_document(
            (_plan(Controller, "read", return_annotation=first),), options
        )


@pytest.mark.parametrize(
    "default",
    [
        (1, 2),
        {1: "invalid"},
        math.inf,
        math.nan,
        b"bytes",
        cast(object, msgspec.Raw(b"null")),
    ],
)
def test_parameter_defaults_accept_only_strict_native_json(default: object) -> None:
    class Controller:
        async def read(self) -> object:
            raise NotImplementedError

    with pytest.raises(OpenApiSchemaError, match="strict native JSON"):
        compile_openapi_document(
            (
                _plan(
                    Controller,
                    "read",
                    parameters=(
                        _parameter("value", object, "query", "value", default=default),
                    ),
                ),
            ),
            OpenApiOptions(OpenApiInfo("Example", "1.0")),
        )


def test_json_defaults_are_copied_and_document_is_deeply_immutable() -> None:
    default = [{"enabled": True}]

    class Controller:
        async def read(self) -> object:
            raise NotImplementedError

    result = compile_openapi_document(
        (
            _plan(
                Controller,
                "read",
                parameters=(
                    _parameter(
                        "value",
                        list[dict[str, bool]],
                        "query",
                        "value",
                        default=default,
                    ),
                ),
            ),
        ),
        OpenApiOptions(OpenApiInfo("Example", "1.0")),
    )
    original_bytes = result.json_bytes
    default[0]["enabled"] = False

    assert isinstance(result.document, MappingProxyType)
    paths = cast(Any, result.document)["paths"]
    assert isinstance(paths, MappingProxyType)
    parameters = paths["/items"]["get"]["parameters"]
    assert isinstance(parameters, tuple)
    assert isinstance(parameters[0]["schema"]["default"], tuple)
    assert result.json_bytes == original_bytes
    assert _json(result)["paths"]["/items"]["get"]["parameters"][0]["schema"][
        "default"
    ] == [{"enabled": True}]
    with pytest.raises(TypeError):
        cast(Any, result.document)["openapi"] = "3.0.0"


def test_schema_generation_and_document_encoding_each_run_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Controller:
        async def read(self) -> object:
            raise NotImplementedError

    schema_calls = 0
    encode_calls = 0
    original_schema_components = msgspec.json.schema_components
    original_encode = msgspec.json.encode

    def counted_schema_components(*args: Any, **kwargs: Any) -> Any:
        nonlocal schema_calls
        schema_calls += 1
        return original_schema_components(*args, **kwargs)

    def counted_encode(*args: Any, **kwargs: Any) -> bytes:
        nonlocal encode_calls
        encode_calls += 1
        return original_encode(*args, **kwargs)

    monkeypatch.setattr(msgspec.json, "schema_components", counted_schema_components)
    monkeypatch.setattr(msgspec.json, "encode", counted_encode)

    compile_openapi_document(
        (
            _plan(
                Controller,
                "read",
                parameters=(_parameter("q", str, "query", "q"),),
                return_annotation=list[int],
            ),
        ),
        OpenApiOptions(OpenApiInfo("Example", "1.0")),
    )

    assert schema_calls == 1
    assert encode_calls == 1

"""Internal OpenAPI document compiler for compiled ToriPy routes."""

from __future__ import annotations

import dataclasses
import enum
import inspect
import math
import re
import types
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from http import HTTPStatus
from types import MappingProxyType
from typing import (
    Annotated,
    Any,
    ForwardRef,
    Literal,
    TypeAliasType,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)
from uuid import UUID

import msgspec
from starlette.routing import compile_path
from tori_py.core import PipelineResult
from tori_py.http import (
    HttpResponse,
    ParameterPlan,
    ResponseHeaderMetadata,
    RoutePlan,
)

from tori_py_openapi.errors import OpenApiSchemaError
from tori_py_openapi.metadata import MergedMetadata, ResponseMetadata, merge_metadata
from tori_py_openapi.options import (
    BearerSecurityScheme,
    OpenApiOptions,
    OpenApiServer,
)

_OPENAPI_METHODS = frozenset(
    {"GET", "PUT", "POST", "DELETE", "OPTIONS", "HEAD", "PATCH", "TRACE"}
)
_COMPONENT_KEY = re.compile(r"^[a-zA-Z0-9._-]+$")
_UNSAFE_OPERATION_ID = re.compile(r"[^a-zA-Z0-9_-]+")
_TEMPLATE_VARIABLE = re.compile(r"\{[^{}]+\}")
_NO_DEFAULT = object()


@dataclass(frozen=True, slots=True)
class CompiledOpenApiDocument:
    """One immutable document and its sole cached JSON representation."""

    json_bytes: bytes
    document: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _RouteContext:
    method: str
    path: str
    handler: str

    @classmethod
    def from_plan(cls, plan: RoutePlan) -> _RouteContext:
        return cls(
            method=plan.method,
            path=plan.path,
            handler=f"{plan.controller.__qualname__}.{plan.method_name}",
        )

    def details(self, **extra: object) -> dict[str, object]:
        return {
            "method": self.method,
            "path": self.path,
            "handler": self.handler,
            **extra,
        }


@dataclass(frozen=True, slots=True)
class _SchemaUse:
    annotation: object
    context: _RouteContext
    purpose: str


@dataclass(frozen=True, slots=True)
class _SchemaSlot:
    index: int
    default: object = _NO_DEFAULT


@dataclass(frozen=True, slots=True)
class _SchemaOverlay:
    slot: _SchemaSlot
    values: tuple[tuple[str, object], ...]


@dataclass(frozen=True, slots=True)
class _PathPlan:
    normalized: str
    regex: re.Pattern[str]
    variables: tuple[str, ...]


class _SchemaCollector:
    def __init__(self) -> None:
        self.uses: list[_SchemaUse] = []

    def add(
        self,
        annotation: object,
        context: _RouteContext,
        purpose: str,
        *,
        default: object = _NO_DEFAULT,
    ) -> _SchemaSlot:
        _validate_annotation(annotation, context, purpose)
        index = len(self.uses)
        self.uses.append(_SchemaUse(annotation, context, purpose))
        return _SchemaSlot(index, default)

    def generate(self) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
        annotations = tuple(use.annotation for use in self.uses)
        try:
            schemas, components = msgspec.json.schema_components(
                annotations,
                ref_template="#/components/schemas/{name}",
            )
        except KeyError as error:
            raise self._generation_error(
                "OpenAPI component schema names collide", error
            ) from error
        except TypeError as error:
            raise self._generation_error(
                "OpenAPI schema generation failed", error
            ) from error

        if len(schemas) != len(self.uses):  # pragma: no cover - msgspec contract
            raise OpenApiSchemaError(
                "OpenAPI schema generation returned an unexpected schema count"
            )
        for use, schema in zip(self.uses, schemas, strict=True):
            if not isinstance(schema, dict) or not schema:
                raise OpenApiSchemaError(
                    f"{use.purpose} annotation produced an unconstrained schema",
                    details=use.context.details(
                        annotation=_annotation_name(use.annotation)
                    ),
                )
        for key, schema in components.items():
            if not isinstance(key, str) or _COMPONENT_KEY.fullmatch(key) is None:
                use = self.uses[0] if self.uses else None
                details = {} if use is None else use.context.details()
                raise OpenApiSchemaError(
                    f"invalid OpenAPI component schema key {key!r}", details=details
                )
            if not isinstance(schema, dict) or not schema:
                raise OpenApiSchemaError(
                    f"OpenAPI component schema {key!r} is unconstrained"
                )
        return schemas, components

    def _generation_error(
        self, message: str, error: TypeError | KeyError
    ) -> OpenApiSchemaError:
        if not self.uses:
            return OpenApiSchemaError(message)
        first = self._error_use(error)
        return OpenApiSchemaError(
            message,
            details=first.context.details(
                annotation=_annotation_name(first.annotation),
                annotations=tuple(
                    _annotation_name(use.annotation) for use in self.uses
                ),
                cause=type(error).__name__,
            ),
        )

    def _error_use(self, error: TypeError | KeyError) -> _SchemaUse:
        if (
            isinstance(error, KeyError)
            and error.args
            and isinstance(error.args[0], type)
        ):
            component_type = error.args[0]
            for use in self.uses:
                if _annotation_contains_type(use.annotation, component_type, set()):
                    return use
        message = str(error)
        for use in self.uses:
            if (
                repr(use.annotation) in message
                or _annotation_name(use.annotation) in message
            ):
                return use
        return self.uses[0]


def compile_openapi_document(
    plans: tuple[RoutePlan, ...], options: OpenApiOptions
) -> CompiledOpenApiDocument:
    """Compile route plans into one cached JSON document and immutable view."""

    if not isinstance(plans, tuple) or any(
        not isinstance(plan, RoutePlan) for plan in plans
    ):
        raise OpenApiSchemaError(
            "OpenAPI compiler plans must be a tuple of RoutePlan values"
        )
    if not isinstance(options, OpenApiOptions):
        raise OpenApiSchemaError("OpenAPI compiler options must be OpenApiOptions")

    collector = _SchemaCollector()
    paths: dict[str, dict[str, object]] = {}
    normalized_operations: set[tuple[str, str]] = set()
    canonical_paths: dict[str, tuple[str, _RouteContext]] = {}
    operation_ids: dict[str, _RouteContext] = {}
    compiled_paths: list[_PathPlan] = []

    for index, plan in enumerate(plans):
        context = _RouteContext.from_plan(plan)
        path_plan = _compile_route_path(plan, context)
        metadata = merge_metadata(plan.controller, plan.handler)
        compiled_paths.append(path_plan)
        if metadata.excluded:
            continue
        if plan.method not in _OPENAPI_METHODS:
            raise OpenApiSchemaError(
                f"unsupported OpenAPI method {plan.method!r}", details=context.details()
            )
        _validate_excluded_template_shadow(
            plan,
            context,
            path_plan,
            plans[:index],
            compiled_paths[:index],
        )
        _validate_concrete_shadow(
            plan,
            context,
            path_plan,
            plans[:index],
            compiled_paths[:index],
        )

        _validate_path_bindings(plan, context, path_plan.variables)
        identity = (plan.method, path_plan.normalized)
        if identity in normalized_operations:
            raise OpenApiSchemaError(
                "duplicate normalized OpenAPI operation", details=context.details()
            )
        normalized_operations.add(identity)

        canonical = _TEMPLATE_VARIABLE.sub("{}", path_plan.normalized)
        previous_path = canonical_paths.get(canonical)
        if previous_path is not None and previous_path[0] != path_plan.normalized:
            raise OpenApiSchemaError(
                "canonically equivalent OpenAPI paths are not allowed",
                details=context.details(
                    normalized_path=path_plan.normalized,
                    conflicting_path=previous_path[0],
                ),
            )
        canonical_paths.setdefault(canonical, (path_plan.normalized, context))

        operation_id = _operation_id(plan, metadata, context)
        previous_operation = operation_ids.get(operation_id)
        if previous_operation is not None:
            raise OpenApiSchemaError(
                f"duplicate OpenAPI operation ID {operation_id!r}",
                details=context.details(),
            )
        operation_ids[operation_id] = context
        operation = _compile_operation(
            plan, context, metadata, operation_id, collector, options
        )
        path_item = paths.setdefault(path_plan.normalized, {})
        path_item[plan.method.lower()] = operation

    schemas, component_schemas = collector.generate()
    document: dict[str, object] = {
        "openapi": "3.1.0",
        "info": _compile_info(options),
    }
    if options.servers:
        document["servers"] = [_compile_server(server) for server in options.servers]
    document["paths"] = _materialize(paths, schemas)

    components: dict[str, object] = {}
    if component_schemas:
        components["schemas"] = component_schemas
    if options.security_schemes:
        components["securitySchemes"] = {
            scheme.name: _compile_security_scheme(scheme)
            for scheme in options.security_schemes
        }
    if components:
        document["components"] = components

    try:
        json_bytes = msgspec.json.encode(document)
    except (TypeError, ValueError, RecursionError) as error:
        raise OpenApiSchemaError(
            "OpenAPI document could not be encoded as JSON"
        ) from error
    frozen = _freeze(document)
    return CompiledOpenApiDocument(
        json_bytes=json_bytes,
        document=cast(Mapping[str, object], frozen),
    )


def _compile_route_path(plan: RoutePlan, context: _RouteContext) -> _PathPlan:
    try:
        regex, normalized, converters = compile_path(plan.path)
    except (AssertionError, TypeError, ValueError) as error:
        raise OpenApiSchemaError(
            "route path could not be compiled by Starlette", details=context.details()
        ) from error
    return _PathPlan(normalized, regex, tuple(converters))


def _validate_path_bindings(
    plan: RoutePlan,
    context: _RouteContext,
    variables: tuple[str, ...],
) -> None:
    bindings = [
        parameter.source for parameter in plan.parameters if parameter.kind == "path"
    ]
    duplicate = next(
        (name for name in bindings if bindings.count(name) > 1),
        None,
    )
    if duplicate is not None:
        raise OpenApiSchemaError(
            f"duplicate Path binding for {duplicate!r}", details=context.details()
        )
    if tuple(bindings) != variables and set(bindings) != set(variables):
        missing = tuple(name for name in variables if name not in bindings)
        extra = tuple(name for name in bindings if name not in variables)
        raise OpenApiSchemaError(
            "Path bindings must exactly match route template variables",
            details=context.details(missing=missing, extra=extra),
        )


def _validate_concrete_shadow(
    plan: RoutePlan,
    context: _RouteContext,
    path_plan: _PathPlan,
    earlier_plans: tuple[RoutePlan, ...],
    earlier_paths: list[_PathPlan],
) -> None:
    if path_plan.variables:
        return
    effective = _effective_methods(plan.method)
    for earlier, earlier_path in zip(earlier_plans, earlier_paths, strict=True):
        if (
            earlier_path.variables
            and effective.intersection(_effective_methods(earlier.method))
            and earlier_path.regex.fullmatch(path_plan.normalized) is not None
        ):
            raise OpenApiSchemaError(
                "earlier templated route shadows concrete OpenAPI path",
                details=context.details(
                    shadowing_method=earlier.method,
                    shadowing_path=earlier.path,
                ),
            )


def _validate_excluded_template_shadow(
    plan: RoutePlan,
    context: _RouteContext,
    path_plan: _PathPlan,
    earlier_plans: tuple[RoutePlan, ...],
    earlier_paths: list[_PathPlan],
) -> None:
    if not path_plan.variables:
        return
    canonical = _TEMPLATE_VARIABLE.sub("{}", path_plan.normalized)
    effective = _effective_methods(plan.method)
    for earlier, earlier_path in zip(earlier_plans, earlier_paths, strict=True):
        if (
            earlier_path.variables
            and effective.intersection(_effective_methods(earlier.method))
            and _TEMPLATE_VARIABLE.sub("{}", earlier_path.normalized) == canonical
            and merge_metadata(earlier.controller, earlier.handler).excluded
        ):
            raise OpenApiSchemaError(
                "earlier excluded template shadows OpenAPI path",
                details=context.details(
                    shadowing_method=earlier.method,
                    shadowing_path=earlier.path,
                ),
            )


def _effective_methods(method: str) -> frozenset[str]:
    if method == "GET":
        return frozenset({"GET", "HEAD"})
    return frozenset({method})


def _operation_id(
    plan: RoutePlan, metadata: MergedMetadata, context: _RouteContext
) -> str:
    explicit = None if metadata.operation is None else metadata.operation.operation_id
    if explicit is not None:
        operation_id = explicit
    else:
        operation_id = _UNSAFE_OPERATION_ID.sub(
            "_", f"{plan.controller.__qualname__}_{plan.method_name}"
        ).strip("_")
    if not operation_id:
        raise OpenApiSchemaError(
            "OpenAPI operation ID must not be empty", details=context.details()
        )
    return operation_id


def _compile_operation(
    plan: RoutePlan,
    context: _RouteContext,
    metadata: MergedMetadata,
    operation_id: str,
    collector: _SchemaCollector,
    options: OpenApiOptions,
) -> dict[str, object]:
    operation: dict[str, object] = {"operationId": operation_id}
    if metadata.tags:
        operation["tags"] = list(metadata.tags)
    if metadata.operation is not None:
        if metadata.operation.summary is not None:
            operation["summary"] = metadata.operation.summary
        if metadata.operation.deprecated:
            operation["deprecated"] = True
    description = _operation_description(plan, metadata)
    if description is not None:
        operation["description"] = description

    parameters: list[dict[str, object]] = []
    parameter_identities: set[tuple[str, str]] = set()
    parameter_overrides = {
        (item.name, item.location): item for item in metadata.parameters
    }
    body: ParameterPlan | None = None
    for parameter in plan.parameters:
        if parameter.kind in {"context", "inject"}:
            continue
        if parameter.kind in {"body", "body_stream"}:
            if body is not None:
                raise OpenApiSchemaError(
                    "an OpenAPI operation may have only one body binding",
                    details=context.details(),
                )
            body = parameter
            continue
        if parameter.kind not in {"path", "query", "header", "cookie"}:
            raise OpenApiSchemaError(
                f"unsupported route binding kind {parameter.kind!r}",
                details=context.details(parameter=parameter.name),
            )
        if not isinstance(parameter.source, str) or not parameter.source:
            raise OpenApiSchemaError(
                "documented route binding requires a source name",
                details=context.details(parameter=parameter.name),
            )
        identity = (parameter.source, parameter.kind)
        if identity in parameter_identities:
            raise OpenApiSchemaError(
                f"duplicate {parameter.kind.title()} binding for {parameter.source!r}",
                details=context.details(parameter=parameter.name),
            )
        parameter_identities.add(identity)
        default = _NO_DEFAULT
        if parameter.has_default:
            default = _copy_json_default(parameter.default, context, parameter.name)
        parameter_schema = collector.add(
            parameter.annotation,
            context,
            f"parameter {parameter.name!r}",
            default=default,
        )
        override = parameter_overrides.pop(identity, None)
        if override is not None:
            parameter_schema = _SchemaOverlay(parameter_schema, override.schema)
        document: dict[str, object] = {
            "name": parameter.source,
            "in": parameter.kind,
            "required": parameter.kind == "path" or not parameter.has_default,
            "schema": parameter_schema,
        }
        if override is not None and override.description is not None:
            document["description"] = override.description
        parameters.append(document)
    if parameters:
        operation["parameters"] = parameters
    if parameter_overrides:
        raise OpenApiSchemaError(
            "OpenAPI parameter metadata has no matching route binding",
            details=context.details(parameters=tuple(parameter_overrides)),
        )
    if body is not None:
        if body.kind == "body_stream":
            media_type = "application/octet-stream"
            schema: object = {"type": "string", "format": "binary"}
        else:
            media_type = "application/json"
            schema = collector.add(
                body.annotation, context, f"request body {body.name!r}"
            )
        operation["requestBody"] = {
            "required": True,
            "content": {media_type: {"schema": schema}},
        }

    operation["responses"] = _compile_responses(plan, context, metadata, collector)
    configured_schemes = {scheme.name for scheme in options.security_schemes}
    for security in metadata.security:
        if security.name not in configured_schemes:
            raise OpenApiSchemaError(
                f"unknown OpenAPI security scheme {security.name!r}",
                details=context.details(),
            )
    if metadata.public:
        operation["security"] = []
    elif metadata.security:
        operation["security"] = [
            {security.name: list(security.scopes)} for security in metadata.security
        ]
    return operation


def _operation_description(
    plan: RoutePlan,
    metadata: MergedMetadata,
) -> str | None:
    if metadata.operation is not None and metadata.operation.description is not None:
        return metadata.operation.description
    docstring = inspect.getdoc(plan.handler)
    if docstring is None:
        return None
    public = docstring.partition("\f")[0].strip()
    return public or None


def _compile_responses(
    plan: RoutePlan,
    context: _RouteContext,
    metadata: MergedMetadata,
    collector: _SchemaCollector,
) -> dict[str, dict[str, object]]:
    if type(plan.status_code) is not int or not 100 <= plan.status_code <= 599:
        raise OpenApiSchemaError(
            "route status is not an HTTP status code", details=context.details()
        )
    annotation = _unwrap_annotation(plan.return_annotation)
    opaque = _is_opaque_response(annotation)
    explicit_statuses = {response.status_code for response in metadata.responses}
    inferred_primary = not opaque and plan.status_code not in explicit_statuses
    media_type = (
        _response_media_type(plan.response_headers, context)
        if inferred_primary
        else "application/json"
    )
    if not opaque and plan.status_code in {204, 304}:
        raise OpenApiSchemaError(
            "204 and 304 routes require an explicit HttpResponse annotation",
            details=context.details(annotation=_annotation_name(annotation)),
        )
    if opaque and not metadata.responses:
        raise OpenApiSchemaError(
            "HttpResponse and PipelineResult annotations require explicit responses",
            details=context.details(annotation=_annotation_name(annotation)),
        )

    responses: dict[str, dict[str, object]] = {}
    if inferred_primary:
        inferred: dict[str, object] = {
            "description": _response_description(plan.status_code)
        }
        if (
            plan.status_code not in {204, 304}
            and annotation is not inspect.Signature.empty
        ):
            inferred["content"] = {
                media_type: {"schema": collector.add(annotation, context, "return")}
            }
        responses[str(plan.status_code)] = inferred

    for explicit in metadata.responses:
        responses[str(explicit.status_code)] = _compile_explicit_response(
            explicit,
            context,
            collector,
        )
    primary = responses.get(str(plan.status_code))
    if inferred_primary and primary is not None:
        _apply_response_headers(primary, plan.response_headers)
    return responses


def _compile_explicit_response(
    response: ResponseMetadata,
    context: _RouteContext,
    collector: _SchemaCollector,
) -> dict[str, object]:
    if response.has_model and response.status_code in {204, 304}:
        raise OpenApiSchemaError(
            f"response status {response.status_code} cannot declare a model",
            details=context.details(annotation=_annotation_name(response.model)),
        )
    compiled: dict[str, object] = {
        "description": (
            _response_description(response.status_code)
            if response.description is None
            else response.description
        )
    }
    if response.has_model:
        compiled["content"] = {
            response.media_type: {
                "schema": collector.add(
                    response.model,
                    context,
                    f"response {response.status_code}",
                )
            }
        }
    _apply_response_headers(compiled, response.headers)
    return compiled


def _response_media_type(
    headers: tuple[ResponseHeaderMetadata, ...],
    context: _RouteContext,
) -> str:
    value = next(
        (
            header.value
            for header in headers
            if header.name.casefold() == "content-type"
        ),
        "application/json",
    )
    media_type = value.partition(";")[0].strip()
    if not media_type or "/" not in media_type:
        raise OpenApiSchemaError(
            "response Content-Type header is not a media type",
            details=context.details(value=value),
        )
    return media_type


def _apply_response_headers(
    response: dict[str, object],
    headers: tuple[ResponseHeaderMetadata, ...],
) -> None:
    documented = {
        header.name: {
            "schema": {"type": "string"},
            "example": header.value,
        }
        for header in headers
        if header.name.casefold() not in {"content-type", "x-request-id"}
    }
    if documented:
        response["headers"] = documented


def _is_opaque_response(annotation: object) -> bool:
    if not isinstance(annotation, type):
        return False
    return issubclass(annotation, (HttpResponse, PipelineResult))


def _response_description(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Response"


def _validate_annotation(
    annotation: object,
    context: _RouteContext,
    purpose: str,
) -> None:
    if _unwrap_annotation(annotation) is object:
        raise OpenApiSchemaError(
            f"{purpose} annotation produced an unconstrained schema",
            details=context.details(annotation=_annotation_name(annotation)),
        )
    try:
        _walk_annotation(annotation, set())
    except (NameError, TypeError) as error:
        raise OpenApiSchemaError(
            f"{purpose} annotation is unresolved or unsupported",
            details=context.details(annotation=_annotation_name(annotation)),
        ) from error


def _walk_annotation(annotation: object, seen: set[int]) -> None:
    if annotation is Any:
        raise TypeError("Any is not a constrained JSON schema annotation")
    if isinstance(annotation, (str, ForwardRef)):
        raise NameError("unresolved forward reference")
    if isinstance(annotation, TypeVar):
        raise TypeError("unresolved type variable")
    if isinstance(annotation, TypeAliasType):
        identity = id(annotation)
        if identity in seen:
            return
        seen.add(identity)
        _walk_annotation(annotation.__value__, seen)
        return

    origin = get_origin(annotation)
    if origin is Annotated:
        _walk_annotation(get_args(annotation)[0], seen)
        return
    if origin is Literal:
        return
    if origin in {types.UnionType, Union}:
        arguments = get_args(annotation)
        _validate_union(arguments)
        for argument in arguments:
            _walk_annotation(argument, seen)
        return
    if origin is not None:
        for argument in get_args(annotation):
            if argument is Ellipsis:
                continue
            _walk_annotation(argument, seen)
        model = origin
    else:
        model = annotation
    if not isinstance(model, type) or not _is_model_type(model):
        return
    identity = id(model)
    if identity in seen:
        return
    seen.add(identity)
    try:
        hints = get_type_hints(model, include_extras=True)
    except (NameError, TypeError) as error:
        raise NameError("model annotation could not be resolved") from error
    for field_annotation in hints.values():
        _walk_annotation(field_annotation, seen)


def _validate_union(arguments: tuple[object, ...]) -> None:
    non_null = tuple(argument for argument in arguments if argument is not type(None))
    if all(_is_scalar_annotation(argument) for argument in non_null):
        return
    if len(arguments) == 2 and len(non_null) == 1 and _is_model_annotation(non_null[0]):
        return
    if (
        len(non_null) >= 2
        and len(non_null) == len(arguments)
        and all(_is_tagged_struct(argument) for argument in non_null)
    ):
        return
    raise TypeError("unsupported union shape")


def _is_scalar_annotation(annotation: object) -> bool:
    annotation = _unwrap_annotation(annotation)
    origin = get_origin(annotation)
    if origin is Literal:
        return True
    if origin in {types.UnionType, Union}:
        return all(_is_scalar_annotation(argument) for argument in get_args(annotation))
    if origin is not None or not isinstance(annotation, type):
        return False
    return not _is_model_type(annotation) and (
        annotation
        in {
            str,
            int,
            float,
            bool,
            bytes,
            bytearray,
            memoryview,
            date,
            datetime,
            time,
            timedelta,
            Decimal,
            UUID,
            type(None),
        }
        or issubclass(annotation, enum.Enum)
    )


def _is_model_annotation(annotation: object) -> bool:
    annotation = _unwrap_annotation(annotation)
    return isinstance(annotation, type) and _is_model_type(annotation)


def _is_tagged_struct(annotation: object) -> bool:
    annotation = _unwrap_annotation(annotation)
    return (
        isinstance(annotation, type)
        and issubclass(annotation, msgspec.Struct)
        and annotation.__struct_config__.tag is not None
    )


def _annotation_contains_type(
    annotation: object, expected: type[object], seen: set[int]
) -> bool:
    if annotation is expected:
        return True
    if isinstance(annotation, TypeAliasType):
        identity = id(annotation)
        if identity in seen:
            return False
        seen.add(identity)
        return _annotation_contains_type(annotation.__value__, expected, seen)
    origin = get_origin(annotation)
    if origin is not None:
        if origin is expected:
            return True
        return any(
            argument is not Ellipsis
            and _annotation_contains_type(argument, expected, seen)
            for argument in get_args(annotation)
        )
    if not isinstance(annotation, type) or not _is_model_type(annotation):
        return False
    identity = id(annotation)
    if identity in seen:
        return False
    seen.add(identity)
    try:
        hints = get_type_hints(annotation, include_extras=True)
    except NameError, TypeError:
        return False
    return any(
        _annotation_contains_type(field_annotation, expected, seen)
        for field_annotation in hints.values()
    )


def _is_model_type(value: type[object]) -> bool:
    return (
        dataclasses.is_dataclass(value)
        or is_typeddict(value)
        or issubclass(value, msgspec.Struct)
        or (issubclass(value, tuple) and hasattr(value, "_fields"))
    ) and not issubclass(value, enum.Enum)


def _unwrap_annotation(annotation: object) -> object:
    aliases: set[int] = set()
    while True:
        if get_origin(annotation) is Annotated:
            annotation = get_args(annotation)[0]
            continue
        if isinstance(annotation, TypeAliasType):
            identity = id(annotation)
            if identity in aliases:
                return annotation
            aliases.add(identity)
            annotation = annotation.__value__
            continue
        break
    return annotation


def _annotation_name(annotation: object) -> str:
    return getattr(annotation, "__qualname__", repr(annotation))


def _copy_json_default(
    value: object,
    context: _RouteContext,
    parameter_name: str,
) -> object:
    try:
        return _copy_native_json(value, set())
    except (TypeError, ValueError, RecursionError) as error:
        raise OpenApiSchemaError(
            f"parameter {parameter_name!r} default must be strict native JSON",
            details=context.details(parameter=parameter_name),
        ) from error


def _copy_native_json(value: object, ancestors: set[int]) -> object:
    value_type = type(value)
    if value is None or value_type in {bool, int, str}:
        return value
    if value_type is float:
        if not math.isfinite(cast(float, value)):
            raise ValueError("JSON float must be finite")
        return value
    if value_type not in {list, dict}:
        raise TypeError("default is not a native JSON value")
    identity = id(value)
    if identity in ancestors:
        raise RecursionError("cyclic JSON default")
    ancestors.add(identity)
    try:
        if value_type is list:
            return [
                _copy_native_json(item, ancestors) for item in cast(list[object], value)
            ]
        mapping = cast(dict[object, object], value)
        if any(type(key) is not str for key in mapping):
            raise TypeError("JSON object keys must be strings")
        return {
            cast(str, key): _copy_native_json(item, ancestors)
            for key, item in mapping.items()
        }
    finally:
        ancestors.remove(identity)


def _materialize(value: object, schemas: tuple[dict[str, Any], ...]) -> object:
    if isinstance(value, _SchemaOverlay):
        schema = _materialize(value.slot, schemas)
        if not isinstance(schema, dict):  # pragma: no cover - internal invariant
            raise TypeError("schema slot did not materialize to an object")
        return {
            **schema,
            **{key: _materialize_frozen_json(item) for key, item in value.values},
        }
    if isinstance(value, _SchemaSlot):
        schema = dict(schemas[value.index])
        if value.default is not _NO_DEFAULT:
            schema["default"] = value.default
        return schema
    if isinstance(value, dict):
        return {key: _materialize(item, schemas) for key, item in value.items()}
    if isinstance(value, list):
        return [_materialize(item, schemas) for item in value]
    return value


def _materialize_frozen_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _materialize_frozen_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_materialize_frozen_json(item) for item in value]
    return value


def _compile_info(options: OpenApiOptions) -> dict[str, object]:
    info: dict[str, object] = {
        "title": options.info.title,
        "version": options.info.version,
    }
    if options.info.description is not None:
        info["description"] = options.info.description
    return info


def _compile_server(server: OpenApiServer) -> dict[str, object]:
    compiled: dict[str, object] = {"url": server.url}
    if server.description is not None:
        compiled["description"] = server.description
    return compiled


def _compile_security_scheme(scheme: BearerSecurityScheme) -> dict[str, object]:
    compiled: dict[str, object] = {"type": "http", "scheme": "bearer"}
    if scheme.bearer_format is not None:
        compiled["bearerFormat"] = scheme.bearer_format
    if scheme.description is not None:
        compiled["description"] = scheme.description
    return compiled


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


__all__: list[str] = []

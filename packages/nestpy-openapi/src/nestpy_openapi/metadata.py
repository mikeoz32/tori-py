"""Direct immutable OpenAPI metadata decorators and lookup helpers."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from nestpy_openapi.errors import OpenApiMetadataError

_METADATA_ATTRIBUTE = "__nestpy_openapi_metadata__"


class _MissingModel:
    __slots__ = ()

    def __repr__(self) -> str:
        return "MISSING"


_MISSING_MODEL = _MissingModel()


@dataclass(frozen=True, slots=True)
class OperationMetadata:
    summary: str | None
    description: str | None
    operation_id: str | None
    deprecated: bool


@dataclass(frozen=True, slots=True)
class ResponseMetadata:
    status_code: int
    description: str | None
    model: object = _MISSING_MODEL

    @property
    def has_model(self) -> bool:
        return self.model is not _MISSING_MODEL


@dataclass(frozen=True, slots=True)
class SecurityMetadata:
    name: str
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TargetMetadata:
    tags: tuple[str, ...] | None = None
    operation: OperationMetadata | None = None
    responses: tuple[ResponseMetadata, ...] = ()
    security: tuple[SecurityMetadata, ...] = ()
    public: bool = False
    excluded: bool = False


@dataclass(frozen=True, slots=True)
class MergedMetadata:
    tags: tuple[str, ...]
    operation: OperationMetadata | None
    responses: tuple[ResponseMetadata, ...]
    security: tuple[SecurityMetadata, ...]
    public: bool
    excluded: bool


_EMPTY_METADATA = TargetMetadata()


def _require_target(target: object, *, route_only: bool = False) -> None:
    valid = (
        inspect.isfunction(target)
        if route_only
        else (inspect.isfunction(target) or isinstance(target, type))
    )
    if not valid:
        expected = "route function" if route_only else "class or function"
        raise OpenApiMetadataError(f"OpenAPI metadata target must be a {expected}")


def _require_non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpenApiMetadataError(f"{name} must be a non-empty string")
    return value


def _optional_non_empty_string(value: object, name: str) -> None:
    if value is not None:
        _require_non_empty_string(value, name)


def get_direct_metadata(target: object) -> TargetMetadata:
    """Read only metadata declared directly on a class or unbound function."""

    _require_target(target)
    value = target.__dict__.get(_METADATA_ATTRIBUTE)
    if value is None:
        return _EMPTY_METADATA
    if not isinstance(value, TargetMetadata):
        raise OpenApiMetadataError("OpenAPI metadata storage on target is invalid")
    return value


def _write_metadata[T](
    target: T,
    transform: Callable[[TargetMetadata], TargetMetadata],
    *,
    route_only: bool = False,
) -> T:
    _require_target(target, route_only=route_only)
    metadata = get_direct_metadata(target)
    setattr(target, _METADATA_ATTRIBUTE, transform(metadata))
    return target


def _prepend_unique[T](values: tuple[T, ...], value: T, name: str) -> tuple[T, ...]:
    if value in values:
        raise OpenApiMetadataError(f"duplicate {name} declaration")
    return (value, *values)


def api_tags[TargetT](*tags: str) -> Callable[[TargetT], TargetT]:
    """Declare controller or route tags."""

    if not tags:
        raise OpenApiMetadataError("api_tags requires at least one tag")
    selected = tuple(_require_non_empty_string(tag, "tag") for tag in tags)

    def decorate(target: TargetT) -> TargetT:
        def add(metadata: TargetMetadata) -> TargetMetadata:
            if metadata.tags is not None:
                raise OpenApiMetadataError("tags are already declared on target")
            return replace(metadata, tags=selected)

        return _write_metadata(target, add)

    return decorate


def api_operation[TargetT](
    *,
    summary: str | None = None,
    description: str | None = None,
    operation_id: str | None = None,
    deprecated: bool = False,
) -> Callable[[TargetT], TargetT]:
    """Declare descriptive metadata for one route operation."""

    _optional_non_empty_string(summary, "operation summary")
    _optional_non_empty_string(description, "operation description")
    _optional_non_empty_string(operation_id, "operation_id")
    if not isinstance(deprecated, bool):
        raise OpenApiMetadataError("operation deprecated must be boolean")
    operation = OperationMetadata(summary, description, operation_id, deprecated)

    def decorate(target: TargetT) -> TargetT:
        def add(metadata: TargetMetadata) -> TargetMetadata:
            if metadata.operation is not None:
                raise OpenApiMetadataError(
                    "operation metadata is already declared on target"
                )
            return replace(metadata, operation=operation)

        return _write_metadata(target, add, route_only=True)

    return decorate


def api_response[TargetT](
    status_code: int,
    *,
    description: str | None = None,
    model: object = _MISSING_MODEL,
) -> Callable[[TargetT], TargetT]:
    """Declare one explicit controller or route response."""

    if isinstance(status_code, bool) or not isinstance(status_code, int):
        raise OpenApiMetadataError("response status_code must be an integer")
    if not 100 <= status_code <= 599:
        raise OpenApiMetadataError("response status_code must be from 100 through 599")
    if description is not None and not isinstance(description, str):
        raise OpenApiMetadataError("response description must be a string or None")
    response = ResponseMetadata(status_code, description, model)

    def decorate(target: TargetT) -> TargetT:
        def add(metadata: TargetMetadata) -> TargetMetadata:
            if any(
                existing.status_code == response.status_code
                for existing in metadata.responses
            ):
                raise OpenApiMetadataError(
                    f"response status {response.status_code} "
                    "is already declared on target"
                )
            return replace(metadata, responses=(response, *metadata.responses))

        return _write_metadata(target, add)

    return decorate


def api_security[TargetT](
    name: str,
    scopes: Iterable[str] = (),
) -> Callable[[TargetT], TargetT]:
    """Declare one alternative security requirement with OR semantics."""

    selected_name = _require_non_empty_string(name, "security scheme name")
    if isinstance(scopes, str) or not isinstance(scopes, Iterable):
        raise OpenApiMetadataError("security scopes must be an iterable of strings")
    selected_scopes = tuple(
        _require_non_empty_string(scope, "security scope") for scope in scopes
    )
    if len(selected_scopes) != len(set(selected_scopes)):
        raise OpenApiMetadataError("security scopes must not contain duplicates")
    security = SecurityMetadata(selected_name, selected_scopes)

    def decorate(target: TargetT) -> TargetT:
        def add(metadata: TargetMetadata) -> TargetMetadata:
            if metadata.public:
                raise OpenApiMetadataError(
                    "api_security cannot be combined with api_public"
                )
            return replace(
                metadata,
                security=_prepend_unique(
                    metadata.security,
                    security,
                    "security requirement",
                ),
            )

        return _write_metadata(target, add)

    return decorate


def api_public[TargetT]() -> Callable[[TargetT], TargetT]:
    """Clear inherited controller security for one route."""

    def decorate(target: TargetT) -> TargetT:
        def add(metadata: TargetMetadata) -> TargetMetadata:
            if metadata.public:
                raise OpenApiMetadataError("api_public is already declared on target")
            if metadata.security:
                raise OpenApiMetadataError(
                    "api_public cannot be combined with api_security"
                )
            return replace(metadata, public=True)

        return _write_metadata(target, add, route_only=True)

    return decorate


def api_exclude[TargetT]() -> Callable[[TargetT], TargetT]:
    """Exclude a controller or route from generated documentation."""

    def decorate(target: TargetT) -> TargetT:
        def add(metadata: TargetMetadata) -> TargetMetadata:
            if metadata.excluded:
                raise OpenApiMetadataError("api_exclude is already declared on target")
            return replace(metadata, excluded=True)

        return _write_metadata(target, add)

    return decorate


def _deduplicate(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _merge_responses(
    controller: tuple[ResponseMetadata, ...],
    route: tuple[ResponseMetadata, ...],
) -> tuple[ResponseMetadata, ...]:
    route_by_status = {response.status_code: response for response in route}
    merged = tuple(
        route_by_status.pop(response.status_code, response) for response in controller
    )
    return (
        *merged,
        *(response for response in route if response.status_code in route_by_status),
    )


def merge_metadata(controller: object, route: object) -> MergedMetadata:
    """Merge direct controller defaults with one unbound route function."""

    if not isinstance(controller, type):
        raise OpenApiMetadataError("controller metadata owner must be a class")
    if not inspect.isfunction(route):
        raise OpenApiMetadataError("route metadata owner must be an unbound function")
    controller_metadata = get_direct_metadata(controller)
    route_metadata = get_direct_metadata(route)
    controller_tags = controller_metadata.tags or ()
    route_tags = route_metadata.tags or ()
    if route_metadata.public:
        security: tuple[SecurityMetadata, ...] = ()
    elif route_metadata.security:
        security = route_metadata.security
    else:
        security = controller_metadata.security
    return MergedMetadata(
        tags=_deduplicate((*controller_tags, *route_tags)),
        operation=route_metadata.operation,
        responses=_merge_responses(
            controller_metadata.responses,
            route_metadata.responses,
        ),
        security=security,
        public=route_metadata.public,
        excluded=controller_metadata.excluded or route_metadata.excluded,
    )


__all__: list[str] = []

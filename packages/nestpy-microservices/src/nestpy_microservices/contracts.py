"""Typed outbound RPC contracts backed by one dynamic service proxy."""

from __future__ import annotations

import inspect
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Protocol, cast, get_args, get_origin, get_type_hints
from uuid import UUID

import msgspec
from nestpy import MetadataKey, Reflector, metadata

from nestpy_microservices.cluster import ServiceCluster, ServiceProxy
from nestpy_microservices.errors import HandlerCompilationError
from nestpy_microservices.identities import (
    ServiceIdentity,
    validate_alias,
    validate_version,
)


@dataclass(frozen=True, slots=True)
class ServiceContractMetadata:
    """Identity owned by one outbound RPC protocol."""

    identity: ServiceIdentity


@dataclass(frozen=True, slots=True)
class RpcCallMetadata:
    """Wire declaration for one outbound protocol method."""

    method: str
    payload_type: type[msgspec.Struct]
    schema_version: int
    timeout: float | None


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    """Bind a keyword-only protocol parameter to the RPC idempotency key."""


@dataclass(frozen=True, slots=True)
class CorrelationId:
    """Bind a keyword-only protocol parameter to the RPC correlation ID."""


@dataclass(frozen=True, slots=True)
class CausationId:
    """Bind a keyword-only protocol parameter to the RPC causation ID."""


@dataclass(frozen=True, slots=True)
class CallHeaders:
    """Bind a keyword-only protocol parameter to safe RPC headers."""


@dataclass(frozen=True, slots=True)
class CallTimeout:
    """Bind a keyword-only protocol parameter to the RPC deadline."""


@dataclass(frozen=True, slots=True)
class RpcCallPlan:
    """Precompiled argument binding for one outbound protocol method."""

    name: str
    signature: inspect.Signature
    metadata: RpcCallMetadata
    payload_parameters: tuple[str, ...]
    metadata_parameters: Mapping[str, str]
    response_type: type[object]


@dataclass(frozen=True, slots=True)
class ServiceContractPlan:
    """Immutable compiled protocol contract for one target service."""

    contract: type[object]
    identity: ServiceIdentity
    methods: Mapping[str, RpcCallPlan]


_CONTRACT_KEY: MetadataKey[ServiceContractMetadata] = MetadataKey(
    "nestpy.microservices.service_contract"
)
_CALL_KEY: MetadataKey[RpcCallMetadata] = MetadataKey("nestpy.microservices.rpc_call")
_REFLECTOR = Reflector()
_OUTBOUND_MARKERS = {
    IdempotencyKey: "idempotency_key",
    CorrelationId: "correlation_id",
    CausationId: "causation_id",
    CallHeaders: "headers",
    CallTimeout: "timeout",
}
_CALL_IDENTITIES: dict[object, ServiceIdentity] = {}


def service_contract(identity: ServiceIdentity):
    """Declare a Protocol as the typed client contract for one service identity."""

    if not isinstance(identity, ServiceIdentity):
        raise TypeError("service contract identity must be ServiceIdentity")
    declare = metadata(_CONTRACT_KEY, ServiceContractMetadata(identity))

    def decorate(contract: type[object]) -> type[object]:
        declared = declare(contract)
        for base in contract.__mro__[1:]:
            inherited = get_service_contract_metadata(base)
            if inherited is not None and inherited.identity != identity:
                raise HandlerCompilationError(
                    "service contract cannot inherit another service identity"
                )
        for base in contract.__mro__:
            for target in base.__dict__.values():
                if get_rpc_call_metadata(target) is not None:
                    owner = _CALL_IDENTITIES.get(target)
                    if owner is not None and owner != identity:
                        raise HandlerCompilationError(
                            "service contract cannot reuse a method from another "
                            "service identity"
                        )
                    _CALL_IDENTITIES[target] = identity
        return declared

    return decorate


def rpc_call(
    method: str,
    *,
    payload: type[msgspec.Struct],
    schema_version: int = 1,
    timeout: float | None = None,
):
    """Declare one typed outbound RPC call on a service contract Protocol."""

    normalized_method = validate_alias(method, "RPC method")
    normalized_version = validate_version(schema_version, "schema_version")
    if not isinstance(payload, type) or not issubclass(payload, msgspec.Struct):
        raise TypeError("RPC call payload must be a msgspec.Struct type")
    if timeout is not None and (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("RPC call timeout must be a positive number or None")
    return metadata(
        _CALL_KEY,
        RpcCallMetadata(normalized_method, payload, normalized_version, timeout),
    )


def get_service_contract_metadata(target: object) -> ServiceContractMetadata | None:
    """Return metadata declared directly on one service contract."""

    return _REFLECTOR.get_own(_CONTRACT_KEY, target)


def get_rpc_call_metadata(target: object) -> RpcCallMetadata | None:
    """Return metadata declared directly on one protocol method."""

    return _REFLECTOR.get_own(_CALL_KEY, target)


def get_rpc_call_service_identity(target: object) -> ServiceIdentity | None:
    """Return the service identity owning one declared contract method."""

    return _CALL_IDENTITIES.get(target)


def compile_service_contract(contract: type[object]) -> ServiceContractPlan:
    """Compile and validate a typed outbound Protocol before application startup."""

    metadata = get_service_contract_metadata(contract)
    if metadata is None:
        raise HandlerCompilationError("service contract requires @service_contract")
    if not getattr(contract, "_is_protocol", False):
        raise HandlerCompilationError("service contract must be a Protocol")
    methods: dict[str, RpcCallPlan] = {}
    aliases: set[tuple[str, int]] = set()
    declared_methods: dict[str, object] = {}
    for base in reversed(contract.__mro__):
        if base in {object, Protocol}:
            continue
        declared_methods.update(base.__dict__)
    for name, target in declared_methods.items():
        call = get_rpc_call_metadata(target)
        if call is None:
            if inspect.isfunction(target) and not name.startswith("_"):
                raise HandlerCompilationError(
                    f"service contract method {name} requires @rpc_call"
                )
            continue
        plan = _compile_rpc_call(name, cast(Callable[..., object], target), call)
        identity = (call.method, call.schema_version)
        if identity in aliases:
            raise HandlerCompilationError("service contract has duplicate RPC calls")
        aliases.add(identity)
        methods[name] = plan
    if not methods:
        raise HandlerCompilationError(
            "service contract requires at least one @rpc_call"
        )
    return ServiceContractPlan(contract, metadata.identity, methods)


class ProtocolServiceProxy:
    """Dynamic proxy that realizes one precompiled typed service Protocol."""

    def __init__(self, plan: ServiceContractPlan, service: ServiceProxy) -> None:
        self._plan = plan
        self._service = service
        self._methods: dict[str, Callable[..., object]] = {}

    def __getattr__(self, name: str) -> object:
        plan = self._plan.methods.get(name)
        if plan is None:
            raise AttributeError(name)
        method = self._methods.get(name)
        if method is None:
            method = self._make_method(plan)
            self._methods[name] = method
        return method

    def _make_method(self, plan: RpcCallPlan) -> Callable[..., object]:
        async def invoke(*args: object, **kwargs: object) -> object:
            bound = plan.signature.bind(None, *args, **kwargs)
            bound.apply_defaults()
            arguments = bound.arguments
            payload = msgspec.convert(
                {name: arguments[name] for name in plan.payload_parameters},
                type=plan.metadata.payload_type,
            )
            options = {
                option: arguments[name]
                for name, option in plan.metadata_parameters.items()
            }
            return await self._service.request(
                plan.metadata.method,
                payload,
                response_type=plan.response_type,
                schema_version=plan.metadata.schema_version,
                timeout=cast(
                    float | None,
                    options.get("timeout", plan.metadata.timeout),
                ),
                idempotency_key=cast(str | None, options.get("idempotency_key")),
                correlation_id=cast(UUID | None, options.get("correlation_id")),
                causation_id=cast(UUID | None, options.get("causation_id")),
                headers=cast(Mapping[str, object] | None, options.get("headers")),
            )

        return invoke


def create_service_proxy(
    contract: type[object],
    cluster: ServiceCluster,
) -> ProtocolServiceProxy:
    """Create one runtime proxy for a validated service contract Protocol."""

    plan = compile_service_contract(contract)
    return ProtocolServiceProxy(plan, cluster.service(plan.identity))


def _compile_rpc_call(
    name: str,
    target: Callable[..., object],
    metadata: RpcCallMetadata,
) -> RpcCallPlan:
    if not inspect.iscoroutinefunction(target):
        raise HandlerCompilationError(f"service contract method {name} must be async")
    try:
        signature = inspect.signature(target)
        hints = get_type_hints(target, include_extras=True)
    except (TypeError, ValueError, NameError) as error:
        raise HandlerCompilationError(
            f"service contract method {name} annotations could not be resolved"
        ) from error
    parameters = tuple(signature.parameters.values())
    if not parameters or parameters[0].name != "self":
        raise HandlerCompilationError(f"service contract method {name} requires self")
    response_type = hints.get("return", signature.return_annotation)
    if response_type is inspect.Signature.empty or response_type is None:
        raise HandlerCompilationError(
            f"service contract method {name} requires a response annotation"
        )
    payload_parameters: list[str] = []
    metadata_parameters: dict[str, str] = {}
    for parameter in parameters[1:]:
        if parameter.kind in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            raise HandlerCompilationError(
                f"service contract parameter {parameter.name} cannot be "
                "variadic or positional-only"
            )
        annotation = hints.get(parameter.name, parameter.annotation)
        marker = _outbound_marker(annotation)
        if marker is None:
            payload_parameters.append(parameter.name)
            continue
        if parameter.kind is not inspect.Parameter.KEYWORD_ONLY:
            raise HandlerCompilationError(
                f"service contract metadata parameter {parameter.name} "
                "must be keyword-only"
            )
        if marker in metadata_parameters.values():
            raise HandlerCompilationError(
                f"service contract method {name} duplicates {marker} metadata"
            )
        metadata_parameters[parameter.name] = marker
    expected_fields = tuple(
        field.name for field in msgspec.structs.fields(metadata.payload_type)
    )
    if tuple(payload_parameters) != expected_fields:
        raise HandlerCompilationError(
            f"service contract method {name} payload parameters must match "
            f"{metadata.payload_type.__name__} fields"
        )
    return RpcCallPlan(
        name,
        signature,
        metadata,
        tuple(payload_parameters),
        metadata_parameters,
        cast(type[object], response_type),
    )


def _outbound_marker(annotation: object) -> str | None:
    if get_origin(annotation) is not Annotated:
        return None
    markers = [
        kind
        for marker in get_args(annotation)[1:]
        for marker_type, kind in _OUTBOUND_MARKERS.items()
        if isinstance(marker, marker_type)
    ]
    if len(markers) > 1:
        raise HandlerCompilationError("service contract parameter has multiple markers")
    return markers[0] if markers else None


__all__ = [
    "CallHeaders",
    "CallTimeout",
    "CausationId",
    "CorrelationId",
    "IdempotencyKey",
    "ProtocolServiceProxy",
    "RpcCallMetadata",
    "RpcCallPlan",
    "ServiceContractMetadata",
    "ServiceContractPlan",
    "compile_service_contract",
    "create_service_proxy",
    "get_rpc_call_metadata",
    "get_service_contract_metadata",
    "rpc_call",
    "service_contract",
]

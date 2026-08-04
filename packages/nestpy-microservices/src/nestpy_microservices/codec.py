"""Deterministic JSON codec for transport-neutral wire envelopes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID

import msgspec

from nestpy_microservices.errors import (
    IdentityValidationError,
    WireDecodingError,
    WireEncodingError,
    WireSizeLimitError,
    WireValidationError,
)
from nestpy_microservices.identities import MessageLimits, ReplyRoute, ServiceIdentity
from nestpy_microservices.wire import (
    RESULT_MISSING,
    EventEnvelope,
    RemoteRpcErrorData,
    RpcRequestEnvelope,
    RpcResponseEnvelope,
    freeze_headers,
)

_REQUEST_FIELDS = frozenset(
    {
        "message_id",
        "kind",
        "namespace",
        "service",
        "contract_version",
        "method",
        "schema_version",
        "created_at",
        "deadline_at",
        "correlation_id",
        "causation_id",
        "idempotency_key",
        "reply_to",
        "headers",
        "payload",
    }
)
_RESPONSE_BASE_FIELDS = frozenset(
    {"message_id", "kind", "correlation_id", "completed_at"}
)
_EVENT_FIELDS = frozenset(
    {
        "message_id",
        "kind",
        "namespace",
        "service",
        "contract_version",
        "event",
        "schema_version",
        "occurred_at",
        "correlation_id",
        "causation_id",
        "headers",
        "payload",
    }
)


class MessageCodec(Protocol):
    """Transport-neutral envelope codec contract."""

    def encode_request(self, envelope: RpcRequestEnvelope) -> bytes: ...

    def decode_request(self, data: bytes) -> RpcRequestEnvelope: ...

    def encode_response(self, envelope: RpcResponseEnvelope) -> bytes: ...

    def decode_response(self, data: bytes) -> RpcResponseEnvelope: ...

    def encode_event(self, envelope: EventEnvelope) -> bytes: ...

    def decode_event(self, data: bytes) -> EventEnvelope: ...


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical(value: object, field_name: str) -> object:
    if isinstance(value, Mapping):
        return _canonical_builtins(value, field_name)
    try:
        builtins = msgspec.to_builtins(value)
    except (TypeError, ValueError, msgspec.ValidationError) as error:
        raise WireEncodingError(f"{field_name} is not codec-compatible") from error
    return _canonical_builtins(builtins, field_name)


def _canonical_builtins(value: object, field_name: str, depth: int = 0) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        items: list[tuple[str, object]] = []
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise WireEncodingError(f"{field_name} keys must be non-empty strings")
            items.append((key, _canonical_builtins(item, field_name, depth + 1)))
        return dict(sorted(items))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical_builtins(item, field_name, depth + 1) for item in value]
    raise WireEncodingError(f"{field_name} contains an unsupported value")


def _plain_headers(headers: Mapping[str, object]) -> dict[str, object]:
    value = _canonical(headers, "headers")
    if not isinstance(value, dict):
        raise WireEncodingError("headers must encode as an object")
    return cast(dict[str, object], value)


def _wire_service(service: ServiceIdentity) -> dict[str, object]:
    return {
        "namespace": service.namespace,
        "service": service.name,
        "contract_version": service.contract_version,
    }


def _encode_json(value: Mapping[str, object], limits: MessageLimits) -> bytes:
    try:
        data = msgspec.json.encode(value)
    except (TypeError, ValueError, msgspec.EncodeError) as error:
        raise WireEncodingError("wire envelope is not JSON encodable") from error
    if len(data) > limits.max_envelope_bytes:
        raise WireSizeLimitError("wire envelope exceeds the configured byte limit")
    return data


def _decode_json(data: bytes, limits: MessageLimits) -> dict[str, Any]:
    if not isinstance(data, bytes):
        raise WireDecodingError("wire data must be bytes")
    if len(data) > limits.max_envelope_bytes:
        raise WireSizeLimitError("wire envelope exceeds the configured byte limit")
    try:
        value = msgspec.json.decode(data)
    except (msgspec.DecodeError, ValueError, TypeError) as error:
        raise WireDecodingError("wire data is not valid JSON") from error
    if not isinstance(value, dict):
        raise WireDecodingError("wire envelope must be a JSON object")
    _check_limits(value, limits)
    return cast(dict[str, Any], value)


def _check_limits(value: object, limits: MessageLimits, depth: int = 0) -> None:
    if depth > limits.max_nesting_depth:
        raise WireSizeLimitError("wire value exceeds the nesting depth limit")
    if isinstance(value, dict):
        if len(value) > limits.max_collection_items:
            raise WireSizeLimitError("wire object exceeds the collection limit")
        for key, item in value.items():
            if not isinstance(key, str):
                raise WireDecodingError("wire object keys must be strings")
            _check_limits(item, limits, depth + 1)
    elif isinstance(value, list):
        if len(value) > limits.max_collection_items:
            raise WireSizeLimitError("wire array exceeds the collection limit")
        for item in value:
            _check_limits(item, limits, depth + 1)


def _require_fields(
    value: Mapping[str, object], required: frozenset[str], field_name: str
) -> None:
    actual = set(value)
    missing = required - actual
    unknown = actual - required
    if missing:
        raise WireDecodingError(f"{field_name} is missing fields: {sorted(missing)}")
    if unknown:
        raise WireDecodingError(f"{field_name} has unknown fields: {sorted(unknown)}")


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise WireDecodingError(f"{field_name} must be a string")
    return value


def _uuid(value: object, field_name: str) -> UUID:
    text = _string(value, field_name)
    try:
        parsed = UUID(text)
    except ValueError as error:
        raise WireDecodingError(f"{field_name} must be a UUID") from error
    if str(parsed) != text:
        raise WireDecodingError(f"{field_name} must use canonical UUID text")
    return parsed


def _timestamp_value(value: object, field_name: str) -> datetime:
    text = _string(value, field_name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise WireDecodingError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise WireDecodingError(f"{field_name} must be UTC")
    return parsed


def _service(value: Mapping[str, object]) -> ServiceIdentity:
    required = frozenset({"namespace", "service", "contract_version"})
    missing = required - set(value)
    if missing:
        raise WireDecodingError(f"service is missing fields: {sorted(missing)}")
    return ServiceIdentity(
        _string(value["namespace"], "namespace"),
        _string(value["service"], "service"),
        _positive_int(value["contract_version"], "contract_version"),
    )


def _positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise WireDecodingError(f"{field_name} must be a positive integer")
    return value


def _headers(value: object, limits: MessageLimits) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise WireDecodingError("headers must be a JSON object")
    headers = cast(Mapping[str, object], value)
    try:
        frozen = freeze_headers(headers, limits)
    except WireSizeLimitError:
        raise
    except WireValidationError as error:
        raise WireDecodingError(str(error)) from error
    if len(msgspec.json.encode(_plain_headers(frozen))) > limits.max_header_bytes:
        raise WireSizeLimitError("headers exceed the configured byte limit")
    return frozen


def _checked_headers(
    headers: Mapping[str, object], limits: MessageLimits
) -> dict[str, object]:
    plain = _plain_headers(headers)
    if len(msgspec.json.encode(plain)) > limits.max_header_bytes:
        raise WireSizeLimitError("headers exceed the configured byte limit")
    return plain


def _remote_error(value: object) -> RemoteRpcErrorData:
    if not isinstance(value, dict):
        raise WireDecodingError("error must be a JSON object")
    value = cast(dict[str, object], value)
    _require_fields(
        value, frozenset({"code", "message", "retryable", "details"}), "error"
    )
    details = value["details"]
    if not isinstance(details, dict):
        raise WireDecodingError("error.details must be a JSON object")
    details = cast(Mapping[str, object], details)
    retryable = value["retryable"]
    if not isinstance(retryable, bool):
        raise WireDecodingError("error.retryable must be boolean")
    try:
        return RemoteRpcErrorData(
            _string(value["code"], "error.code"),
            _string(value["message"], "error.message"),
            retryable,
            details,
        )
    except WireSizeLimitError:
        raise
    except (IdentityValidationError, WireValidationError) as error:
        raise WireDecodingError(str(error)) from error


class MsgspecJsonMessageCodec:
    """Deterministic UTF-8 JSON codec with envelope and size validation."""

    def __init__(self, limits: MessageLimits | None = None) -> None:
        self.limits = limits or MessageLimits()

    def encode_request(self, envelope: RpcRequestEnvelope) -> bytes:
        value = {
            "message_id": str(envelope.message_id),
            "kind": envelope.kind,
            **_wire_service(envelope.service),
            "method": envelope.method,
            "schema_version": envelope.schema_version,
            "created_at": _timestamp(envelope.created_at),
            "deadline_at": _timestamp(envelope.deadline_at),
            "correlation_id": str(envelope.correlation_id),
            "causation_id": (
                str(envelope.causation_id)
                if envelope.causation_id is not None
                else None
            ),
            "idempotency_key": envelope.idempotency_key,
            "reply_to": envelope.reply_to.value,
            "headers": _checked_headers(envelope.headers, self.limits),
            "payload": _canonical(envelope.payload, "payload"),
        }
        return _encode_json(value, self.limits)

    def decode_request(self, data: bytes) -> RpcRequestEnvelope:
        value = _decode_json(data, self.limits)
        _require_fields(value, _REQUEST_FIELDS, "RPC request")
        causation = value["causation_id"]
        idempotency = value["idempotency_key"]
        if causation is not None:
            causation = _uuid(causation, "causation_id")
        if idempotency is not None and not isinstance(idempotency, str):
            raise WireDecodingError("idempotency_key must be a string or null")
        try:
            if value["kind"] != "rpc_request":
                raise WireDecodingError("RPC request kind is invalid")
            return RpcRequestEnvelope(
                message_id=_uuid(value["message_id"], "message_id"),
                service=_service(value),
                method=_string(value["method"], "method"),
                schema_version=_positive_int(value["schema_version"], "schema_version"),
                created_at=_timestamp_value(value["created_at"], "created_at"),
                deadline_at=_timestamp_value(value["deadline_at"], "deadline_at"),
                correlation_id=_uuid(value["correlation_id"], "correlation_id"),
                causation_id=causation,
                idempotency_key=idempotency,
                reply_to=ReplyRoute(_string(value["reply_to"], "reply_to")),
                headers=_headers(value["headers"], self.limits),
                payload=value["payload"],
            )
        except WireSizeLimitError:
            raise
        except (IdentityValidationError, WireValidationError) as error:
            raise WireDecodingError(str(error)) from error

    def encode_response(self, envelope: RpcResponseEnvelope) -> bytes:
        value: dict[str, object] = {
            "message_id": str(envelope.message_id),
            "kind": envelope.kind,
            "correlation_id": str(envelope.correlation_id),
            "completed_at": _timestamp(envelope.completed_at),
        }
        if envelope.result is not RESULT_MISSING:
            value["result"] = _canonical(envelope.result, "result")
        else:
            assert envelope.error is not None
            value["error"] = {
                "code": envelope.error.code,
                "message": envelope.error.message,
                "retryable": envelope.error.retryable,
                "details": _checked_headers(envelope.error.details, self.limits),
            }
        return _encode_json(value, self.limits)

    def decode_response(self, data: bytes) -> RpcResponseEnvelope:
        value = _decode_json(data, self.limits)
        actual = set(value)
        if not _RESPONSE_BASE_FIELDS <= actual:
            raise WireDecodingError("RPC response is missing required fields")
        if actual - (_RESPONSE_BASE_FIELDS | {"result", "error"}):
            raise WireDecodingError("RPC response has unknown fields")
        if value["kind"] != "rpc_response":
            raise WireDecodingError("RPC response kind is invalid")
        has_result = "result" in value
        has_error = "error" in value
        if has_result == has_error:
            raise WireDecodingError(
                "RPC response must contain exactly one result/error"
            )
        try:
            return RpcResponseEnvelope(
                message_id=_uuid(value["message_id"], "message_id"),
                correlation_id=_uuid(value["correlation_id"], "correlation_id"),
                completed_at=_timestamp_value(value["completed_at"], "completed_at"),
                result=value["result"] if has_result else RESULT_MISSING,
                error=_remote_error(value["error"]) if has_error else None,
            )
        except WireSizeLimitError:
            raise
        except (IdentityValidationError, WireValidationError) as error:
            raise WireDecodingError(str(error)) from error

    def encode_event(self, envelope: EventEnvelope) -> bytes:
        value = {
            "message_id": str(envelope.message_id),
            "kind": envelope.kind,
            **_wire_service(envelope.source),
            "event": envelope.event,
            "schema_version": envelope.schema_version,
            "occurred_at": _timestamp(envelope.occurred_at),
            "correlation_id": (
                str(envelope.correlation_id)
                if envelope.correlation_id is not None
                else None
            ),
            "causation_id": (
                str(envelope.causation_id)
                if envelope.causation_id is not None
                else None
            ),
            "headers": _checked_headers(envelope.headers, self.limits),
            "payload": _canonical(envelope.payload, "payload"),
        }
        return _encode_json(value, self.limits)

    def decode_event(self, data: bytes) -> EventEnvelope:
        value = _decode_json(data, self.limits)
        _require_fields(value, _EVENT_FIELDS, "event")
        correlation = value["correlation_id"]
        causation = value["causation_id"]
        if correlation is not None:
            correlation = _uuid(correlation, "correlation_id")
        if causation is not None:
            causation = _uuid(causation, "causation_id")
        if value["kind"] != "event":
            raise WireDecodingError("event kind is invalid")
        try:
            return EventEnvelope(
                message_id=_uuid(value["message_id"], "message_id"),
                source=_service(value),
                event=_string(value["event"], "event"),
                schema_version=_positive_int(value["schema_version"], "schema_version"),
                occurred_at=_timestamp_value(value["occurred_at"], "occurred_at"),
                correlation_id=correlation,
                causation_id=causation,
                headers=_headers(value["headers"], self.limits),
                payload=value["payload"],
            )
        except WireSizeLimitError:
            raise
        except (IdentityValidationError, WireValidationError) as error:
            raise WireDecodingError(str(error)) from error


__all__ = ["MessageCodec", "MsgspecJsonMessageCodec"]

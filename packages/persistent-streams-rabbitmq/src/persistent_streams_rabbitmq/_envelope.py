from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import IntEnum
from struct import Struct
from types import MappingProxyType
from typing import cast
from uuid import UUID

from persistent_streams_rabbitmq.errors import EnvelopeError

MAGIC = b"PSRM"
VERSION = 2
CONTENT_TYPE = "application/vnd.persistent-streams.record.v2"
_PREFIX = Struct(">4sBB16sIH")
_HEADER = Struct(">HI")
_PAYLOAD_LENGTH = Struct(">Q")


class EnvelopeKind(IntEnum):
    RECORD = 1
    BARRIER = 2


@dataclass(frozen=True, slots=True)
class EnvelopeLimits:
    max_message_bytes: int = 2 * 1024 * 1024
    max_payload_bytes: int = 1024 * 1024
    max_partition_key_bytes: int = 4096
    max_headers: int = 64
    max_header_name_bytes: int = 256
    max_header_value_bytes: int = 16_384
    max_header_bytes: int = 65_536
    max_content_type_bytes: int = 128

    def __post_init__(self) -> None:
        if any(
            isinstance(getattr(self, name), bool)
            or not isinstance(getattr(self, name), int)
            or getattr(self, name) <= 0
            for name in self.__dataclass_fields__
        ):
            raise ValueError("envelope limits must be positive integers")


DEFAULT_ENVELOPE_LIMITS = EnvelopeLimits()


@dataclass(frozen=True, slots=True)
class RecordEnvelope:
    record_id: UUID
    partition_key: bytes
    headers: Mapping[str, bytes]
    payload: bytes
    content_type: str = field(default=CONTENT_TYPE, compare=False)
    kind: EnvelopeKind = EnvelopeKind.RECORD

    def __post_init__(self) -> None:
        if not isinstance(self.record_id, UUID):
            raise TypeError("record_id must be a UUID")
        if not isinstance(self.kind, EnvelopeKind):
            raise EnvelopeError("kind must be an EnvelopeKind")
        object.__setattr__(
            self, "partition_key", _require_bytes(self.partition_key, "partition_key")
        )
        if not self.partition_key:
            raise EnvelopeError("partition_key must not be empty")
        if not isinstance(self.headers, Mapping):
            raise TypeError("headers must be a mapping")
        headers: dict[str, bytes] = {}
        for name, value in self.headers.items():
            if not isinstance(name, str) or not name:
                raise EnvelopeError("header names must be non-empty strings")
            headers[name] = _require_bytes(value, f"header {name}")
        object.__setattr__(self, "headers", MappingProxyType(headers))
        object.__setattr__(self, "payload", _require_bytes(self.payload, "payload"))
        if self.kind is EnvelopeKind.BARRIER and (
            self.partition_key != b"_psrm" or self.headers or self.payload
        ):
            raise EnvelopeError("barrier envelope has invalid application fields")
        _validate_content_type(self.content_type, DEFAULT_ENVELOPE_LIMITS)


def encode_envelope(
    envelope: RecordEnvelope, limits: EnvelopeLimits = DEFAULT_ENVELOPE_LIMITS
) -> bytes:
    partition_key = bytes(envelope.partition_key)
    payload = bytes(envelope.payload)
    headers = sorted(envelope.headers.items(), key=lambda item: item[0].encode("utf-8"))
    if len(partition_key) > limits.max_partition_key_bytes:
        raise EnvelopeError("partition key exceeds limit")
    if len(payload) > limits.max_payload_bytes or len(headers) > limits.max_headers:
        raise EnvelopeError("payload or header count exceeds limit")
    output = bytearray(
        _PREFIX.pack(
            MAGIC,
            VERSION,
            envelope.kind,
            envelope.record_id.bytes,
            len(partition_key),
            len(headers),
        )
    )
    output.extend(partition_key)
    aggregate = 0
    previous_name: bytes | None = None
    for name, value in headers:
        try:
            name_bytes = name.encode("utf-8")
        except UnicodeEncodeError as error:
            raise EnvelopeError("header name is not valid UTF-8") from error
        value_bytes = bytes(value)
        if not name_bytes or previous_name == name_bytes:
            raise EnvelopeError("header names must be non-empty and unique")
        if (
            len(name_bytes) > limits.max_header_name_bytes
            or len(value_bytes) > limits.max_header_value_bytes
        ):
            raise EnvelopeError("header exceeds limit")
        aggregate += len(name_bytes) + len(value_bytes)
        if aggregate > limits.max_header_bytes:
            raise EnvelopeError("aggregate headers exceed limit")
        output.extend(_HEADER.pack(len(name_bytes), len(value_bytes)))
        output.extend(name_bytes)
        output.extend(value_bytes)
        previous_name = name_bytes
    output.extend(_PAYLOAD_LENGTH.pack(len(payload)))
    output.extend(payload)
    if len(output) > limits.max_message_bytes:
        raise EnvelopeError("encoded envelope exceeds message limit")
    return bytes(output)


def decode_envelope(
    data: bytes, limits: EnvelopeLimits = DEFAULT_ENVELOPE_LIMITS
) -> RecordEnvelope:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("envelope must be bytes-like")
    view = memoryview(data)
    if len(view) > limits.max_message_bytes or len(view) < _PREFIX.size:
        raise EnvelopeError("envelope is oversized or truncated")
    magic, version, raw_kind, record_id, partition_length, header_count = (
        _PREFIX.unpack_from(view)
    )
    if magic != MAGIC or version != VERSION:
        raise EnvelopeError("unsupported envelope magic or version")
    try:
        kind = EnvelopeKind(raw_kind)
    except ValueError as error:
        raise EnvelopeError("unsupported envelope kind") from error
    if (
        partition_length == 0
        or partition_length > limits.max_partition_key_bytes
        or header_count > limits.max_headers
    ):
        raise EnvelopeError("envelope component exceeds limit")
    position = _PREFIX.size
    partition_key, position = _take(view, position, partition_length)
    headers: dict[str, bytes] = {}
    previous_name: bytes | None = None
    aggregate = 0
    for _ in range(header_count):
        if len(view) - position < _HEADER.size:
            raise EnvelopeError("truncated header lengths")
        name_length, value_length = _HEADER.unpack_from(view, position)
        position += _HEADER.size
        if (
            name_length == 0
            or name_length > limits.max_header_name_bytes
            or value_length > limits.max_header_value_bytes
        ):
            raise EnvelopeError("header exceeds limit")
        aggregate += name_length + value_length
        if aggregate > limits.max_header_bytes:
            raise EnvelopeError("aggregate headers exceed limit")
        name_bytes, position = _take(view, position, name_length)
        value, position = _take(view, position, value_length)
        if previous_name is not None and name_bytes <= previous_name:
            raise EnvelopeError("header names are not in unique canonical order")
        try:
            name = name_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise EnvelopeError("header name is not UTF-8") from error
        headers[name] = value
        previous_name = name_bytes
    if len(view) - position < _PAYLOAD_LENGTH.size:
        raise EnvelopeError("truncated payload length")
    (payload_length,) = _PAYLOAD_LENGTH.unpack_from(view, position)
    position += _PAYLOAD_LENGTH.size
    if payload_length > limits.max_payload_bytes:
        raise EnvelopeError("payload exceeds limit")
    payload, position = _take(view, position, payload_length)
    if position != len(view):
        raise EnvelopeError("trailing envelope bytes")
    return RecordEnvelope(
        UUID(bytes=record_id), partition_key, headers, payload, kind=kind
    )


def encode_amqp_message(
    envelope: RecordEnvelope, limits: EnvelopeLimits = DEFAULT_ENVELOPE_LIMITS
):
    from rstream import AMQPMessage, Properties

    _validate_content_type(envelope.content_type, limits)
    return AMQPMessage(
        body=encode_envelope(envelope, limits),
        properties=Properties(
            message_id=str(envelope.record_id), content_type=envelope.content_type
        ),
    )


def decode_amqp_message(
    message: object, limits: EnvelopeLimits = DEFAULT_ENVELOPE_LIMITS
) -> RecordEnvelope:
    properties = getattr(message, "properties", None)
    body = getattr(message, "body", None)
    message_id = _text(getattr(properties, "message_id", None), "message-id")
    content_type = _text(getattr(properties, "content_type", None), "content-type")
    _validate_content_type(content_type, limits)
    envelope = decode_envelope(cast(bytes, body), limits)
    if message_id != str(envelope.record_id) or content_type != CONTENT_TYPE:
        raise EnvelopeError("AMQP properties do not match the canonical envelope")
    return envelope


def _take(view: memoryview, position: int, length: int) -> tuple[bytes, int]:
    end = position + length
    if end > len(view):
        raise EnvelopeError("truncated envelope field")
    return bytes(view[position:end]), end


def _require_bytes(value: object, name: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError(f"{name} must be bytes-like")
    return bytes(value)


def _text(value: object, name: str) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("ascii")
        except UnicodeDecodeError as error:
            raise EnvelopeError(f"{name} must be ASCII") from error
    if not isinstance(value, str):
        raise EnvelopeError(f"{name} is required")
    return value


def _validate_content_type(value: str, limits: EnvelopeLimits) -> None:
    if (
        not isinstance(value, str)
        or not value
        or _ascii_length(value) > limits.max_content_type_bytes
    ):
        raise EnvelopeError("content-type must be bounded ASCII")
    if value != CONTENT_TYPE:
        raise EnvelopeError("content-type is not the canonical PSRM v2 type")


def _ascii_length(value: str) -> int:
    try:
        return len(value.encode("ascii", "strict"))
    except UnicodeEncodeError as error:
        raise EnvelopeError("content-type must be bounded ASCII") from error

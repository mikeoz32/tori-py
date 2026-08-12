from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from persistent_streams import StoredRecord, StreamDefinition
from rstream import amqp_decoder
from rstream.consumer import MessageContext

from persistent_streams_rabbitmq._envelope import (
    EnvelopeKind,
    EnvelopeLimits,
    RecordEnvelope,
    decode_amqp_message,
)
from persistent_streams_rabbitmq.errors import EnvelopeError


def envelope_limits(definition: StreamDefinition) -> EnvelopeLimits:
    limits = definition.limits
    return EnvelopeLimits(
        max_message_bytes=limits.max_payload_bytes
        + limits.max_header_bytes
        + limits.max_partition_key_bytes
        + 4096,
        max_payload_bytes=limits.max_payload_bytes,
        max_partition_key_bytes=limits.max_partition_key_bytes,
        max_headers=limits.max_headers,
        max_header_name_bytes=limits.max_header_name_chars * 4,
        max_header_value_bytes=limits.max_header_value_bytes,
        max_header_bytes=limits.max_header_bytes,
    )


def decode_message(message: object, limits: EnvelopeLimits) -> RecordEnvelope:
    if isinstance(message, BaseException):
        raise EnvelopeError("AMQP 1.0 message decoding failed") from message
    return decode_amqp_message(message, limits)


def stored_record(
    envelope: RecordEnvelope,
    context: MessageContext,
    stream: str,
    partition: int,
) -> StoredRecord:
    if envelope.kind is not EnvelopeKind.RECORD:
        raise EnvelopeError("control envelope cannot become a StoredRecord")
    return StoredRecord(
        envelope.record_id,
        stream,
        envelope.partition_key,
        envelope.payload,
        envelope.headers,
        partition,
        context.offset,
        datetime.fromtimestamp(context.timestamp / 1000, UTC),
    )


def safe_amqp_decoder(data: bytes) -> object:
    try:
        return amqp_decoder(data)
    except BaseException as error:
        return error


async def best_effort(operation) -> None:
    try:
        await operation
    except asyncio.CancelledError:
        raise
    except BaseException:
        pass


async def best_effort_close(resource: object) -> None:
    close = getattr(resource, "close", None)
    if close is not None:
        await best_effort(close())


__all__ = [
    "best_effort",
    "best_effort_close",
    "decode_message",
    "envelope_limits",
    "safe_amqp_decoder",
    "stored_record",
]

from __future__ import annotations

from typing import cast
from uuid import UUID

import pytest
from persistent_streams import ResumeCursor
from persistent_streams_rabbitmq._capabilities import RABBITMQ_START_MODE_CAPABILITIES
from persistent_streams_rabbitmq._cursor_codec import (
    MAX_BROKER_CURSOR,
    MAX_CURSOR_OFFSET,
    decode_cursor,
    encode_cursor,
)
from persistent_streams_rabbitmq._envelope import (
    RecordEnvelope,
    decode_envelope,
    encode_envelope,
)
from persistent_streams_rabbitmq._rstream_compat import compatibility_facts
from rstream.client import Client


def test_pinned_rstream_compatibility_audit() -> None:
    facts = compatibility_facts()
    assert facts["rstream_version"] == "1.0.1"
    assert facts["stream_stats_key"] == 0x1C
    assert facts["sync_request_signature"] == (
        "(self, frame: 'schema.Frame', resp_schema: 'Type[FT]', "
        "raise_exception=True) -> 'FT'"
    )
    assert facts["query_publisher_sequence_signature"] == (
        "(self, stream: 'str', reference: 'str') -> 'int'"
    )
    request, response = facts["schema_registry_entries"]
    assert request.__name__ == "_StreamStats"
    assert response.__name__ == "_StreamStatsResponse"
    assert "query_publisher_sequence" in Client.__dict__


def test_start_capabilities_reject_unproven_timestamp_modes() -> None:
    assert RABBITMQ_START_MODE_CAPABILITIES.beginning is True
    assert RABBITMQ_START_MODE_CAPABILITIES.end is True
    assert RABBITMQ_START_MODE_CAPABILITIES.exact_offset is True
    assert RABBITMQ_START_MODE_CAPABILITIES.timestamp is False
    assert RABBITMQ_START_MODE_CAPABILITIES.relative_time is False


@pytest.mark.parametrize(
    ("cursor", "encoded"),
    [
        (ResumeCursor.initialized(0), 0),
        (ResumeCursor.last_successful(0), 1),
        (ResumeCursor.initialized(42), 84),
        (ResumeCursor.last_successful(42), 85),
        (ResumeCursor.last_successful(MAX_CURSOR_OFFSET), MAX_BROKER_CURSOR),
    ],
)
def test_cursor_uint64_golden_vectors(cursor: ResumeCursor, encoded: int) -> None:
    assert encode_cursor(cursor) == encoded
    assert decode_cursor(encoded) == cursor


def test_cursor_codec_rejects_overflow() -> None:
    with pytest.raises(OverflowError):
        encode_cursor(ResumeCursor.initialized(MAX_CURSOR_OFFSET + 1))
    with pytest.raises(OverflowError):
        decode_cursor(MAX_BROKER_CURSOR + 1)


def test_binary_envelope_golden_vector_and_round_trip() -> None:
    envelope = RecordEnvelope(
        record_id=UUID("00112233-4455-6677-8899-aabbccddeeff"),
        partition_key=b"pk",
        headers={"z": b"last", "a": b"first"},
        payload=b"payload",
    )
    encoded = encode_envelope(envelope)
    assert encoded.hex() == (
        "5053524d0201"
        "00112233445566778899aabbccddeeff"
        "000000020002706b"
        "000100000005616669727374"
        "0001000000047a6c617374"
        "00000000000000077061796c6f6164"
    )
    decoded = decode_envelope(encoded)
    assert decoded.record_id == envelope.record_id
    assert decoded.partition_key == b"pk"
    assert dict(decoded.headers) == {"a": b"first", "z": b"last"}
    assert decoded.payload == b"payload"


def test_binary_envelope_rejects_non_bytes_values() -> None:
    with pytest.raises(TypeError, match="partition_key must be bytes-like"):
        RecordEnvelope(
            record_id=UUID(int=0),
            partition_key=cast(bytes, 1),
            headers={},
            payload=b"",
        )

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from nestpy_microservices import (
    EventEnvelope,
    MessageLimits,
    MsgspecJsonMessageCodec,
    RemoteRpcErrorData,
    RpcRequestEnvelope,
    RpcResponseEnvelope,
    ServiceIdentity,
    WireDecodingError,
    WireEncodingError,
    WireSizeLimitError,
)


@dataclass(frozen=True)
class ProfilePayload:
    handle: str
    age_attested: bool


def _request() -> RpcRequestEnvelope:
    created_at = datetime(2026, 1, 1, 12, tzinfo=UTC)
    return RpcRequestEnvelope(
        message_id=uuid4(),
        service=ServiceIdentity("kinker", "members", 1),
        method="resolve-profile",
        schema_version=1,
        created_at=created_at,
        deadline_at=created_at + timedelta(seconds=5),
        correlation_id=uuid4(),
        causation_id=uuid4(),
        headers={"trace": {"sampled": True}, "tenant": "community"},
        payload=ProfilePayload("velvet", True),
    )


def test_request_round_trip_is_deterministic_and_typed() -> None:
    codec = MsgspecJsonMessageCodec()
    request = _request()
    first = codec.encode_request(request)
    second = codec.encode_request(request)

    assert first == second
    assert b'"kind":"rpc_request"' in first
    assert b'"idempotency_key"' not in first
    decoded = codec.decode_request(first)
    assert decoded == codec.decode_request(second)
    assert decoded.service == request.service
    assert decoded.causation_id == request.causation_id
    assert decoded.payload == {"age_attested": True, "handle": "velvet"}
    trace = cast(Mapping[str, object], decoded.headers["trace"])
    assert trace["sampled"] is True

    legacy = json.loads(first)
    legacy["idempotency_key"] = "legacy-key"
    with pytest.raises(WireDecodingError):
        codec.decode_request(json.dumps(legacy).encode())


def test_response_result_none_and_remote_error_are_exclusive() -> None:
    codec = MsgspecJsonMessageCodec()
    response_id = uuid4()
    correlation_id = uuid4()
    completed_at = datetime(2026, 1, 1, 12, tzinfo=UTC)

    success = RpcResponseEnvelope(
        message_id=response_id,
        correlation_id=correlation_id,
        completed_at=completed_at,
        result=None,
    )
    decoded_success = codec.decode_response(codec.encode_response(success))
    assert decoded_success.result is None
    assert decoded_success.error is None

    failure = RpcResponseEnvelope(
        message_id=response_id,
        correlation_id=correlation_id,
        completed_at=completed_at,
        error=RemoteRpcErrorData(
            "unsupported_schema",
            "The requested schema is not supported.",
            False,
            {"supported": [1]},
        ),
    )
    decoded_failure = codec.decode_response(codec.encode_response(failure))
    assert decoded_failure.error == failure.error


def test_event_round_trip_uses_source_identity_and_schema_routing() -> None:
    codec = MsgspecJsonMessageCodec()
    event = EventEnvelope(
        message_id=uuid4(),
        source=ServiceIdentity("kinker", "members", 1),
        event="profile-created",
        schema_version=2,
        occurred_at=datetime(2026, 1, 1, 12, tzinfo=UTC),
        correlation_id=uuid4(),
        headers={"source": "onboarding"},
        payload={"handle": "velvet"},
    )

    encoded = codec.encode_event(event)
    assert b'"event":"profile-created"' in encoded
    assert b'"schema_version":2' in encoded
    decoded = codec.decode_event(encoded)
    assert decoded == event


def test_headers_are_defensively_copied_and_deeply_immutable() -> None:
    headers = {"nested": {"value": "before"}}
    envelope = _request()
    request = RpcRequestEnvelope(
        message_id=envelope.message_id,
        service=envelope.service,
        method=envelope.method,
        schema_version=envelope.schema_version,
        created_at=envelope.created_at,
        deadline_at=envelope.deadline_at,
        correlation_id=envelope.correlation_id,
        headers=headers,
    )
    headers["nested"]["value"] = "after"
    nested = cast(Mapping[str, object], request.headers["nested"])
    assert nested["value"] == "before"
    with pytest.raises(TypeError):
        cast(Any, nested)["value"] = "after"


@pytest.mark.parametrize(
    "wire",
    [
        b'{"kind":"rpc_request"}',
        b'{"kind":"unknown"}',
        b'{"kind":"rpc_response","message_id":"bad"}',
        b'{"kind":"event","message_id":"bad"}',
    ],
)
def test_malformed_wire_values_fail_before_handler_use(wire: bytes) -> None:
    codec = MsgspecJsonMessageCodec()
    with pytest.raises(WireDecodingError):
        if b"rpc_response" in wire:
            codec.decode_response(wire)
        elif b'"event"' in wire:
            codec.decode_event(wire)
        else:
            codec.decode_request(wire)


def test_envelope_byte_limit_is_checked_before_decode() -> None:
    codec = MsgspecJsonMessageCodec(MessageLimits(max_envelope_bytes=8))
    with pytest.raises(WireSizeLimitError):
        codec.decode_request(b'{"payload":"too large"}')


def test_header_byte_limit_preserves_size_error_during_decode() -> None:
    wire = MsgspecJsonMessageCodec().encode_request(_request())

    with pytest.raises(WireSizeLimitError):
        MsgspecJsonMessageCodec(MessageLimits(max_header_bytes=10)).decode_request(wire)


def test_json_rejects_duplicate_members_and_non_finite_numbers() -> None:
    codec = MsgspecJsonMessageCodec()

    with pytest.raises(WireDecodingError):
        codec.decode_request(b'{"kind":"rpc_request","kind":"rpc_request"}')
    with pytest.raises(WireDecodingError):
        codec.decode_request(b'{"kind":"rpc_request","payload":NaN}')
    with pytest.raises(WireDecodingError):
        codec.decode_request(b'{"kind":"rpc_request","payload":1e999}')

    with pytest.raises(WireEncodingError):
        codec.encode_request(replace(_request(), payload=float("inf")))


def test_custom_limits_apply_to_deeper_outgoing_payloads() -> None:
    payload: object = "leaf"
    for _ in range(65):
        payload = [payload]

    codec = MsgspecJsonMessageCodec(MessageLimits(max_nesting_depth=66))
    decoded = codec.decode_request(
        codec.encode_request(replace(_request(), payload=payload))
    )

    assert decoded.payload == payload


def test_outgoing_payload_limits_match_decode_limits() -> None:
    request = _request()

    with pytest.raises(WireSizeLimitError):
        MsgspecJsonMessageCodec(MessageLimits(max_nesting_depth=1)).encode_request(
            replace(request, payload={"nested": {"value": True}})
        )

    with pytest.raises(WireSizeLimitError):
        MsgspecJsonMessageCodec(MessageLimits(max_collection_items=1)).encode_request(
            replace(request, payload=["first", "second"])
        )

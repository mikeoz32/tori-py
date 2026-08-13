from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime
from operator import setitem
from typing import cast
from uuid import uuid4

import pytest
from tori_py_cqrs_core import (
    Command,
    DeliveryMetadata,
    DeliveryReceipt,
    Envelope,
    EnvelopeValidationError,
    ReplyEnvelope,
    message_type_for,
)


@dataclass(frozen=True, slots=True)
class CreateProfile(Command[int]):
    username: str


def make_delivery() -> DeliveryMetadata:
    return DeliveryMetadata(
        delivery_id=uuid4(),
        enqueued_at=datetime.now(UTC),
    )


def make_envelope() -> Envelope[CreateProfile]:
    message = CreateProfile(username="alice")
    return Envelope(
        message=message,
        message_type=message_type_for(type(message)),
        message_id=uuid4(),
        correlation_id=uuid4(),
        causation_id=None,
        headers={"tenant": "demo"},
        delivery=make_delivery(),
    )


def test_envelope_preserves_values_and_freezes_headers() -> None:
    envelope = make_envelope()

    assert envelope.message.username == "alice"
    assert envelope.headers["tenant"] == "demo"

    with pytest.raises(TypeError):
        setitem(
            cast(MutableMapping[str, str], envelope.headers),
            "tenant",
            "other",
        )


def test_envelope_rejects_wrong_message_identity() -> None:
    message = CreateProfile(username="alice")

    with pytest.raises(EnvelopeValidationError, match="message_type must be"):
        Envelope(
            message=message,
            message_type="wrong.Message",
            message_id=uuid4(),
            correlation_id=None,
            causation_id=None,
            headers={},
            delivery=make_delivery(),
        )


def test_envelope_rejects_marker_message_instances() -> None:
    with pytest.raises(
        EnvelopeValidationError,
        match="concrete Message subclass instance",
    ):
        Envelope(
            message=Command(),  # type: ignore[abstract]
            message_type="tori_py_cqrs_core.messages.Command",
            message_id=uuid4(),
            correlation_id=None,
            causation_id=None,
            headers={},
            delivery=make_delivery(),
        )


def test_envelope_rejects_non_string_headers() -> None:
    message = CreateProfile(username="alice")

    with pytest.raises(EnvelopeValidationError, match="string keys and values"):
        Envelope(
            message=message,
            message_type=message_type_for(type(message)),
            message_id=uuid4(),
            correlation_id=None,
            causation_id=None,
            headers=cast(Mapping[str, str], {"attempt": 1}),
            delivery=make_delivery(),
        )


def test_delivery_metadata_requires_timezone_and_positive_attempt() -> None:
    with pytest.raises(EnvelopeValidationError, match="timezone-aware"):
        DeliveryMetadata(delivery_id=uuid4(), enqueued_at=datetime.now())

    with pytest.raises(EnvelopeValidationError, match="at least 1"):
        DeliveryMetadata(
            delivery_id=uuid4(),
            enqueued_at=datetime.now(UTC),
            attempt=0,
        )


def test_reply_with_none_result_is_successful() -> None:
    reply = ReplyEnvelope[None](reply_id=uuid4(), correlation_id=uuid4())

    assert reply.result is None
    assert reply.error is None


def test_reply_can_carry_an_exception_object() -> None:
    error = RuntimeError("failed")
    reply = ReplyEnvelope[None](
        reply_id=uuid4(),
        correlation_id=uuid4(),
        error=error,
    )

    assert reply.error is error


def test_reply_rejects_result_and_error_together() -> None:
    with pytest.raises(EnvelopeValidationError, match="both result and error"):
        ReplyEnvelope(
            reply_id=uuid4(),
            correlation_id=uuid4(),
            result="ok",
            error=RuntimeError("failed"),
        )


def test_delivery_receipt_validates_timestamp() -> None:
    receipt = DeliveryReceipt(
        message_id=uuid4(),
        delivery_id=uuid4(),
        enqueued_at=datetime.now(UTC),
    )

    assert receipt.message_id

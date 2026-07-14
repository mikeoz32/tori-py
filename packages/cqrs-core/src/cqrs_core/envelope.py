"""Immutable transport envelope and delivery value objects."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from uuid import UUID

from cqrs_core.errors import EnvelopeValidationError
from cqrs_core.identity import message_type_for
from cqrs_core.messages import Message


def _validate_uuid(value: UUID, *, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise EnvelopeValidationError(f"{field_name} must be a UUID")


def _validate_timestamp(value: datetime, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise EnvelopeValidationError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise EnvelopeValidationError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class DeliveryMetadata:
    """Transport delivery information attached to every envelope."""

    delivery_id: UUID
    enqueued_at: datetime
    attempt: int = 1

    def __post_init__(self) -> None:
        _validate_uuid(self.delivery_id, field_name="delivery_id")
        _validate_timestamp(self.enqueued_at, field_name="enqueued_at")
        if not isinstance(self.attempt, int) or isinstance(self.attempt, bool):
            raise EnvelopeValidationError("attempt must be an integer")
        if self.attempt < 1:
            raise EnvelopeValidationError("attempt must be at least 1")


@dataclass(frozen=True, slots=True)
class Envelope[MessageT: Message]:
    """Immutable typed message envelope used by transports."""

    message: MessageT
    message_type: str
    message_id: UUID
    correlation_id: UUID | None
    causation_id: UUID | None
    headers: Mapping[str, str]
    delivery: DeliveryMetadata

    def __post_init__(self) -> None:
        if not isinstance(self.message, Message):
            raise EnvelopeValidationError("message must be a Message instance")

        try:
            expected_type = message_type_for(type(self.message))
        except TypeError as error:
            raise EnvelopeValidationError(
                "message must be a concrete Message subclass instance"
            ) from error
        if self.message_type != expected_type:
            raise EnvelopeValidationError(
                f"message_type must be {expected_type}, got {self.message_type}"
            )

        _validate_uuid(self.message_id, field_name="message_id")
        if self.correlation_id is not None:
            _validate_uuid(self.correlation_id, field_name="correlation_id")
        if self.causation_id is not None:
            _validate_uuid(self.causation_id, field_name="causation_id")

        if not isinstance(self.headers, Mapping):
            raise EnvelopeValidationError("headers must be a mapping")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.headers.items()
        ):
            raise EnvelopeValidationError(
                "headers must contain only string keys and values"
            )

        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


@dataclass(frozen=True, slots=True)
class ReplyEnvelope[ResultT]:
    """Reply returned by a request transport."""

    reply_id: UUID
    correlation_id: UUID
    result: ResultT | None = None
    error: BaseException | None = None

    def __post_init__(self) -> None:
        _validate_uuid(self.reply_id, field_name="reply_id")
        _validate_uuid(self.correlation_id, field_name="correlation_id")
        if self.error is not None and not isinstance(self.error, BaseException):
            raise EnvelopeValidationError("error must be a BaseException or None")
        if self.error is not None and self.result is not None:
            raise EnvelopeValidationError("reply cannot contain both result and error")


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """Proof that a transport accepted a message into its queue."""

    message_id: UUID
    delivery_id: UUID
    enqueued_at: datetime

    def __post_init__(self) -> None:
        _validate_uuid(self.message_id, field_name="message_id")
        _validate_uuid(self.delivery_id, field_name="delivery_id")
        _validate_timestamp(self.enqueued_at, field_name="enqueued_at")

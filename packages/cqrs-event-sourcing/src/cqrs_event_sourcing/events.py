"""Immutable event occurrence and stream value objects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from uuid import UUID

from cqrs_core import Event

from cqrs_event_sourcing.errors import (
    InvalidEventMetadataError,
    InvalidEventRecordError,
    InvalidStreamIdError,
)


def _stable_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise InvalidEventRecordError(
            f"{field_name} must be a non-empty string without surrounding whitespace"
        )
    if not value.isprintable():
        raise InvalidEventRecordError(f"{field_name} must contain printable text")
    return value


def _positive_int(value: object, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise InvalidEventRecordError(f"{field_name} must be a positive integer")
    return value


def _non_negative_int(value: object, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise InvalidEventRecordError(f"{field_name} must be a non-negative integer")
    return value


def _uuid(value: object, *, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise InvalidEventMetadataError(f"{field_name} must be a UUID")
    return value


def _optional_uuid(value: object, *, field_name: str) -> UUID | None:
    if value is None:
        return None
    return _uuid(value, field_name=field_name)


def _aware_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise InvalidEventMetadataError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidEventMetadataError(f"{field_name} must be timezone-aware")
    return value


def _headers(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise InvalidEventMetadataError("headers must be a mapping")
    try:
        copied = dict(value)
    except Exception as error:
        raise InvalidEventMetadataError("headers could not be copied") from error
    if any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in copied.items()
    ):
        raise InvalidEventMetadataError(
            "headers must contain only string keys and values"
        )
    try:
        for key, item in copied.items():
            key.encode("utf-8")
            item.encode("utf-8")
    except UnicodeEncodeError as error:
        raise InvalidEventMetadataError("headers must contain valid UTF-8") from error
    return MappingProxyType(copied)


def _event(value: object) -> Event:
    if not isinstance(value, Event) or type(value) is Event:
        raise InvalidEventRecordError("event must be a concrete Event instance")
    return value


@dataclass(frozen=True, slots=True)
class StreamId:
    """Stable category and aggregate key identifying one event stream."""

    category: str
    key: str

    def __post_init__(self) -> None:
        try:
            category = _stable_text(self.category, field_name="category")
            key = _stable_text(self.key, field_name="key")
        except InvalidEventRecordError as error:
            raise InvalidStreamIdError(str(error)) from error
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "key", key)


@dataclass(frozen=True, slots=True)
class EventMetadata:
    """Immutable identity and context captured when a domain event occurs."""

    event_id: UUID
    occurred_at: datetime
    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    headers: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_id", _uuid(self.event_id, field_name="event_id")
        )
        object.__setattr__(
            self,
            "occurred_at",
            _aware_datetime(self.occurred_at, field_name="occurred_at"),
        )
        object.__setattr__(
            self,
            "correlation_id",
            _optional_uuid(self.correlation_id, field_name="correlation_id"),
        )
        object.__setattr__(
            self,
            "causation_id",
            _optional_uuid(self.causation_id, field_name="causation_id"),
        )
        object.__setattr__(self, "headers", _headers(self.headers))


@dataclass(frozen=True, slots=True)
class PendingEvent:
    """A domain event recorded by an aggregate but not yet committed."""

    event: Event
    metadata: EventMetadata

    def __post_init__(self) -> None:
        object.__setattr__(self, "event", _event(self.event))
        if not isinstance(self.metadata, EventMetadata):
            raise InvalidEventRecordError("metadata must be EventMetadata")


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    """A decoded committed event used to replay aggregate state."""

    stream_id: StreamId
    stream_version: int
    global_position: int
    event_type: str
    schema_version: int
    event: Event
    metadata: EventMetadata

    def __post_init__(self) -> None:
        if not isinstance(self.stream_id, StreamId):
            raise InvalidEventRecordError("stream_id must be StreamId")
        object.__setattr__(
            self,
            "stream_version",
            _positive_int(self.stream_version, field_name="stream_version"),
        )
        object.__setattr__(
            self,
            "global_position",
            _positive_int(self.global_position, field_name="global_position"),
        )
        object.__setattr__(
            self,
            "event_type",
            _stable_text(self.event_type, field_name="event_type"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _positive_int(self.schema_version, field_name="schema_version"),
        )
        object.__setattr__(self, "event", _event(self.event))
        if not isinstance(self.metadata, EventMetadata):
            raise InvalidEventRecordError("metadata must be EventMetadata")


@dataclass(frozen=True, slots=True)
class EncodedEvent:
    """Stable schema identity and opaque encoded event payload."""

    event_type: str
    schema_version: int
    payload: bytes

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "event_type",
            _stable_text(self.event_type, field_name="event_type"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _positive_int(self.schema_version, field_name="schema_version"),
        )
        if not isinstance(self.payload, bytes):
            raise InvalidEventRecordError("payload must be bytes")


@dataclass(frozen=True, slots=True)
class AppendEvent:
    """Complete occurrence metadata and encoded body staged for append."""

    encoded: EncodedEvent
    metadata: EventMetadata

    def __post_init__(self) -> None:
        if not isinstance(self.encoded, EncodedEvent):
            raise InvalidEventRecordError("encoded must be EncodedEvent")
        if not isinstance(self.metadata, EventMetadata):
            raise InvalidEventRecordError("metadata must be EventMetadata")

    @property
    def event_id(self) -> UUID:
        """Return the stable persisted event identity."""

        return self.metadata.event_id


@dataclass(frozen=True, slots=True)
class StoredEvent:
    """An encoded event assigned committed stream and global positions."""

    stream_id: StreamId
    stream_version: int
    global_position: int
    event: AppendEvent

    def __post_init__(self) -> None:
        if not isinstance(self.stream_id, StreamId):
            raise InvalidEventRecordError("stream_id must be StreamId")
        object.__setattr__(
            self,
            "stream_version",
            _positive_int(self.stream_version, field_name="stream_version"),
        )
        object.__setattr__(
            self,
            "global_position",
            _positive_int(self.global_position, field_name="global_position"),
        )
        if not isinstance(self.event, AppendEvent):
            raise InvalidEventRecordError("event must be AppendEvent")

    @property
    def event_id(self) -> UUID:
        """Return the stable persisted event identity."""

        return self.event.event_id


@dataclass(frozen=True, slots=True)
class CommitResult:
    """Confirmed committed events in transaction staging order."""

    events: tuple[StoredEvent, ...]

    def __post_init__(self) -> None:
        events = tuple(self.events)
        if any(not isinstance(event, StoredEvent) for event in events):
            raise InvalidEventRecordError(
                "commit result must contain StoredEvent values"
            )
        object.__setattr__(self, "events", events)

    def final_version(self, stream_id: StreamId) -> int | None:
        """Return the last committed version for one stream in this result."""

        versions = (
            event.stream_version
            for event in self.events
            if event.stream_id == stream_id
        )
        return max(versions, default=None)


__all__ = [
    "AppendEvent",
    "CommitResult",
    "EncodedEvent",
    "EventMetadata",
    "PendingEvent",
    "RecordedEvent",
    "StoredEvent",
    "StreamId",
]

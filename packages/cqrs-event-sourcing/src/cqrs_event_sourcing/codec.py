"""Explicit stable event schemas, codecs, and byte upcasters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from cqrs_core import Event

from cqrs_event_sourcing.errors import (
    DuplicateEventSchemaError,
    EventCodecError,
    EventUpcastError,
    ResourceLimitError,
    SchemaRegistryFrozenError,
    SchemaRegistryNotFrozenError,
    SchemaValidationError,
    UnknownEventSchemaError,
    UnsupportedEventSchemaVersionError,
)
from cqrs_event_sourcing.events import (
    AppendEvent,
    EncodedEvent,
    PendingEvent,
    RecordedEvent,
    StoredEvent,
)

type EventEncoder[EventT: Event] = Callable[[EventT], bytes]
type EventDecoder[EventT: Event] = Callable[[bytes], EventT]
type EventUpcaster = Callable[[bytes], bytes]


def _positive(value: object, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise SchemaValidationError(f"{field_name} must be a positive integer")
    return value


def _alias(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise SchemaValidationError(
            "event alias must be a non-empty string without surrounding whitespace"
        )
    if not value.isprintable():
        raise SchemaValidationError("event alias must contain printable text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise SchemaValidationError("event alias must contain valid UTF-8") from error
    return value


@dataclass(frozen=True, slots=True)
class EventSourcingLimits:
    """Finite resource limits shared by codecs, stores, and repositories."""

    max_payload_bytes: int = 1_048_576
    max_headers: int = 64
    max_header_name_bytes: int = 256
    max_header_value_bytes: int = 4_096
    max_upcast_steps: int = 32
    read_page_size: int = 500
    max_events_per_append: int = 1_000
    max_events_per_transaction: int = 10_000
    max_transaction_bytes: int = 16_777_216

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            object.__setattr__(
                self,
                field_name,
                _positive(getattr(self, field_name), field_name=field_name),
            )


@dataclass(frozen=True, slots=True)
class EventSchema[EventT: Event]:
    """One stable event alias and its current bytes codec."""

    alias: str
    version: int
    event_type: type[EventT]
    encoder: EventEncoder[EventT]
    decoder: EventDecoder[EventT]
    upcasters: Mapping[int, EventUpcaster] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "alias", _alias(self.alias))
        object.__setattr__(
            self,
            "version",
            _positive(self.version, field_name="schema version"),
        )
        if (
            not isinstance(self.event_type, type)
            or not issubclass(self.event_type, Event)
            or self.event_type is Event
        ):
            raise SchemaValidationError("event_type must be a concrete Event subclass")
        if not callable(self.encoder) or not callable(self.decoder):
            raise SchemaValidationError("encoder and decoder must be callable")
        copied = dict(self.upcasters)
        if any(
            not isinstance(version, int)
            or isinstance(version, bool)
            or not callable(upcaster)
            for version, upcaster in copied.items()
        ):
            raise SchemaValidationError(
                "upcasters must map integer source versions to callables"
            )
        source_versions = sorted(copied)
        if len(source_versions) != self.version - 1 or any(
            source_version != expected
            for expected, source_version in enumerate(source_versions, start=1)
        ):
            raise SchemaValidationError(
                f"upcasters for {self.alias} must contain source versions "
                f"1 through {self.version - 1}"
            )
        object.__setattr__(self, "upcasters", MappingProxyType(copied))


class EventSchemaRegistry:
    """Explicit schema registry that must be frozen before persistence use."""

    def __init__(self, *, limits: EventSourcingLimits | None = None) -> None:
        self.limits = limits or EventSourcingLimits()
        self._by_alias: dict[str, EventSchema[Any]] = {}
        self._by_class: dict[type[Event], EventSchema[Any]] = {}
        self._frozen = False

    @property
    def is_frozen(self) -> bool:
        """Return whether registration has been sealed."""

        return self._frozen

    def register[EventT: Event](
        self,
        schema: EventSchema[EventT],
    ) -> EventSchemaRegistry:
        """Register one explicit event schema before freeze."""

        if self._frozen:
            raise SchemaRegistryFrozenError("event schema registry is frozen")
        if not isinstance(schema, EventSchema):
            raise SchemaValidationError("schema must be EventSchema")
        if schema.version - 1 > self.limits.max_upcast_steps:
            raise ResourceLimitError(
                f"schema {schema.alias!r} exceeds the upcast step limit"
            )
        if schema.alias in self._by_alias:
            raise DuplicateEventSchemaError(
                f"event alias {schema.alias!r} is already registered"
            )
        if schema.event_type in self._by_class:
            raise DuplicateEventSchemaError(
                f"event class {schema.event_type.__qualname__} is already registered"
            )
        self._by_alias[schema.alias] = schema
        self._by_class[schema.event_type] = schema
        return self

    def freeze(self) -> EventSchemaRegistry:
        """Seal registration and return this registry."""

        self._frozen = True
        return self

    def encode(self, pending: PendingEvent) -> AppendEvent:
        """Encode one pending event while preserving occurrence metadata."""

        self._require_frozen()
        if not isinstance(pending, PendingEvent):
            raise EventCodecError("encode requires PendingEvent")
        schema = self._by_class.get(type(pending.event))
        if schema is None:
            raise UnknownEventSchemaError(
                f"no schema registered for {type(pending.event).__qualname__}"
            )
        self._validate_headers(pending)
        try:
            payload = schema.encoder(pending.event)
        except Exception as error:
            raise EventCodecError(
                f"encoder failed for event alias {schema.alias!r}"
            ) from error
        payload = self._validate_payload(payload)
        return AppendEvent(
            encoded=EncodedEvent(schema.alias, schema.version, payload),
            metadata=pending.metadata,
        )

    def decode(self, stored: StoredEvent) -> RecordedEvent:
        """Upcast and decode one stored event into a replay record."""

        self._require_frozen()
        if not isinstance(stored, StoredEvent):
            raise EventCodecError("decode requires StoredEvent")
        encoded = stored.event.encoded
        schema = self._by_alias.get(encoded.event_type)
        if schema is None:
            raise UnknownEventSchemaError(
                f"no schema registered for event alias {encoded.event_type!r}"
            )
        if encoded.schema_version > schema.version:
            raise UnsupportedEventSchemaVersionError(
                f"event alias {schema.alias!r} has future schema version "
                f"{encoded.schema_version}; current version is {schema.version}"
            )
        self._validate_headers_from_stored(stored)
        payload = self._validate_payload(encoded.payload)
        version = encoded.schema_version
        steps = 0
        while version < schema.version:
            steps += 1
            if steps > self.limits.max_upcast_steps:
                raise ResourceLimitError("event upcast step limit exceeded")
            upcaster = schema.upcasters.get(version)
            if upcaster is None:
                raise EventUpcastError(
                    f"missing upcaster for {schema.alias!r} version {version}"
                )
            try:
                payload = upcaster(payload)
            except Exception as error:
                raise EventUpcastError(
                    f"upcaster failed for {schema.alias!r} version {version}"
                ) from error
            payload = self._validate_payload(payload)
            version += 1
        try:
            event = schema.decoder(payload)
        except Exception as error:
            raise EventCodecError(
                f"decoder failed for event alias {schema.alias!r}"
            ) from error
        if type(event) is not schema.event_type:
            raise EventCodecError(
                f"decoder for {schema.alias!r} returned {type(event).__qualname__}, "
                f"expected {schema.event_type.__qualname__}"
            )
        return RecordedEvent(
            stream_id=stored.stream_id,
            stream_version=stored.stream_version,
            global_position=stored.global_position,
            event_type=schema.alias,
            schema_version=schema.version,
            event=event,
            metadata=stored.event.metadata,
        )

    def _require_frozen(self) -> None:
        if not self._frozen:
            raise SchemaRegistryNotFrozenError(
                "event schema registry must be frozen before use"
            )

    def _validate_payload(self, payload: object) -> bytes:
        if not isinstance(payload, bytes):
            raise EventCodecError("event codec must return bytes")
        if len(payload) > self.limits.max_payload_bytes:
            raise ResourceLimitError("event payload byte limit exceeded")
        return payload

    def _validate_headers(self, pending: PendingEvent) -> None:
        self._validate_header_mapping(pending.metadata.headers)

    def _validate_headers_from_stored(self, stored: StoredEvent) -> None:
        self._validate_header_mapping(stored.event.metadata.headers)

    def _validate_header_mapping(self, headers: Mapping[str, str]) -> None:
        if len(headers) > self.limits.max_headers:
            raise ResourceLimitError("event header count limit exceeded")
        for name, value in headers.items():
            if len(name.encode()) > self.limits.max_header_name_bytes:
                raise ResourceLimitError("event header name byte limit exceeded")
            if len(value.encode()) > self.limits.max_header_value_bytes:
                raise ResourceLimitError("event header value byte limit exceeded")


__all__ = [
    "EventDecoder",
    "EventEncoder",
    "EventSchema",
    "EventSchemaRegistry",
    "EventSourcingLimits",
    "EventUpcaster",
]

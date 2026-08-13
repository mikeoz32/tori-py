from __future__ import annotations

import math
from collections.abc import Hashable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from types import MappingProxyType
from uuid import UUID

from tori_py_persistent_streams_core.errors import ResourceLimitError, ValidationError
from tori_py_persistent_streams_core.routing import (
    DEFAULT_PARTITION_ROUTER,
    PartitionRouter,
)


def _positive(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError(f"{name} must be a positive integer")
    return value


def _offset(value: int, name: str = "offset") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(f"{name} must be a non-negative integer")
    return value


def _name(value: str, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{name} must be a non-empty string")
    if len(value) > limit:
        raise ResourceLimitError(f"{name} exceeds {limit} characters")
    return value


def _aware(value: datetime, name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValidationError(f"{name} must be timezone-aware")
    return value


def _bytes(value: object, name: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise ValidationError(f"{name} must be bytes-like")
    return bytes(value)


@dataclass(frozen=True, slots=True)
class StreamLimits:
    max_name_chars: int = 128
    max_group_chars: int = 128
    max_owner_chars: int = 128
    max_producer_chars: int = 128
    max_header_name_chars: int = 128
    max_partitions: int = 1024
    max_payload_bytes: int = 1_048_576
    max_partition_key_bytes: int = 4096
    max_headers: int = 64
    max_header_value_bytes: int = 16_384
    max_header_bytes: int = 65_536
    max_read_records: int = 1000
    max_relative_age_days: int = 365_000

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            _positive(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class StreamDefinition:
    name: str
    partition_count: int
    limits: StreamLimits = field(default_factory=StreamLimits)
    router: PartitionRouter = DEFAULT_PARTITION_ROUTER
    _router_identity: str = field(init=False, repr=False)
    _router_compatibility_key: Hashable = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.limits, StreamLimits):
            raise ValidationError("limits must be StreamLimits")
        _name(self.name, "stream name", self.limits.max_name_chars)
        _positive(self.partition_count, "partition_count")
        if self.partition_count > self.limits.max_partitions:
            raise ResourceLimitError("partition_count exceeds stream limit")
        try:
            router = deepcopy(self.router)
        except Exception as error:
            raise ValidationError("router must be copyable") from error
        if not isinstance(router, PartitionRouter):
            raise ValidationError("router must implement PartitionRouter")
        try:
            identity = router.identity
        except Exception as error:
            raise ValidationError("router identity must be readable") from error
        if not isinstance(identity, str) or not identity:
            raise ValidationError("router identity must be a non-empty string")
        try:
            compatibility_key = deepcopy(router.compatibility_key)
            hash(compatibility_key)
        except Exception as error:
            raise ValidationError(
                "router compatibility_key must be readable, copyable, and hashable"
            ) from error
        object.__setattr__(self, "router", router)
        object.__setattr__(self, "_router_identity", identity)
        object.__setattr__(self, "_router_compatibility_key", compatibility_key)

    @property
    def compatibility_key(self) -> tuple[object, ...]:
        return (
            self.partition_count,
            self.limits,
            self._router_identity,
            self._router_compatibility_key,
        )


@dataclass(frozen=True, slots=True)
class AppendRequest:
    record_id: UUID
    partition_key: bytes | bytearray | memoryview
    payload: bytes | bytearray | memoryview = b""
    headers: Mapping[str, bytes | bytearray | memoryview] = field(default_factory=dict)
    producer_name: str | None = None
    publishing_id: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.record_id, UUID):
            raise ValidationError("record_id must be a UUID")
        key = _bytes(self.partition_key, "partition_key")
        if not key:
            raise ValidationError("partition_key must not be empty")
        payload = _bytes(self.payload, "payload")
        if not isinstance(self.headers, Mapping):
            raise ValidationError("headers must be a mapping")
        copied: dict[str, bytes] = {}
        for name, value in self.headers.items():
            if not isinstance(name, str) or not name:
                raise ValidationError("header names must be non-empty strings")
            if name in copied:
                raise ValidationError("header names must be unique")
            copied[name] = _bytes(value, f"header {name!r}")
        if (self.producer_name is None) != (self.publishing_id is None):
            raise ValidationError(
                "producer_name and publishing_id must be supplied together"
            )
        if self.producer_name is not None and (
            not isinstance(self.producer_name, str) or not self.producer_name
        ):
            raise ValidationError("producer_name must be a non-empty string")
        if self.publishing_id is not None:
            _offset(self.publishing_id, "publishing_id")
        object.__setattr__(self, "partition_key", key)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "headers", MappingProxyType(copied))


class PublishOutcome(Enum):
    CONFIRMED = "confirmed"
    DEDUPLICATED = "deduplicated"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    CLOSED = "closed"
    BACKPRESSURED = "backpressured"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class PublishReceipt:
    record_id: UUID
    partition: int
    outcome: PublishOutcome
    confirmation_facts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.record_id, UUID):
            raise ValidationError("record_id must be a UUID")
        _offset(self.partition, "partition")
        if not isinstance(self.outcome, PublishOutcome):
            raise ValidationError("outcome must be a PublishOutcome")
        try:
            facts = tuple(self.confirmation_facts)
        except TypeError as error:
            raise ValidationError("confirmation_facts must be iterable") from error
        if len(facts) > 16 or any(
            not isinstance(fact, str) or len(fact) > 256 for fact in facts
        ):
            raise ResourceLimitError("confirmation facts exceed limits")
        object.__setattr__(self, "confirmation_facts", facts)


@dataclass(frozen=True, slots=True)
class StoredRecord:
    record_id: UUID
    stream: str
    partition_key: bytes
    payload: bytes
    headers: Mapping[str, bytes]
    partition: int
    offset: int
    appended_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.record_id, UUID):
            raise ValidationError("record_id must be a UUID")
        if not isinstance(self.stream, str) or not self.stream:
            raise ValidationError("stream must be a non-empty string")
        key = _bytes(self.partition_key, "partition_key")
        if not key:
            raise ValidationError("partition_key must not be empty")
        object.__setattr__(self, "partition_key", key)
        object.__setattr__(self, "payload", _bytes(self.payload, "payload"))
        if not isinstance(self.headers, Mapping):
            raise ValidationError("headers must be a mapping")
        headers: dict[str, bytes] = {}
        for name, value in self.headers.items():
            if not isinstance(name, str) or not name:
                raise ValidationError("header names must be non-empty strings")
            headers[name] = _bytes(value, name)
        object.__setattr__(self, "headers", MappingProxyType(headers))
        _offset(self.partition, "partition")
        _offset(self.offset)
        _aware(self.appended_at, "appended_at")


@dataclass(frozen=True, slots=True)
class AvailableBounds:
    earliest_offset: int
    end_offset: int

    def __post_init__(self) -> None:
        _offset(self.earliest_offset, "earliest_offset")
        _offset(self.end_offset, "end_offset")
        if self.end_offset < self.earliest_offset:
            raise ValidationError("end_offset precedes earliest_offset")


@dataclass(frozen=True, slots=True)
class RecordPage:
    records: tuple[StoredRecord, ...]
    bounds: AvailableBounds | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        if any(not isinstance(record, StoredRecord) for record in self.records):
            raise ValidationError("records must contain StoredRecord values")
        if any(
            current.offset >= following.offset
            for current, following in zip(self.records, self.records[1:], strict=False)
        ):
            raise ValidationError("records must have strictly increasing offsets")


@dataclass(frozen=True, slots=True)
class Beginning:
    pass


@dataclass(frozen=True, slots=True)
class End:
    pass


@dataclass(frozen=True, slots=True)
class ExactOffset:
    offset: int

    def __post_init__(self) -> None:
        _offset(self.offset)


@dataclass(frozen=True, slots=True)
class Timestamp:
    timestamp: datetime

    def __post_init__(self) -> None:
        _aware(self.timestamp, "timestamp")


@dataclass(frozen=True, slots=True)
class RelativeTime:
    age: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.age, timedelta):
            raise ValidationError("age must be a timedelta")
        seconds = self.age.total_seconds()
        if not math.isfinite(seconds) or seconds < 0:
            raise ValidationError("age must be finite and non-negative")


type StartPosition = Beginning | End | ExactOffset | Timestamp | RelativeTime


@dataclass(frozen=True, slots=True)
class StartModeCapabilities:
    beginning: bool = False
    end: bool = False
    exact_offset: bool = False
    timestamp: bool = False
    relative_time: bool = False

    def __post_init__(self) -> None:
        if any(
            not isinstance(getattr(self, name), bool)
            for name in self.__dataclass_fields__
        ):
            raise ValidationError("start-mode capabilities must be booleans")

    def supports(self, start: StartPosition) -> bool:
        if isinstance(start, Beginning):
            return self.beginning
        if isinstance(start, End):
            return self.end
        if isinstance(start, ExactOffset):
            return self.exact_offset
        if isinstance(start, Timestamp):
            return self.timestamp
        return self.relative_time


class CursorKind(Enum):
    INITIALIZED = "initialized"
    LAST_SUCCESSFUL = "last_successful"


@dataclass(frozen=True, slots=True)
class ResumeCursor:
    kind: CursorKind
    offset: int

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CursorKind):
            raise ValidationError("kind must be a CursorKind")
        _offset(self.offset)

    @classmethod
    def initialized(cls, offset: int) -> ResumeCursor:
        return cls(CursorKind.INITIALIZED, offset)

    @classmethod
    def last_successful(cls, offset: int) -> ResumeCursor:
        return cls(CursorKind.LAST_SUCCESSFUL, offset)


@dataclass(frozen=True, slots=True)
class CheckpointKey:
    stream: str
    group: str
    partition: int

    def __post_init__(self) -> None:
        if not isinstance(self.stream, str) or not self.stream:
            raise ValidationError("checkpoint stream must be a non-empty string")
        if not isinstance(self.group, str) or not self.group:
            raise ValidationError("checkpoint group must be a non-empty string")
        _offset(self.partition, "partition")


@dataclass(frozen=True, slots=True)
class OwnershipToken:
    owner_id: str
    generation: int

    def __post_init__(self) -> None:
        if not isinstance(self.owner_id, str) or not self.owner_id:
            raise ValidationError("owner_id must be a non-empty string")
        _positive(self.generation, "generation")


@dataclass(frozen=True, slots=True)
class Subscription:
    stream: str
    group: str
    owner_id: str
    start: StartPosition

    def __post_init__(self) -> None:
        for name in ("stream", "group", "owner_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValidationError(f"{name} must be a non-empty string")
        if not isinstance(
            self.start, (Beginning, End, ExactOffset, Timestamp, RelativeTime)
        ):
            raise ValidationError("unsupported start position")

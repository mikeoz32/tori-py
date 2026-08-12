"""Adapter, codec, routing, and publisher contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol, runtime_checkable
from uuid import UUID

from persistent_streams import PersistentStreamAdapter, PublishReceipt, StoredRecord


@runtime_checkable
class StreamCodec[PayloadT](Protocol):
    """Encode typed values and decode bounded records to a declared DTO type."""

    def encode(self, payload: PayloadT) -> bytes: ...

    def decode(self, payload: bytes, target: type[PayloadT]) -> PayloadT: ...


@runtime_checkable
class PartitionKeyResolver[PayloadT](Protocol):
    """Derive a stable partition key from a typed payload."""

    def resolve(self, payload: PayloadT) -> bytes: ...


@runtime_checkable
class PublishingIdSource(Protocol):
    """Return a stable publishing ID for a named producer publication."""

    def next_id(self, record_id: UUID, partition_key: bytes) -> int: ...


@runtime_checkable
class StreamAdapterFactory(Protocol):
    """Create one application-owned persistent log without starting intake."""

    def create(
        self, bindings: tuple[object, ...]
    ) -> PersistentStreamAdapter | Awaitable[PersistentStreamAdapter]: ...


@runtime_checkable
class StreamPublisher(Protocol):
    """Publish typed values through an already configured stream alias."""

    async def publish(
        self,
        stream: str,
        payload: object,
        *,
        record_id: UUID | None = None,
        headers: Mapping[str, bytes] | None = None,
    ) -> PublishReceipt: ...


@runtime_checkable
class ConfiguredStreamPublisher[PayloadT](Protocol):
    """Publish through one fixed stream binding."""

    async def publish(
        self,
        payload: PayloadT,
        *,
        record_id: UUID | None = None,
        headers: Mapping[str, bytes] | None = None,
    ) -> PublishReceipt: ...


type RecordCallback = Callable[[StoredRecord], Awaitable[None]]


__all__ = [
    "ConfiguredStreamPublisher",
    "PartitionKeyResolver",
    "PublishingIdSource",
    "RecordCallback",
    "StreamAdapterFactory",
    "StreamCodec",
    "StreamPublisher",
]

"""Immutable persistent stream configuration."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field

from nestpy import PipelineOptions, Token
from persistent_streams import (
    Beginning,
    CheckpointStrategy,
    ExternalCheckpointStrategy,
    StartPosition,
    StreamDefinition,
)

from nestpy_persistent_streams.contracts import (
    PartitionKeyResolver,
    PublishingIdSource,
    StreamCodec,
)
from nestpy_persistent_streams.decorators import validate_alias
from nestpy_persistent_streams.errors import StreamConfigurationError


@dataclass(frozen=True, slots=True)
class StreamBinding[PayloadT]:
    """One fixed logical stream compatibility contract."""

    alias: str
    definition: StreamDefinition
    payload_type: type[PayloadT]
    codec: StreamCodec[PayloadT] | Token
    partition_key_resolver: PartitionKeyResolver[PayloadT] | Token
    producer_name: str | None = None
    publishing_id_source: PublishingIdSource | Token | None = None
    start: StartPosition = field(default_factory=Beginning)
    checkpoint_strategy: CheckpointStrategy | ExternalCheckpointStrategy = (
        CheckpointStrategy.BROKER_MANAGED
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "alias", validate_alias(self.alias))
        if not isinstance(self.definition, StreamDefinition):
            raise StreamConfigurationError(
                "binding definition must be StreamDefinition"
            )
        if not isinstance(self.payload_type, type):
            raise StreamConfigurationError("binding payload_type must be a type")
        if not isinstance(self.codec, (str, type)) and not isinstance(
            self.codec, StreamCodec
        ):
            raise StreamConfigurationError("binding codec must implement StreamCodec")
        if not isinstance(self.partition_key_resolver, (str, type)) and not isinstance(
            self.partition_key_resolver, PartitionKeyResolver
        ):
            raise StreamConfigurationError(
                "partition_key_resolver must implement PartitionKeyResolver"
            )
        if (self.producer_name is None) != (self.publishing_id_source is None):
            raise StreamConfigurationError(
                "named producers require both producer_name and publishing_id_source"
            )
        if self.producer_name is not None and not self.producer_name:
            raise StreamConfigurationError("producer_name must be non-empty")


@dataclass(frozen=True, slots=True)
class PublisherRegistration:
    """Expose one binding through a named token or explicit Protocol token."""

    stream: str
    name: str | None = None
    protocol: type[object] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream", validate_alias(self.stream))
        if self.name is None and self.protocol is None:
            raise StreamConfigurationError(
                "publisher registration requires a name or Protocol token"
            )
        if self.name is not None:
            object.__setattr__(
                self, "name", validate_alias(self.name, "publisher name")
            )
        if self.protocol is not None and not isinstance(self.protocol, type):
            raise StreamConfigurationError("publisher protocol must be a type")


@dataclass(frozen=True, slots=True)
class PersistentStreamsRuntimeOptions:
    """Runtime-only values that an injected async factory may produce."""

    max_concurrency: int = 16
    poll_interval: float = 0.01
    owner_id: str = "nestpy"
    single_instance_consumer_groups: bool = False
    owner_id_is_replica_unique: bool = False
    global_pipeline: PipelineOptions = field(default_factory=PipelineOptions)
    max_pending_publications: int = 1024

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_concurrency, bool)
            or not isinstance(self.max_concurrency, int)
            or self.max_concurrency <= 0
        ):
            raise StreamConfigurationError("max_concurrency must be positive")
        if (
            isinstance(self.poll_interval, bool)
            or not isinstance(self.poll_interval, (int, float))
            or not math.isfinite(self.poll_interval)
            or self.poll_interval <= 0
        ):
            raise StreamConfigurationError("poll_interval must be positive")
        if not isinstance(self.owner_id, str) or not self.owner_id:
            raise StreamConfigurationError("owner_id must be non-empty")
        if not isinstance(self.single_instance_consumer_groups, bool):
            raise StreamConfigurationError(
                "single_instance_consumer_groups must be a boolean"
            )
        if not isinstance(self.owner_id_is_replica_unique, bool):
            raise StreamConfigurationError(
                "owner_id_is_replica_unique must be a boolean"
            )
        if (
            isinstance(self.max_pending_publications, bool)
            or not isinstance(self.max_pending_publications, int)
            or self.max_pending_publications <= 0
        ):
            raise StreamConfigurationError("max_pending_publications must be positive")


@dataclass(frozen=True, slots=True)
class PersistentStreamsOptions:
    """Static application inventory plus bounded runtime settings."""

    bindings: tuple[StreamBinding, ...]
    publishers: tuple[PublisherRegistration, ...] = ()
    runtime: PersistentStreamsRuntimeOptions = field(
        default_factory=PersistentStreamsRuntimeOptions
    )

    def __post_init__(self) -> None:
        bindings, publishers = validate_stream_inventory(self.bindings, self.publishers)
        if not isinstance(self.runtime, PersistentStreamsRuntimeOptions):
            raise StreamConfigurationError(
                "runtime must be PersistentStreamsRuntimeOptions"
            )
        if any(
            len(self.runtime.owner_id) > binding.definition.limits.max_owner_chars
            for binding in bindings
        ):
            raise StreamConfigurationError("owner_id exceeds a binding limit")
        if any(
            isinstance(binding.checkpoint_strategy, ExternalCheckpointStrategy)
            for binding in bindings
        ) and not (
            self.runtime.single_instance_consumer_groups
            or self.runtime.owner_id_is_replica_unique
        ):
            raise StreamConfigurationError(
                "external checkpoints require a replica-unique owner_id declaration"
            )
        object.__setattr__(self, "bindings", bindings)
        object.__setattr__(self, "publishers", publishers)


def validate_stream_inventory(
    bindings: Iterable[StreamBinding],
    publishers: Iterable[PublisherRegistration],
) -> tuple[tuple[StreamBinding, ...], tuple[PublisherRegistration, ...]]:
    """Validate static provider-generating inventory without runtime values."""

    bindings = tuple(bindings)
    publishers = tuple(publishers)
    if not bindings:
        raise StreamConfigurationError("at least one stream binding is required")
    if any(not isinstance(binding, StreamBinding) for binding in bindings):
        raise StreamConfigurationError("bindings must contain StreamBinding values")
    if any(
        not isinstance(publisher, PublisherRegistration) for publisher in publishers
    ):
        raise StreamConfigurationError(
            "publishers must contain PublisherRegistration values"
        )
    aliases = [binding.alias for binding in bindings]
    if len(set(aliases)) != len(aliases):
        raise StreamConfigurationError("stream binding aliases must be unique")
    names = [publisher.name for publisher in publishers if publisher.name is not None]
    protocols = [
        publisher.protocol for publisher in publishers if publisher.protocol is not None
    ]
    if len(set(names)) != len(names) or len(set(protocols)) != len(protocols):
        raise StreamConfigurationError("publisher tokens must be unique")
    if set(names) & set(aliases):
        raise StreamConfigurationError(
            "publisher names must not collide with stream binding aliases"
        )
    if any(publisher.stream not in aliases for publisher in publishers):
        raise StreamConfigurationError("publisher references an unknown stream")
    return bindings, publishers


__all__ = [
    "PersistentStreamsOptions",
    "PersistentStreamsRuntimeOptions",
    "PublisherRegistration",
    "StreamBinding",
]

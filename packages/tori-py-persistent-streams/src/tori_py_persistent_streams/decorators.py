"""Persistent-stream-only metadata and parameter markers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tori_py import Inject, MetadataKey, Reflector, metadata

from tori_py_persistent_streams.errors import StreamConfigurationError


def validate_alias(value: str, field: str = "stream alias") -> str:
    if not isinstance(value, str) or not value:
        raise StreamConfigurationError(f"{field} must be a non-empty string")
    if len(value) > 63 or not value[0].islower() or not value[0].isascii():
        raise StreamConfigurationError(f"{field} is invalid")
    if any(
        not (
            character.islower()
            and character.isascii()
            or character.isdigit()
            or character in "_-"
        )
        for character in value
    ):
        raise StreamConfigurationError(f"{field} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class StreamHandlerMetadata:
    stream: str
    consumer_group: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream", validate_alias(self.stream))
        object.__setattr__(
            self,
            "consumer_group",
            validate_alias(self.consumer_group, "consumer group"),
        )


@dataclass(frozen=True, slots=True)
class StreamPublishMetadata:
    payload: type[object]

    def __post_init__(self) -> None:
        if not isinstance(self.payload, type):
            raise StreamConfigurationError("publisher payload must be a type")


@dataclass(frozen=True, slots=True)
class StreamPayload:
    """Bind the decoded typed stream payload."""


@dataclass(frozen=True, slots=True)
class StreamRecordContext:
    """Bind the transport-neutral stream context."""


@dataclass(frozen=True, slots=True)
class StreamHeaders:
    """Bind the immutable safe record headers."""


@dataclass(frozen=True, slots=True)
class StreamHeader:
    """Bind one immutable safe record header."""

    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise StreamConfigurationError("stream header name must be non-empty")


@dataclass(frozen=True, slots=True)
class StreamPartition:
    """Bind the physical partition number."""


@dataclass(frozen=True, slots=True)
class StreamOffset:
    """Bind the physical record offset."""


class StreamInject(Inject):
    """Bind a normal ToriPy provider from the handler work scope."""


_HANDLER_KEY: MetadataKey[StreamHandlerMetadata] = MetadataKey(
    "tori_py.tori_py_persistent_streams_core.handler"
)
_PUBLISH_KEY: MetadataKey[StreamPublishMetadata] = MetadataKey(
    "tori_py.tori_py_persistent_streams_core.publish"
)


def stream_handler(*, stream: str, consumer_group: str) -> Any:
    """Mark one direct async controller method as a stream handler."""

    return metadata(_HANDLER_KEY, StreamHandlerMetadata(stream, consumer_group))


def stream_publish(*, payload: type[object]) -> Any:
    """Mark one Protocol method as a configured publication operation."""

    return metadata(_PUBLISH_KEY, StreamPublishMetadata(payload))


def get_stream_handler_metadata(target: object) -> StreamHandlerMetadata | None:
    return Reflector().get_own(_HANDLER_KEY, target)


def get_stream_publish_metadata(target: object) -> StreamPublishMetadata | None:
    return Reflector().get_own(_PUBLISH_KEY, target)


__all__ = [
    "StreamHandlerMetadata",
    "StreamHeader",
    "StreamHeaders",
    "StreamInject",
    "StreamOffset",
    "StreamPartition",
    "StreamPayload",
    "StreamPublishMetadata",
    "StreamRecordContext",
    "get_stream_handler_metadata",
    "get_stream_publish_metadata",
    "stream_handler",
    "stream_publish",
]

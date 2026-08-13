"""Three publisher surfaces over one managed stream runtime."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import cast
from uuid import UUID

from tori_py_persistent_streams_core import PublishReceipt

from tori_py_persistent_streams.compiler import validate_publisher_protocol
from tori_py_persistent_streams.contracts import StreamPublisher
from tori_py_persistent_streams.errors import StreamConfigurationError


def stream_publisher_token(name: str) -> str:
    """Return the deterministic token for one named configured publisher."""

    if not isinstance(name, str) or not name:
        raise StreamConfigurationError("publisher name must be non-empty")
    return f"tori-py-persistent-streams:publisher:{name}"


class BoundStreamPublisher:
    """Narrow publisher whose stream and payload contract are fixed."""

    def __init__(self, runtime: object, stream: str) -> None:
        self._runtime = runtime
        self._stream = stream

    async def publish(
        self,
        payload: object,
        *,
        record_id: UUID | None = None,
        headers: Mapping[str, bytes] | None = None,
    ) -> PublishReceipt:
        runtime = cast(StreamPublisher, self._runtime)
        return await runtime.publish(
            self._stream,
            payload,
            record_id=record_id,
            headers=headers,
        )


class ProtocolStreamPublisher:
    """Dynamic Protocol proxy using normal Python signature binding."""

    def __init__(
        self,
        protocol: type[object],
        publisher: BoundStreamPublisher,
        payload_type: type[object],
    ) -> None:
        methods = validate_publisher_protocol(protocol, payload_type)
        self._publisher = publisher
        self._methods = {
            name: inspect.signature(protocol.__dict__[name]) for name in methods
        }

    def __getattr__(self, name: str):
        try:
            signature = self._methods[name]
        except KeyError as error:
            raise AttributeError(name) from error

        async def invoke(*args: object, **kwargs: object) -> PublishReceipt:
            bound = signature.bind(None, *args, **kwargs)
            values = list(bound.arguments.values())[1:]
            payload = values[0]
            return await self._publisher.publish(
                payload,
                record_id=bound.arguments.get("record_id"),
                headers=bound.arguments.get("headers"),
            )

        return invoke


__all__ = [
    "BoundStreamPublisher",
    "ProtocolStreamPublisher",
    "stream_publisher_token",
]

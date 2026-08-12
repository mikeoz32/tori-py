from __future__ import annotations

import asyncio
import inspect
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Self, TypedDict, cast

import rstream
from rstream import SlasMechanism, schema
from rstream.client import Client
from rstream.constants import Key, T

_RSTREAM_VERSION = "1.0.1"
_STREAM_STATS_KEY_VALUE = 0x1C
_EXPECTED_KEY_VALUES = (*range(1, 28), 29, 30, 32794)


def _require_pinned_api() -> None:
    if rstream.__version__ != _RSTREAM_VERSION:
        raise RuntimeError(
            "rstream compatibility requires "
            f"{_RSTREAM_VERSION}, got {rstream.__version__}"
        )
    if tuple(member.value for member in Key) != _EXPECTED_KEY_VALUES:
        raise RuntimeError("rstream command keys changed; audit the StreamStats bridge")
    if _STREAM_STATS_KEY_VALUE in Key._value2member_map_:
        raise RuntimeError(
            "rstream now defines StreamStats; remove and re-audit this bridge"
        )
    if str(inspect.signature(Client.sync_request)) != (
        "(self, frame: 'schema.Frame', resp_schema: 'Type[FT]', "
        "raise_exception=True) -> 'FT'"
    ):
        raise RuntimeError("rstream Client.sync_request changed; audit the bridge")
    if str(inspect.signature(Client.query_publisher_sequence)) != (
        "(self, stream: 'str', reference: 'str') -> 'int'"
    ):
        raise RuntimeError("rstream publisher-sequence API changed; audit the bridge")


def _missing_key(value: int, name: str) -> Key:
    # rstream's decoder resolves every frame through Key(value). The pinned release
    # omitted only 0x1c, so install that protocol member before registering schemas.
    member = object.__new__(Key)
    object.__setattr__(member, "_name_", name)
    object.__setattr__(member, "_value_", value)
    Key._value2member_map_[value] = member
    return cast(Key, member)


_require_pinned_api()
_STREAM_STATS_KEY = _missing_key(_STREAM_STATS_KEY_VALUE, "StreamStatsCompatibility")


@dataclass
class _Statistic(schema.Struct):
    key: str = field(metadata={"type": T.string})
    value: int = field(metadata={"type": T.int64})


@dataclass
class _StreamStats(schema.Frame):
    key = _STREAM_STATS_KEY
    correlation_id: int = field(metadata={"type": T.uint32})
    stream: str = field(metadata={"type": T.string})


@dataclass
class _StreamStatsResponse(schema.Frame, is_response=True):
    key = _STREAM_STATS_KEY
    correlation_id: int = field(metadata={"type": T.uint32})
    response_code: int = field(metadata={"type": T.uint16})
    stats: list[_Statistic] = field(metadata={"type": [_Statistic]})


for _struct in (_Statistic, _StreamStats, _StreamStatsResponse):
    _struct.prepare()


class MetadataClient:
    """Dedicated, serialized low-level connection for pinned metadata queries."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        username: str,
        password: str,
        vhost: str = "/",
        ssl_context: ssl.SSLContext | None = None,
        heartbeat: int = 60,
        sasl_configuration_mechanism: SlasMechanism = SlasMechanism.MechanismPlain,
        on_close_handler: Callable[[object], None] | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self._vhost = vhost
        self._client = Client(
            host,
            port,
            frame_max=1024 * 1024,
            heartbeat=heartbeat,
            connection_name="persistent-streams-metadata",
            ssl_context=ssl_context,
            sasl_configuration_mechanism=sasl_configuration_mechanism,
            connection_closed_handler=on_close_handler,
        )
        self._correlation_id = 0x4000_0000
        self._request_lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def start(self) -> None:
        await self._client.start()
        try:
            await self._client.authenticate(self._vhost, self._username, self._password)
        except BaseException:
            await self._client.close()
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        await self.close()

    async def close(self) -> None:
        await self._client.close()

    async def query_publisher_sequence(self, stream: str, reference: str) -> int:
        async with self._request_lock:
            return await self._client.query_publisher_sequence(stream, reference)

    async def stream_stats(self, stream: str) -> dict[str, int]:
        async with self._request_lock:
            correlation_id = self._correlation_id
            self._correlation_id += 1
            response = await self._client.sync_request(
                _StreamStats(correlation_id=correlation_id, stream=stream),
                resp_schema=_StreamStatsResponse,
            )
            typed_response = cast(Any, response)
            return {stat.key: stat.value for stat in typed_response.stats}


class CompatibilityFacts(TypedDict):
    rstream_version: str
    stream_stats_key: int
    sync_request_signature: str
    query_publisher_sequence_signature: str
    schema_registry_entries: tuple[type[schema.Frame], type[schema.Frame]]


def compatibility_facts() -> CompatibilityFacts:
    return {
        "rstream_version": rstream.__version__,
        "stream_stats_key": _STREAM_STATS_KEY.value,
        "sync_request_signature": str(inspect.signature(Client.sync_request)),
        "query_publisher_sequence_signature": str(
            inspect.signature(Client.query_publisher_sequence)
        ),
        "schema_registry_entries": (
            schema.registry[(False, _STREAM_STATS_KEY)],
            schema.registry[(True, _STREAM_STATS_KEY)],
        ),
    }

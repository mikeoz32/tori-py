"""Immutable execution context for one persistent stream record."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from uuid import UUID

from tori_py import ModuleId, ScopedResolver


@dataclass(frozen=True, slots=True)
class StreamContext:
    application: str
    module_identity: ModuleId
    handler_id: str
    stream: str
    consumer_group: str
    partition: int
    offset: int
    timestamp: datetime
    record_id: UUID
    headers: Mapping[str, bytes]
    scope_resolver: ScopedResolver
    native_value: object | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))

    @property
    def application_id(self) -> str:
        return self.application

    @property
    def module_id(self) -> str:
        label = self.module_identity.module.__qualname__
        return (
            label
            if self.module_identity.key is None
            else f"{label}[{self.module_identity.key}]"
        )

    @property
    def route_id(self) -> str:
        return self.handler_id

    @property
    def request_id(self) -> str:
        return str(self.record_id)

    @property
    def resolver(self) -> ScopedResolver:
        return self.scope_resolver

    @property
    def metadata(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "stream": self.stream,
                "consumer_group": self.consumer_group,
                "partition": self.partition,
                "offset": self.offset,
            }
        )

    @property
    def execution_kind(self) -> str:
        return "stream"

    def unwrap[NativeT](
        self, expected: type[NativeT] | None = None
    ) -> NativeT | object | None:
        if expected is not None and not isinstance(self.native_value, expected):
            raise TypeError("native stream context has an unexpected type")
        return self.native_value


__all__ = ["StreamContext"]

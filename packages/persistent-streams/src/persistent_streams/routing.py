from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, runtime_checkable

from persistent_streams.errors import ValidationError


@runtime_checkable
class PartitionRouter(Protocol):
    @property
    def identity(self) -> str: ...

    @property
    def compatibility_key(self) -> Hashable: ...

    def route(self, partition_key: bytes, partition_count: int) -> int: ...


@dataclass(frozen=True, slots=True)
class Sha256PartitionRouter:
    identity: str = "sha256-v1"

    @property
    def compatibility_key(self) -> tuple[str]:
        return ("sha256-v1",)

    def route(self, partition_key: bytes, partition_count: int) -> int:
        if not partition_key:
            raise ValidationError("partition_key must not be empty")
        if (
            isinstance(partition_count, bool)
            or not isinstance(partition_count, int)
            or partition_count <= 0
        ):
            raise ValidationError("partition_count must be a positive integer")
        return int.from_bytes(sha256(partition_key).digest(), "big") % partition_count


DEFAULT_PARTITION_ROUTER = Sha256PartitionRouter()

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from tori_py_persistent_streams_core.errors import (
    AdapterContractError,
    CheckpointError,
    CheckpointPersistenceError,
    OwnershipError,
    ValidationError,
)
from tori_py_persistent_streams_core.models import (
    CheckpointKey,
    CursorKind,
    OwnershipToken,
    ResumeCursor,
)


@runtime_checkable
class CheckpointStore(Protocol):
    """Shared store with atomic owner replacement and exact-owner writes.

    ``fence`` must atomically replace the current owner for ``key``. Subsequent
    compare/create and save calls must accept only that exact owner token.
    """

    async def fence(self, key: CheckpointKey, owner: OwnershipToken) -> None: ...

    async def load(self, key: CheckpointKey) -> ResumeCursor | None: ...

    async def compare_and_create(
        self,
        key: CheckpointKey,
        cursor: ResumeCursor,
        owner: OwnershipToken,
    ) -> ResumeCursor: ...

    async def save(
        self,
        key: CheckpointKey,
        expected: ResumeCursor,
        cursor: ResumeCursor,
        owner: OwnershipToken,
    ) -> None: ...


class CheckpointStrategy(Enum):
    BROKER_MANAGED = "broker_managed"


@dataclass(frozen=True, slots=True)
class ExternalCheckpointStrategy:
    identity: str
    store: CheckpointStore

    def __post_init__(self) -> None:
        if not isinstance(self.identity, str) or not self.identity:
            raise ValidationError("external checkpoint identity must be non-empty")
        if len(self.identity) > 256:
            raise ValidationError(
                "external checkpoint identity must not exceed 256 characters"
            )
        if not isinstance(self.store, CheckpointStore):
            raise TypeError("store must implement CheckpointStore")


class InMemoryCheckpointStore:
    """Fenced, process-local checkpoint store for tests and examples."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._cursors: dict[CheckpointKey, ResumeCursor] = {}
        self._owners: dict[CheckpointKey, OwnershipToken] = {}

    async def fence(self, key: CheckpointKey, owner: OwnershipToken) -> None:
        async with self._lock:
            self._owners[key] = owner

    async def load(self, key: CheckpointKey) -> ResumeCursor | None:
        async with self._lock:
            return self._cursors.get(key)

    async def compare_and_create(
        self,
        key: CheckpointKey,
        cursor: ResumeCursor,
        owner: OwnershipToken,
    ) -> ResumeCursor:
        if (
            not isinstance(cursor, ResumeCursor)
            or cursor.kind is not CursorKind.INITIALIZED
        ):
            raise CheckpointError("initial checkpoint must be an initialized cursor")
        async with self._lock:
            self._require_owner(key, owner)
            return self._cursors.setdefault(key, cursor)

    async def save(
        self,
        key: CheckpointKey,
        expected: ResumeCursor,
        cursor: ResumeCursor,
        owner: OwnershipToken,
    ) -> None:
        if not isinstance(expected, ResumeCursor) or not isinstance(
            cursor, ResumeCursor
        ):
            raise CheckpointError("checkpoint values must be ResumeCursor instances")
        async with self._lock:
            self._require_owner(key, owner)
            current = self._cursors.get(key)
            if current != expected:
                raise CheckpointError("checkpoint changed concurrently")
            if cursor.kind is not CursorKind.LAST_SUCCESSFUL:
                raise CheckpointError("saved checkpoint must be last-successful")
            if (
                expected.kind is CursorKind.LAST_SUCCESSFUL
                and cursor.offset <= expected.offset
            ):
                raise CheckpointError("checkpoint must advance")
            if (
                expected.kind is CursorKind.INITIALIZED
                and cursor.offset < expected.offset
            ):
                raise CheckpointError("checkpoint precedes initialized start")
            self._cursors[key] = cursor

    def _require_owner(self, key: CheckpointKey, owner: OwnershipToken) -> None:
        if self._owners.get(key) != owner:
            raise OwnershipError("checkpoint owner is not current")


async def validate_checkpoint_store_call(
    operation: Awaitable[object],
    *,
    cursor: ResumeCursor | None,
    returns: str,
) -> ResumeCursor | None:
    """Call an external store and normalize malformed results and failures."""
    try:
        result = await operation
        if returns == "none":
            if result is not None:
                raise AdapterContractError("checkpoint store call must return None")
            return None
        if returns == "cursor":
            if not isinstance(result, ResumeCursor):
                raise AdapterContractError(
                    "checkpoint store call must return ResumeCursor"
                )
            return result
        if returns == "optional_cursor":
            if result is not None and not isinstance(result, ResumeCursor):
                raise AdapterContractError(
                    "checkpoint store call must return ResumeCursor or None"
                )
            return result
        raise ValueError(f"unsupported checkpoint return contract: {returns}")
    except asyncio.CancelledError:
        raise
    except Exception as error:
        raise CheckpointPersistenceError(cursor, error) from error

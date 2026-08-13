from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import MappingProxyType
from typing import Any, cast
from uuid import uuid4

import pytest
from tori_py_persistent_streams_core import (
    AppendRequest,
    ExactOffset,
    ExternalCheckpointStrategy,
    InMemoryCheckpointStore,
    RelativeTime,
    ResumeCursor,
    Sha256PartitionRouter,
    StreamDefinition,
    Timestamp,
    ValidationError,
)


def test_append_request_copies_bytes_and_headers() -> None:
    key = bytearray(b"key")
    payload = bytearray(b"payload")
    headers = {"trace": bytearray(b"one")}
    request = AppendRequest(uuid4(), key, payload, headers)
    key[:] = b"bad"
    payload[:] = b"changed"
    headers["trace"] = bytearray(b"two")

    assert request.partition_key == b"key"
    assert request.payload == b"payload"
    assert request.headers == {"trace": b"one"}
    assert isinstance(request.headers, MappingProxyType)
    with pytest.raises(TypeError):
        request.headers["other"] = b"value"  # type: ignore[index]


def test_router_uses_complete_sha256_digest() -> None:
    key = b"stable-member-key"
    expected = int.from_bytes(sha256(key).digest(), "big") % 17
    assert Sha256PartitionRouter().route(key, 17) == expected
    assert StreamDefinition("events", 17).router.identity == "sha256-v1"


class _MutableRouter:
    identity = "mutable-v1"

    def __init__(self, partition: int) -> None:
        self.partition = partition

    @property
    def compatibility_key(self) -> tuple[str, int]:
        return (self.identity, self.partition)

    def route(self, partition_key: bytes, partition_count: int) -> int:
        return self.partition % partition_count


class _NonCopyableRouter(_MutableRouter):
    def __deepcopy__(self, memo):
        raise TypeError("cannot copy")


def test_stream_definition_snapshots_configured_router() -> None:
    router = _MutableRouter(1)
    definition = StreamDefinition("events", 3, router=router)

    router.partition = 2

    assert definition.router is not router
    assert definition.router.route(b"key", 3) == 1
    assert definition.compatibility_key[-1] == ("mutable-v1", 1)


def test_stream_definition_rejects_non_copyable_router() -> None:
    with pytest.raises(ValidationError, match="copyable"):
        StreamDefinition("events", 1, router=_NonCopyableRouter(0))


@pytest.mark.parametrize("identity", ["", 1])
def test_external_checkpoint_identity_is_validated(identity) -> None:
    with pytest.raises(ValidationError):
        ExternalCheckpointStrategy(identity, InMemoryCheckpointStore())


@pytest.mark.parametrize(
    "factory",
    [
        lambda: AppendRequest(uuid4(), b""),
        lambda: AppendRequest(cast(Any, "not-uuid"), b"key"),
        lambda: AppendRequest(uuid4(), b"key", producer_name="producer"),
        lambda: ExactOffset(True),
        lambda: Timestamp(datetime.now()),
        lambda: RelativeTime(timedelta(seconds=-1)),
    ],
)
def test_invalid_values_are_rejected(factory) -> None:
    with pytest.raises(ValidationError):
        factory()


def test_resume_cursor_variants_are_distinct() -> None:
    assert ResumeCursor.initialized(4) != ResumeCursor.last_successful(4)
    Timestamp(datetime.now(UTC))

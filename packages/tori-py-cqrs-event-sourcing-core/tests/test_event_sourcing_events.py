from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, cast
from uuid import uuid4

import pytest
from tori_py_cqrs_core import Event
from tori_py_cqrs_event_sourcing_core import (
    EventMetadata,
    InvalidEventMetadataError,
    InvalidEventRecordError,
    InvalidStreamIdError,
    PendingEvent,
    RecordedEvent,
    StreamId,
)


@dataclass(frozen=True, slots=True)
class Happened(Event):
    value: int


def test_stream_id_requires_stable_non_empty_parts() -> None:
    assert StreamId("profile", "42") == StreamId(category="profile", key="42")
    for value in ("", " profile", "profile ", "profile\n"):
        with pytest.raises(InvalidStreamIdError):
            StreamId(cast(Any, value), "42")


def test_metadata_copies_headers_and_validates_occurrence_values() -> None:
    source = {"tenant": "one"}
    occurrence = EventMetadata(
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
        headers=source,
    )
    source["tenant"] = "changed"

    assert occurrence.headers == {"tenant": "one"}
    assert isinstance(occurrence.headers, MappingProxyType)
    with pytest.raises(TypeError):
        occurrence.headers["tenant"] = "blocked"  # type: ignore[index]

    with pytest.raises(InvalidEventMetadataError, match="timezone-aware"):
        EventMetadata(event_id=uuid4(), occurred_at=datetime.now())
    with pytest.raises(InvalidEventMetadataError, match="UUID"):
        EventMetadata(
            event_id=cast(Any, "invalid"),
            occurred_at=datetime.now(UTC),
        )
    with pytest.raises(InvalidEventMetadataError, match="string keys"):
        EventMetadata(
            event_id=uuid4(),
            occurred_at=datetime.now(UTC),
            headers=cast(Any, {1: "invalid"}),
        )
    with pytest.raises(InvalidEventMetadataError, match="UTF-8"):
        EventMetadata(
            event_id=uuid4(),
            occurred_at=datetime.now(UTC),
            headers={"invalid": "\ud800"},
        )


def test_pending_and_recorded_events_validate_concrete_event_and_versions() -> None:
    occurrence = EventMetadata(event_id=uuid4(), occurred_at=datetime.now(UTC))
    event = Happened(1)
    pending = PendingEvent(event, occurrence)
    record = RecordedEvent(
        stream_id=StreamId("profile", "42"),
        stream_version=1,
        global_position=1,
        event_type="profile.happened",
        schema_version=1,
        event=event,
        metadata=occurrence,
    )

    assert pending.event is event
    assert record.event is event
    with pytest.raises(InvalidEventRecordError, match="concrete Event"):
        PendingEvent(Event(), occurrence)
    with pytest.raises(InvalidEventRecordError, match="positive integer"):
        RecordedEvent(
            stream_id=StreamId("profile", "42"),
            stream_version=cast(Any, False),
            global_position=1,
            event_type="profile.happened",
            schema_version=1,
            event=event,
            metadata=occurrence,
        )

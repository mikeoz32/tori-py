from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from tori_py_cqrs_core import Event
from tori_py_cqrs_event_sourcing_core import (
    AppendEvent,
    DuplicateEventSchemaError,
    EncodedEvent,
    EventCodecError,
    EventMetadata,
    EventSchema,
    EventSchemaRegistry,
    EventSourcingLimits,
    PendingEvent,
    ResourceLimitError,
    SchemaRegistryFrozenError,
    SchemaRegistryNotFrozenError,
    SchemaValidationError,
    StoredEvent,
    StreamId,
    UnknownEventSchemaError,
    UnsupportedEventSchemaVersionError,
)


@dataclass(frozen=True, slots=True)
class Named(Event):
    name: str


@dataclass(frozen=True, slots=True)
class OtherNamed(Event):
    name: str


def named_schema(*, version: int = 1, upcasters=None) -> EventSchema[Named]:
    return EventSchema(
        alias="profile.named",
        version=version,
        event_type=Named,
        encoder=lambda event: event.name.encode(),
        decoder=lambda payload: Named(payload.decode()),
        upcasters={} if upcasters is None else upcasters,
    )


def pending(*, name: str = "Alice", headers=None) -> PendingEvent:
    return PendingEvent(
        Named(name),
        EventMetadata(
            event_id=uuid4(),
            occurred_at=datetime.now(UTC),
            headers={} if headers is None else headers,
        ),
    )


def stored(
    append: AppendEvent,
    *,
    version: int = 1,
    event_type: str | None = None,
    schema_version: int | None = None,
) -> StoredEvent:
    encoded = append.encoded
    return StoredEvent(
        StreamId("profile", "42"),
        stream_version=version,
        global_position=version,
        event=AppendEvent(
            EncodedEvent(
                event_type or encoded.event_type,
                schema_version or encoded.schema_version,
                encoded.payload,
            ),
            append.metadata,
        ),
    )


def test_registry_requires_freeze_and_round_trips_occurrence_metadata() -> None:
    registry = EventSchemaRegistry().register(named_schema())
    occurrence = pending()

    with pytest.raises(SchemaRegistryNotFrozenError):
        registry.encode(occurrence)

    registry.freeze()
    append = registry.encode(occurrence)
    decoded = registry.decode(stored(append))

    assert append.metadata is occurrence.metadata
    assert append.encoded == EncodedEvent("profile.named", 1, b"Alice")
    assert decoded.event == Named("Alice")
    assert decoded.metadata is occurrence.metadata
    with pytest.raises(SchemaRegistryFrozenError):
        registry.register(
            EventSchema(
                "profile.other-named",
                1,
                OtherNamed,
                lambda event: event.name.encode(),
                lambda payload: OtherNamed(payload.decode()),
            )
        )


def test_duplicate_alias_and_event_class_are_rejected() -> None:
    registry = EventSchemaRegistry().register(named_schema())
    with pytest.raises(DuplicateEventSchemaError, match="alias"):
        registry.register(named_schema())
    with pytest.raises(DuplicateEventSchemaError, match="event class"):
        registry.register(
            EventSchema(
                "profile.renamed-alias",
                1,
                Named,
                lambda event: event.name.encode(),
                lambda payload: Named(payload.decode()),
            )
        )


def test_schema_requires_complete_one_version_upcast_chain() -> None:
    with pytest.raises(SchemaValidationError, match="source versions"):
        named_schema(version=3, upcasters={1: lambda payload: payload})

    registry = (
        EventSchemaRegistry()
        .register(
            named_schema(
                version=3,
                upcasters={
                    1: lambda payload: payload + b"-v2",
                    2: lambda payload: payload + b"-v3",
                },
            )
        )
        .freeze()
    )
    occurrence = pending()
    historical = StoredEvent(
        StreamId("profile", "42"),
        stream_version=1,
        global_position=1,
        event=AppendEvent(
            EncodedEvent("profile.named", 1, b"Alice"),
            occurrence.metadata,
        ),
    )

    decoded = registry.decode(historical)

    assert decoded.event == Named("Alice-v2-v3")
    assert decoded.schema_version == 3

    with pytest.raises(SchemaValidationError, match="source versions"):
        named_schema(version=1_000_000_000)
    limited = EventSchemaRegistry(limits=EventSourcingLimits(max_upcast_steps=1))
    with pytest.raises(ResourceLimitError, match="upcast step"):
        limited.register(
            named_schema(
                version=3,
                upcasters={1: lambda value: value, 2: lambda value: value},
            )
        )


def test_unknown_and_future_schemas_fail_without_dynamic_imports() -> None:
    registry = EventSchemaRegistry().register(named_schema()).freeze()
    append = registry.encode(pending())

    with pytest.raises(UnknownEventSchemaError):
        registry.decode(stored(append, event_type="renamed.python.Class"))
    with pytest.raises(UnsupportedEventSchemaVersionError):
        registry.decode(stored(append, schema_version=2))


def test_codec_type_and_resource_limits_are_enforced() -> None:
    limits = EventSourcingLimits(
        max_payload_bytes=4,
        max_headers=1,
        max_header_name_bytes=4,
        max_header_value_bytes=4,
    )
    registry = EventSchemaRegistry(limits=limits).register(named_schema()).freeze()

    with pytest.raises(ResourceLimitError, match="payload"):
        registry.encode(pending(name="Alice"))
    with pytest.raises(ResourceLimitError, match="count"):
        registry.encode(pending(name="A", headers={"one": "1", "two": "2"}))
    with pytest.raises(ResourceLimitError, match="name"):
        registry.encode(pending(name="A", headers={"long-name": "1"}))
    with pytest.raises(ResourceLimitError, match="value"):
        registry.encode(pending(name="A", headers={"name": "long-value"}))


def test_codec_rejects_non_bytes_and_wrong_decoded_event_class() -> None:
    invalid_encoder = EventSchema(
        "profile.named",
        1,
        Named,
        cast(Any, lambda event: event.name),
        lambda payload: Named(payload.decode()),
    )
    registry = EventSchemaRegistry().register(invalid_encoder).freeze()
    with pytest.raises(EventCodecError, match="bytes"):
        registry.encode(pending())

    wrong_decoder = EventSchema(
        "profile.named",
        1,
        Named,
        lambda event: event.name.encode(),
        cast(Any, lambda payload: OtherNamed(payload.decode())),
    )
    registry = EventSchemaRegistry().register(wrong_decoder).freeze()
    with pytest.raises(EventCodecError, match="expected Named"):
        registry.decode(stored(registry.encode(pending())))

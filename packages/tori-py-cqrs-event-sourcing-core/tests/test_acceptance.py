from dataclasses import dataclass
from uuid import UUID

import pytest
from tori_py_cqrs_core import Event
from tori_py_cqrs_event_sourcing_core import (
    AggregateRoot,
    EventSchema,
    EventSchemaRegistry,
    EventSourcedRepository,
    EventSourcingUnitOfWork,
    InMemoryEventStore,
)


@dataclass(frozen=True, slots=True)
class ProfileOpened(Event):
    display_name: str


@dataclass(frozen=True, slots=True)
class DisplayNameChanged(Event):
    display_name: str


class Profile(AggregateRoot[UUID]):
    def __init__(self, profile_id: UUID) -> None:
        super().__init__(profile_id)
        self.display_name = ""

    def open(self, display_name: str) -> None:
        self.raise_event(ProfileOpened(display_name))

    def change_display_name(self, display_name: str) -> None:
        if not display_name.strip():
            raise ValueError("display name cannot be empty")
        self.raise_event(DisplayNameChanged(display_name.strip()))

    def _apply(self, event: Event) -> None:
        match event:
            case (
                ProfileOpened(display_name=name) | DisplayNameChanged(display_name=name)
            ):
                self.display_name = name
            case _:
                raise AssertionError(f"unknown event: {event!r}")


def schemas() -> EventSchemaRegistry:
    return (
        EventSchemaRegistry()
        .register(
            EventSchema(
                "profile.opened",
                1,
                ProfileOpened,
                lambda event: event.display_name.encode(),
                lambda payload: ProfileOpened(payload.decode()),
            )
        )
        .register(
            EventSchema(
                "profile.display-name-changed",
                1,
                DisplayNameChanged,
                lambda event: event.display_name.encode(),
                lambda payload: DisplayNameChanged(payload.decode()),
            )
        )
        .freeze()
    )


def repository(unit_of_work, registry):
    return EventSourcedRepository(
        unit_of_work,
        category="profile",
        aggregate_factory=Profile,
        aggregate_type=Profile,
        id_encoder=str,
        schemas=registry,
    )


@pytest.mark.asyncio
async def test_profile_state_is_rebuilt_exclusively_from_committed_events() -> None:
    store = InMemoryEventStore()
    registry = schemas()
    profile_id = UUID(int=42)

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        profile = Profile(profile_id)
        profile.open("Alice")
        repository(unit_of_work, registry).save(profile)
        await unit_of_work.commit()

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        profile = await repository(unit_of_work, registry).get(profile_id)
        profile.change_display_name("  Alicia  ")
        repository(unit_of_work, registry).save(profile)
        await unit_of_work.commit()

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        rebuilt = await repository(unit_of_work, registry).get(profile_id)

    committed = await store.read_all(limit=10)
    assert rebuilt.display_name == "Alicia"
    assert rebuilt.version == 2
    assert rebuilt.pending_events == ()
    assert [event.event.encoded.event_type for event in committed] == [
        "profile.opened",
        "profile.display-name-changed",
    ]
    assert [event.global_position for event in committed] == [1, 2]

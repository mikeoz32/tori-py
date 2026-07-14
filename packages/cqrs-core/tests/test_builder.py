from dataclasses import dataclass
from typing import cast

import pytest
from cqrs_core import (
    Command,
    CommandHandler,
    CqrsBuilder,
    CqrsValidationError,
    Event,
    EventsHandler,
    InvalidHandlerRegistrationError,
    Message,
    Query,
    QueryHandler,
)


@dataclass(frozen=True, slots=True)
class CreateProfile(Command[int]):
    username: str


@dataclass(frozen=True, slots=True)
class GetProfile(Query[str]):
    profile_id: int


@dataclass(frozen=True, slots=True)
class ProfileCreated(Event):
    profile_id: int


class NoopTransport:
    def __init__(self) -> None:
        self.started = False

    async def start(self, consumer) -> None:
        del consumer
        self.started = True

    async def request(self, envelope, *, timeout=None):
        del envelope, timeout
        raise AssertionError("not used")

    async def publish(self, envelope, *, timeout=None):
        del envelope, timeout
        raise AssertionError("not used")

    async def shutdown(self, *, timeout=None) -> None:
        del timeout


@CommandHandler(CreateProfile)
class CreateProfileHandler:
    async def handle(self, message: CreateProfile) -> int:
        return len(message.username)


@QueryHandler(GetProfile)
class GetProfileHandler:
    async def handle(self, message: GetProfile) -> str:
        return str(message.profile_id)


@EventsHandler(ProfileCreated)
class ProfileCreatedHandler:
    async def handle(self, message: ProfileCreated) -> None:
        return None


def configured_builder() -> CqrsBuilder:
    transport = NoopTransport()
    return (
        CqrsBuilder()
        .add_command_handler(CreateProfileHandler)
        .add_query_handler(GetProfileHandler)
        .add_event_handler(ProfileCreatedHandler)
        .with_command_transport(transport)
        .with_query_transport(NoopTransport())
        .with_event_transport(NoopTransport())
    )


def test_builder_requires_all_transports() -> None:
    with pytest.raises(CqrsValidationError, match="command transport"):
        CqrsBuilder().build()


def test_builder_builds_three_bus_facades() -> None:
    builder = configured_builder()
    buses = builder.build()

    assert buses.command_bus
    assert buses.query_bus
    assert buses.event_bus


def test_builder_requires_metadata_when_message_type_is_omitted() -> None:
    with pytest.raises(InvalidHandlerRegistrationError, match="metadata"):
        configured_builder().add_command_handler(object())


def test_builder_accepts_explicit_instance_registration() -> None:
    builder = (
        CqrsBuilder()
        .add_command_handler(CreateProfile, CreateProfileHandler())
        .add_query_handler(GetProfile, GetProfileHandler())
        .add_event_handler(ProfileCreated, ProfileCreatedHandler())
        .with_command_transport(NoopTransport())
        .with_query_transport(NoopTransport())
        .with_event_transport(NoopTransport())
    )

    buses = builder.build()

    assert buses.command_bus


def test_builder_accepts_factory_registration() -> None:
    def command_factory() -> CreateProfileHandler:
        return CreateProfileHandler()

    builder = (
        CqrsBuilder()
        .add_command_handler_factory(CreateProfile, command_factory)
        .with_command_transport(NoopTransport())
        .with_query_transport(NoopTransport())
        .with_event_transport(NoopTransport())
    )

    buses = builder.build()

    assert buses.command_bus


def test_builder_rejects_invalid_factory_message_type() -> None:
    with pytest.raises(InvalidHandlerRegistrationError, match="Message subclass"):
        CqrsBuilder().add_command_handler_factory(
            cast(type[Message], "not-a-message"),
            CreateProfileHandler,
        )


def test_builder_rejects_shared_transport_instances() -> None:
    transport = NoopTransport()
    builder = (
        CqrsBuilder()
        .with_command_transport(transport)
        .with_query_transport(transport)
        .with_event_transport(transport)
    )

    with pytest.raises(CqrsValidationError, match="distinct transport"):
        builder.build()

from dataclasses import dataclass

import pytest
from cqrs_core import (
    Command,
    CommandHandler,
    DuplicateCommandHandlerError,
    Event,
    EventsHandler,
    HandlerKind,
    InvalidHandlerRegistrationError,
    Query,
    QueryHandler,
    RegisteredHandler,
    TargetMode,
    get_handler_metadata,
    handles,
)
from cqrs_core.registrations import HandlerStyle
from cqrs_core.registry import HandlerRegistry


@dataclass(frozen=True, slots=True)
class CreateProfile(Command[int]):
    username: str


@dataclass(frozen=True, slots=True)
class GetProfile(Query[str]):
    profile_id: int


@dataclass(frozen=True, slots=True)
class ProfileCreated(Event):
    profile_id: int


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


@handles(GetProfile)
async def get_profile_function(message: GetProfile, context: object) -> str:
    del context
    return str(message.profile_id)


def test_decorators_attach_metadata_without_global_registration() -> None:
    command_metadata = get_handler_metadata(CreateProfileHandler)
    query_metadata = get_handler_metadata(get_profile_function)
    event_metadata = get_handler_metadata(ProfileCreatedHandler)

    assert command_metadata is not None
    assert command_metadata.kind is HandlerKind.COMMAND
    assert command_metadata.message_type is CreateProfile
    assert query_metadata is not None
    assert query_metadata.kind is HandlerKind.QUERY
    assert event_metadata is not None
    assert event_metadata.kind is HandlerKind.EVENT


def test_decorators_reject_wrong_message_category() -> None:
    with pytest.raises(InvalidHandlerRegistrationError, match="inherit"):

        @CommandHandler(GetProfile)
        class InvalidCommandHandler:
            async def handle(self, message: GetProfile) -> str:
                return str(message.profile_id)

    with pytest.raises(InvalidHandlerRegistrationError, match="concrete"):

        @CommandHandler(Command)
        class InvalidMarkerHandler:
            async def handle(self, message: Command[object]) -> object:
                return None


def test_class_and_function_decorators_enforce_their_roles() -> None:
    with pytest.raises(InvalidHandlerRegistrationError, match="requires a class"):

        @CommandHandler(CreateProfile)
        async def invalid_class_handler(message: CreateProfile) -> int:
            return len(message.username)

    with pytest.raises(InvalidHandlerRegistrationError, match="requires a function"):

        @handles(GetProfile)
        class InvalidFunctionHandler:
            async def handle(self, message: GetProfile) -> str:
                return str(message.profile_id)


def test_handler_metadata_is_not_inherited_implicitly() -> None:
    class InheritedHandler(CreateProfileHandler):
        pass

    assert get_handler_metadata(InheritedHandler) is None

    @CommandHandler(CreateProfile)
    class ExplicitHandler(InheritedHandler):
        pass

    metadata = get_handler_metadata(ExplicitHandler)
    assert metadata is not None
    assert metadata.message_type is CreateProfile


def test_registry_rejects_duplicate_command_handlers() -> None:
    registrations = [
        RegisteredHandler(
            kind=HandlerKind.COMMAND,
            message_type=CreateProfile,
            target=CreateProfileHandler,
            style=HandlerStyle.CLASS,
            target_mode=TargetMode.CLASS,
        ),
        RegisteredHandler(
            kind=HandlerKind.COMMAND,
            message_type=CreateProfile,
            target=CreateProfileHandler,
            style=HandlerStyle.CLASS,
            target_mode=TargetMode.CLASS,
        ),
    ]

    with pytest.raises(DuplicateCommandHandlerError):
        HandlerRegistry.build(registrations)


def test_registry_keeps_event_handlers_in_registration_order() -> None:
    first = RegisteredHandler(
        kind=HandlerKind.EVENT,
        message_type=ProfileCreated,
        target=ProfileCreatedHandler,
        style=HandlerStyle.CLASS,
        target_mode=TargetMode.CLASS,
    )
    second_target = ProfileCreatedHandler()
    second = RegisteredHandler(
        kind=HandlerKind.EVENT,
        message_type=ProfileCreated,
        target=second_target,
        style=HandlerStyle.CLASS,
        target_mode=TargetMode.INSTANCE,
    )

    registry = HandlerRegistry.build([first, second])

    assert registry.event_handlers(ProfileCreated) == (first, second)


def test_registry_rejects_sync_handler_targets() -> None:
    class SyncCommandHandler:
        def handle(self, message: CreateProfile) -> int:
            return len(message.username)

    sync_registration = RegisteredHandler(
        kind=HandlerKind.COMMAND,
        message_type=CreateProfile,
        target=SyncCommandHandler,
        style=HandlerStyle.CLASS,
        target_mode=TargetMode.CLASS,
    )

    with pytest.raises(InvalidHandlerRegistrationError, match="async handle"):
        HandlerRegistry.build([sync_registration])


def test_registry_rejects_function_with_wrong_signature() -> None:
    async def one_argument_handler(message: GetProfile) -> str:
        return str(message.profile_id)

    registration = RegisteredHandler(
        kind=HandlerKind.QUERY,
        message_type=GetProfile,
        target=one_argument_handler,
        style=HandlerStyle.FUNCTION,
        target_mode=TargetMode.FUNCTION,
    )

    with pytest.raises(InvalidHandlerRegistrationError, match="message, context"):
        HandlerRegistry.build([registration])

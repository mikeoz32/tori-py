import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cqrs_core import (
    Command,
    CommandHandler,
    DeliveryMetadata,
    DeliveryReceipt,
    Envelope,
    EnvelopeValidationError,
    Event,
    EventsHandler,
    HandlerContext,
    InvalidLifecycleTransitionError,
    MissingHandlerError,
    Query,
    QueryHandler,
    TransportNotStartedError,
    TransportStoppedError,
    handles,
    message_type_for,
)
from cqrs_core.builder import CqrsBuilder


@dataclass(frozen=True, slots=True)
class CreateProfile(Command[int]):
    username: str


@dataclass(frozen=True, slots=True)
class GetProfile(Query[str]):
    profile_id: int


@dataclass(frozen=True, slots=True)
class ProfileCreated(Event):
    profile_id: int


class DirectTransport:
    def __init__(self) -> None:
        self.consumer = None
        self.published: list[Envelope] = []
        self.started = False
        self.stopped = False

    async def start(self, consumer) -> None:
        self.consumer = consumer
        self.started = True

    async def request(self, envelope, *, timeout: float | None = None):
        del timeout
        assert self.consumer is not None
        reply = await self.consumer(envelope)
        assert reply is not None
        return reply

    async def publish(self, envelope, *, timeout: float | None = None):
        del timeout
        self.published.append(envelope)
        return DeliveryReceipt(
            message_id=envelope.message_id,
            delivery_id=envelope.delivery.delivery_id,
            enqueued_at=envelope.delivery.enqueued_at,
        )

    async def shutdown(self, *, timeout: float | None = None) -> None:
        del timeout
        self.stopped = True


class BlockingShutdownTransport(DirectTransport):
    def __init__(self) -> None:
        super().__init__()
        self.shutdown_started = asyncio.Event()
        self.allow_shutdown = asyncio.Event()

    async def shutdown(self, *, timeout: float | None = None) -> None:
        del timeout
        self.shutdown_started.set()
        await self.allow_shutdown.wait()
        self.stopped = True


@CommandHandler(CreateProfile)
class CreateProfileHandler:
    async def handle(self, message: CreateProfile) -> int:
        return len(message.username)


@QueryHandler(GetProfile)
class GetProfileHandler:
    async def handle(self, message: GetProfile) -> str:
        return str(message.profile_id)


@handles(GetProfile)
async def get_profile_function(
    message: GetProfile,
    context: HandlerContext,
) -> str:
    assert context.envelope.message is message
    assert context.command_bus is not None
    return str(message.profile_id)


@CommandHandler(CreateProfile)
class FailingCreateProfileHandler:
    async def handle(self, message: CreateProfile) -> int:
        raise RuntimeError(message.username)


@EventsHandler(ProfileCreated)
class ProfileCreatedHandler:
    async def handle(self, message: ProfileCreated) -> None:
        handled_profile_ids.append(message.profile_id)
        return None


handled_profile_ids: list[int] = []


def make_envelope(message: Command[int] | Query[str] | Event) -> Envelope:
    return Envelope(
        message=message,
        message_type=message_type_for(type(message)),
        message_id=uuid4(),
        correlation_id=None if isinstance(message, Event) else uuid4(),
        causation_id=None,
        headers={},
        delivery=DeliveryMetadata(
            delivery_id=uuid4(),
            enqueued_at=datetime.now(UTC),
        ),
    )


def builder_for(
    command_transport: DirectTransport,
    query_transport: DirectTransport,
    event_transport: DirectTransport,
) -> CqrsBuilder:
    return (
        CqrsBuilder()
        .add_command_handler(CreateProfileHandler)
        .add_query_handler(get_profile_function)
        .add_event_handler(ProfileCreatedHandler)
        .with_command_transport(command_transport)
        .with_query_transport(query_transport)
        .with_event_transport(event_transport)
    )


@pytest.mark.asyncio
async def test_buses_execute_class_and_function_handlers() -> None:
    command_transport = DirectTransport()
    query_transport = DirectTransport()
    event_transport = DirectTransport()
    buses = builder_for(
        command_transport,
        query_transport,
        event_transport,
    ).build()

    await buses.command_bus.start()
    await buses.query_bus.start()
    await buses.event_bus.start()

    assert await buses.command_bus.execute(CreateProfile(username="alice")) == 5
    assert await buses.query_bus.execute(GetProfile(profile_id=7)) == "7"

    receipt = await buses.event_bus.publish(ProfileCreated(profile_id=7))
    assert receipt.message_id == event_transport.published[0].message_id
    assert event_transport.published[0].correlation_id is None

    await buses.command_bus.shutdown()
    await buses.query_bus.shutdown()
    await buses.event_bus.shutdown()
    assert command_transport.stopped
    assert query_transport.stopped
    assert event_transport.stopped


@pytest.mark.asyncio
async def test_buses_reject_work_before_start_and_after_shutdown() -> None:
    command_transport = DirectTransport()
    query_transport = DirectTransport()
    event_transport = DirectTransport()
    buses = builder_for(
        command_transport,
        query_transport,
        event_transport,
    ).build()

    with pytest.raises(TransportNotStartedError):
        await buses.command_bus.execute(CreateProfile(username="alice"))
    with pytest.raises(TransportNotStartedError):
        await buses.query_bus.execute(GetProfile(profile_id=1))
    with pytest.raises(TransportNotStartedError):
        await buses.event_bus.publish(ProfileCreated(profile_id=1))

    await buses.command_bus.start()
    await buses.query_bus.start()
    await buses.event_bus.start()
    await buses.command_bus.shutdown()
    await buses.query_bus.shutdown()
    await buses.event_bus.shutdown()

    with pytest.raises(TransportStoppedError):
        await buses.command_bus.execute(CreateProfile(username="alice"))
    with pytest.raises(TransportStoppedError):
        await buses.query_bus.execute(GetProfile(profile_id=1))
    with pytest.raises(TransportStoppedError):
        await buses.event_bus.publish(ProfileCreated(profile_id=1))


@pytest.mark.asyncio
async def test_bus_rejects_work_while_shutdown_is_in_progress() -> None:
    command_transport = BlockingShutdownTransport()
    query_transport = DirectTransport()
    event_transport = DirectTransport()
    buses = builder_for(
        command_transport,
        query_transport,
        event_transport,
    ).build()
    await buses.command_bus.start()

    shutdown = asyncio.create_task(buses.command_bus.shutdown())
    await command_transport.shutdown_started.wait()

    with pytest.raises(InvalidLifecycleTransitionError, match="stopping"):
        await buses.command_bus.execute(CreateProfile(username="alice"))

    shutdown.cancel()
    with pytest.raises(asyncio.CancelledError):
        await shutdown
    with pytest.raises(TransportStoppedError):
        await buses.command_bus.execute(CreateProfile(username="alice"))


@pytest.mark.asyncio
async def test_command_handler_errors_propagate_through_bus() -> None:
    command_transport = DirectTransport()
    query_transport = DirectTransport()
    event_transport = DirectTransport()
    buses = (
        CqrsBuilder()
        .add_command_handler(FailingCreateProfileHandler)
        .with_command_transport(command_transport)
        .with_query_transport(query_transport)
        .with_event_transport(event_transport)
        .build()
    )
    await buses.command_bus.start()

    with pytest.raises(RuntimeError, match="alice"):
        await buses.command_bus.execute(CreateProfile(username="alice"))


@pytest.mark.asyncio
async def test_dispatcher_rejects_request_without_correlation_id() -> None:
    command_transport = DirectTransport()
    query_transport = DirectTransport()
    event_transport = DirectTransport()
    buses = builder_for(
        command_transport,
        query_transport,
        event_transport,
    ).build()
    await buses.command_bus.start()

    envelope = make_envelope(CreateProfile(username="alice"))
    envelope = Envelope(
        message=envelope.message,
        message_type=envelope.message_type,
        message_id=envelope.message_id,
        correlation_id=None,
        causation_id=None,
        headers={},
        delivery=envelope.delivery,
    )

    with pytest.raises(EnvelopeValidationError, match="correlation_id"):
        assert command_transport.consumer is not None
        await command_transport.consumer(envelope)


@pytest.mark.asyncio
async def test_dispatcher_rejects_envelope_for_the_wrong_bus_category() -> None:
    command_transport = DirectTransport()
    query_transport = DirectTransport()
    event_transport = DirectTransport()
    buses = builder_for(
        command_transport,
        query_transport,
        event_transport,
    ).build()
    await buses.command_bus.start()
    await buses.event_bus.start()

    query_envelope = make_envelope(GetProfile(profile_id=7))

    with pytest.raises(EnvelopeValidationError, match="command dispatcher"):
        assert command_transport.consumer is not None
        await command_transport.consumer(query_envelope)
    with pytest.raises(EnvelopeValidationError, match="event dispatcher"):
        assert event_transport.consumer is not None
        await event_transport.consumer(query_envelope)


@pytest.mark.asyncio
async def test_missing_request_handler_returns_correlated_error_reply() -> None:
    command_transport = DirectTransport()
    query_transport = DirectTransport()
    event_transport = DirectTransport()
    buses = (
        CqrsBuilder()
        .add_command_handler(CreateProfileHandler)
        .with_command_transport(command_transport)
        .with_query_transport(query_transport)
        .with_event_transport(event_transport)
        .build()
    )
    await buses.query_bus.start()
    envelope = make_envelope(GetProfile(profile_id=7))

    assert query_transport.consumer is not None
    reply = await query_transport.consumer(envelope)

    assert reply is not None
    assert reply.correlation_id == envelope.correlation_id
    assert isinstance(reply.error, MissingHandlerError)


@pytest.mark.asyncio
async def test_event_dispatcher_invokes_registered_handlers() -> None:
    handled_profile_ids.clear()
    command_transport = DirectTransport()
    query_transport = DirectTransport()
    event_transport = DirectTransport()
    buses = builder_for(
        command_transport,
        query_transport,
        event_transport,
    ).build()
    await buses.event_bus.start()

    assert event_transport.consumer is not None
    result = await event_transport.consumer(make_envelope(ProfileCreated(profile_id=7)))

    assert result is None
    await buses.event_bus.drain()
    assert handled_profile_ids == [7]

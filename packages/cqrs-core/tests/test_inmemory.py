import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cqrs_core import (
    Command,
    CommandHandler,
    CqrsBuilder,
    DeliveryMetadata,
    Envelope,
    Event,
    EventsHandler,
    InMemoryTransport,
    InvalidLifecycleTransitionError,
    InvalidReplyCorrelationError,
    InvalidTransportReplyError,
    Query,
    QueryHandler,
    QueueCapacityError,
    ReplyEnvelope,
    RequestTimeoutError,
    TransportNotStartedError,
    TransportState,
    TransportStoppedError,
    message_type_for,
)


@dataclass(frozen=True, slots=True)
class Ping(Command[int]):
    value: int


@dataclass(frozen=True, slots=True)
class Read(Query[int]):
    value: int


@dataclass(frozen=True, slots=True)
class Notification(Event):
    value: int


@CommandHandler(Ping)
class PingHandler:
    async def handle(self, message: Ping) -> int:
        return message.value * 2


@QueryHandler(Read)
class ReadHandler:
    async def handle(self, message: Read) -> int:
        return message.value


@EventsHandler(Notification)
class NotificationHandler:
    async def handle(self, message: Notification) -> None:
        return None


def envelope_for(
    message: Command[int] | Query[int] | Event,
    *,
    correlation: bool = True,
) -> Envelope:
    return Envelope(
        message=message,
        message_type=message_type_for(type(message)),
        message_id=uuid4(),
        correlation_id=uuid4() if correlation else None,
        causation_id=None,
        headers={},
        delivery=DeliveryMetadata(
            delivery_id=uuid4(),
            enqueued_at=datetime.now(UTC),
        ),
    )


def reply_for(envelope: Envelope, result: object = None) -> ReplyEnvelope[object]:
    assert envelope.correlation_id is not None
    return ReplyEnvelope(
        reply_id=uuid4(),
        correlation_id=envelope.correlation_id,
        result=result,
    )


@pytest.mark.asyncio
async def test_transport_requires_start_and_has_idempotent_shutdown() -> None:
    transport = InMemoryTransport()
    envelope = envelope_for(Ping(value=1))

    with pytest.raises(TransportNotStartedError):
        await transport.request(envelope)

    await transport.shutdown()
    assert transport.state is TransportState.STOPPED
    await transport.shutdown()

    with pytest.raises(TransportStoppedError):
        await transport.publish(envelope_for(Notification(value=1), correlation=False))


@pytest.mark.asyncio
async def test_transport_start_is_single_use() -> None:
    transport = InMemoryTransport()

    async def consumer(envelope: Envelope):
        return reply_for(envelope)

    await transport.start(consumer)
    assert transport.state is TransportState.RUNNING

    with pytest.raises(InvalidLifecycleTransitionError):
        await transport.start(consumer)
    await transport.shutdown()


@pytest.mark.asyncio
async def test_request_processing_is_fifo_and_single_worker() -> None:
    transport = InMemoryTransport()
    received: list[int] = []
    active = 0
    maximum_active = 0

    async def consumer(envelope: Envelope):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0)
        received.append(envelope.message.value)
        active -= 1
        return reply_for(envelope, envelope.message.value * 2)

    await transport.start(consumer)
    replies = await asyncio.gather(
        *(transport.request(envelope_for(Ping(value=value))) for value in range(5))
    )

    assert received == list(range(5))
    assert [reply.result for reply in replies] == [0, 2, 4, 6, 8]
    assert maximum_active == 1
    await transport.shutdown()


@pytest.mark.asyncio
async def test_consumer_error_becomes_request_error_reply_and_worker_continues() -> (
    None
):
    transport = InMemoryTransport()
    calls = 0

    async def consumer(envelope: Envelope):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("first failure")
        return reply_for(envelope, 42)

    await transport.start(consumer)
    first = await transport.request(envelope_for(Ping(value=1)))
    second = await transport.request(envelope_for(Ping(value=2)))

    assert isinstance(first.error, RuntimeError)
    assert second.result == 42
    await transport.shutdown()


@pytest.mark.asyncio
async def test_cancelled_error_hook_does_not_stop_the_worker() -> None:
    calls = 0

    async def consumer(envelope: Envelope):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("consumer failure")
        return reply_for(envelope, 42)

    async def error_hook(error: BaseException, envelope: Envelope | None) -> None:
        raise asyncio.CancelledError

    transport = InMemoryTransport(error_handler=error_hook)
    await transport.start(consumer)

    first = await transport.request(envelope_for(Ping(value=1)))
    second = await transport.request(envelope_for(Ping(value=2)))

    assert isinstance(first.error, RuntimeError)
    assert second.result == 42
    await transport.shutdown()


@pytest.mark.asyncio
async def test_unrecoverable_worker_failure_calls_error_hook() -> None:
    class FailingTransport(InMemoryTransport):
        async def _process_publish(self, item) -> None:
            raise RuntimeError("worker failure")

    failures: list[tuple[BaseException, Envelope | None]] = []

    async def error_hook(error: BaseException, envelope: Envelope | None) -> None:
        failures.append((error, envelope))

    transport = FailingTransport(error_handler=error_hook)

    async def consumer(envelope: Envelope):
        return None

    await transport.start(consumer)
    published = envelope_for(Notification(value=1), correlation=False)
    await transport.publish(published)
    await asyncio.sleep(0)

    assert transport.state is TransportState.STOPPED
    assert len(failures) == 1
    assert failures[0][0].args == ("worker failure",)
    assert failures[0][1] == published
    await transport.shutdown()


@pytest.mark.asyncio
async def test_unrecoverable_request_failure_returns_error_reply() -> None:
    class FailingTransport(InMemoryTransport):
        async def _process_request(self, item) -> None:
            raise RuntimeError("worker failure")

    transport = FailingTransport()

    async def consumer(envelope: Envelope):
        return reply_for(envelope)

    await transport.start(consumer)
    envelope = envelope_for(Ping(value=1))
    reply = await transport.request(envelope)

    assert reply.correlation_id == envelope.correlation_id
    assert isinstance(reply.error, RuntimeError)
    assert transport.state is TransportState.STOPPED
    await transport.shutdown()


@pytest.mark.asyncio
async def test_cancelled_consumer_error_keeps_request_worker_running() -> None:
    transport = InMemoryTransport()
    calls = 0

    async def consumer(envelope: Envelope):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise asyncio.CancelledError
        return reply_for(envelope, 42)

    await transport.start(consumer)
    first = await transport.request(envelope_for(Ping(value=1)))
    second = await transport.request(envelope_for(Ping(value=2)))

    assert isinstance(first.error, asyncio.CancelledError)
    assert second.result == 42
    await transport.shutdown()


@pytest.mark.asyncio
async def test_publish_cancelled_error_does_not_stop_the_worker() -> None:
    transport = InMemoryTransport()
    calls = 0
    second_started = asyncio.Event()

    async def consumer(envelope: Envelope):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise asyncio.CancelledError
        second_started.set()

    await transport.start(consumer)
    await transport.publish(envelope_for(Notification(value=1), correlation=False))
    await transport.publish(envelope_for(Notification(value=2), correlation=False))
    await second_started.wait()
    await transport.shutdown()


@pytest.mark.asyncio
async def test_invalid_consumer_reply_is_reported_as_error_reply() -> None:
    transport = InMemoryTransport()

    async def consumer(envelope: Envelope):
        wrong_correlation = uuid4()
        return ReplyEnvelope(reply_id=uuid4(), correlation_id=wrong_correlation)

    await transport.start(consumer)
    reply = await transport.request(envelope_for(Ping(value=1)))

    assert isinstance(reply.error, InvalidReplyCorrelationError)
    await transport.shutdown()


@pytest.mark.asyncio
async def test_missing_consumer_reply_is_reported_as_error_reply() -> None:
    transport = InMemoryTransport()

    async def consumer(envelope: Envelope):
        return None

    await transport.start(consumer)
    reply = await transport.request(envelope_for(Ping(value=1)))

    assert isinstance(reply.error, InvalidTransportReplyError)
    await transport.shutdown()


@pytest.mark.asyncio
async def test_publish_returns_before_consumer_finishes() -> None:
    transport = InMemoryTransport()
    started = asyncio.Event()
    release = asyncio.Event()

    async def consumer(envelope: Envelope):
        started.set()
        await release.wait()

    await transport.start(consumer)
    receipt = await transport.publish(
        envelope_for(Notification(value=1), correlation=False)
    )
    assert receipt.message_id
    await started.wait()
    assert not release.is_set()

    release.set()
    await transport.shutdown()


@pytest.mark.asyncio
async def test_bounded_queue_waits_then_times_out() -> None:
    transport = InMemoryTransport(max_queue_size=1)
    started = asyncio.Event()
    release = asyncio.Event()

    async def consumer(envelope: Envelope):
        started.set()
        await release.wait()
        return reply_for(envelope)

    await transport.start(consumer)
    await transport.publish(envelope_for(Notification(value=1), correlation=False))
    await started.wait()
    await transport.publish(envelope_for(Notification(value=2), correlation=False))

    with pytest.raises(QueueCapacityError):
        await transport.publish(
            envelope_for(Notification(value=3), correlation=False),
            timeout=0.01,
        )

    release.set()
    await transport.shutdown()


@pytest.mark.asyncio
async def test_bounded_queue_waits_for_capacity() -> None:
    transport = InMemoryTransport(max_queue_size=1)
    first_started = asyncio.Event()
    first_release = asyncio.Event()
    second_release = asyncio.Event()
    calls = 0

    async def consumer(envelope: Envelope):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            await first_release.wait()
        else:
            await second_release.wait()

    await transport.start(consumer)
    await transport.publish(envelope_for(Notification(value=1), correlation=False))
    await first_started.wait()

    second = asyncio.create_task(
        transport.publish(envelope_for(Notification(value=2), correlation=False))
    )
    await asyncio.sleep(0)
    assert not second.done()

    first_release.set()
    receipt = await second
    assert receipt.message_id

    second_release.set()
    await transport.shutdown()


@pytest.mark.asyncio
async def test_default_timeout_is_reported_on_queue_capacity_error() -> None:
    transport = InMemoryTransport(max_queue_size=1, default_timeout=0.01)
    started = asyncio.Event()
    release = asyncio.Event()

    async def consumer(envelope: Envelope):
        started.set()
        await release.wait()

    await transport.start(consumer)
    await transport.publish(envelope_for(Notification(value=1), correlation=False))
    await started.wait()
    await transport.publish(envelope_for(Notification(value=2), correlation=False))

    with pytest.raises(QueueCapacityError) as error:
        await transport.publish(envelope_for(Notification(value=3), correlation=False))

    assert error.value.timeout == 0.01
    release.set()
    await transport.shutdown()


@pytest.mark.asyncio
async def test_request_cancellation_does_not_cancel_started_consumer() -> None:
    transport = InMemoryTransport()
    started = asyncio.Event()
    release = asyncio.Event()

    async def consumer(envelope: Envelope):
        started.set()
        await release.wait()
        return reply_for(envelope, 7)

    await transport.start(consumer)
    request = asyncio.create_task(transport.request(envelope_for(Ping(value=1))))
    await started.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request

    release.set()
    await asyncio.sleep(0)
    await transport.shutdown()


@pytest.mark.asyncio
async def test_request_timeout_keeps_worker_running_for_late_reply() -> None:
    transport = InMemoryTransport()
    started = asyncio.Event()
    release = asyncio.Event()

    async def consumer(envelope: Envelope):
        started.set()
        await release.wait()
        return reply_for(envelope, 9)

    await transport.start(consumer)
    request = asyncio.create_task(
        transport.request(envelope_for(Ping(value=1)), timeout=0.01)
    )
    await started.wait()
    with pytest.raises(RequestTimeoutError):
        await request

    release.set()
    await asyncio.sleep(0)
    await transport.shutdown()


@pytest.mark.asyncio
async def test_request_timeout_then_shutdown_has_no_shielded_future_warning() -> None:
    transport = InMemoryTransport()
    started = asyncio.Event()
    never_release = asyncio.Event()
    contexts: list[dict[str, object]] = []
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()

    def exception_handler(
        current_loop: asyncio.AbstractEventLoop,
        context: dict[str, object],
    ) -> None:
        contexts.append(context)

    loop.set_exception_handler(exception_handler)

    async def consumer(envelope: Envelope):
        started.set()
        await never_release.wait()
        return reply_for(envelope)

    try:
        await transport.start(consumer)
        request = asyncio.create_task(
            transport.request(envelope_for(Ping(value=1)), timeout=0.01)
        )
        await started.wait()
        with pytest.raises(RequestTimeoutError):
            await request

        await transport.shutdown(timeout=0.01)
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(previous_handler)

    assert not any(
        context.get("message") == "exception in shielded future" for context in contexts
    )


@pytest.mark.asyncio
async def test_shutdown_drains_before_stopping() -> None:
    transport = InMemoryTransport()
    started = asyncio.Event()
    release = asyncio.Event()

    async def consumer(envelope: Envelope):
        started.set()
        await release.wait()
        return reply_for(envelope, 11)

    await transport.start(consumer)
    request = asyncio.create_task(transport.request(envelope_for(Ping(value=1))))
    await started.wait()
    shutdown = asyncio.create_task(transport.shutdown(timeout=1))
    await asyncio.sleep(0)
    assert transport.state is TransportState.STOPPING
    release.set()

    assert (await request).result == 11
    await shutdown
    assert transport.state is TransportState.STOPPED


@pytest.mark.asyncio
async def test_default_timeout_does_not_limit_shutdown() -> None:
    transport = InMemoryTransport(default_timeout=0.001)
    started = asyncio.Event()
    release = asyncio.Event()

    async def consumer(envelope: Envelope):
        started.set()
        await release.wait()

    await transport.start(consumer)
    await transport.publish(envelope_for(Notification(value=1), correlation=False))
    await started.wait()

    shutdown = asyncio.create_task(transport.shutdown())
    await asyncio.sleep(0.01)
    assert not shutdown.done()

    release.set()
    await shutdown
    assert transport.state is TransportState.STOPPED


@pytest.mark.asyncio
async def test_shutdown_timeout_cancels_worker_and_pending_requests() -> None:
    transport = InMemoryTransport()
    started = asyncio.Event()
    never_release = asyncio.Event()

    async def consumer(envelope: Envelope):
        started.set()
        await never_release.wait()
        return reply_for(envelope)

    await transport.start(consumer)
    request = asyncio.create_task(transport.request(envelope_for(Ping(value=1))))
    await started.wait()

    await transport.shutdown(timeout=0)
    with pytest.raises(TransportStoppedError):
        await request
    assert transport.state is TransportState.STOPPED
    assert transport._worker is not None
    assert transport._worker.done()


@pytest.mark.asyncio
async def test_concurrent_shutdown_timeout_forces_first_shutdown_to_finish() -> None:
    transport = InMemoryTransport(max_queue_size=1)
    started = asyncio.Event()
    never_release = asyncio.Event()

    async def consumer(envelope: Envelope):
        started.set()
        await never_release.wait()
        return reply_for(envelope)

    await transport.start(consumer)
    active = asyncio.create_task(transport.request(envelope_for(Ping(value=1))))
    await started.wait()
    queued = asyncio.create_task(transport.request(envelope_for(Ping(value=2))))
    await asyncio.sleep(0.01)
    assert transport._queue.qsize() == 1

    first_shutdown = asyncio.create_task(transport.shutdown())
    await asyncio.sleep(0)
    second_shutdown = asyncio.create_task(transport.shutdown(timeout=0))

    await second_shutdown
    await first_shutdown
    with pytest.raises(TransportStoppedError):
        await active
    with pytest.raises(TransportStoppedError):
        await queued
    assert transport.state is TransportState.STOPPED
    assert transport._worker is not None
    assert transport._worker.done()


@pytest.mark.asyncio
async def test_cancelled_shutdown_still_stops_the_transport() -> None:
    transport = InMemoryTransport()
    started = asyncio.Event()
    never_release = asyncio.Event()

    async def consumer(envelope: Envelope):
        started.set()
        await never_release.wait()
        return reply_for(envelope)

    await transport.start(consumer)
    request = asyncio.create_task(transport.request(envelope_for(Ping(value=1))))
    await started.wait()

    shutdown = asyncio.create_task(transport.shutdown(timeout=1))
    await asyncio.sleep(0)
    shutdown.cancel()
    with pytest.raises(asyncio.CancelledError):
        await shutdown

    with pytest.raises(TransportStoppedError):
        await request
    assert transport.state is TransportState.STOPPED
    assert transport._worker is not None
    assert transport._worker.done()


@pytest.mark.asyncio
async def test_all_buses_run_with_separate_inmemory_transports() -> None:
    command_transport = InMemoryTransport(name="command")
    query_transport = InMemoryTransport(name="query")
    event_transport = InMemoryTransport(name="event")
    buses = (
        CqrsBuilder()
        .add_command_handler(PingHandler)
        .add_query_handler(ReadHandler)
        .add_event_handler(NotificationHandler)
        .with_command_transport(command_transport)
        .with_query_transport(query_transport)
        .with_event_transport(event_transport)
        .build()
    )

    await buses.command_bus.start()
    await buses.query_bus.start()
    await buses.event_bus.start()

    assert await buses.command_bus.execute(Ping(value=3)) == 6
    assert await buses.query_bus.execute(Read(value=4)) == 4
    await buses.event_bus.publish(Notification(value=5))

    await buses.command_bus.shutdown()
    await buses.query_bus.shutdown()
    await buses.event_bus.shutdown()

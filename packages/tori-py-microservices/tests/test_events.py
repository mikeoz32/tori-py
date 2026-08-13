from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from inspect import signature
from typing import Any, cast
from uuid import uuid4

import pytest
from tori_py import ApplicationOptions, ValueProvider, module
from tori_py.testing import TestingModule
from tori_py_microservices.codec import MsgspecJsonMessageCodec
from tori_py_microservices.errors import (
    IdentityValidationError,
    TransportStateError,
    TransportUnroutableError,
    WireEncodingError,
    WireValidationError,
)
from tori_py_microservices.events import EventDispatcher
from tori_py_microservices.identities import EventIdentity, ServiceIdentity
from tori_py_microservices.inmemory import (
    InMemoryBroker,
    InMemoryClientTransport,
    InMemoryServerTransport,
)
from tori_py_microservices.invocation import SettlementRecommendation
from tori_py_microservices.transport import EventSubscription, TransportStatus

SOURCE = ServiceIdentity("tests", "publisher", 1)
DESTINATION = ServiceIdentity("tests", "consumer", 1)


@dataclass(slots=True)
class ClientFactory:
    broker: InMemoryBroker
    client: InMemoryClientTransport | None = None

    def create(self) -> InMemoryClientTransport:
        self.client = InMemoryClientTransport(self.broker)
        return self.client


class Shutdown:
    def __init__(self, remaining: float | None = None) -> None:
        self._remaining = remaining

    def remaining(self) -> float | None:
        return self._remaining


async def _wait_for_count(values: list[object], count: int) -> None:
    async with asyncio.timeout(1):
        while len(values) < count:
            await asyncio.sleep(0)


def test_event_dispatcher_surface_cannot_override_source_or_message_id() -> None:
    assert tuple(signature(EventDispatcher.publish).parameters) == (
        "self",
        "event",
        "schema_version",
        "payload",
        "headers",
        "correlation_id",
        "causation_id",
        "occurred_at",
        "require_route",
    )
    dispatcher = EventDispatcher(SOURCE, ClientFactory(InMemoryBroker()))
    assert not hasattr(dispatcher, "transport")


@pytest.mark.asyncio
async def test_inmemory_dispatcher_round_trips_identity_and_metadata() -> None:
    broker = InMemoryBroker()
    factory = ClientFactory(broker)
    dispatcher = EventDispatcher(SOURCE, factory)
    with pytest.raises(AttributeError):
        cast(Any, dispatcher).identity = DESTINATION
    identity = EventIdentity(SOURCE, "profile-created", 2)
    subscriptions = (
        EventSubscription(
            identity,
            "service_pool",
            "first-view",
            destination=DESTINATION,
        ),
        EventSubscription(
            identity,
            "service_pool",
            "second-view",
            destination=DESTINATION,
        ),
    )
    server = InMemoryServerTransport(broker, DESTINATION)
    await server.prepare(subscriptions=subscriptions)
    codec = MsgspecJsonMessageCodec()
    received = []

    async def receive(delivery):
        received.append((delivery.subscription, codec.decode_event(delivery.body)))
        return SettlementRecommendation.ACK

    await server.start(receive)
    correlation_id = uuid4()
    causation_id = uuid4()
    occurred_at = datetime(2026, 8, 5, 12, 30, tzinfo=UTC)
    await dispatcher.on_application_bootstrap()
    assert factory.client is not None
    assert factory.client._reply_queue is None

    receipt = await dispatcher.publish(
        "profile-created",
        2,
        {"handle": "river"},
        headers={"trace": "safe", "nested": [1, True]},
        correlation_id=correlation_id,
        causation_id=causation_id,
        occurred_at=occurred_at,
        require_route=True,
    )
    await _wait_for_count(received, 2)

    assert receipt.routed is True
    assert {item[0] for item in received} == set(subscriptions)
    assert all(envelope.message_id == receipt.message_id for _, envelope in received)
    for _, envelope in received:
        assert envelope.source == SOURCE
        assert envelope.event == "profile-created"
        assert envelope.schema_version == 2
        assert envelope.payload == {"handle": "river"}
        assert envelope.headers == {"trace": "safe", "nested": (1, True)}
        assert envelope.correlation_id == correlation_id
        assert envelope.causation_id == causation_id
        assert envelope.occurred_at == occurred_at

    generated_after = datetime.now(UTC)
    generated = await dispatcher.publish("profile-created", 2, None)
    await _wait_for_count(received, 4)
    generated_envelopes = [envelope for _, envelope in received[2:]]
    assert generated.message_id != receipt.message_id
    assert all(
        envelope.message_id == generated.message_id
        and envelope.occurred_at >= generated_after
        for envelope in generated_envelopes
    )

    orphan = await dispatcher.publish("orphaned", 1, None)
    assert orphan.routed is False
    with pytest.raises(TransportUnroutableError):
        await dispatcher.publish("orphaned", 1, None, require_route=True)

    await dispatcher.on_application_quiesce(Shutdown())
    with pytest.raises(TransportStateError):
        await dispatcher.publish("profile-created", 2, None)
    await dispatcher.on_application_shutdown()
    await dispatcher.on_application_shutdown()
    await server.close()
    await broker.close()


@pytest.mark.asyncio
async def test_dispatcher_rejects_before_start_and_uses_existing_validation() -> None:
    broker = InMemoryBroker()
    dispatcher = EventDispatcher(SOURCE, ClientFactory(broker))
    with pytest.raises(TransportStateError):
        await dispatcher.publish("created", 1, None)

    await dispatcher.on_application_bootstrap()
    await dispatcher.on_application_bootstrap()
    with pytest.raises(IdentityValidationError):
        await dispatcher.publish("Invalid", 1, None)
    with pytest.raises(IdentityValidationError):
        await dispatcher.publish("created", True, None)
    with pytest.raises(WireValidationError):
        await dispatcher.publish("created", 1, None, headers={"unsafe": object()})
    with pytest.raises(WireEncodingError):
        await dispatcher.publish("created", 1, object())
    with pytest.raises(TypeError):
        await dispatcher.publish("created", 1, None, require_route=cast(bool, 1))
    await dispatcher.close()
    await broker.close()

    quiesced_broker = InMemoryBroker()
    quiesced = EventDispatcher(SOURCE, ClientFactory(quiesced_broker))
    await quiesced.on_application_quiesce(Shutdown())
    with pytest.raises(TransportStateError, match="cannot be restarted"):
        await quiesced.on_application_bootstrap()
    await quiesced.close()
    await quiesced_broker.close()


class BlockingClient(InMemoryClientTransport):
    def __init__(self, broker: InMemoryBroker) -> None:
        super().__init__(broker)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def publish_event(self, identity, publication):
        self.entered.set()
        await self.release.wait()
        return await super().publish_event(identity, publication)


class CancellationResistantClient(BlockingClient):
    async def publish_event(self, identity, publication):
        self.entered.set()
        while not self.release.is_set():
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                continue
        return await InMemoryClientTransport.publish_event(self, identity, publication)


@dataclass(slots=True)
class BlockingFactory:
    client: BlockingClient

    def create(self) -> BlockingClient:
        return self.client


@pytest.mark.asyncio
async def test_quiesce_rejects_new_work_and_drains_accepted_publication() -> None:
    broker = InMemoryBroker()
    client = BlockingClient(broker)
    dispatcher = EventDispatcher(SOURCE, BlockingFactory(client))
    await dispatcher.on_application_bootstrap()
    publication = asyncio.create_task(dispatcher.publish("created", 1, None))
    await client.entered.wait()

    quiesce = asyncio.create_task(dispatcher.on_application_quiesce(Shutdown()))
    await asyncio.sleep(0)
    assert not quiesce.done()
    with pytest.raises(TransportStateError):
        await dispatcher.publish("created", 1, None)

    client.release.set()
    await publication
    await quiesce
    await dispatcher.close()
    await broker.close()


@pytest.mark.asyncio
async def test_quiesce_cancels_publication_when_deadline_is_exhausted() -> None:
    broker = InMemoryBroker()
    client = BlockingClient(broker)
    dispatcher = EventDispatcher(SOURCE, BlockingFactory(client))
    await dispatcher.on_application_bootstrap()
    publication = asyncio.create_task(dispatcher.publish("created", 1, None))
    await client.entered.wait()

    await dispatcher.on_application_quiesce(Shutdown(0))
    with pytest.raises(asyncio.CancelledError):
        await publication
    await dispatcher.close()
    await broker.close()


@pytest.mark.asyncio
async def test_close_rejects_new_work_and_drains_accepted_publication() -> None:
    broker = InMemoryBroker()
    client = BlockingClient(broker)
    dispatcher = EventDispatcher(SOURCE, BlockingFactory(client))
    await dispatcher.on_application_bootstrap()
    publication = asyncio.create_task(dispatcher.publish("created", 1, None))
    await client.entered.wait()

    close = asyncio.create_task(dispatcher.close())
    await asyncio.sleep(0)
    assert not close.done()
    with pytest.raises(TransportStateError):
        await dispatcher.publish("created", 1, None)

    client.release.set()
    await publication
    await close
    await broker.close()


@pytest.mark.asyncio
async def test_application_shutdown_closes_after_publication_resists_cancellation() -> (
    None
):
    broker = InMemoryBroker()
    client = CancellationResistantClient(broker)
    dispatcher = EventDispatcher(SOURCE, BlockingFactory(client))

    @module(providers=(ValueProvider(EventDispatcher, dispatcher),))
    class ApplicationModule:
        pass

    application = await TestingModule.create(ApplicationModule).compile(
        options=ApplicationOptions(
            shutdown_timeout=0.05,
            cancellation_grace=0,
            cleanup_reserve=0,
        )
    )
    publication = asyncio.create_task(dispatcher.publish("created", 1, None))
    await client.entered.wait()

    with pytest.raises(TimeoutError):
        await application.close()
    assert client.status is TransportStatus.CLOSED

    client.release.set()
    with pytest.raises(TransportStateError):
        await publication
    await broker.close()

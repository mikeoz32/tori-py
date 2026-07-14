from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from cqrs_core import (
    Command,
    DeliveryMetadata,
    DeliveryReceipt,
    DispatchContext,
    Envelope,
    HandlerProvider,
    HandlerRegistration,
    ReplyEnvelope,
    Transport,
    TransportConsumer,
    message_type_for,
)


@dataclass(frozen=True, slots=True)
class Ping(Command[str]):
    value: str


class Registration:
    message_type = Ping


class Context:
    def __init__(self, envelope: Envelope[Ping]) -> None:
        self.envelope = envelope


def make_envelope() -> Envelope[Ping]:
    return Envelope(
        message=Ping(value="ok"),
        message_type=message_type_for(Ping),
        message_id=uuid4(),
        correlation_id=uuid4(),
        causation_id=None,
        headers={},
        delivery=DeliveryMetadata(
            delivery_id=uuid4(),
            enqueued_at=datetime.now(UTC),
        ),
    )


class FakeProvider:
    def provide(
        self,
        registration: HandlerRegistration,
        context: DispatchContext,
    ) -> AbstractAsyncContextManager[object]:
        @asynccontextmanager
        async def scope() -> AsyncIterator[object]:
            yield lambda message: message

        return scope()


class FakeTransport:
    async def start(self, consumer: TransportConsumer) -> None:
        self.consumer = consumer

    async def request(
        self,
        envelope: Envelope[Ping],
        *,
        timeout: float | None = None,
    ) -> ReplyEnvelope[object]:
        assert envelope.correlation_id is not None
        return ReplyEnvelope(reply_id=uuid4(), correlation_id=envelope.correlation_id)

    async def publish(
        self,
        envelope: Envelope[Ping],
        *,
        timeout: float | None = None,
    ) -> DeliveryReceipt:
        return DeliveryReceipt(
            message_id=envelope.message_id,
            delivery_id=envelope.delivery.delivery_id,
            enqueued_at=envelope.delivery.enqueued_at,
        )

    async def shutdown(self, *, timeout: float | None = None) -> None:
        return None


class FakeConsumer:
    async def __call__(self, envelope: Envelope[Ping]) -> ReplyEnvelope[object] | None:
        return None


def test_protocols_are_runtime_checkable_shapes() -> None:
    assert isinstance(FakeProvider(), HandlerProvider)
    assert isinstance(Registration(), HandlerRegistration)
    assert isinstance(Context(make_envelope()), DispatchContext)
    assert isinstance(FakeTransport(), Transport)
    assert isinstance(FakeConsumer(), TransportConsumer)

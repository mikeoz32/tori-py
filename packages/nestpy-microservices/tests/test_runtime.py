from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast
from uuid import uuid4

import pytest
from nestpy import (
    DiscoveryService,
    ModulesContainer,
    ModuleSpec,
    NestApplication,
    controller,
    module,
)

from nestpy_microservices import (
    InMemoryBroker,
    InMemoryClientTransport,
    InMemoryServerTransport,
    MessageCodec,
    MicroservicesModule,
    MicroservicesOptions,
    MsgspecJsonMessageCodec,
    Payload,
    Publication,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqTransport,
    RpcRequestEnvelope,
    RpcTarget,
    ServiceIdentity,
    ServiceRuntime,
    SettlementRecommendation,
    TransportStatus,
    rpc,
)

SERVICE = ServiceIdentity("kinker", "members", 1)


class EmptyDiscovery:
    def get_controllers(self):
        return ()


class EmptyModules:
    pass


@dataclass
class Factory:
    broker: InMemoryBroker
    created: int = 0

    def create(self, identity, options):
        del identity, options
        self.created += 1
        return InMemoryServerTransport(self.broker, SERVICE)


@dataclass
class Shutdown:
    value: float = 1.0

    def remaining(self) -> float:
        return self.value


def test_options_validate_finite_service_limits() -> None:
    with pytest.raises(ValueError):
        MicroservicesOptions(max_concurrency=2, max_inflight_deliveries=1)

    options = MicroservicesOptions(max_concurrency=2, max_inflight_deliveries=4)
    assert options.max_concurrency == 2


def test_module_materialization_only_captures_configuration() -> None:
    broker = InMemoryBroker()
    factory = Factory(broker)
    descriptor = MicroservicesModule.for_root(SERVICE, transport=factory)

    assert factory.created == 0
    spec = cast(ModuleSpec, descriptor.factory())
    assert factory.created == 0
    assert len(tuple(spec.providers)) == 2


@pytest.mark.asyncio
async def test_runtime_starts_after_bootstrap_and_quiesces_before_close() -> None:
    broker = InMemoryBroker()
    factory = Factory(broker)

    async def dispatch(delivery):
        del delivery
        return SettlementRecommendation.ACK

    runtime = ServiceRuntime(
        SERVICE,
        transport_factory=factory,
        discovery=cast(DiscoveryService, EmptyDiscovery()),
        modules=cast(ModulesContainer, EmptyModules()),
        dispatcher=dispatch,
    )

    await runtime.on_application_bootstrap()
    assert runtime.accepting
    assert runtime.transport is not None
    assert runtime.transport.status is TransportStatus.RUNNING
    assert factory.created == 1

    await runtime.on_application_quiesce(Shutdown())
    assert not runtime.accepting
    assert runtime.transport.status is TransportStatus.QUIESCING
    await runtime.close()
    assert runtime.transport is None
    await broker.close()


@pytest.mark.asyncio
async def test_module_installs_runtime_in_nest_application_lifecycle() -> None:
    broker = InMemoryBroker()
    factory = Factory(broker)
    application = await NestApplication.create(
        MicroservicesModule.for_root(SERVICE, transport=factory)
    )

    await application.start()
    assert factory.created == 1
    await application.shutdown()
    assert application.state.value == "stopped"
    await broker.close()


@pytest.mark.asyncio
async def test_rabbitmq_module_wires_transport_factories() -> None:
    application = await NestApplication.create(
        MicroservicesModule.for_root(
            SERVICE,
            transport=RabbitMqTransport(),
            imports=(RabbitMqModule.for_root(RabbitMqOptions("amqp://localhost")),),
        )
    )

    assert application.state.value == "compiled"


@pytest.mark.asyncio
async def test_module_default_dispatcher_executes_compiled_rpc() -> None:
    broker = InMemoryBroker()

    @controller()
    class Controller:
        @rpc("ping")
        async def ping(self, payload: Annotated[str, Payload()]) -> str:
            return payload.upper()

    @module(controllers=[Controller])
    class ApplicationModule:
        pass

    factory = Factory(broker)
    application = await NestApplication.create(
        MicroservicesModule.for_root(
            SERVICE,
            transport=factory,
            imports=(ApplicationModule,),
        )
    )
    await application.start()
    client = InMemoryClientTransport(broker)
    await client.start()
    codec: MessageCodec = MsgspecJsonMessageCodec()
    correlation_id = uuid4()
    created_at = datetime.now(UTC)
    request = RpcRequestEnvelope(
        message_id=uuid4(),
        service=SERVICE,
        method="ping",
        schema_version=1,
        created_at=created_at,
        deadline_at=created_at + timedelta(seconds=5),
        correlation_id=correlation_id,
        reply_to=client.reply_to,
        payload="hello",
    )
    target = RpcTarget(SERVICE, "ping", 1)
    await client.publish_rpc(
        target,
        Publication(
            message_id=request.message_id,
            routing_key=target.routing_key,
            body=codec.encode_request(request),
            headers={},
            reply_to=client.reply_to,
            correlation_id=correlation_id,
        ),
    )
    response = await anext(client.replies())

    decoded = codec.decode_response(response.body)
    assert decoded.result == "HELLO"
    await client.close()
    await application.shutdown()
    await broker.close()

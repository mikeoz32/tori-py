from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Annotated, Protocol, cast
from uuid import UUID, uuid4

import msgspec
import pytest
from nestpy import NestApplication, ValueProvider, module
from nestpy_microservices import (
    CallHeaders,
    CallTimeout,
    CausationId,
    ClientsModule,
    CorrelationId,
    InMemoryBroker,
    InMemoryClientTransport,
    InMemoryServerTransport,
    MsgspecJsonMessageCodec,
    Publication,
    RabbitMqClientTransportFactory,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqServerTransportFactory,
    RabbitMqTransport,
    RpcResponseEnvelope,
    RpcTarget,
    RpcTimeoutError,
    ServiceCluster,
    ServiceClusterOptions,
    ServiceIdentity,
    SettlementRecommendation,
    TransportCapacityError,
    UnknownServiceError,
    WireValidationError,
    create_service_proxy,
    rabbitmq_client_factory_token,
    rabbitmq_server_factory_token,
    rpc_call,
    service_contract,
    utc_now,
)

SERVICE = ServiceIdentity("kinker", "members", 1)
TARGET = RpcTarget(SERVICE, "ping", 1)


class Request(msgspec.Struct):
    value: str


@service_contract(SERVICE)
class MembersClient(Protocol):
    @rpc_call("ping", payload=Request)
    async def ping(
        self,
        value: str,
        *,
        correlation_id: Annotated[UUID | None, CorrelationId()] = None,
        causation_id: Annotated[UUID | None, CausationId()] = None,
        headers: Annotated[Mapping[str, object] | None, CallHeaders()] = None,
        timeout: Annotated[float | None, CallTimeout()] = None,
    ) -> str: ...


@pytest.mark.asyncio
async def test_cluster_uses_one_reply_route_for_rpc_success() -> None:
    broker = InMemoryBroker()
    server = InMemoryServerTransport(broker, SERVICE)
    await server.prepare(rpc_methods=(TARGET.method,))
    codec = MsgspecJsonMessageCodec()

    async def dispatch(delivery):
        request = codec.decode_request(delivery.body)
        response = RpcResponseEnvelope(
            message_id=uuid4(),
            correlation_id=request.correlation_id,
            completed_at=utc_now(),
            result=str(request.payload).upper(),
        )
        await server.publish_reply(
            Publication(
                message_id=response.message_id,
                routing_key=request.reply_to.value,
                body=codec.encode_response(response),
                headers={},
                mandatory=True,
                correlation_id=request.correlation_id,
            )
        )
        return SettlementRecommendation.ACK

    await server.start(dispatch)
    client = InMemoryClientTransport(broker)
    cluster = ServiceCluster(client)

    result = await cluster.service(SERVICE).request("ping", "hello", response_type=str)

    assert result == "HELLO"
    await cluster.close()
    await server.close()
    await broker.close()


@pytest.mark.asyncio
async def test_dynamic_protocol_proxy_binds_payload_and_metadata() -> None:
    broker = InMemoryBroker()
    server = InMemoryServerTransport(broker, SERVICE)
    await server.prepare(rpc_methods=(TARGET.method,))
    codec = MsgspecJsonMessageCodec()

    async def dispatch(delivery):
        request = codec.decode_request(delivery.body)
        assert request.payload == {"value": "hello"}
        assert request.correlation_id == correlation_id
        assert request.causation_id == causation_id
        assert request.headers == {"trace": "request-1"}
        assert (request.deadline_at - request.created_at).total_seconds() <= 0.2
        response = RpcResponseEnvelope(
            message_id=uuid4(),
            correlation_id=request.correlation_id,
            completed_at=utc_now(),
            result="HELLO",
        )
        await server.publish_reply(
            Publication(
                message_id=response.message_id,
                routing_key=request.reply_to.value,
                body=codec.encode_response(response),
                headers={},
                mandatory=True,
                correlation_id=request.correlation_id,
            )
        )
        return SettlementRecommendation.ACK

    await server.start(dispatch)
    cluster = ServiceCluster(InMemoryClientTransport(broker))
    client = cast(MembersClient, create_service_proxy(MembersClient, cluster))
    correlation_id = uuid4()
    causation_id = uuid4()

    assert (
        await client.ping(
            "hello",
            correlation_id=correlation_id,
            causation_id=causation_id,
            headers={"trace": "request-1"},
            timeout=0.2,
        )
        == "HELLO"
    )

    await cluster.close()
    await server.close()
    await broker.close()


@pytest.mark.asyncio
async def test_clients_module_registers_protocol_contract_tokens() -> None:
    broker = InMemoryBroker()
    application = await NestApplication.create(
        ClientsModule.register_cluster(
            InMemoryClientTransport(broker),
            contracts=(MembersClient,),
        )
    )
    resolver = application._kernel.resolver(application.graph.root)

    client = cast(MembersClient, await resolver.resolve(MembersClient))

    assert callable(client.ping)
    await broker.close()


@pytest.mark.asyncio
async def test_cluster_timeout_removes_pending_call() -> None:
    broker = InMemoryBroker()
    server = InMemoryServerTransport(broker, SERVICE)
    await server.prepare(rpc_methods=(TARGET.method,))

    async def dispatch(delivery):
        del delivery
        return SettlementRecommendation.ACK

    await server.start(dispatch)
    cluster = ServiceCluster(
        InMemoryClientTransport(broker),
        options=ServiceClusterOptions(default_rpc_timeout=0.01, max_rpc_timeout=1),
    )

    with pytest.raises(RpcTimeoutError):
        await cluster.service(SERVICE).request("ping", "hello", response_type=str)

    assert not cluster._pending
    await cluster.close()
    await server.close()
    await broker.close()


@pytest.mark.asyncio
async def test_cluster_rejects_pending_map_exhaustion_before_publish() -> None:
    broker = InMemoryBroker()
    client = InMemoryClientTransport(broker)
    cluster = ServiceCluster(
        client,
        options=ServiceClusterOptions(max_pending_requests=1),
    )
    await cluster.start()
    loop = asyncio.get_running_loop()
    pending = loop.create_future()
    cluster._pending[uuid4()] = pending

    with pytest.raises(TransportCapacityError):
        await cluster.service(SERVICE).request("ping", "hello", response_type=str)

    await cluster.close()
    assert isinstance(pending.exception(), Exception)
    await broker.close()


@pytest.mark.asyncio
async def test_cluster_cleans_pending_entry_when_request_construction_fails() -> None:
    broker = InMemoryBroker()
    cluster = ServiceCluster(InMemoryClientTransport(broker))

    with pytest.raises(WireValidationError):
        await cluster.service(SERVICE).request(
            "ping",
            "hello",
            response_type=str,
            headers={"": "invalid"},
        )

    assert not cluster._pending
    assert not cluster._pending_generations
    await cluster.close()
    await broker.close()


@pytest.mark.asyncio
async def test_cluster_maps_unroutable_rpc_to_unknown_service() -> None:
    broker = InMemoryBroker()
    cluster = ServiceCluster(InMemoryClientTransport(broker))

    with pytest.raises(UnknownServiceError):
        await cluster.service(SERVICE).request("ping", "hello", response_type=str)

    assert not cluster._pending
    await cluster.close()
    await broker.close()


def test_cluster_proxy_cache_is_bounded() -> None:
    broker = InMemoryBroker()
    cluster = ServiceCluster(
        InMemoryClientTransport(broker),
        options=ServiceClusterOptions(max_cached_proxies=2),
    )

    first = cluster.service(ServiceIdentity("kinker", "first", 1))
    second = cluster.service(ServiceIdentity("kinker", "second", 1))
    cluster.service(ServiceIdentity("kinker", "third", 1))

    assert len(cluster._proxies) == 2
    assert first not in cluster._proxies.values()
    assert second in cluster._proxies.values()


@pytest.mark.asyncio
async def test_clients_module_wires_rabbitmq_factory() -> None:
    application = await NestApplication.create(
        ClientsModule.register_cluster(
            RabbitMqTransport(),
            imports=(RabbitMqModule.for_root(RabbitMqOptions("amqp://localhost")),),
        )
    )

    assert application.state.value == "compiled"
    assert (application.graph.root, ServiceCluster) in application.graph.visibility


@pytest.mark.asyncio
async def test_keyed_rabbitmq_clients_export_distinct_cluster_tokens() -> None:
    first = ClientsModule.register_cluster(
        RabbitMqTransport("first"),
        imports=(
            RabbitMqModule.for_root(
                RabbitMqOptions("amqp://localhost"),
                key="first",
            ),
        ),
        key="first",
    )
    second = ClientsModule.register_cluster(
        RabbitMqTransport("second"),
        imports=(
            RabbitMqModule.for_root(
                RabbitMqOptions("amqp://localhost"),
                key="second",
            ),
        ),
        key="second",
    )

    @module(imports=[first, second])
    class Root:
        pass

    application = await NestApplication.create(Root)
    first_ref = application.graph.visibility[
        (application.graph.root, ClientsModule.get_cluster_token("first"))
    ]
    second_ref = application.graph.visibility[
        (application.graph.root, ClientsModule.get_cluster_token("second"))
    ]

    assert first_ref.module_id.key == "first"
    assert second_ref.module_id.key == "second"
    assert first_ref != second_ref
    assert (application.graph.root, ServiceCluster) not in application.graph.visibility


@pytest.mark.asyncio
async def test_two_rabbitmq_roots_resolve_only_their_exact_factory_tokens() -> None:
    @module(
        imports=[
            RabbitMqModule.for_root(
                RabbitMqOptions("amqp://first.example"), key="first"
            ),
            RabbitMqModule.for_root(
                RabbitMqOptions("amqp://second.example"), key="second"
            ),
        ]
    )
    class Root:
        pass

    application = await NestApplication.create(Root)
    resolver = application._kernel.resolver(application.graph.root)
    first_server = await resolver.resolve(rabbitmq_server_factory_token("first"))
    second_server = await resolver.resolve(rabbitmq_server_factory_token("second"))
    first_client = await resolver.resolve(rabbitmq_client_factory_token("first"))
    second_client = await resolver.resolve(rabbitmq_client_factory_token("second"))

    assert isinstance(first_server, RabbitMqServerTransportFactory)
    assert isinstance(second_server, RabbitMqServerTransportFactory)
    assert isinstance(first_client, RabbitMqClientTransportFactory)
    assert isinstance(second_client, RabbitMqClientTransportFactory)
    assert first_server.manager.options.url == "amqp://first.example"
    assert second_server.manager.options.url == "amqp://second.example"
    assert first_client.manager is first_server.manager
    assert second_client.manager is second_server.manager
    assert first_server.manager is not second_server.manager
    assert (application.graph.root, RabbitMqServerTransportFactory) not in (
        application.graph.visibility
    )
    assert (application.graph.root, RabbitMqClientTransportFactory) not in (
        application.graph.visibility
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("manage_transport", [False, True])
async def test_application_shutdown_closes_cluster_router_and_owned_transport(
    manage_transport: bool,
) -> None:
    broker = InMemoryBroker()
    transport = InMemoryClientTransport(broker)
    cluster = ServiceCluster(transport, manage_transport=manage_transport)

    @module(providers=[ValueProvider(ServiceCluster, cluster)])
    class Root:
        pass

    application = await NestApplication.create(Root)
    await application.start()
    await cluster.start()
    router = cluster._router_task
    assert router is not None and not router.done()

    await application.shutdown()

    assert cluster._closed is True
    assert router.done()
    assert transport.status.value == ("closed" if manage_transport else "running")
    if not manage_transport:
        await transport.close()
    await broker.close()

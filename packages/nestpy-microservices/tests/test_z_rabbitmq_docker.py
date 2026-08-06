from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Annotated, cast
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest
from nestpy import controller, module
from nestpy.testing import TestingModule

pytest.importorskip("pytest_docker")

from nestpy_microservices.errors import (  # noqa: E402
    RabbitMqConnectionError,
    RpcOutcomeUnknownError,
    RpcTimeoutError,
    TransportIndeterminateError,
)
from nestpy_microservices.rabbitmq import compile_event_topology  # noqa: E402
from nestpy_microservices.testing import assert_transport_conformance  # noqa: E402

from nestpy_microservices import (  # noqa: E402
    Context,
    EncodedDelivery,
    EventContext,
    EventDispatcher,
    EventDispatchMode,
    EventEnvelope,
    EventIdentity,
    EventSubscription,
    Headers,
    MicroservicesModule,
    MsgspecJsonMessageCodec,
    Payload,
    Publication,
    RabbitMqClientTransport,
    RabbitMqConnectionManager,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqPublisher,
    RabbitMqServerTransport,
    RabbitMqTransport,
    RpcResponseEnvelope,
    RpcTarget,
    ServiceCluster,
    ServiceIdentity,
    SettlementRecommendation,
    TransportError,
    TransportStatus,
    TransportUnroutableError,
    event_handler,
    utc_now,
)

SERVICE = ServiceIdentity("integration", "worker", 1)
EVENT = EventIdentity(
    ServiceIdentity("integration", "publisher", 1),
    "profile-created",
    1,
)


@pytest.fixture(scope="session")
def docker_compose_file() -> str:
    return str(Path(__file__).with_name("docker-compose.yml"))


@pytest.fixture
def rabbitmq_url(docker_services, docker_ip: str) -> str:
    pytest.importorskip("aio_pika")
    port = docker_services.port_for("rabbitmq", 5672)
    url = f"amqp://nestpy:nestpy@{docker_ip}:{port}/"
    docker_services.wait_until_responsive(
        check=lambda: _amqp_is_ready(url),
        timeout=30,
        pause=0.5,
    )
    return url


@pytest.fixture
def rabbitmq_management_url(docker_services, docker_ip: str, rabbitmq_url: str) -> str:
    del rabbitmq_url
    port = docker_services.port_for("rabbitmq", 15672)
    return f"http://{docker_ip}:{port}/api"


def _amqp_is_ready(url: str) -> bool:
    async def connect() -> None:
        import aio_pika

        connection = await aio_pika.connect(url, timeout=1)
        await connection.close()

    try:
        asyncio.run(connect())
    except Exception:
        return False
    return True


@dataclass(slots=True)
class _ClientFactory:
    manager: RabbitMqConnectionManager

    def create(self) -> RabbitMqClientTransport:
        return RabbitMqClientTransport(self.manager)


async def _start_dispatcher(
    rabbitmq_url: str, source: ServiceIdentity, suffix: str
) -> tuple[RabbitMqConnectionManager, EventDispatcher]:
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(
            rabbitmq_url,
            connection_name=f"pytest-event-publisher-{suffix}",
        )
    )
    await manager.start()
    dispatcher = EventDispatcher(source, _ClientFactory(manager))
    try:
        await dispatcher.on_application_bootstrap()
    except BaseException:
        await manager.close()
        raise
    return manager, dispatcher


async def _start_event_server(
    rabbitmq_url: str,
    service: ServiceIdentity,
    subscriptions: tuple[EventSubscription, ...],
    label: str,
    received: list[tuple[str, EncodedDelivery]],
) -> tuple[RabbitMqConnectionManager, RabbitMqServerTransport]:
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(
            rabbitmq_url,
            connection_name=f"pytest-event-consumer-{label}",
        )
    )
    server = RabbitMqServerTransport(
        manager,
        service,
        prefetch=max(1, len(subscriptions)),
    )

    async def dispatch(delivery: EncodedDelivery) -> SettlementRecommendation:
        received.append((label, delivery))
        return SettlementRecommendation.ACK

    try:
        await manager.start()
        await server.prepare(subscriptions=subscriptions)
        await server.start(dispatch)
    except BaseException:
        await server.close()
        await manager.close()
        raise
    return manager, server


async def _close_event_server(
    manager: RabbitMqConnectionManager, server: RabbitMqServerTransport
) -> None:
    try:
        await server.close()
    finally:
        await manager.close()


async def _wait_for_delivery_count(
    received: list[tuple[str, EncodedDelivery]], count: int
) -> None:
    async with asyncio.timeout(5):
        while len(received) < count:
            await asyncio.sleep(0.05)


async def _wait_for_message_id(
    received: list[tuple[str, EncodedDelivery]], message_id
) -> None:
    async with asyncio.timeout(10):
        while not any(delivery.message_id == message_id for _, delivery in received):
            await asyncio.sleep(0.05)


async def _restart_rabbitmq(docker_services) -> None:
    def restart() -> None:
        compose = docker_services._docker_compose
        compose.execute("exec -T rabbitmq rabbitmqctl stop_app")
        compose.execute("exec -T rabbitmq rabbitmqctl start_app")

    await asyncio.to_thread(restart)


class _BlackholeProxy:
    def __init__(self, target_url: str) -> None:
        target = urlsplit(target_url)
        if target.hostname is None or target.port is None:
            raise ValueError("RabbitMQ target URL must include host and port")
        self._target_host = target.hostname
        self._target_port = target.port
        self._server: asyncio.Server | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._forwarding = asyncio.Event()
        self._forwarding.set()

    @property
    def port(self) -> int:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("blackhole proxy is not started")
        return cast(int, self._server.sockets[0].getsockname()[1])

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._accept,
            host="127.0.0.1",
            port=0,
        )

    def url_for(self, target_url: str) -> str:
        target = urlsplit(target_url)
        credentials = ""
        if target.username is not None:
            credentials = target.username
            if target.password is not None:
                credentials += f":{target.password}"
            credentials += "@"
        return urlunsplit(target._replace(netloc=f"{credentials}127.0.0.1:{self.port}"))

    async def block(self) -> None:
        self._forwarding.clear()

    async def unblock(self) -> None:
        self._forwarding.set()

    async def close(self) -> None:
        self._forwarding.set()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _accept(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        task = asyncio.create_task(self._proxy(reader, writer))
        self._tasks.add(task)
        task.add_done_callback(self._task_finished)

    async def _proxy(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        target_writer: asyncio.StreamWriter | None = None
        relays: tuple[asyncio.Task[None], ...] = ()
        try:
            target_reader, target_writer = await asyncio.open_connection(
                self._target_host,
                self._target_port,
            )
            relays = (
                asyncio.create_task(self._relay(reader, target_writer)),
                asyncio.create_task(self._relay(target_reader, writer)),
            )
            _, pending = await asyncio.wait(
                relays,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*relays, return_exceptions=True)
        finally:
            for task in relays:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*relays, return_exceptions=True)
            writer.close()
            await writer.wait_closed()
            if target_writer is not None:
                target_writer.close()
                await target_writer.wait_closed()

    async def _relay(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        while data := await reader.read(65_536):
            await self._forwarding.wait()
            writer.write(data)
            await writer.drain()

    def _task_finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()


async def _wait_for_rabbitmq_ready(docker_services, url: str) -> None:
    await asyncio.to_thread(
        docker_services.wait_until_responsive,
        check=lambda: _amqp_is_ready(url),
        timeout=60,
        pause=0.5,
    )


def _load_management_collection(url: str, resource: str) -> list[dict[str, object]]:
    credentials = base64.b64encode(b"nestpy:nestpy").decode("ascii")
    request = Request(
        f"{url}/{resource}/%2F",
        headers={"Authorization": f"Basic {credentials}"},
    )
    with urlopen(request, timeout=2) as response:  # noqa: S310
        payload = json.load(response)
    if not isinstance(payload, list):
        raise TypeError("RabbitMQ queue response must be a list")
    return [item for item in payload if isinstance(item, dict)]


async def _wait_for_exact_topology(
    url: str,
    prefix: str,
    expected_queue_names: set[str],
    expected_exchange_names: set[str],
    expected_bindings: set[tuple[str, str, str]],
) -> tuple[
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
    set[tuple[str, str, str]],
]:
    async with asyncio.timeout(5):
        while True:
            queues, exchanges, bindings = await asyncio.gather(
                asyncio.to_thread(_load_management_collection, url, "queues"),
                asyncio.to_thread(_load_management_collection, url, "exchanges"),
                asyncio.to_thread(_load_management_collection, url, "bindings"),
            )
            actual = {
                name: item
                for item in queues
                if isinstance(name := item.get("name"), str) and name.startswith(prefix)
            }
            actual_exchanges = {
                name: item
                for item in exchanges
                if isinstance(name := item.get("name"), str)
                and name in expected_exchange_names
            }
            actual_bindings = {
                (source, destination, routing_key)
                for item in bindings
                if item.get("destination_type") == "queue"
                and isinstance(source := item.get("source"), str)
                and source
                and isinstance(destination := item.get("destination"), str)
                and destination.startswith(prefix)
                and isinstance(routing_key := item.get("routing_key"), str)
            }
            if (
                set(actual) == expected_queue_names
                and set(actual_exchanges) == expected_exchange_names
                and actual_bindings == expected_bindings
            ):
                return actual, actual_exchanges, actual_bindings
            await asyncio.sleep(0.1)


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_rabbitmq_rpc_roundtrip_and_event_redelivery(rabbitmq_url: str) -> None:
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(rabbitmq_url, connection_name="pytest-integration")
    )
    server = RabbitMqServerTransport(manager, SERVICE, prefetch=4)
    client = RabbitMqClientTransport(manager, max_pending_replies=8)
    codec = MsgspecJsonMessageCodec()
    event_attempts = []

    async def dispatch(delivery):
        if delivery.routing_key == EVENT.routing_key:
            event_attempts.append(delivery)
            return (
                SettlementRecommendation.RETRY
                if len(event_attempts) == 1
                else SettlementRecommendation.ACK
            )
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

    try:
        for attempt in range(10):
            try:
                await manager.start()
            except RabbitMqConnectionError:
                if attempt == 9:
                    raise
                await asyncio.sleep(0.5)
            else:
                break
        await server.prepare(
            rpc_methods=("ping",),
            subscriptions=(
                EventSubscription(
                    EVENT,
                    "service_pool",
                    "integration",
                    destination=SERVICE,
                ),
            ),
        )
        await server.start(dispatch)
        cluster = ServiceCluster(client, manage_transport=True)
        result = await cluster.service(SERVICE).request(
            "ping", "hello", response_type=str
        )
        assert result == "HELLO"

        await client.publish_event(
            EVENT,
            Publication(
                message_id=uuid4(),
                routing_key=EVENT.routing_key,
                body=b"event",
                headers={},
                mandatory=True,
            ),
        )

        async def wait_for_redelivery() -> None:
            while len(event_attempts) < 2:
                await asyncio.sleep(0.05)

        await asyncio.wait_for(wait_for_redelivery(), timeout=5)
        assert event_attempts[1].redelivered is True
        await cluster.close()
        await server.close()
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_rabbitmq_poison_event_reaches_dead_letter_after_bounded_retries(
    rabbitmq_url: str,
    rabbitmq_management_url: str,
) -> None:
    suffix = uuid4().hex[:8]
    source = ServiceIdentity("poison", f"publisher-{suffix}", 1)
    event = EventIdentity(source, "changed", 1)
    service = ServiceIdentity("poison", f"worker-{suffix}", 1)
    subscription = EventSubscription(
        event,
        "service_pool",
        f"events-{suffix}",
        destination=service,
    )
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(
            rabbitmq_url,
            connection_name=f"pytest-poison-{suffix}",
        )
    )
    server = RabbitMqServerTransport(
        manager,
        service,
        retry_delay_ms=50,
        max_delivery_attempts=2,
    )
    publisher_manager: RabbitMqConnectionManager | None = None
    dispatcher: EventDispatcher | None = None
    deliveries: list[EncodedDelivery] = []

    async def dispatch(delivery: EncodedDelivery) -> SettlementRecommendation:
        deliveries.append(delivery)
        return SettlementRecommendation.RETRY

    topology = compile_event_topology(
        subscription,
        retry_delay_ms=50,
        delivery_limit=2,
    )
    primary = topology.queues[0].name
    dead_letter = f"{primary}.dead-letter"
    try:
        await manager.start()
        await server.prepare(subscriptions=(subscription,))
        await server.start(dispatch)
        publisher_manager, dispatcher = await _start_dispatcher(
            rabbitmq_url, source, suffix
        )
        await dispatcher.publish(
            event.event,
            event.schema_version,
            {"sequence": 1},
            require_route=True,
        )

        async with asyncio.timeout(15):
            while len(deliveries) < 2:
                await asyncio.sleep(0.05)
        assert deliveries[1].redelivered is True
        assert deliveries[1].message_id == deliveries[0].message_id

        async with asyncio.timeout(15):
            while True:
                queues = await asyncio.to_thread(
                    _load_management_collection,
                    rabbitmq_management_url,
                    "queues",
                )
                queue = next(
                    (item for item in queues if item.get("name") == dead_letter),
                    None,
                )
                messages = queue.get("messages") if queue is not None else None
                if isinstance(messages, int) and messages >= 1:
                    break
                await asyncio.sleep(0.1)
        assert len(deliveries) == 2
    finally:
        if dispatcher is not None:
            await dispatcher.close()
        if publisher_manager is not None:
            await publisher_manager.close()
        await server.close()
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_rabbitmq_unknown_event_schema_is_dead_lettered(
    rabbitmq_url: str,
    rabbitmq_management_url: str,
) -> None:
    suffix = uuid4().hex[:8]
    source = ServiceIdentity("schema", f"publisher-{suffix}", 1)
    event = EventIdentity(source, "changed", 1)
    service = ServiceIdentity("schema", f"worker-{suffix}", 1)
    subscription = EventSubscription(
        event,
        "service_pool",
        f"events-{suffix}",
        destination=service,
    )
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(
            rabbitmq_url,
            connection_name=f"pytest-schema-consumer-{suffix}",
        )
    )
    publisher_manager = RabbitMqConnectionManager(
        RabbitMqOptions(
            rabbitmq_url,
            connection_name=f"pytest-schema-publisher-{suffix}",
        )
    )
    server = RabbitMqServerTransport(manager, service)
    codec = MsgspecJsonMessageCodec()
    deliveries: list[EncodedDelivery] = []

    async def dispatch(delivery: EncodedDelivery) -> SettlementRecommendation:
        deliveries.append(delivery)
        decoded = codec.decode_event(delivery.body)
        return (
            SettlementRecommendation.REJECT
            if decoded.schema_version != event.schema_version
            else SettlementRecommendation.ACK
        )

    topology = compile_event_topology(subscription)
    dead_letter = f"{topology.queues[0].name}.dead-letter"
    try:
        await manager.start()
        await server.prepare(subscriptions=(subscription,))
        await server.start(dispatch)
        await publisher_manager.start()
        envelope = EventEnvelope(
            message_id=uuid4(),
            source=source,
            event=event.event,
            schema_version=99,
            occurred_at=utc_now(),
            payload={"poison": True},
        )
        await RabbitMqPublisher(publisher_manager).publish(
            Publication(
                message_id=envelope.message_id,
                routing_key=event.routing_key,
                body=codec.encode_event(envelope),
                headers={},
                mandatory=True,
                native=(event.exchange_name, event.routing_key),
            )
        )

        async with asyncio.timeout(15):
            while not deliveries:
                await asyncio.sleep(0.05)
        async with asyncio.timeout(15):
            while True:
                queues = await asyncio.to_thread(
                    _load_management_collection,
                    rabbitmq_management_url,
                    "queues",
                )
                queue = next(
                    (item for item in queues if item.get("name") == dead_letter),
                    None,
                )
                messages = queue.get("messages") if queue is not None else None
                if isinstance(messages, int) and messages >= 1:
                    break
                await asyncio.sleep(0.1)
        assert len(deliveries) == 1
    finally:
        await server.close()
        await publisher_manager.close()
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_rabbitmq_broker_restart_redeclares_topology_and_reopens_intake(
    rabbitmq_url: str,
    docker_services,
) -> None:
    suffix = uuid4().hex[:8]
    source = ServiceIdentity("recovery", f"publisher-{suffix}", 1)
    event = EventIdentity(source, "changed", 1)
    service = ServiceIdentity("recovery", f"worker-{suffix}", 1)
    subscription = EventSubscription(
        event,
        "service_pool",
        f"events-{suffix}",
        destination=service,
    )
    received: list[tuple[str, EncodedDelivery]] = []
    server_manager: RabbitMqConnectionManager | None = None
    server: RabbitMqServerTransport | None = None
    publisher_manager: RabbitMqConnectionManager | None = None
    dispatcher: EventDispatcher | None = None
    try:
        server_manager, server = await _start_event_server(
            rabbitmq_url,
            service,
            (subscription,),
            f"{suffix}-server",
            received,
        )
        publisher_manager, dispatcher = await _start_dispatcher(
            rabbitmq_url, source, suffix
        )
        assert server_manager is not None
        assert server is not None
        assert publisher_manager is not None
        assert dispatcher is not None
        before = await dispatcher.publish(
            event.event,
            event.schema_version,
            {"sequence": "before"},
            require_route=True,
        )
        await _wait_for_delivery_count(received, 1)
        assert received[0][1].message_id == before.message_id

        await _restart_rabbitmq(docker_services)
        await _wait_for_rabbitmq_ready(docker_services, rabbitmq_url)

        async with asyncio.timeout(45):
            while not (
                server_manager.status.value == "ready"
                and server.status is TransportStatus.RUNNING
                and publisher_manager.status.value == "ready"
                and dispatcher.accepting
            ):
                await asyncio.sleep(0.1)

        after = await dispatcher.publish(
            event.event,
            event.schema_version,
            {"sequence": "after"},
            require_route=True,
        )
        await _wait_for_message_id(received, after.message_id)
        assert after.message_id in {delivery.message_id for _, delivery in received}
    finally:
        try:
            if dispatcher is not None:
                await dispatcher.close()
        finally:
            try:
                if publisher_manager is not None:
                    await publisher_manager.close()
            finally:
                if server_manager is not None and server is not None:
                    await _close_event_server(server_manager, server)


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_rabbitmq_network_blackhole_is_bounded_and_recovers(
    rabbitmq_url: str,
) -> None:
    proxy = _BlackholeProxy(rabbitmq_url)
    await proxy.start()
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(
            proxy.url_for(rabbitmq_url),
            connection_name="pytest-network-blackhole",
            heartbeat=1,
            connection_timeout=2,
        )
    )
    blocked = False
    try:
        await manager.start()
        await proxy.block()
        blocked = True

        async with asyncio.timeout(15):
            while manager.status.value == "ready":
                await asyncio.sleep(0.1)
        assert manager.status.value == "recovering"
    finally:
        if blocked:
            await proxy.unblock()
            async with asyncio.timeout(30):
                while manager.status.value != "ready":
                    await asyncio.sleep(0.1)
        await manager.close()
        await proxy.close()


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_rabbitmq_network_blackhole_before_connect_is_bounded(
    rabbitmq_url: str,
) -> None:
    proxy = _BlackholeProxy(rabbitmq_url)
    await proxy.start()
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(
            proxy.url_for(rabbitmq_url),
            connection_name="pytest-network-before-connect",
            heartbeat=1,
            connection_timeout=2,
        )
    )
    replacement: RabbitMqConnectionManager | None = None
    try:
        await proxy.block()
        with pytest.raises(RabbitMqConnectionError):
            await asyncio.wait_for(manager.start(), timeout=8)
        assert manager.status.value == "failed"
        await proxy.unblock()
        replacement = RabbitMqConnectionManager(
            RabbitMqOptions(
                rabbitmq_url,
                connection_name="pytest-network-before-connect-replacement",
            )
        )
        await replacement.start()
        assert replacement.status.value == "ready"
    finally:
        await manager.close()
        if replacement is not None:
            await replacement.close()
        await proxy.close()


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_rabbitmq_confirm_uncertainty_fences_and_recovers(
    rabbitmq_url: str,
) -> None:
    proxy = _BlackholeProxy(rabbitmq_url)
    await proxy.start()
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(
            proxy.url_for(rabbitmq_url),
            connection_name="pytest-confirm-uncertainty",
            heartbeat=1,
            connection_timeout=2,
        )
    )
    blocked = False
    try:
        await manager.start()
        await proxy.block()
        blocked = True
        publication = Publication(
            message_id=uuid4(),
            routing_key="integration.confirm-uncertainty",
            body=b"payload",
            headers={},
            mandatory=True,
        )

        with pytest.raises(TransportIndeterminateError):
            await asyncio.wait_for(
                RabbitMqPublisher(manager).publish(publication),
                timeout=15,
            )
        assert manager.generation > 0
    finally:
        if blocked:
            await proxy.unblock()
            async with asyncio.timeout(30):
                while manager.status.value != "ready":
                    await asyncio.sleep(0.1)
        await manager.close()
        await proxy.close()


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_rabbitmq_deleted_reply_route_does_not_republish_request(
    rabbitmq_url: str,
) -> None:
    service = ServiceIdentity("reply-route", f"worker-{uuid4().hex[:8]}", 1)
    target = RpcTarget(service, "run", 1)
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(rabbitmq_url, connection_name="pytest-deleted-reply")
    )
    server = RabbitMqServerTransport(manager, service)
    client = RabbitMqClientTransport(manager, max_pending_replies=1)
    cluster = ServiceCluster(client)
    codec = MsgspecJsonMessageCodec()
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    request_task: asyncio.Task[object] | None = None

    async def dispatch(delivery: EncodedDelivery) -> SettlementRecommendation:
        nonlocal calls
        calls += 1
        request = codec.decode_request(delivery.body)
        entered.set()
        await release.wait()
        response = RpcResponseEnvelope(
            message_id=uuid4(),
            correlation_id=request.correlation_id,
            completed_at=utc_now(),
            result="done",
        )
        try:
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
        except TransportUnroutableError:
            return SettlementRecommendation.ACK
        return SettlementRecommendation.ACK

    try:
        await manager.start()
        await server.prepare(rpc_methods=(target.method,))
        await server.start(dispatch)
        await client.start()
        request_task = asyncio.create_task(
            cluster.service(service).request(
                target.method,
                "payload",
                response_type=str,
                timeout=3,
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=5)
        # The exclusive reply queue is deleted when its client consumer closes.
        await client.close()
        release.set()

        with pytest.raises((RpcTimeoutError, RpcOutcomeUnknownError)):
            await request_task
        request_task = None
        await asyncio.sleep(0.5)
        assert calls == 1
    finally:
        release.set()
        if request_task is not None:
            request_task.cancel()
            await asyncio.gather(request_task, return_exceptions=True)
        try:
            await cluster.close()
        finally:
            try:
                await server.close()
            finally:
                await manager.close()


async def _run_rabbitmq_blackhole_redelivery_case(
    rabbitmq_url: str,
    *,
    during_reply: bool,
) -> int:
    suffix = uuid4().hex[:8]
    service = ServiceIdentity("blackhole", f"worker-{suffix}", 1)
    target = RpcTarget(service, "run", 1)
    proxy = _BlackholeProxy(rabbitmq_url)
    await proxy.start()
    server_manager = RabbitMqConnectionManager(
        RabbitMqOptions(
            proxy.url_for(rabbitmq_url),
            connection_name=f"pytest-blackhole-server-{suffix}",
            heartbeat=1,
            connection_timeout=2,
        )
    )
    client_manager = RabbitMqConnectionManager(
        RabbitMqOptions(
            rabbitmq_url,
            connection_name=f"pytest-blackhole-client-{suffix}",
        )
    )
    server = RabbitMqServerTransport(server_manager, service, prefetch=1)
    client = RabbitMqClientTransport(client_manager, max_pending_replies=1)
    cluster = ServiceCluster(client, manage_transport=True)
    codec = MsgspecJsonMessageCodec()
    phase_started = asyncio.Event()
    release_phase = asyncio.Event()
    calls = 0
    message_ids: list[object] = []
    request_task: asyncio.Task[object] | None = None
    blocked = False

    async def dispatch(delivery: EncodedDelivery) -> SettlementRecommendation:
        nonlocal calls
        calls += 1
        request = codec.decode_request(delivery.body)
        message_ids.append(request.message_id)
        if calls == 1:
            phase_started.set()
            await release_phase.wait()
            if not during_reply:
                return SettlementRecommendation.ACK
        response = RpcResponseEnvelope(
            message_id=uuid4(),
            correlation_id=request.correlation_id,
            completed_at=utc_now(),
            result="done",
        )
        try:
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
        except TransportError:
            if calls == 1 and during_reply:
                return SettlementRecommendation.UNSETTLED
            raise
        return SettlementRecommendation.ACK

    try:
        await server_manager.start()
        await server.prepare(rpc_methods=(target.method,))
        await server.start(dispatch)
        await client_manager.start()
        request_task = asyncio.create_task(
            cluster.service(service).request(
                target.method,
                "payload",
                response_type=str,
                timeout=30,
            )
        )
        await asyncio.wait_for(phase_started.wait(), timeout=5)
        await proxy.block()
        blocked = True
        async with asyncio.timeout(15):
            while server_manager.status.value == "ready":
                await asyncio.sleep(0.1)
        release_phase.set()
        await proxy.unblock()
        blocked = False
        async with asyncio.timeout(30):
            while server_manager.status.value != "ready":
                await asyncio.sleep(0.1)
        result = await asyncio.wait_for(request_task, timeout=30)
        request_task = None
        assert result == "done"
        assert calls >= 2
        assert len(set(message_ids)) == 1
        return calls
    finally:
        release_phase.set()
        if blocked:
            await proxy.unblock()
        if request_task is not None:
            request_task.cancel()
            await asyncio.gather(request_task, return_exceptions=True)
        try:
            await cluster.close()
        finally:
            try:
                await server.close()
            finally:
                try:
                    await client_manager.close()
                finally:
                    try:
                        await server_manager.close()
                    finally:
                        await proxy.close()


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_rabbitmq_blackhole_during_handler_redelivers_without_client_republish(
    rabbitmq_url: str,
) -> None:
    assert (
        await _run_rabbitmq_blackhole_redelivery_case(
            rabbitmq_url,
            during_reply=False,
        )
        >= 2
    )


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_rabbitmq_blackhole_during_reply_redelivers_unsettled_request(
    rabbitmq_url: str,
) -> None:
    assert (
        await _run_rabbitmq_blackhole_redelivery_case(
            rabbitmq_url,
            during_reply=True,
        )
        >= 2
    )


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_rabbitmq_rpc_pending_request_is_unknown_across_broker_restart(
    rabbitmq_url: str,
    docker_services,
) -> None:
    suffix = uuid4().hex[:8]
    service = ServiceIdentity("rpc-recovery", f"worker-{suffix}", 1)
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(
            rabbitmq_url,
            connection_name=f"pytest-rpc-recovery-{suffix}",
        )
    )
    server = RabbitMqServerTransport(manager, service)
    client = RabbitMqClientTransport(manager, max_pending_replies=4)
    cluster = ServiceCluster(client)
    codec = MsgspecJsonMessageCodec()
    first_request_started = asyncio.Event()
    block_first_request = asyncio.Event()
    request_task: asyncio.Task[object] | None = None
    calls = 0

    async def dispatch(delivery: EncodedDelivery) -> SettlementRecommendation:
        nonlocal calls
        calls += 1
        request = codec.decode_request(delivery.body)
        if calls == 1:
            first_request_started.set()
            await block_first_request.wait()
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

    try:
        await manager.start()
        await server.prepare(rpc_methods=("run",))
        await server.start(dispatch)
        await client.start()
        request_task = asyncio.create_task(
            cluster.service(service).request(
                "run",
                "before",
                response_type=str,
                timeout=30,
            )
        )
        await asyncio.wait_for(first_request_started.wait(), timeout=5)

        await _restart_rabbitmq(docker_services)
        await _wait_for_rabbitmq_ready(docker_services, rabbitmq_url)

        with pytest.raises(RpcOutcomeUnknownError):
            await asyncio.wait_for(request_task, timeout=15)
            request_task = None

        async with asyncio.timeout(45):
            while not (
                manager.status.value == "ready"
                and server.status is TransportStatus.RUNNING
                and client.status is TransportStatus.RUNNING
            ):
                await asyncio.sleep(0.1)

        result = await cluster.service(service).request(
            "run",
            "after",
            response_type=str,
            timeout=30,
        )
        assert result == "AFTER"
    finally:
        block_first_request.set()
        if request_task is not None:
            request_task.cancel()
            await asyncio.gather(request_task, return_exceptions=True)
        await cluster.close()
        await client.close()
        await server.close()
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_mandatory_event_without_subscriber_is_unroutable(
    rabbitmq_url: str,
) -> None:
    suffix = uuid4().hex[:8]
    source = ServiceIdentity("integration", f"publisher-{suffix}", 1)
    received: list[tuple[str, object, object, object]] = []

    @controller()
    class EventController:
        @event_handler(
            source,
            "profile-created",
            schema_version=1,
            mode=EventDispatchMode.SERVICE_POOL,
            subscription=f"first-{suffix}",
        )
        async def first(
            self,
            payload: Annotated[dict[str, object], Payload()],
            headers: Annotated[dict[str, object], Headers()],
            context: Annotated[EventContext, Context()],
        ) -> None:
            received.append(("first", payload, headers, context.correlation_id))

        @event_handler(
            source,
            "profile-created",
            schema_version=1,
            mode=EventDispatchMode.SERVICE_POOL,
            subscription=f"second-{suffix}",
        )
        async def second(
            self,
            payload: Annotated[dict[str, object], Payload()],
            headers: Annotated[dict[str, object], Headers()],
            context: Annotated[EventContext, Context()],
        ) -> None:
            received.append(("second", payload, headers, context.correlation_id))

    microservices = MicroservicesModule.for_root(
        source,
        transport=RabbitMqTransport(),
        imports=(
            RabbitMqModule.for_root(
                RabbitMqOptions(
                    rabbitmq_url,
                    connection_name=f"pytest-dispatcher-{suffix}",
                )
            ),
        ),
    )

    @module(imports=(microservices,), controllers=(EventController,))
    class ApplicationModule:
        pass

    application = await TestingModule.create(ApplicationModule).compile()
    dispatcher = await application.resolve(EventDispatcher)
    assert isinstance(dispatcher, EventDispatcher)
    correlation_id = uuid4()
    try:
        receipt = await dispatcher.publish(
            "profile-created",
            1,
            {"handle": "river"},
            headers={"trace": suffix},
            correlation_id=correlation_id,
            require_route=True,
        )

        async with asyncio.timeout(5):
            while len(received) < 2:
                await asyncio.sleep(0.05)

        assert receipt.routed is True
        assert {item[0] for item in received} == {"first", "second"}
        assert all(item[1] == {"handle": "river"} for item in received)
        assert all(item[2] == {"trace": suffix} for item in received)
        assert all(item[3] == correlation_id for item in received)

        unrouted = await dispatcher.publish("orphaned-event", 1, None)
        assert unrouted.routed is False
        with pytest.raises(TransportUnroutableError):
            await dispatcher.publish("orphaned-event", 1, None, require_route=True)
    finally:
        await application.close()


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_rabbitmq_event_mode_cardinality_and_exact_queue_count(
    rabbitmq_url: str,
    rabbitmq_management_url: str,
) -> None:
    suffix = uuid4().hex[:8]
    source = ServiceIdentity("cardinality", f"publisher-{suffix}", 1)
    event = EventIdentity(source, "changed", 1)
    service_a = ServiceIdentity("cardinality", f"worker-a-{suffix}", 1)
    service_b = ServiceIdentity("cardinality", f"worker-b-{suffix}", 1)
    pool_a = EventSubscription(
        event,
        "service_pool",
        f"shared-{suffix}",
        destination=service_a,
    )
    pool_b = EventSubscription(
        event,
        "service_pool",
        f"projection-{suffix}",
        destination=service_b,
    )
    singleton = EventSubscription(event, "singleton", f"global-{suffix}")
    broadcasts = tuple(
        EventSubscription(
            event,
            "broadcast",
            f"cache-{suffix}",
            destination=service_a,
        )
        for _ in range(3)
    )
    assert len({item.instance_id for item in broadcasts}) == 3

    server_specs = (
        (service_a, (pool_a, singleton, broadcasts[0]), "a"),
        (service_a, (pool_a, broadcasts[1]), "b"),
        (service_a, (broadcasts[2],), "c"),
        (service_b, (pool_b, singleton), "d"),
    )
    received: list[tuple[str, EncodedDelivery]] = []
    servers: list[tuple[RabbitMqConnectionManager, RabbitMqServerTransport]] = []
    publisher_manager: RabbitMqConnectionManager | None = None
    dispatcher: EventDispatcher | None = None
    try:
        for service, subscriptions, label in server_specs:
            servers.append(
                await _start_event_server(
                    rabbitmq_url,
                    service,
                    subscriptions,
                    f"{suffix}-{label}",
                    received,
                )
            )

        queue_prefix = (
            f"nestpy.event.{source.label}.{event.event}.v{event.schema_version}"
        )
        durable_primaries = {
            f"{queue_prefix}--pool.{service_a.label}.{pool_a.subscription}",
            f"{queue_prefix}--pool.{service_b.label}.{pool_b.subscription}",
            f"{queue_prefix}--singleton.{singleton.subscription}",
        }
        broadcast_queues = {
            f"{queue_prefix}--broadcast.{service_a.label}.{item.subscription}."
            f"{item.instance_id}"
            for item in broadcasts
        }
        retry_exchanges = {f"{name}.retry" for name in durable_primaries}
        assert all(len(name.encode("utf-8")) <= 127 for name in retry_exchanges)
        expected_queue_names = {
            *durable_primaries,
            *(f"{name}.dead-letter" for name in durable_primaries),
            *(f"{name}.retry" for name in durable_primaries),
            *broadcast_queues,
        }
        assert len(expected_queue_names) == 12
        expected_exchange_names = {
            event.exchange_name,
            "nestpy.dead-letter",
            *retry_exchanges,
        }
        expected_bindings = (
            {
                (event.exchange_name, name, event.routing_key)
                for name in durable_primaries | broadcast_queues
            }
            | {
                ("nestpy.dead-letter", f"{name}.dead-letter", name)
                for name in durable_primaries
            }
            | {
                (f"{name}.retry", f"{name}.retry", event.routing_key)
                for name in durable_primaries
            }
        )
        (
            actual_queues,
            actual_exchanges,
            actual_bindings,
        ) = await _wait_for_exact_topology(
            rabbitmq_management_url,
            queue_prefix,
            expected_queue_names,
            expected_exchange_names,
            expected_bindings,
        )
        assert actual_bindings == expected_bindings
        for actual in actual_exchanges.values():
            assert actual["type"] == "topic"
            assert actual["durable"] is True
            assert actual["auto_delete"] is False
            assert actual["internal"] is False

        for name, actual in actual_queues.items():
            arguments = actual["arguments"]
            assert isinstance(arguments, dict)
            arguments = cast(dict[str, object], arguments)
            assert actual["exclusive"] is (name in broadcast_queues)
            assert actual["auto_delete"] is (name in broadcast_queues)
            assert actual["durable"] is (name not in broadcast_queues)
            if name in broadcast_queues:
                assert actual["type"] == "classic"
                assert arguments == {"x-queue-type": "classic"}
            elif name.endswith(".dead-letter"):
                assert actual["type"] == "quorum"
                assert arguments == {
                    "x-queue-type": "quorum",
                    "x-max-length": 10_000,
                    "x-overflow": "drop-head",
                }
            elif name.endswith(".retry"):
                assert actual["type"] == "classic"
                assert arguments == {
                    "x-queue-type": "classic",
                    "x-message-ttl": 1_000,
                    "x-dead-letter-exchange": event.exchange_name,
                    "x-max-length": 10_000,
                    "x-overflow": "reject-publish",
                }
            else:
                assert actual["type"] == "quorum"
                assert arguments == {
                    "x-queue-type": "quorum",
                    "x-delivery-limit": 5,
                    "x-dead-letter-exchange": "nestpy.dead-letter",
                    "x-dead-letter-routing-key": name,
                }

        publisher_manager, dispatcher = await _start_dispatcher(
            rabbitmq_url, source, suffix
        )
        receipt = await dispatcher.publish(
            event.event,
            event.schema_version,
            {"sequence": 1},
            require_route=True,
        )
        assert receipt.routed is True
        await _wait_for_delivery_count(received, 6)
        await asyncio.sleep(0.2)

        subscriptions = [delivery.subscription for _, delivery in received]
        assert len(received) == 6
        assert subscriptions.count(pool_a) == 1
        assert subscriptions.count(pool_b) == 1
        assert subscriptions.count(singleton) == 1
        assert all(subscriptions.count(item) == 1 for item in broadcasts)
    finally:
        if dispatcher is not None:
            await dispatcher.close()
        if publisher_manager is not None:
            await publisher_manager.close()
        for manager, server in reversed(servers):
            await _close_event_server(manager, server)


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_ephemeral_broadcast_misses_events_while_offline(
    rabbitmq_url: str,
) -> None:
    suffix = uuid4().hex[:8]
    source = ServiceIdentity("ephemeral", f"publisher-{suffix}", 1)
    event = EventIdentity(source, "invalidated", 1)
    service = ServiceIdentity("ephemeral", f"worker-{suffix}", 1)
    first_subscription = EventSubscription(
        event,
        "broadcast",
        f"cache-{suffix}",
        destination=service,
    )
    received: list[tuple[str, EncodedDelivery]] = []
    first_manager, first_server = await _start_event_server(
        rabbitmq_url,
        service,
        (first_subscription,),
        f"{suffix}-first",
        received,
    )
    publisher_manager, dispatcher = await _start_dispatcher(
        rabbitmq_url, source, suffix
    )
    second_manager: RabbitMqConnectionManager | None = None
    second_server: RabbitMqServerTransport | None = None
    try:
        await _close_event_server(first_manager, first_server)

        async with asyncio.timeout(5):
            while True:
                probe = await dispatcher.publish(event.event, 1, {"probe": True})
                if probe.routed is False:
                    break
                await asyncio.sleep(0.05)
        offline = await dispatcher.publish(event.event, 1, {"state": "offline"})
        assert offline.routed is False

        second_subscription = EventSubscription(
            event,
            "broadcast",
            f"cache-{suffix}",
            destination=service,
        )
        assert second_subscription.instance_id != first_subscription.instance_id
        second_manager, second_server = await _start_event_server(
            rabbitmq_url,
            service,
            (second_subscription,),
            f"{suffix}-second",
            received,
        )
        await asyncio.sleep(0.2)
        assert received == []

        online = await dispatcher.publish(
            event.event,
            1,
            {"state": "online"},
            require_route=True,
        )
        await _wait_for_delivery_count(received, 1)
        assert [delivery.message_id for _, delivery in received] == [online.message_id]
    finally:
        await dispatcher.close()
        await publisher_manager.close()
        await _close_event_server(first_manager, first_server)
        if second_manager is not None and second_server is not None:
            await _close_event_server(second_manager, second_server)


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_reliable_broadcast_rejects_duplicate_and_retains_across_restart(
    rabbitmq_url: str,
    rabbitmq_management_url: str,
) -> None:
    from aiormq.exceptions import ChannelAccessRefused

    suffix = uuid4().hex[:8]
    source = ServiceIdentity("reliable", f"publisher-{suffix}", 1)
    event = EventIdentity(source, "changed", 1)
    service = ServiceIdentity("reliable", f"worker-{suffix}", 1)
    subscription = EventSubscription(
        event,
        "broadcast",
        f"cache-{suffix}",
        destination=service,
        instance_id=f"instance-{suffix}",
        reliable=True,
    )
    received: list[tuple[str, EncodedDelivery]] = []
    first_manager, first_server = await _start_event_server(
        rabbitmq_url,
        service,
        (subscription,),
        f"{suffix}-first",
        received,
    )
    publisher_manager, dispatcher = await _start_dispatcher(
        rabbitmq_url, source, suffix
    )
    duplicate_manager = RabbitMqConnectionManager(
        RabbitMqOptions(
            rabbitmq_url,
            connection_name=f"pytest-event-consumer-{suffix}-duplicate",
        )
    )
    duplicate_server = RabbitMqServerTransport(duplicate_manager, service)
    restarted_manager: RabbitMqConnectionManager | None = None
    restarted_server: RabbitMqServerTransport | None = None

    async def duplicate_dispatch(
        delivery: EncodedDelivery,
    ) -> SettlementRecommendation:
        del delivery
        return SettlementRecommendation.ACK

    try:
        queue_prefix = (
            f"nestpy.event.{source.label}.{event.event}.v{event.schema_version}"
        )
        primary_queue = (
            f"{queue_prefix}--broadcast.{service.label}."
            f"{subscription.subscription}.{subscription.instance_id}"
        )
        retry_exchange = f"{primary_queue}.retry"
        if len(retry_exchange.encode("utf-8")) > 127:
            retry_exchange = (
                f"nestpy.retry.{sha256(primary_queue.encode('utf-8')).hexdigest()}"
            )
        expected_queue_names = {
            primary_queue,
            f"{primary_queue}.dead-letter",
            f"{primary_queue}.retry",
        }
        expected_exchange_names = {
            event.exchange_name,
            "nestpy.dead-letter",
            retry_exchange,
        }
        expected_bindings = {
            (event.exchange_name, primary_queue, event.routing_key),
            (
                "nestpy.dead-letter",
                f"{primary_queue}.dead-letter",
                primary_queue,
            ),
            (retry_exchange, f"{primary_queue}.retry", event.routing_key),
        }
        actual_queues, _, _ = await _wait_for_exact_topology(
            rabbitmq_management_url,
            queue_prefix,
            expected_queue_names,
            expected_exchange_names,
            expected_bindings,
        )
        reliable_queue = actual_queues[primary_queue]
        assert reliable_queue["type"] == "classic"
        assert reliable_queue["durable"] is True
        assert reliable_queue["exclusive"] is False
        assert reliable_queue["auto_delete"] is False
        reliable_arguments = reliable_queue["arguments"]
        assert isinstance(reliable_arguments, dict)
        assert cast(dict[str, object], reliable_arguments) == {
            "x-queue-type": "classic",
            "x-expires": 604_800_000,
            "x-message-ttl": 86_400_000,
            "x-dead-letter-exchange": "nestpy.dead-letter",
            "x-dead-letter-routing-key": primary_queue,
        }

        await duplicate_manager.start()
        await duplicate_server.prepare(subscriptions=(subscription,))
        with pytest.raises(ChannelAccessRefused, match="exclusive use"):
            await duplicate_server.start(duplicate_dispatch)

        live = await dispatcher.publish(
            event.event,
            1,
            {"state": "live"},
            require_route=True,
        )
        await _wait_for_delivery_count(received, 1)
        assert received[0][1].message_id == live.message_id

        await _close_event_server(duplicate_manager, duplicate_server)
        await _close_event_server(first_manager, first_server)
        offline = await dispatcher.publish(
            event.event,
            1,
            {"state": "offline"},
            require_route=True,
        )
        assert offline.routed is True

        restarted_manager, restarted_server = await _start_event_server(
            rabbitmq_url,
            service,
            (subscription,),
            f"{suffix}-restarted",
            received,
        )
        await _wait_for_delivery_count(received, 2)
        assert [delivery.message_id for _, delivery in received] == [
            live.message_id,
            offline.message_id,
        ]
    finally:
        await dispatcher.close()
        await publisher_manager.close()
        await _close_event_server(duplicate_manager, duplicate_server)
        await _close_event_server(first_manager, first_server)
        if restarted_manager is not None and restarted_server is not None:
            await _close_event_server(restarted_manager, restarted_server)


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_rabbitmq_transport_conformance(rabbitmq_url: str) -> None:
    suffix = uuid4().hex[:8]
    service = ServiceIdentity("conformance", f"worker-{suffix}", 1)
    event = EventIdentity(
        ServiceIdentity("conformance", f"publisher-{suffix}", 1),
        "changed",
        1,
    )
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(
            rabbitmq_url,
            connection_name="pytest-conformance",
            retry_delay_ms=50,
            max_delivery_attempts=3,
        )
    )
    try:
        await manager.start()
        await assert_transport_conformance(
            RabbitMqServerTransport(
                manager,
                service,
                prefetch=2,
                retry_delay_ms=50,
                max_delivery_attempts=3,
            ),
            RabbitMqClientTransport(manager, max_pending_replies=8),
            service=service,
            event=event,
            max_delivery_attempts=3,
            max_inflight_deliveries=2,
            timeout=5,
        )
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_rabbitmq_server_close_drains_admitted_callback(
    rabbitmq_url: str,
) -> None:
    service = ServiceIdentity("lifecycle", f"worker-{uuid4().hex[:8]}", 1)
    target = RpcTarget(service, "wait", 1)
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(rabbitmq_url, connection_name="pytest-close-drain")
    )
    server = RabbitMqServerTransport(manager, service)
    client = RabbitMqClientTransport(manager, max_pending_replies=1)
    admitted = asyncio.Event()
    release = asyncio.Event()

    async def dispatch(delivery):
        del delivery
        admitted.set()
        await release.wait()
        return SettlementRecommendation.ACK

    try:
        await manager.start()
        await server.prepare(rpc_methods=(target.method,))
        await server.start(dispatch)
        await client.start()
        await client.publish_rpc(
            target,
            Publication(
                uuid4(),
                target.routing_key,
                b"request",
                {},
                correlation_id=uuid4(),
                reply_to=client.reply_to,
            ),
        )
        await asyncio.wait_for(admitted.wait(), timeout=5)

        closing = asyncio.create_task(server.close())
        await asyncio.sleep(0.05)
        assert not closing.done()
        release.set()
        await asyncio.wait_for(closing, timeout=5)

        assert not server._callback_tasks
        await client.close()
    finally:
        release.set()
        await server.close()
        await client.close()
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_rabbitmq_forced_shutdown_fails_active_rpc_and_cleans_tasks(
    rabbitmq_url: str,
) -> None:
    service = ServiceIdentity("shutdown", f"worker-{uuid4().hex[:8]}", 1)
    target = RpcTarget(service, "wait", 1)
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(rabbitmq_url, connection_name="pytest-forced-shutdown")
    )
    server = RabbitMqServerTransport(manager, service)
    client = RabbitMqClientTransport(manager, max_pending_replies=1)
    cluster = ServiceCluster(client, manage_transport=True)
    admitted = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()
    request_task: asyncio.Task[object] | None = None

    async def dispatch(delivery: EncodedDelivery) -> SettlementRecommendation:
        del delivery
        admitted.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return SettlementRecommendation.ACK

    try:
        await manager.start()
        await server.prepare(rpc_methods=(target.method,))
        await server.start(dispatch)
        request_task = asyncio.create_task(
            cluster.service(service).request(
                target.method,
                "request",
                response_type=str,
                timeout=10,
            )
        )
        await asyncio.wait_for(admitted.wait(), timeout=5)

        await cluster.close()
        await server.close()
        assert cluster._router_task is None or cluster._router_task.done()
        assert cluster._status_task is None or cluster._status_task.done()
        assert not client._callback_tasks
        assert not manager._listener_tasks

        with pytest.raises(RpcOutcomeUnknownError):
            await request_task
        request_task = None
        assert cancelled.is_set()
        assert not server._callback_tasks
    finally:
        release.set()
        if request_task is not None:
            request_task.cancel()
            await asyncio.gather(request_task, return_exceptions=True)
        await cluster.close()
        await server.close()
        await manager.close()

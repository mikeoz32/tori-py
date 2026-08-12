from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, cast
from uuid import uuid4

import pytest
from nestpy import controller, module
from nestpy.testing import TestingModule
from nestpy_persistent_streams import (
    PersistentStreamsModule,
    PersistentStreamsOptions,
    PersistentStreamsRuntimeOptions,
    StreamBinding,
    StreamPayload,
    StreamPublisher,
    StreamRuntime,
    stream_handler,
)
from persistent_streams import (
    AppendRequest,
    Beginning,
    CheckpointStrategy,
    End,
    ExactOffset,
    ExternalCheckpointStrategy,
    InMemoryCheckpointStore,
    OwnershipError,
    PublishingConflictError,
    PublishOutcome,
    StreamDefinition,
    Subscription,
)
from persistent_streams_rabbitmq import (
    EnvelopeError,
    RabbitMqConnectionOptions,
    RabbitMqPartitionLease,
    RabbitMqPersistentLog,
    RabbitMqPersistentStreamsModule,
    RabbitMqPersistentStreamsOptions,
)
from rstream import Producer, RouteType, SuperStreamProducer

pytestmark = [pytest.mark.asyncio, pytest.mark.rabbitmq]


@dataclass(frozen=True)
class BrokerEvent:
    value: str


class BrokerCodec:
    def encode(self, payload: object) -> bytes:
        return cast(BrokerEvent, payload).value.encode()

    def decode(self, payload: bytes, target: type[object]) -> object:
        return target(payload.decode())


class BrokerKey:
    def resolve(self, payload: object) -> bytes:
        return cast(BrokerEvent, payload).value.encode()


@pytest.fixture(autouse=True)
def require_broker() -> None:
    if os.environ.get("RPS0_RABBITMQ") != "1":
        pytest.skip("set RPS0_RABBITMQ=1 for RabbitMQ adapter tests")


@pytest.fixture(scope="module", autouse=True)
def clean_production_broker(rabbitmq_compose) -> None:
    if os.environ.get("RPS0_RABBITMQ") == "1":
        rabbitmq_compose.clean_start()


def adapter() -> RabbitMqPersistentLog:
    return RabbitMqPersistentLog(
        RabbitMqPersistentStreamsOptions(
            RabbitMqConnectionOptions("127.0.0.1", "streams", "streams"),
            broker_managed_single_instance=True,
        )
    )


async def next_record(lease):
    async with asyncio.timeout(10):
        while True:
            record = await lease.next_record()
            if record is not None:
                return record
            await asyncio.sleep(0.02)


async def delete(log: RabbitMqPersistentLog, definition: StreamDefinition) -> None:
    producer, _ = log.unwrap()
    if definition.partition_count == 1:
        assert producer is not None
        await producer.delete_stream(definition.name, missing_ok=True)
        return

    async def route(message: object) -> str:
        del message
        return "0"

    owner = SuperStreamProducer(
        host="127.0.0.1",
        username="streams",
        password="streams",
        super_stream=definition.name,
        routing_extractor=route,
        routing=RouteType.Key,
    )
    await owner.start()
    try:
        await owner.delete_super_stream(definition.name, missing_ok=True)
    finally:
        await owner.close()


async def test_regular_publish_read_broker_and_external_resume() -> None:
    log = adapter()
    consumers: list[RabbitMqPersistentLog] = []
    definition = StreamDefinition(f"rps-regular-{uuid4().hex}", 1)
    try:
        await log.declare_stream(definition)
        await log.start()
        unnamed = AppendRequest(uuid4(), b"key", b"first", {"trace": b"one"})
        named = AppendRequest(
            uuid4(),
            b"key",
            b"second",
            producer_name="acceptance-producer",
            publishing_id=41,
        )
        assert (
            await log.append(definition.name, unnamed)
        ).outcome is PublishOutcome.CONFIRMED
        assert (
            await log.append(definition.name, named)
        ).outcome is PublishOutcome.CONFIRMED
        assert (
            await log.append(definition.name, named)
        ).outcome is PublishOutcome.DEDUPLICATED

        page = await log.read(definition.name, 0, 0, 10)
        assert [record.payload for record in page.records] == [b"first", b"second"]
        assert page.records[0].headers == {"trace": b"one"}
        assert page.records[0].offset < page.records[1].offset

        broker_log = adapter()
        consumers.append(broker_log)
        await broker_log.declare_stream(definition)
        broker = await broker_log.acquire(
            Subscription(definition.name, "broker", "replica-a", Beginning()),
            0,
            strategy=CheckpointStrategy.BROKER_MANAGED,
        )
        await broker_log.start()
        first = await next_record(broker)
        await broker.checkpoint(first)
        await broker.release()
        await broker_log.close()
        restarted_log = adapter()
        consumers.append(restarted_log)
        await restarted_log.declare_stream(definition)
        restarted = await restarted_log.acquire(
            Subscription(definition.name, "broker", "replica-b", Beginning()),
            0,
            strategy=CheckpointStrategy.BROKER_MANAGED,
        )
        await restarted_log.start()
        second = await next_record(restarted)
        assert second.payload == b"second"
        await restarted.checkpoint(second)
        await restarted.release()

        strategy = ExternalCheckpointStrategy("acceptance", InMemoryCheckpointStore())
        external_log = adapter()
        consumers.append(external_log)
        await external_log.declare_stream(definition)
        external = await external_log.acquire(
            Subscription(
                definition.name,
                "external",
                "replica-a",
                ExactOffset(page.records[1].offset),
            ),
            0,
            strategy=strategy,
        )
        await external_log.start()
        external_record = await next_record(external)
        assert external_record.payload == b"second"
        await external.checkpoint(external_record)
        await external.release()

        producer, _ = log.unwrap()
        assert producer is not None
        await producer.send_wait(definition.name, b"not-a-psrm-envelope")
        with pytest.raises(EnvelopeError):
            await log.read(definition.name, 0, page.records[-1].offset + 1, 1)
    finally:
        for consumer_log in consumers:
            await consumer_log.close()
        if log.started:
            await delete(log, definition)
        await log.close()


async def test_super_stream_uses_core_router_and_empty_end_is_safe() -> None:
    log = adapter()
    definition = StreamDefinition(f"rps-super-{uuid4().hex}", 3)
    try:
        await log.declare_stream(definition)
        await log.start()
        requests = [AppendRequest(uuid4(), key, key) for key in (b"a", b"b", b"c")]
        receipts = [await log.append(definition.name, request) for request in requests]
        assert [receipt.partition for receipt in receipts] == [
            definition.router.route(bytes(request.partition_key), 3)
            for request in requests
        ]
        for request, receipt in zip(requests, receipts, strict=True):
            records = (
                await log.read(definition.name, receipt.partition, 0, 10)
            ).records
            assert any(record.record_id == request.record_id for record in records)

        empty_log = adapter()
        empty = StreamDefinition(f"rps-empty-{uuid4().hex}", 1)
        await empty_log.declare_stream(empty)
        lease = await empty_log.acquire(
            Subscription(empty.name, "end", "replica-a", End()),
            0,
            strategy=CheckpointStrategy.BROKER_MANAGED,
        )
        await empty_log.start()
        assert await lease.next_record() is None
        later = AppendRequest(uuid4(), b"key", b"later")
        await empty_log.append(empty.name, later)
        later_record = await next_record(lease)
        assert later_record.record_id == later.record_id
        await lease.checkpoint(later_record)
        await lease.release()
        await delete(empty_log, empty)
        await empty_log.close()
    finally:
        if log.started:
            await delete(log, definition)
        await log.close()


async def test_quiesce_closes_admission_and_close_releases_resources() -> None:
    log = adapter()
    definition = StreamDefinition(f"rps-lifecycle-{uuid4().hex}", 1)
    await log.declare_stream(definition)
    await log.start()
    await log.quiesce()
    with pytest.raises(Exception, match="not accepting"):
        await log.append(definition.name, AppendRequest(uuid4(), b"key", b"data"))
    await delete(log, definition)
    await log.close()
    assert log.unwrap() == (None, None)


async def test_external_sac_standby_starts_before_shared_store_takeover() -> None:
    first_log = adapter()
    second_log = adapter()
    definition = StreamDefinition(f"rps-takeover-{uuid4().hex}", 1)
    strategy = ExternalCheckpointStrategy("shared-takeover", InMemoryCheckpointStore())
    try:
        for log in (first_log, second_log):
            await log.declare_stream(definition)
        first = await first_log.acquire(
            Subscription(definition.name, "takeover", "replica-a", Beginning()),
            0,
            strategy=strategy,
        )
        second = await second_log.acquire(
            Subscription(definition.name, "takeover", "replica-b", Beginning()),
            0,
            strategy=strategy,
        )
        assert first_log.unwrap() == (None, None)
        assert second_log.unwrap() == (None, None)

        await first_log.start()
        await second_log.start()
        first_request = AppendRequest(uuid4(), b"key", b"first")
        await first_log.append(definition.name, first_request)
        first_record = await next_record(first)
        await first.checkpoint(first_record)
        await first.release()

        second_request = AppendRequest(uuid4(), b"key", b"second")
        await first_log.append(definition.name, second_request)
        second_record = await next_record(second)
        assert second_record.record_id == second_request.record_id
        await second.checkpoint(second_record)
        with pytest.raises(OwnershipError):
            await first.checkpoint(first_record)
        await second.release()
    finally:
        if first_log.started:
            await delete(first_log, definition)
        await second_log.close()
        await first_log.close()


async def test_named_producers_are_coordinate_isolated_and_restart_is_honest() -> None:
    log = adapter()
    restarted = adapter()
    definition = StreamDefinition(f"rps-producers-{uuid4().hex}", 1)
    first = AppendRequest(
        uuid4(), b"key", b"alpha", producer_name="alpha", publishing_id=1
    )
    second = AppendRequest(
        uuid4(), b"key", b"beta", producer_name="beta", publishing_id=1
    )
    try:
        await log.declare_stream(definition)
        await log.start()
        receipts = await asyncio.gather(
            log.append(definition.name, first),
            log.append(definition.name, second),
        )
        assert [receipt.outcome for receipt in receipts] == [
            PublishOutcome.CONFIRMED,
            PublishOutcome.CONFIRMED,
        ]
        assert (
            sum(slot.producer is not None for slot in log._publisher_slots.values())
            == 2
        )
        assert (
            await log.append(definition.name, first)
        ).outcome is PublishOutcome.DEDUPLICATED
        with pytest.raises(PublishingConflictError):
            await log.append(
                definition.name,
                AppendRequest(
                    uuid4(),
                    b"key",
                    b"different",
                    producer_name="alpha",
                    publishing_id=1,
                ),
            )

        await restarted.declare_stream(definition)
        await restarted.start()
        retry = await restarted.append(definition.name, first)
        assert retry.outcome is PublishOutcome.INDETERMINATE
        assert (
            "cross-restart-content-association-unsupported" in retry.confirmation_facts
        )
    finally:
        await restarted.close()
        if log.started:
            await delete(log, definition)
        await log.close()


async def test_blocked_consumer_backlog_is_bounded_by_credit_and_queue() -> None:
    log = RabbitMqPersistentLog(
        RabbitMqPersistentStreamsOptions(
            RabbitMqConnectionOptions("127.0.0.1", "streams", "streams"),
            callback_queue_capacity=4,
            broker_managed_single_instance=True,
        )
    )
    definition = StreamDefinition(f"rps-backpressure-{uuid4().hex}", 1)
    try:
        await log.declare_stream(definition)
        lease = cast(
            RabbitMqPartitionLease,
            await log.acquire(
                Subscription(definition.name, "blocked", "replica-a", Beginning()),
                0,
                strategy=CheckpointStrategy.BROKER_MANAGED,
            ),
        )
        await log.start()
        for index in range(500):
            await log.append(
                definition.name,
                AppendRequest(uuid4(), b"key", str(index).encode()),
            )
        async with asyncio.timeout(10):
            while lease._queue.qsize() < 4:
                await asyncio.sleep(0.05)
        assert lease._queue.qsize() == 4
        assert lease._consumer is not None
        assert lease._subscriber_id is not None
        subscriber = lease._consumer._subscribers[lease._subscriber_id]
        assert subscriber.client._frames[lease._subscriber_id].qsize() <= 1
        await lease.release()
    finally:
        if log.started:
            await delete(log, definition)
        await log.close()


async def test_nestpy_module_publisher_handler_and_lifecycle() -> None:
    received: list[str] = []

    @controller()
    class Projection:
        @stream_handler(stream="events", consumer_group="nest-acceptance")
        async def apply(self, payload: Annotated[BrokerEvent, StreamPayload()]) -> None:
            received.append(payload.value)

    name = f"rps-nest-{uuid4().hex}"
    selected = RabbitMqPersistentStreamsOptions(
        RabbitMqConnectionOptions("127.0.0.1", "streams", "streams"),
        broker_managed_single_instance=True,
    )
    streams = PersistentStreamsModule.for_root(
        PersistentStreamsOptions(
            bindings=(
                StreamBinding(
                    "events",
                    StreamDefinition(name, 1),
                    BrokerEvent,
                    BrokerCodec(),
                    BrokerKey(),
                ),
            ),
            runtime=PersistentStreamsRuntimeOptions(
                owner_id="nest-broker-1",
                single_instance_consumer_groups=True,
            ),
        ),
        adapter=RabbitMqPersistentStreamsModule.for_root(selected),
    )

    @module(imports=[streams], controllers=[Projection])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    receipt = await publisher.publish("events", BrokerEvent("accepted"))
    assert receipt.outcome is PublishOutcome.CONFIRMED
    async with asyncio.timeout(10):
        while received != ["accepted"]:
            await asyncio.sleep(0.02)
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    assert runtime.ready
    await application.close()
    assert runtime.state.value == "closed"
    cleanup = Producer(host="127.0.0.1", username="streams", password="streams")
    await cleanup.start()
    try:
        await cleanup.delete_stream(name, missing_ok=True)
    finally:
        await cleanup.close()


async def test_nestpy_quiesce_waits_for_blocked_handler_checkpoint() -> None:
    entered = asyncio.Event()
    unblock = asyncio.Event()

    @controller()
    class Projection:
        @stream_handler(stream="events", consumer_group="blocked-quiesce")
        async def apply(self, payload: Annotated[BrokerEvent, StreamPayload()]) -> None:
            del payload
            entered.set()
            await unblock.wait()

    name = f"rps-nest-blocked-{uuid4().hex}"
    selected = RabbitMqPersistentStreamsOptions(
        RabbitMqConnectionOptions("127.0.0.1", "streams", "streams"),
        broker_managed_single_instance=True,
    )
    streams = PersistentStreamsModule.for_root(
        PersistentStreamsOptions(
            bindings=(
                StreamBinding(
                    "events",
                    StreamDefinition(name, 1),
                    BrokerEvent,
                    BrokerCodec(),
                    BrokerKey(),
                ),
            ),
            runtime=PersistentStreamsRuntimeOptions(
                owner_id="nest-broker-2",
                single_instance_consumer_groups=True,
            ),
        ),
        adapter=RabbitMqPersistentStreamsModule.for_root(selected),
    )

    @module(imports=[streams], controllers=[Projection])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    await publisher.publish("events", BrokerEvent("blocked"))
    await asyncio.wait_for(entered.wait(), 10)
    closing = asyncio.create_task(application.close())
    await asyncio.sleep(0.2)
    assert not closing.done()
    unblock.set()
    await asyncio.wait_for(closing, 10)

    cleanup = Producer(host="127.0.0.1", username="streams", password="streams")
    await cleanup.start()
    try:
        await cleanup.delete_stream(name, missing_ok=True)
    finally:
        await cleanup.close()


@pytest.mark.parametrize("failure", ["handler", "checkpoint"])
async def test_nestpy_failure_abandons_delivery_without_shutdown_delay(
    failure: str,
) -> None:
    class FailingStore(InMemoryCheckpointStore):
        async def save(self, key, expected, cursor, owner):
            if failure == "checkpoint":
                raise RuntimeError("checkpoint failed")
            await super().save(key, expected, cursor, owner)

    @controller()
    class Projection:
        @stream_handler(stream="events", consumer_group="failure-stop")
        async def apply(self, payload: Annotated[BrokerEvent, StreamPayload()]) -> None:
            if failure == "handler":
                raise RuntimeError(payload.value)

    name = f"rps-nest-{failure}-{uuid4().hex}"
    store = FailingStore()
    strategy = ExternalCheckpointStrategy("failure-store", store)
    selected = RabbitMqPersistentStreamsOptions(
        RabbitMqConnectionOptions("127.0.0.1", "streams", "streams"),
        close_timeout=5,
    )
    streams = PersistentStreamsModule.for_root(
        PersistentStreamsOptions(
            bindings=(
                StreamBinding(
                    "events",
                    StreamDefinition(name, 1),
                    BrokerEvent,
                    BrokerCodec(),
                    BrokerKey(),
                    checkpoint_strategy=strategy,
                ),
            ),
            runtime=PersistentStreamsRuntimeOptions(
                owner_id=f"{failure}-replica",
                owner_id_is_replica_unique=True,
            ),
        ),
        adapter=RabbitMqPersistentStreamsModule.for_root(selected),
    )

    @module(imports=[streams], controllers=[Projection])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    log = cast(RabbitMqPersistentLog, runtime._log)
    lease = cast(RabbitMqPartitionLease, runtime._leases[0][2])
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    await publisher.publish("events", BrokerEvent("failed"))

    async with asyncio.timeout(1):
        while runtime.statuses[0].state != "blocked" or log._leases:
            await asyncio.sleep(0.01)
    cursor = await store.load(lease.key)
    assert cursor is not None
    assert cursor.kind.value == "initialized"
    assert runtime.statuses[0].offset == 0
    assert not log._leases

    await asyncio.wait_for(application.close(), 2)
    cleanup = Producer(host="127.0.0.1", username="streams", password="streams")
    await cleanup.start()
    try:
        await cleanup.delete_stream(name, missing_ok=True)
    finally:
        await cleanup.close()


async def test_z_broker_restart_fails_adapter_closed_without_driver_replay() -> None:
    log = adapter()
    definition = StreamDefinition(f"rps-fail-closed-{uuid4().hex}", 1)
    compose = Path(__file__).parent / "feasibility" / "docker-compose.yml"
    root = Path(__file__).parents[3]

    def control(command: str, *, check: bool = True) -> None:
        subprocess.run(
            [
                "uv",
                "run",
                "docker",
                "compose",
                "-f",
                str(compose),
                "-p",
                "kinker-rps0",
                "exec",
                "-T",
                "rabbitmq-stream-spike",
                "rabbitmqctl",
                command,
            ],
            cwd=root,
            check=check,
            capture_output=True,
            text=True,
        )

    restarted = False
    try:
        await log.declare_stream(definition)
        await log.start()
        await log.append(definition.name, AppendRequest(uuid4(), b"key", b"before"))
        await asyncio.to_thread(control, "stop_app")
        async with asyncio.timeout(10):
            while not log._failed:
                await asyncio.sleep(0.05)
        await asyncio.to_thread(control, "start_app")
        restarted = True
        with pytest.raises(Exception, match="not accepting"):
            await log.append(definition.name, AppendRequest(uuid4(), b"key", b"after"))
    finally:
        if not restarted:
            await asyncio.to_thread(control, "start_app", check=False)
        await asyncio.to_thread(control, "await_startup")
        await log.close()
        cleanup = Producer(host="127.0.0.1", username="streams", password="streams")
        await cleanup.start()
        try:
            await cleanup.delete_stream(definition.name, missing_ok=True)
        finally:
            await cleanup.close()

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict, cast
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

import pytest
from persistent_streams import ResumeCursor
from persistent_streams_rabbitmq._cursor_codec import decode_cursor, encode_cursor
from persistent_streams_rabbitmq._envelope import (
    RecordEnvelope,
    decode_envelope,
    encode_envelope,
)
from persistent_streams_rabbitmq._rstream_compat import MetadataClient
from rstream import (
    AMQPMessage,
    Consumer,
    ConsumerOffsetSpecification,
    OffsetNotFound,
    OffsetSpecification,
    OffsetType,
    Producer,
    Properties,
    RawMessage,
    RouteType,
    SuperStreamCreationOption,
    SuperStreamProducer,
    amqp_decoder,
)
from rstream.consumer import EventContext, MessageContext
from rstream.producer import ConfirmationStatus

pytestmark = [pytest.mark.asyncio, pytest.mark.rabbitmq]


class Connection(TypedDict):
    host: str
    port: int
    username: str
    password: str


def unique_name(prefix: str) -> str:
    return f"rps0-{prefix}-{uuid4().hex}"


async def eventually(assertion: Callable[[], None], timeout: float = 10) -> None:
    async with asyncio.timeout(timeout):
        while True:
            try:
                assertion()
            except AssertionError:
                await asyncio.sleep(0.05)
            else:
                return


async def collect(
    connection: Connection,
    stream: str,
    offset: ConsumerOffsetSpecification,
    expected: int,
    *,
    decoder: Callable[[bytes], Any] | None = None,
) -> list[tuple[Any, MessageContext]]:
    records: list[tuple[Any, MessageContext]] = []
    ready = asyncio.Event()
    consumer = Consumer(**connection)

    async def callback(message: Any, context: MessageContext) -> None:
        records.append((message, context))
        if len(records) >= expected:
            ready.set()

    try:
        await consumer.start()
        subscriber_id = await consumer.subscribe(
            stream,
            cast(Any, callback),
            decoder=decoder,
            offset_specification=offset,
            initial_credit=1,
        )
        await asyncio.wait_for(ready.wait(), 10)
        await consumer.unsubscribe(subscriber_id)
    finally:
        await consumer.close()
    return records


async def queue_stats(management_url: str, stream: str) -> dict[str, Any]:
    token = base64.b64encode(b"streams:streams").decode("ascii")
    request = Request(
        f"{management_url}/queues/%2F/{quote(stream, safe='')}",
        headers={"Authorization": f"Basic {token}"},
    )

    def fetch() -> dict[str, Any]:
        with urlopen(request, timeout=5) as response:
            return cast(dict[str, Any], json.load(response))

    return await asyncio.to_thread(fetch)


@pytest.mark.parametrize("owner_type", [Producer, Consumer])
async def test_ordinary_stream_create_exists_delete(
    rabbitmq_connection: Connection, owner_type: type[Producer] | type[Consumer]
) -> None:
    stream = unique_name("ordinary")
    owner = owner_type(**rabbitmq_connection)
    try:
        await owner.start()
        await owner.create_stream(stream)
        assert await owner.stream_exists(stream)
        await owner.create_stream(stream, exists_ok=True)
        await owner.delete_stream(stream)
        assert not await owner.stream_exists(stream)
    finally:
        await owner.close()


async def test_super_stream_partitions_binding_routes_and_confirmed_send(
    rabbitmq_connection: Connection,
) -> None:
    super_stream = unique_name("super")

    async def route(message: bytes) -> str:
        return message.decode()

    producer = SuperStreamProducer(
        **rabbitmq_connection,
        super_stream=super_stream,
        super_stream_creation_option=SuperStreamCreationOption(
            n_partitions=0,
            binding_keys=["alpha", "beta", "gamma"],
        ),
        routing_extractor=route,
        routing=RouteType.Key,
    )
    try:
        await producer.start()
        assert await producer.super_stream_metadata.routes("beta") == [
            f"{super_stream}-beta"
        ]

        confirmed = asyncio.Event()
        statuses: list[ConfirmationStatus] = []

        async def on_confirm(status: ConfirmationStatus) -> None:
            statuses.append(status)
            confirmed.set()

        result = await producer.send(b"beta", on_publish_confirm=on_confirm)
        assert result is None
        await asyncio.wait_for(confirmed.wait(), 10)
        status = statuses[0]
        assert status.is_confirmed is True
        assert set(vars(status)) == {"message_id", "is_confirmed", "response_code"}

        records = await collect(
            rabbitmq_connection,
            f"{super_stream}-beta",
            ConsumerOffsetSpecification(OffsetType.FIRST),
            1,
        )
        assert records[0][0] == b"beta"

        # partitions() closes rstream's locator, so inspect with a fresh owner.
        inspector = SuperStreamProducer(
            **rabbitmq_connection,
            super_stream=super_stream,
            routing_extractor=route,
            routing=RouteType.Key,
        )
        try:
            await inspector.start()
            assert await inspector.super_stream_metadata.partitions() == [
                f"{super_stream}-alpha",
                f"{super_stream}-beta",
                f"{super_stream}-gamma",
            ]
        finally:
            await inspector.close()
    finally:
        await producer.close()
        cleanup = SuperStreamProducer(
            **rabbitmq_connection,
            super_stream=super_stream,
            routing_extractor=route,
            routing=RouteType.Key,
        )
        await cleanup.start()
        await cleanup.delete_super_stream(super_stream, missing_ok=True)
        await cleanup.close()


async def test_canonical_binary_envelope_and_broker_timestamp_round_trip(
    rabbitmq_connection: Connection,
) -> None:
    stream = unique_name("amqp")
    producer = Producer(**rabbitmq_connection)
    record_id = str(uuid4())
    envelope = RecordEnvelope(
        record_id=UUID(record_id),
        partition_key=b"partition",
        headers={"trace": b"value", "binary": b"\x00\xff"},
        payload=b"payload",
    )
    message = AMQPMessage(
        body=encode_envelope(envelope),
        properties=Properties(
            message_id=record_id,
            content_type="application/octet-stream",
        ),
    )
    before = int(time.time() * 1000)
    try:
        await producer.start()
        await producer.create_stream(stream)
        publishing_id = await producer.send_wait(stream, message)
        after = int(time.time() * 1000)
        assert isinstance(publishing_id, int)

        records = await collect(
            rabbitmq_connection,
            stream,
            ConsumerOffsetSpecification(OffsetType.FIRST),
            1,
            decoder=amqp_decoder,
        )
        consumed, context = records[0]
        received_at = int(time.time() * 1000)
        decoded = decode_envelope(consumed.body)
        assert decoded == envelope
        assert consumed.properties.message_id == record_id.encode()
        assert consumed.properties.content_type == b"application/octet-stream"
        assert consumed.properties.subject is None
        assert not consumed.application_properties
        assert before <= context.timestamp <= received_at
        assert before <= after <= received_at
        assert context.offset == 0
    finally:
        await producer.delete_stream(stream, missing_ok=True)
        await producer.close()


async def test_broker_tracking_is_queryable_and_creates_sparse_data_offsets(
    rabbitmq_connection: Connection,
    rabbitmq_management_url: str,
) -> None:
    stream = unique_name("tracking")
    reference = unique_name("group")
    producer = Producer(**rabbitmq_connection)
    tracker = Consumer(**rabbitmq_connection)
    try:
        await producer.start()
        await tracker.start()
        await producer.create_stream(stream)
        await producer.send_wait(stream, b"zero")
        await producer.send_wait(stream, b"one")
        await tracker.store_offset(stream, reference, 1)

        queried: list[int] = []

        async def query_until_visible() -> None:
            queried.append(await tracker.query_offset(stream, reference))

        async with asyncio.timeout(10):
            while True:
                try:
                    await query_until_visible()
                except Exception:
                    await asyncio.sleep(0.05)
                else:
                    if queried[-1] == 1:
                        break
                    await asyncio.sleep(0.05)

        await producer.send_wait(stream, b"two")
        records = await collect(
            rabbitmq_connection,
            stream,
            ConsumerOffsetSpecification(OffsetType.FIRST),
            3,
        )
        assert [message for message, _ in records] == [b"zero", b"one", b"two"]
        assert [context.offset for _, context in records] == [0, 1, 3]
        stats = await queue_stats(rabbitmq_management_url, stream)
        assert stats["type"] == "stream"
        assert "messages" not in stats
    finally:
        await producer.delete_stream(stream, missing_ok=True)
        await tracker.close()
        await producer.close()


async def test_named_producer_exact_retry_is_deduplicated_without_an_offset(
    rabbitmq_connection: Connection,
) -> None:
    stream = unique_name("named")
    publisher_name = unique_name("publisher")
    first = Producer(**rabbitmq_connection)
    retry = Producer(**rabbitmq_connection)
    try:
        await first.start()
        await first.create_stream(stream)
        first_id = await first.send_wait(
            stream,
            RawMessage(b"once", publishing_id=42),
            publisher_name=publisher_name,
        )
        await first.close()

        retry_id = await retry.send_wait(
            stream,
            RawMessage(b"duplicate", publishing_id=42),
            publisher_name=publisher_name,
        )
        next_id = await retry.send_wait(
            stream,
            RawMessage(b"next", publishing_id=43),
            publisher_name=publisher_name,
        )
        assert (first_id, retry_id, next_id) == (42, 42, 43)

        async with MetadataClient(**rabbitmq_connection) as metadata:
            assert await metadata.query_publisher_sequence(stream, publisher_name) == 43

        records = await collect(
            rabbitmq_connection,
            stream,
            ConsumerOffsetSpecification(OffsetType.FIRST),
            2,
        )
        assert [message for message, _ in records] == [b"once", b"next"]
        assert [context.offset for _, context in records] == [0, 1]
    finally:
        await retry.delete_stream(stream, missing_ok=True)
        await retry.close()


async def test_beginning_next_exact_timestamp_and_native_clamping(
    rabbitmq_connection: Connection,
) -> None:
    stream = unique_name("starts")
    producer = Producer(**rabbitmq_connection)
    try:
        await producer.start()
        await producer.create_stream(stream)
        for body in (b"zero", b"one", b"two"):
            await producer.send_wait(stream, body)
            await asyncio.sleep(0.02)

        beginning = await collect(
            rabbitmq_connection,
            stream,
            ConsumerOffsetSpecification(OffsetType.FIRST),
            3,
        )
        exact = await collect(
            rabbitmq_connection,
            stream,
            ConsumerOffsetSpecification(OffsetType.OFFSET, 1),
            2,
        )
        timestamp = await collect(
            rabbitmq_connection,
            stream,
            ConsumerOffsetSpecification(
                OffsetType.TIMESTAMP,
                beginning[1][1].timestamp,
            ),
            2,
        )
        last = await collect(
            rabbitmq_connection,
            stream,
            ConsumerOffsetSpecification(OffsetType.LAST),
            1,
        )
        assert [context.offset for _, context in beginning] == [0, 1, 2]
        assert [context.offset for _, context in exact] == [1, 2]
        assert [message for message, _ in timestamp] == [b"one", b"two"]
        assert [message for message, _ in last] == [b"two"]

        future_records: list[bytes] = []
        subscribed = asyncio.Event()
        received = asyncio.Event()
        consumer = Consumer(**rabbitmq_connection)

        async def callback(message: bytes, context: MessageContext) -> None:
            del context
            future_records.append(message)
            received.set()

        await consumer.start()
        subscriber_id = await consumer.subscribe(
            stream,
            cast(Any, callback),
            offset_specification=ConsumerOffsetSpecification(OffsetType.NEXT),
            initial_credit=1,
        )
        subscribed.set()
        assert subscribed.is_set()
        await asyncio.sleep(0.2)
        assert future_records == []
        await producer.send_wait(stream, b"future")
        await asyncio.wait_for(received.wait(), 10)
        await consumer.unsubscribe(subscriber_id)
        await consumer.close()
        assert future_records == [b"future"]

        clamped: list[bytes] = []
        clamp_consumer = Consumer(**rabbitmq_connection)

        async def clamp_callback(message: bytes, context: MessageContext) -> None:
            del context
            clamped.append(message)

        await clamp_consumer.start()
        clamp_id = await clamp_consumer.subscribe(
            stream,
            cast(Any, clamp_callback),
            offset_specification=ConsumerOffsetSpecification(OffsetType.OFFSET, 10_000),
            initial_credit=1,
        )
        await asyncio.sleep(0.2)
        assert clamped == []
        await producer.send_wait(stream, b"after-clamp")
        await asyncio.sleep(0.2)
        await clamp_consumer.unsubscribe(clamp_id)
        await clamp_consumer.close()
        assert clamped == []

        tie_confirms = asyncio.Event()
        tie_confirmed = 0

        async def tie_confirm(status: ConfirmationStatus) -> None:
            nonlocal tie_confirmed
            assert status.is_confirmed
            tie_confirmed += 1
            if tie_confirmed == 2:
                tie_confirms.set()

        await producer.send_batch(
            stream,
            [b"tie-a", b"tie-b"],
            on_publish_confirm=tie_confirm,
        )
        await asyncio.wait_for(tie_confirms.wait(), 10)
        tied = await collect(
            rabbitmq_connection,
            stream,
            ConsumerOffsetSpecification(OffsetType.OFFSET, 5),
            2,
        )
        assert [message for message, _ in tied] == [b"tie-a", b"tie-b"]
        assert tied[0][1].timestamp == tied[1][1].timestamp
        tied_by_timestamp = await collect(
            rabbitmq_connection,
            stream,
            ConsumerOffsetSpecification(
                OffsetType.TIMESTAMP,
                tied[0][1].timestamp,
            ),
            2,
        )
        assert [message for message, _ in tied_by_timestamp] == [b"tie-a", b"tie-b"]

        future_timestamp_records: list[bytes] = []
        future_timestamp_delivery = asyncio.Event()
        future_timestamp_consumer = Consumer(**rabbitmq_connection)

        async def future_timestamp_callback(
            message: bytes, context: MessageContext
        ) -> None:
            del context
            future_timestamp_records.append(message)
            future_timestamp_delivery.set()

        await future_timestamp_consumer.start()
        future_timestamp_id = await future_timestamp_consumer.subscribe(
            stream,
            cast(Any, future_timestamp_callback),
            offset_specification=ConsumerOffsetSpecification(
                OffsetType.TIMESTAMP,
                int(time.time() * 1000) + 60_000,
            ),
            initial_credit=1,
        )
        await producer.send_wait(stream, b"future-timestamp-clamp")
        await asyncio.wait_for(future_timestamp_delivery.wait(), 10)
        await future_timestamp_consumer.unsubscribe(future_timestamp_id)
        await future_timestamp_consumer.close()
        assert future_timestamp_records == [b"future-timestamp-clamp"]
    finally:
        await producer.delete_stream(stream, missing_ok=True)
        await producer.close()


async def test_empty_stream_next_is_not_a_durable_restart_cursor(
    rabbitmq_connection: Connection,
) -> None:
    stream = unique_name("empty-end")
    producer = Producer(**rabbitmq_connection)
    consumer = Consumer(**rabbitmq_connection)
    try:
        await producer.start()
        await consumer.start()
        await producer.create_stream(stream)
        subscriber_id = await consumer.subscribe(
            stream,
            lambda message, context: None,
            offset_specification=ConsumerOffsetSpecification(OffsetType.NEXT),
        )
        await consumer.unsubscribe(subscriber_id)

        with pytest.raises(OffsetNotFound):
            await consumer.query_offset(stream, unique_name("never-stored"))
    finally:
        await producer.delete_stream(stream, missing_ok=True)
        await consumer.close()
        await producer.close()


async def test_stream_stats_and_tagged_broker_cursor_round_trip(
    rabbitmq_connection: Connection,
) -> None:
    stream = unique_name("stats-cursor")
    reference = unique_name("cursor")
    producer = Producer(**rabbitmq_connection)
    tracker = Consumer(**rabbitmq_connection)
    try:
        await producer.start()
        await tracker.start()
        await producer.create_stream(stream)
        async with MetadataClient(**rabbitmq_connection) as metadata:
            assert await metadata.stream_stats(stream) == {
                "first_chunk_id": -1,
                "last_chunk_id": -1,
                "committed_chunk_id": -1,
            }

            initialized = ResumeCursor.initialized(0)
            await tracker.store_offset(stream, reference, encode_cursor(initialized))
            await eventually_query_cursor(tracker, stream, reference, initialized)
            await producer.send_wait(stream, b"first-after-empty-end")

            records = await collect(
                rabbitmq_connection,
                stream,
                ConsumerOffsetSpecification(OffsetType.OFFSET, initialized.offset),
                1,
            )
            assert records[0][0] == b"first-after-empty-end"
            assert records[0][1].offset == 1
            assert await metadata.stream_stats(stream) == {
                "first_chunk_id": 0,
                "last_chunk_id": 1,
                "committed_chunk_id": 1,
            }

            completed = ResumeCursor.last_successful(records[0][1].offset)
            await tracker.store_offset(stream, reference, encode_cursor(completed))
            await eventually_query_cursor(tracker, stream, reference, completed)
    finally:
        await producer.delete_stream(stream, missing_ok=True)
        await tracker.close()
        await producer.close()


async def eventually_query_cursor(
    consumer: Consumer,
    stream: str,
    reference: str,
    expected: ResumeCursor,
) -> None:
    async with asyncio.timeout(10):
        while True:
            try:
                actual = decode_cursor(await consumer.query_offset(stream, reference))
            except OffsetNotFound:
                await asyncio.sleep(0.05)
                continue
            if actual == expected:
                return
            await asyncio.sleep(0.05)


async def test_stream_stats_low_watermark_exposes_retention_gap(
    rabbitmq_connection: Connection,
) -> None:
    stream = unique_name("retention")
    producer = Producer(**rabbitmq_connection)
    try:
        await producer.start()
        await producer.create_stream(
            stream,
            arguments={
                "max-length-bytes": 600_000,
                "stream-max-segment-size-bytes": 500_000,
            },
        )
        payload = b"x" * 1_000
        for _ in range(2_000):
            await producer.send_wait(stream, payload)

        async with MetadataClient(**rabbitmq_connection) as metadata:
            async with asyncio.timeout(20):
                while True:
                    stats = await metadata.stream_stats(stream)
                    if stats["first_chunk_id"] > 0:
                        break
                    await asyncio.sleep(0.1)
        assert set(stats) == {
            "first_chunk_id",
            "last_chunk_id",
            "committed_chunk_id",
        }
        assert 0 < stats["first_chunk_id"] <= stats["committed_chunk_id"]
        assert stats["last_chunk_id"] <= stats["committed_chunk_id"]
        assert 0 < stats["first_chunk_id"]  # exact offset 0 is a proven retention gap
    finally:
        await producer.delete_stream(stream, missing_ok=True)
        await producer.close()


async def test_sac_consumer_update_group_activation_and_promotion(
    rabbitmq_connection: Connection,
) -> None:
    stream = unique_name("sac")
    group = unique_name("sac-group")
    producer = Producer(**rabbitmq_connection)
    consumers = [Consumer(**rabbitmq_connection), Consumer(**rabbitmq_connection)]
    active_events: list[list[bool]] = [[], []]
    deliveries: list[list[bytes]] = [[], []]

    def listener(
        index: int,
    ) -> Callable[[bool, EventContext], Awaitable[OffsetSpecification]]:
        async def update(active: bool, context: EventContext) -> OffsetSpecification:
            assert context.reference == group
            active_events[index].append(active)
            return OffsetSpecification(OffsetType.NEXT, 0)

        return update

    def callback(index: int) -> Callable[[bytes, MessageContext], None]:
        def receive(message: bytes, context: MessageContext) -> None:
            del context
            deliveries[index].append(message)

        return receive

    try:
        await producer.start()
        await producer.create_stream(stream)
        ids: list[int] = []
        for index, consumer in enumerate(consumers):
            await consumer.start()
            ids.append(
                await consumer.subscribe(
                    stream,
                    cast(Any, callback(index)),
                    properties={"single-active-consumer": "true", "name": group},
                    subscriber_name=group,
                    consumer_update_listener=listener(index),
                    initial_credit=1,
                )
            )

        await eventually(lambda: assert_an_active(active_events))
        first_active = 0 if active_events[0] else 1
        standby = 1 - first_active
        assert active_events[first_active] == [True]
        assert active_events[standby] == []
        await producer.send_wait(stream, b"first")
        await eventually(lambda: assert_delivery_count(deliveries, 1))
        assert deliveries[first_active] == [b"first"]

        await consumers[first_active].unsubscribe(ids[first_active])
        await eventually(lambda: assert_promoted(active_events[standby]))
        await producer.send_wait(stream, b"second")
        await eventually(lambda: assert_delivery_count(deliveries, 2))
        assert deliveries[standby] == [b"second"]
    finally:
        await producer.delete_stream(stream, missing_ok=True)
        for consumer in consumers:
            await consumer.close()
        await producer.close()


def assert_an_active(events: list[list[bool]]) -> None:
    assert any(history and history[-1] for history in events)


def assert_promoted(events: list[bool]) -> None:
    assert events and events[-1] is True


def assert_delivery_count(deliveries: list[list[bytes]], expected: int) -> None:
    assert sum(map(len, deliveries)) == expected


async def test_close_and_new_generation_reconnect(
    rabbitmq_connection: Connection,
) -> None:
    stream = unique_name("reconnect")
    first = Producer(**rabbitmq_connection)
    second = Producer(**rabbitmq_connection)
    try:
        await first.start()
        await first.create_stream(stream)
        await first.send_wait(stream, b"first")
        await first.close()
        await first.close()

        await second.start()
        await second.send_wait(stream, b"second")
        records = await collect(
            rabbitmq_connection,
            stream,
            ConsumerOffsetSpecification(OffsetType.FIRST),
            2,
        )
        assert [message for message, _ in records] == [b"first", b"second"]
    finally:
        await second.delete_stream(stream, missing_ok=True)
        await second.close()


async def test_driver_automatic_recovery_after_broker_restart(
    rabbitmq_connection: Connection,
    destructive_rabbitmq_application,
) -> None:
    stream = unique_name("recovery")
    disconnected = asyncio.Event()

    async def on_close(info: object) -> None:
        del info
        disconnected.set()

    producer = Producer(**rabbitmq_connection, on_close_handler=on_close)
    try:
        await producer.start()
        await producer.create_stream(stream)
        await producer.send_wait(stream, b"before")
        await asyncio.to_thread(
            destructive_rabbitmq_application.control_application, "stop_app"
        )
        await asyncio.wait_for(disconnected.wait(), 10)
        await asyncio.to_thread(destructive_rabbitmq_application.recover_application)
        await asyncio.wait_for(producer.send_wait(stream, b"after"), 30)
        records = await collect(
            rabbitmq_connection,
            stream,
            ConsumerOffsetSpecification(OffsetType.FIRST),
            2,
        )
        assert [message for message, _ in records] == [b"before", b"after"]
    finally:
        await asyncio.to_thread(destructive_rabbitmq_application.recover_application)
        await producer.delete_stream(stream, missing_ok=True)
        await producer.close()

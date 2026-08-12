from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from nestpy import ModuleSpec, module
from nestpy_persistent_streams import StreamAdapterFactory
from persistent_streams import (
    AdapterContractError,
    AppendRequest,
    Beginning,
    CheckpointKey,
    CheckpointPersistenceError,
    CheckpointStrategy,
    CheckpointStrategyError,
    ExternalCheckpointStrategy,
    InMemoryCheckpointStore,
    OwnershipToken,
    ResourceLimitError,
    ResumeCursor,
    RetentionGapError,
    StoredRecord,
    StreamDefinition,
    StreamLimits,
    Subscription,
)
from persistent_streams_rabbitmq import (
    CONTENT_TYPE,
    DeclarationMode,
    EnvelopeError,
    RabbitMqConnectionOptions,
    RabbitMqPartitionLease,
    RabbitMqPersistentLog,
    RabbitMqPersistentStreamsModule,
    RabbitMqPersistentStreamsOptions,
    RabbitMqStreamAdapterFactory,
    RabbitMqTlsOptions,
    RecordEnvelope,
    decode_amqp_message,
    decode_envelope,
    encode_amqp_message,
    encode_envelope,
)
from persistent_streams_rabbitmq import log as log_module
from persistent_streams_rabbitmq import publishing as publishing_module
from persistent_streams_rabbitmq import reading as reading_module
from persistent_streams_rabbitmq import topology as topology_module
from rstream import (
    AMQPMessage,
    ConsumerOffsetSpecification,
    OffsetType,
    Properties,
)


def options() -> RabbitMqPersistentStreamsOptions:
    return RabbitMqPersistentStreamsOptions(
        RabbitMqConnectionOptions("rabbit.example", "streams", "secret")
    )


def test_options_are_immutable_bounded_redacted_and_finite() -> None:
    selected = options()
    assert selected.declaration is DeclarationMode.CREATE
    assert "secret" not in repr(selected)
    assert dict(selected.declaration_arguments) == {
        "max-age": "604800s",
        "max-length-bytes": 1_073_741_824,
        "stream-max-segment-size-bytes": 100_000_000,
    }
    assert type(selected).__dataclass_params__.frozen
    with pytest.raises(ValueError):
        RabbitMqPersistentStreamsOptions(selected.connection, max_pending_bytes=0)
    with pytest.raises(ValueError, match="positive integer"):
        RabbitMqConnectionOptions("host", "user", "secret", heartbeat=True)
    with pytest.raises(ValueError, match="initial_credit"):
        RabbitMqPersistentStreamsOptions(selected.connection, initial_credit=2)
    with pytest.raises(ValueError, match="between"):
        RabbitMqConnectionOptions("host", "user", "secret", frame_max=2**31)
    with pytest.raises(ValueError, match="max_named_producers"):
        RabbitMqPersistentStreamsOptions(selected.connection, max_named_producers=0)
    with pytest.raises(ValueError, match="max_streams"):
        RabbitMqPersistentStreamsOptions(selected.connection, max_streams=0)
    with pytest.raises(TypeError, match="single_instance"):
        RabbitMqPersistentStreamsOptions(
            selected.connection,
            broker_managed_single_instance=cast(Any, 1),
        )


@pytest.mark.asyncio
async def test_broker_checkpoints_require_explicit_single_instance_before_start() -> (
    None
):
    log = RabbitMqPersistentLog(options())
    definition = StreamDefinition("events", 1)
    log._definitions[definition.name] = definition

    with pytest.raises(CheckpointStrategyError, match="single-instance"):
        await log.acquire(
            Subscription("events", "group", "replica-a", Beginning()),
            0,
            strategy=CheckpointStrategy.BROKER_MANAGED,
        )
    assert log.unwrap() == (None, None)


def test_producer_name_stream_limit_is_checked_before_resource_allocation() -> None:
    log = RabbitMqPersistentLog(options())
    definition = StreamDefinition(
        "events", 1, limits=StreamLimits(max_producer_chars=3)
    )
    with pytest.raises(ResourceLimitError, match="producer_name"):
        log._validate_request(
            definition,
            AppendRequest(uuid4(), b"key", producer_name="long", publishing_id=1),
        )
    assert not log._publisher_slots


def test_tls_hostname_must_be_the_actual_advertised_endpoint() -> None:
    with pytest.raises(ValueError, match="advertised endpoint"):
        RabbitMqConnectionOptions(
            "load-balancer.internal",
            "streams",
            "secret",
            advertised_host="streams.example",
            tls=RabbitMqTlsOptions("ca.pem", server_hostname="other.example"),
        )


def test_psrm_v2_golden_vector_and_strict_rejections() -> None:
    envelope = RecordEnvelope(
        UUID("00112233-4455-6677-8899-aabbccddeeff"),
        b"key",
        {"z": b"last", "a": b"\x00\xff"},
        b"payload",
    )
    encoded = encode_envelope(envelope)
    assert encoded.hex() == (
        "5053524d020100112233445566778899aabbccddeeff0000000300026b6579"
        "0001000000026100ff0001000000047a6c61737400000000000000077061796c6f6164"
    )
    assert decode_envelope(encoded) == envelope
    with pytest.raises(EnvelopeError):
        decode_envelope(b"BAD!" + encoded[4:])
    with pytest.raises(EnvelopeError):
        decode_envelope(encoded + b"trailing")
    with pytest.raises(EnvelopeError):
        decode_envelope(encoded[:-1])


def test_amqp_contract_uses_only_flat_standard_properties() -> None:
    envelope = RecordEnvelope(UUID(int=1), b"key", {"trace": b"value"}, b"data")
    message = encode_amqp_message(envelope)
    assert message.properties.message_id == str(envelope.record_id)
    assert message.properties.content_type == CONTENT_TYPE
    assert message.properties.subject is None
    assert not message.application_properties
    assert decode_amqp_message(message) == envelope
    message = AMQPMessage(
        body=message.body,
        properties=Properties(message_id=str(UUID(int=2)), content_type=CONTENT_TYPE),
    )
    with pytest.raises(EnvelopeError, match="do not match"):
        decode_amqp_message(message)


def test_unicode_content_type_failure_is_typed() -> None:
    with pytest.raises(EnvelopeError, match="ASCII"):
        RecordEnvelope(UUID(int=1), b"key", {}, b"", content_type="snowman-\u2603")


@pytest.mark.asyncio
async def test_super_stream_inspection_propagates_timeout(monkeypatch) -> None:
    selected = RabbitMqPersistentStreamsOptions(
        options().connection, operation_timeout=0.01
    )
    log = RabbitMqPersistentLog(selected)

    class Metadata:
        async def partitions(self):
            await asyncio.sleep(1)
            return []

    class Owner:
        super_stream_metadata = Metadata()

        async def start(self):
            return None

        async def close(self):
            return None

    monkeypatch.setattr(log, "_new_super_owner", lambda name: Owner())
    with pytest.raises(TimeoutError):
        await log._inspect_super_partitions("events")


@pytest.mark.asyncio
async def test_read_rechecks_retention_after_exact_subscription(monkeypatch) -> None:
    subscribed: list[ConsumerOffsetSpecification] = []

    class Consumer:
        def __init__(self, **kwargs):
            del kwargs

        async def start(self):
            return None

        async def subscribe(self, stream, callback, **kwargs):
            del stream, callback
            subscribed.append(
                cast(ConsumerOffsetSpecification, kwargs["offset_specification"])
            )
            return 1

        async def unsubscribe(self, subscriber_id):
            del subscriber_id

        async def close(self):
            return None

    selected = RabbitMqPersistentStreamsOptions(options().connection)
    log = RabbitMqPersistentLog(selected)
    definition = StreamDefinition("events", 1)
    log._definitions[definition.name] = definition
    log._started = True
    earliest = iter((4, 6))

    async def current_earliest(stream, partition):
        del stream, partition
        return next(earliest)

    async def barrier(physical):
        del physical
        return uuid4()

    monkeypatch.setattr(reading_module, "Consumer", Consumer)
    monkeypatch.setattr(log, "_earliest", current_earliest)
    monkeypatch.setattr(log, "_write_barrier", barrier)

    with pytest.raises(RetentionGapError):
        await log.read("events", 0, 5, 1)
    assert subscribed[0].offset_type is OffsetType.OFFSET
    assert subscribed[0].offset == 5


@pytest.mark.asyncio
async def test_metadata_disconnect_callback_fails_adapter_closed() -> None:
    log = RabbitMqPersistentLog(options())
    generation = 3
    log._resource_generation = generation
    callback = log._close_callback(generation)
    from persistent_streams_rabbitmq._rstream_compat import MetadataClient

    metadata = MetadataClient(
        "rabbit.example",
        5552,
        username="streams",
        password="secret",
        on_close_handler=callback,
    )
    cast(Any, metadata._client._connection_closed_handler)(object())
    assert log._failed
    assert log._quiescing


@pytest.mark.asyncio
async def test_close_uses_one_total_deadline_for_all_resources() -> None:
    closed: list[int] = []

    class Resource:
        def __init__(self, value: int) -> None:
            self.value = value

        async def close(self) -> None:
            await asyncio.sleep(0.02)
            closed.append(self.value)

    selected = RabbitMqPersistentStreamsOptions(options().connection, close_timeout=0.1)
    log = RabbitMqPersistentLog(selected)
    cast(Any, log)._metadata = Resource(1)
    cast(Any, log)._tracker = Resource(2)
    cast(Any, log)._producer = Resource(3)
    slot = await log._publisher_slot(("events", "named"))
    cast(Any, slot).producer = Resource(4)
    await log.close()
    assert set(closed) == {1, 2, 3, 4}


@pytest.mark.asyncio
async def test_named_producer_limit_precedes_native_allocation() -> None:
    selected = RabbitMqPersistentStreamsOptions(
        options().connection, max_named_producers=1
    )
    log = RabbitMqPersistentLog(selected)
    existing = await log._publisher_slot(("events", "one"))

    with pytest.raises(ResourceLimitError, match="resource limit"):
        await log._publisher_slot(("events", "two"))
    assert log._publisher_slots == {("events", "one"): existing}


@pytest.mark.asyncio
async def test_start_closes_resource_whose_start_partially_fails(monkeypatch) -> None:
    started: list[str] = []
    closed: list[str] = []

    class Resource:
        def __init__(self, name: str, *, fail: bool = False) -> None:
            self.name = name
            self.fail = fail

        async def start(self) -> None:
            started.append(self.name)
            if self.fail:
                raise RuntimeError("partial startup failure")

        async def close(self) -> None:
            closed.append(self.name)

    monkeypatch.setattr(log_module, "Producer", lambda **kwargs: Resource("producer"))
    monkeypatch.setattr(
        log_module, "Consumer", lambda **kwargs: Resource("tracker", fail=True)
    )
    monkeypatch.setattr(
        log_module,
        "MetadataClient",
        lambda *args, **kwargs: Resource("metadata"),
    )

    log = RabbitMqPersistentLog(options())
    with pytest.raises(RuntimeError, match="partial startup failure"):
        await log.start()

    assert started == ["producer", "tracker"]
    assert closed == ["tracker", "producer"]
    assert log.unwrap() == (None, None)


@pytest.mark.asyncio
async def test_failed_named_publisher_start_keeps_slot_for_waiters(monkeypatch) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    starts = 0

    class Producer:
        def __init__(self, **kwargs):
            del kwargs

        async def start(self):
            nonlocal starts
            starts += 1
            if starts == 1:
                entered.set()
                await release.wait()
                raise RuntimeError("startup failed")

        async def close(self):
            return None

    log = RabbitMqPersistentLog(options())
    log._resource_generation = 1
    slot = await log._publisher_slot(("events", "named"))
    monkeypatch.setattr(publishing_module, "Producer", Producer)

    async def start_publisher():
        async with slot.lock:
            return await log._publisher(slot, "named")

    first = asyncio.create_task(start_publisher())
    await entered.wait()
    second = asyncio.create_task(start_publisher())
    await asyncio.sleep(0)
    assert not second.done()
    release.set()
    with pytest.raises(RuntimeError, match="startup failed"):
        await first
    producer = await second

    assert starts == 2
    assert log._publisher_slots[("events", "named")] is slot
    assert slot.producer is producer


@pytest.mark.asyncio
async def test_unnamed_publications_reuse_started_base_producer(monkeypatch) -> None:
    class UnexpectedProducer:
        def __init__(self, **kwargs):
            raise AssertionError(f"unexpected producer allocation: {kwargs}")

    log = RabbitMqPersistentLog(options())
    base = object()
    cast(Any, log)._producer = base
    first = await log._publisher_slot(("events-0", None))
    second = await log._publisher_slot(("events-1", None))
    monkeypatch.setattr(publishing_module, "Producer", UnexpectedProducer)

    assert await log._publisher(first, None) is base
    assert await log._publisher(second, None) is base
    assert len(log._publisher_slots) == 2


@pytest.mark.asyncio
async def test_physical_stream_limit_precedes_declaration(monkeypatch) -> None:
    selected = RabbitMqPersistentStreamsOptions(options().connection, max_streams=2)
    log = RabbitMqPersistentLog(selected)
    log._definitions["existing"] = StreamDefinition("existing", 2)

    async def unexpected(definition):
        raise AssertionError(f"unexpected declaration: {definition}")

    monkeypatch.setattr(log, "_declare_regular", unexpected)
    with pytest.raises(ResourceLimitError, match="physical stream resource limit"):
        await log.declare_stream(StreamDefinition("other", 1))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["fence", "load", "compare", "save"])
async def test_malformed_external_checkpoint_results_are_typed(operation: str) -> None:
    class MalformedStore(InMemoryCheckpointStore):
        async def fence(self, key, owner):
            if operation == "fence":
                return "invalid"
            return await super().fence(key, owner)

        async def load(self, key):
            if operation == "load":
                return "invalid"
            return await super().load(key)

        async def compare_and_create(self, key, cursor, owner):
            if operation == "compare":
                return "invalid"
            return await super().compare_and_create(key, cursor, owner)

        async def save(self, key, expected, cursor, owner):
            if operation == "save":
                return "invalid"
            return await super().save(key, expected, cursor, owner)

    log = RabbitMqPersistentLog(options())
    definition = StreamDefinition("events", 1)
    log._definitions[definition.name] = definition
    store = MalformedStore()
    key = CheckpointKey("events", "group", 0)
    owner = OwnershipToken("owner", 1)
    strategy = ExternalCheckpointStrategy("malformed", store)
    lease = RabbitMqPartitionLease(
        log,
        Subscription("events", "group", "owner", Beginning()),
        key,
        owner,
        strategy,
    )
    lease._active = True
    lease._active_generation = 1
    log._leases[key] = lease

    with pytest.raises(CheckpointPersistenceError) as caught:
        if operation in {"fence", "load"}:
            await lease._load_cursor()
        elif operation == "compare":
            await store.fence(key, owner)
            await lease._create_cursor(ResumeCursor.initialized(0), 1)
        else:
            expected = ResumeCursor.initialized(0)
            await store.fence(key, owner)
            await store.compare_and_create(key, expected, owner)
            record = StoredRecord(
                uuid4(), "events", b"key", b"", {}, 0, 1, datetime.now(UTC)
            )
            lease._cursor = expected
            lease._in_flight = record
            await lease.checkpoint(record)

    assert isinstance(caught.value.cause, AdapterContractError)
    assert caught.value.__cause__ is caught.value.cause


@pytest.mark.asyncio
@pytest.mark.parametrize("raced_partitions", [(), ("events-0",)])
async def test_regular_declaration_rechecks_super_stream_race(
    monkeypatch, raced_partitions: tuple[str, ...]
) -> None:
    class Producer:
        def __init__(self, **kwargs):
            del kwargs

        async def start(self):
            return None

        async def stream_exists(self, name):
            del name
            return False

        async def create_stream(self, name, **kwargs):
            del name, kwargs

        async def close(self):
            return None

    log = RabbitMqPersistentLog(options())
    inspections = iter((None, raced_partitions))

    async def inspect(name):
        del name
        return next(inspections)

    monkeypatch.setattr(topology_module, "Producer", Producer)
    monkeypatch.setattr(log, "_inspect_super_partitions", inspect)
    with pytest.raises(Exception, match="Super Stream exists"):
        await log._declare_regular(StreamDefinition("events", 1))


@pytest.mark.asyncio
async def test_fail_closed_cancels_blocked_local_broker_checkpoint() -> None:
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    class Tracker:
        async def store_offset(self, stream, reference, offset):
            del stream, reference, offset
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    selected = RabbitMqPersistentStreamsOptions(
        options().connection,
        broker_managed_single_instance=True,
        operation_timeout=10,
    )
    log = RabbitMqPersistentLog(selected)
    definition = StreamDefinition("events", 1)
    log._definitions[definition.name] = definition
    log._resource_generation = 1
    cast(Any, log)._tracker = Tracker()
    key = CheckpointKey("events", "group", 0)
    lease = RabbitMqPartitionLease(
        log,
        Subscription("events", "group", "only-process", Beginning()),
        key,
        OwnershipToken("only-process", 1),
        CheckpointStrategy.BROKER_MANAGED,
    )
    lease._resource_generation = 1
    lease._active = True
    lease._active_generation = 1
    lease._cursor = ResumeCursor.initialized(0)

    record = StoredRecord(uuid4(), "events", b"key", b"", {}, 0, 1, datetime.now(UTC))
    lease._in_flight = record
    lease._delivery_completed.clear()
    log._leases[key] = lease
    checkpoint = asyncio.create_task(lease.checkpoint(record))
    await entered.wait()

    log._close_callback(1)(object())
    await asyncio.wait_for(cancelled.wait(), 1)
    with pytest.raises(asyncio.CancelledError):
        await checkpoint
    assert lease.stopped
    assert log._failed


def test_factory_and_module_materialization_are_lazy() -> None:
    selected = options()
    factory = RabbitMqStreamAdapterFactory(selected)
    log = factory.create(())
    assert isinstance(log, RabbitMqPersistentLog)
    assert log.unwrap() == (None, None)
    descriptor = RabbitMqPersistentStreamsModule.for_root(selected)
    assert descriptor.module is RabbitMqPersistentStreamsModule
    spec = cast(ModuleSpec, descriptor.factory())
    assert tuple(spec.exports) == (StreamAdapterFactory,)
    assert "rstream.producer" in sys.modules  # imported only by explicit facade use


def test_async_module_preserves_its_options_factory_imports() -> None:
    @module()
    class ConfigurationModule:
        pass

    descriptor = RabbitMqPersistentStreamsModule.for_root_async(
        use_factory=options,
        imports=[ConfigurationModule],
    )
    spec = cast(ModuleSpec, descriptor.factory())

    assert tuple(spec.imports) == (ConfigurationModule,)
    assert tuple(spec.exports) == (StreamAdapterFactory,)


@pytest.mark.asyncio
async def test_successful_strategy_binding_survives_last_lease_release() -> None:
    log = RabbitMqPersistentLog(
        RabbitMqPersistentStreamsOptions(
            options().connection,
            broker_managed_single_instance=True,
        )
    )
    definition = StreamDefinition("events", 2)
    log._definitions[definition.name] = definition
    strategy = ExternalCheckpointStrategy("shared", InMemoryCheckpointStore())
    lease = cast(
        RabbitMqPartitionLease,
        await log.acquire(
            Subscription("events", "group", "replica-a", Beginning()),
            0,
            strategy=strategy,
        ),
    )
    log._commit_strategy(lease.key)
    lease._strategy_initialized = True

    await lease.release()

    assert not log._leases
    assert not log._pending_strategies
    with pytest.raises(CheckpointStrategyError, match="strategy changed"):
        await log.acquire(
            Subscription("events", "group", "only-process", Beginning()),
            1,
            strategy=CheckpointStrategy.BROKER_MANAGED,
        )


@pytest.mark.asyncio
async def test_only_failed_strategy_reservation_is_removed() -> None:
    log = RabbitMqPersistentLog(options())
    definition = StreamDefinition("events", 2)
    log._definitions[definition.name] = definition
    first_store = InMemoryCheckpointStore()
    strategy = ExternalCheckpointStrategy("shared", first_store)
    first = await log.acquire(
        Subscription("events", "group", "replica-a", Beginning()),
        0,
        strategy=strategy,
    )
    second = await log.acquire(
        Subscription("events", "group", "replica-a", Beginning()),
        1,
        strategy=strategy,
    )

    await first.release()

    with pytest.raises(CheckpointStrategyError, match="initialization is in progress"):
        await log.acquire(
            Subscription("events", "group", "replica-a", Beginning()),
            0,
            strategy=ExternalCheckpointStrategy("other", InMemoryCheckpointStore()),
        )
    await second.release()
    replacement = await log.acquire(
        Subscription("events", "group", "replica-a", Beginning()),
        0,
        strategy=ExternalCheckpointStrategy("other", InMemoryCheckpointStore()),
    )
    await replacement.release()

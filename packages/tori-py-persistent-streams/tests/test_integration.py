from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Annotated, Protocol, cast
from uuid import UUID, uuid4

import pytest
from tori_py import (
    ApplicationOptions,
    PipelineResult,
    Scope,
    ValueProvider,
    controller,
    injectable,
    module,
    use_filter,
    use_interceptor,
    use_pipe,
)
from tori_py.testing import TestingModule
from tori_py_persistent_streams import (
    ConfiguredStreamPublisher,
    PersistentStreamsModule,
    PersistentStreamsOptions,
    PersistentStreamsRuntimeOptions,
    PublisherRegistration,
    StreamInject,
    StreamOffset,
    StreamPartition,
    StreamPayload,
    StreamPublisher,
    StreamRuntime,
    stream_handler,
    stream_publish,
    stream_publisher_token,
)
from tori_py_persistent_streams.options import StreamBinding
from tori_py_persistent_streams.testing import (
    InMemoryPersistentStreamsModule,
    InMemoryStreamAdapterFactory,
)
from tori_py_persistent_streams_core import (
    InMemoryPersistentLog,
    PersistentStreamAdapter,
    PublishOutcome,
    PublishReceipt,
    StreamDefinition,
)


@dataclass(frozen=True)
class Event:
    value: str


class Codec:
    def encode(self, payload: object) -> bytes:
        if not isinstance(payload, Event):
            raise TypeError
        return payload.value.encode()

    def decode(self, payload: bytes, target: type[object]) -> object:
        return target(payload.decode())


class Key:
    def resolve(self, payload: object) -> bytes:
        return cast(Event, payload).value.encode()


class EventPublisher(Protocol):
    @stream_publish(payload=Event)
    async def send(
        self,
        payload: Event,
        *,
        record_id: UUID | None = None,
        headers=None,
    ) -> PublishReceipt: ...


async def wait_until(predicate, timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


def stream_options(*, pipeline=()) -> PersistentStreamsOptions:
    del pipeline
    return PersistentStreamsOptions(
        bindings=(
            StreamBinding(
                "events",
                StreamDefinition("events-v1", 2),
                Event,
                Codec(),
                Key(),
            ),
        ),
        publishers=(PublisherRegistration("events", protocol=EventPublisher),),
        runtime=PersistentStreamsRuntimeOptions(max_concurrency=2, poll_interval=0.001),
    )


@pytest.mark.asyncio
async def test_three_publishers_delegate_to_one_runtime_and_handler() -> None:
    received: list[str] = []

    @controller()
    class Projection:
        @stream_handler(stream="events", consumer_group="projection-v1")
        async def apply(self, payload: Annotated[Event, StreamPayload()]) -> None:
            received.append(payload.value)

    factory = InMemoryStreamAdapterFactory()
    streams = PersistentStreamsModule.for_root(
        stream_options(),
        imports=[InMemoryPersistentStreamsModule.for_root(factory)],
    )

    @module(imports=[streams], controllers=[Projection])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    raw = cast(StreamPublisher, await application.resolve(StreamPublisher))
    named = cast(
        ConfiguredStreamPublisher[Event],
        await application.resolve(stream_publisher_token("events")),
    )
    protocol = cast(EventPublisher, await application.resolve(EventPublisher))
    explicit_id = uuid4()

    first = await raw.publish("events", Event("raw"), record_id=explicit_id)
    second = await named.publish(Event("named"))
    third = await protocol.send(Event("protocol"))

    assert first.record_id == explicit_id
    assert {first.outcome, second.outcome, third.outcome} == {PublishOutcome.CONFIRMED}
    await wait_until(lambda: len(received) == 3)
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    assert runtime.ready
    assert all(status.offset is not None for status in runtime.statuses)
    await application.close()
    assert runtime.state.value == "closed"


@pytest.mark.asyncio
async def test_partition_processing_is_serial_and_preserves_sparse_offsets() -> None:
    active = 0
    maximum = 0
    handled: list[tuple[str, int]] = []

    class OneKey:
        def resolve(self, payload: object) -> bytes:
            del payload
            return b"one-partition"

    @controller()
    class Projection:
        @stream_handler(stream="events", consumer_group="projection-v1")
        async def apply(
            self,
            payload: Annotated[Event, StreamPayload()],
            offset: Annotated[int, StreamOffset()],
        ) -> None:
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.002)
            handled.append((payload.value, offset))
            active -= 1

    options = PersistentStreamsOptions(
        bindings=(
            StreamBinding(
                "events",
                StreamDefinition("events-v1", 1),
                Event,
                Codec(),
                OneKey(),
            ),
        ),
        runtime=PersistentStreamsRuntimeOptions(max_concurrency=4, poll_interval=0.001),
    )
    streams = PersistentStreamsModule.for_root(
        options, imports=[InMemoryPersistentStreamsModule.for_root()]
    )

    @module(imports=[streams], controllers=[Projection])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    for index in range(5):
        await publisher.publish("events", Event(str(index)))
    await wait_until(lambda: len(handled) == 5)
    assert handled == [(str(index), index * 2) for index in range(5)]
    assert maximum == 1
    await application.close()


@pytest.mark.asyncio
async def test_cross_partition_concurrency_is_bounded() -> None:
    active = 0
    maximum = 0
    reached_bound = asyncio.Event()
    release = asyncio.Event()

    definition = StreamDefinition("events-v1", 4)
    values: dict[int, str] = {}
    candidate = 0
    while len(values) < definition.partition_count:
        value = str(candidate)
        partition = definition.router.route(value.encode(), definition.partition_count)
        values.setdefault(partition, value)
        candidate += 1

    @controller()
    class Projection:
        @stream_handler(stream="events", consumer_group="projection-v1")
        async def apply(
            self,
            payload: Annotated[Event, StreamPayload()],
            partition: Annotated[int, StreamPartition()],
        ) -> None:
            nonlocal active, maximum
            assert values[partition] == payload.value
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                reached_bound.set()
            await release.wait()
            active -= 1

    options = PersistentStreamsOptions(
        bindings=(StreamBinding("events", definition, Event, Codec(), Key()),),
        runtime=PersistentStreamsRuntimeOptions(max_concurrency=2, poll_interval=0.001),
    )
    streams = PersistentStreamsModule.for_root(
        options, imports=[InMemoryPersistentStreamsModule.for_root()]
    )

    @module(imports=[streams], controllers=[Projection])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    for value in values.values():
        await publisher.publish("events", Event(value))
    await asyncio.wait_for(reached_bound.wait(), 1.0)
    assert maximum == 2
    release.set()
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    await wait_until(
        lambda: all(status.offset is not None for status in runtime.statuses)
    )
    await application.close()


@pytest.mark.asyncio
async def test_shutdown_cancellation_leaves_active_record_uncheckpointed() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    @controller()
    class Projection:
        @stream_handler(stream="events", consumer_group="projection-v1")
        async def apply(self, payload: Annotated[Event, StreamPayload()]) -> None:
            del payload
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    options = PersistentStreamsOptions(
        bindings=(
            StreamBinding(
                "events",
                StreamDefinition("events-v1", 1),
                Event,
                Codec(),
                Key(),
            ),
        ),
        runtime=PersistentStreamsRuntimeOptions(poll_interval=0.001),
    )
    streams = PersistentStreamsModule.for_root(
        options, imports=[InMemoryPersistentStreamsModule.for_root()]
    )

    @module(imports=[streams], controllers=[Projection])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile(
        options=ApplicationOptions(
            shutdown_timeout=0.3,
            cancellation_grace=0.05,
            cleanup_reserve=0.05,
        )
    )
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    await publisher.publish("events", Event("active"))
    await asyncio.wait_for(started.wait(), 1.0)
    await application.close()
    assert cancelled.is_set()
    assert all(status.offset is None for status in runtime.statuses)
    assert runtime.state.value == "closed"


@pytest.mark.asyncio
async def test_pipe_and_interceptor_order_precedes_checkpoint() -> None:
    order: list[str] = []

    class Pipe:
        async def transform(self, value, metadata):
            del metadata
            order.append("pipe")
            return Event(value.value.upper())

    class Interceptor:
        async def intercept(self, context, next):
            del context
            order.append("before")
            result = await next()
            order.append("after")
            return result

    @controller()
    class Projection:
        @stream_handler(stream="events", consumer_group="projection-v1")
        @use_pipe(Pipe())
        @use_interceptor(Interceptor())
        async def apply(self, payload: Annotated[Event, StreamPayload()]) -> None:
            order.append(f"handler:{payload.value}")

    factory = InMemoryStreamAdapterFactory()
    streams = PersistentStreamsModule.for_root(
        stream_options(),
        imports=[InMemoryPersistentStreamsModule.for_root(factory)],
    )

    @module(imports=[streams], controllers=[Projection])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    await publisher.publish("events", Event("value"))
    await wait_until(
        lambda: any(status.offset is not None for status in runtime.statuses)
    )

    assert order == ["pipe", "before", "handler:VALUE", "after"]
    await application.close()


@pytest.mark.asyncio
async def test_handler_failure_blocks_partition_without_checkpoint() -> None:
    attempts = 0

    @controller()
    class Projection:
        @stream_handler(stream="events", consumer_group="projection-v1")
        async def apply(self, payload: Annotated[Event, StreamPayload()]) -> None:
            nonlocal attempts
            attempts += 1
            raise RuntimeError(payload.value)

    factory = InMemoryStreamAdapterFactory()
    streams = PersistentStreamsModule.for_root(
        stream_options(),
        imports=[InMemoryPersistentStreamsModule.for_root(factory)],
    )

    @module(imports=[streams], controllers=[Projection])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    receipt = await publisher.publish("events", Event("poison"))
    await wait_until(lambda: runtime.state.value == "degraded")

    blocked = [status for status in runtime.statuses if status.state == "blocked"]
    assert attempts == 1
    assert len(blocked) == 1
    assert blocked[0].partition == receipt.partition
    assert blocked[0].offset == 0
    assert not runtime.ready
    await application.close()


@pytest.mark.asyncio
async def test_async_factory_is_injected_and_not_called_during_materialization() -> (
    None
):
    calls = 0

    async def create_options() -> PersistentStreamsRuntimeOptions:
        nonlocal calls
        calls += 1
        return PersistentStreamsRuntimeOptions(poll_interval=0.001)

    streams = PersistentStreamsModule.for_root_async(
        use_factory=create_options,
        bindings=stream_options().bindings,
        imports=[InMemoryPersistentStreamsModule.for_root()],
        publishers=(PublisherRegistration("events", name="event-writes"),),
    )
    assert calls == 0
    streams.factory()
    assert calls == 0

    @module(imports=[streams])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    assert calls == 1
    await application.close()


@pytest.mark.asyncio
async def test_provider_token_codec_and_resolver_are_resolved_from_imports() -> None:
    codec_token = "test:stream-codec"
    key_token = "test:partition-key"

    @module(
        providers=[
            ValueProvider(codec_token, Codec()),
            ValueProvider(key_token, Key()),
        ],
        exports=[codec_token, key_token],
    )
    class ComponentsModule:
        pass

    binding = StreamBinding(
        "events",
        StreamDefinition("events-v1", 1),
        Event,
        codec_token,
        key_token,
    )

    async def create_options() -> PersistentStreamsRuntimeOptions:
        return PersistentStreamsRuntimeOptions(
            poll_interval=0.001,
        )

    streams = PersistentStreamsModule.for_root_async(
        use_factory=create_options,
        bindings=(binding,),
        imports=[InMemoryPersistentStreamsModule.for_root(), ComponentsModule],
        publishers=(PublisherRegistration("events", name="event-writes"),),
    )

    @module(imports=[streams])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    receipt = await publisher.publish("events", Event("token-backed"))
    assert receipt.outcome is PublishOutcome.CONFIRMED
    await application.close()


@pytest.mark.asyncio
async def test_filter_cannot_recover_a_failed_attempt() -> None:
    filtered: list[str] = []

    class Filter:
        async def catch(self, error, context):
            del context
            filtered.append(str(error))
            return PipelineResult.from_value(None)

    @controller()
    class Projection:
        @stream_handler(stream="events", consumer_group="projection-v1")
        @use_filter(Filter())
        async def apply(self, payload: Annotated[Event, StreamPayload()]) -> None:
            raise RuntimeError(payload.value)

    streams = PersistentStreamsModule.for_root(
        stream_options(), imports=[InMemoryPersistentStreamsModule.for_root()]
    )

    @module(imports=[streams], controllers=[Projection])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    await publisher.publish("events", Event("still-poison"))
    await wait_until(lambda: runtime.state.value == "degraded")
    assert filtered == ["still-poison"]
    assert any(status.state == "blocked" for status in runtime.statuses)
    await application.close()


@pytest.mark.asyncio
async def test_work_scope_cleanup_happens_before_checkpoint() -> None:
    order: list[str] = []

    @injectable(scope=Scope.REQUEST)
    class Resource:
        async def __aenter__(self):
            order.append("resource-enter")
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            del exc_type, exc, traceback
            order.append("resource-cleanup")

    class TrackingLease:
        def __init__(self, lease):
            self._lease = lease

        @property
        def key(self):
            return self._lease.key

        @property
        def owner(self):
            return self._lease.owner

        @property
        def stopped(self):
            return self._lease.stopped

        async def next_record(self):
            return await self._lease.next_record()

        async def checkpoint(self, record):
            order.append("checkpoint")
            await self._lease.checkpoint(record)

        async def stop(self):
            await self._lease.stop()

        async def release(self):
            await self._lease.release()

    class TrackingLog:
        def __init__(self):
            self.inner = InMemoryPersistentLog()

        @property
        def start_mode_capabilities(self):
            return self.inner.start_mode_capabilities

        async def start(self):
            await self.inner.start()

        async def quiesce(self):
            await self.inner.quiesce()

        async def declare_stream(self, definition):
            await self.inner.declare_stream(definition)

        async def append(self, stream, request):
            return await self.inner.append(stream, request)

        async def bounds(self, stream, partition):
            return await self.inner.bounds(stream, partition)

        async def read(self, stream, partition, from_offset, limit):
            return await self.inner.read(stream, partition, from_offset, limit)

        async def acquire(self, subscription, partition, *, strategy, transfer=False):
            lease = await self.inner.acquire(
                subscription,
                partition,
                strategy=strategy,
                transfer=transfer,
            )
            return TrackingLease(lease)

        async def close(self):
            await self.inner.close()

    @controller()
    class Projection:
        @stream_handler(stream="events", consumer_group="projection-v1")
        async def apply(
            self,
            payload: Annotated[Event, StreamPayload()],
            resource: Annotated[Resource, StreamInject(Resource)],
        ) -> None:
            del payload, resource
            order.append("handler")

    Projection.apply.__annotations__["resource"] = Annotated[
        Resource, StreamInject(Resource)
    ]

    tracking_log = TrackingLog()
    factory = InMemoryStreamAdapterFactory(cast(PersistentStreamAdapter, tracking_log))
    streams = PersistentStreamsModule.for_root(
        stream_options(),
        imports=[InMemoryPersistentStreamsModule.for_root(factory)],
    )

    @module(imports=[streams], controllers=[Projection], providers=[Resource])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    await publisher.publish("events", Event("scope"))
    await wait_until(lambda: "checkpoint" in order)
    assert order == [
        "resource-enter",
        "handler",
        "resource-cleanup",
        "checkpoint",
    ]
    await application.close()

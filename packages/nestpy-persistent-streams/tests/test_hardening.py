from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Annotated, cast

import pytest
from nestpy import (
    ApplicationOptions,
    Inject,
    Scope,
    ValueProvider,
    controller,
    injectable,
    module,
    use_filter,
    use_guard,
    use_interceptor,
    use_pipe,
)
from nestpy.testing import TestingModule
from nestpy_persistent_streams import (
    PersistentStreamsModule,
    PersistentStreamsOptions,
    PersistentStreamsRuntimeOptions,
    StreamBinding,
    StreamConfigurationError,
    StreamInject,
    StreamPayload,
    StreamPublicationSaturatedError,
    StreamPublisher,
    StreamRuntime,
    StreamRuntimeError,
    stream_handler,
)
from nestpy_persistent_streams.testing import (
    InMemoryPersistentStreamsModule,
    InMemoryStreamAdapterFactory,
)
from persistent_streams import (
    ExternalCheckpointStrategy,
    InMemoryCheckpointStore,
    InMemoryPersistentLog,
    PartitionLease,
    PersistentStreamAdapter,
    StreamDefinition,
    StreamLimits,
)

OWNER_TOKEN = "test:stream-owner"
OWNER_MARKER = "test:owner-marker"


@dataclass(frozen=True)
class Event:
    value: str


class Codec:
    def encode(self, payload: object) -> bytes:
        return cast(Event, payload).value.encode()

    def decode(self, payload: bytes, target: type[object]) -> object:
        return target(payload.decode())


class Key:
    def resolve(self, payload: object) -> bytes:
        return cast(Event, payload).value.encode()


def binding() -> StreamBinding:
    return StreamBinding(
        "events", StreamDefinition("events-v1", 1), Event, Codec(), Key()
    )


def options() -> PersistentStreamsOptions:
    return PersistentStreamsOptions(
        (binding(),),
        runtime=PersistentStreamsRuntimeOptions(poll_interval=0.001),
    )


def test_external_multi_replica_requires_unique_owner_declaration() -> None:
    base = binding()
    external = StreamBinding(
        base.alias,
        base.definition,
        base.payload_type,
        base.codec,
        base.partition_key_resolver,
        checkpoint_strategy=ExternalCheckpointStrategy(
            "shared", InMemoryCheckpointStore()
        ),
    )
    with pytest.raises(StreamConfigurationError, match="replica-unique owner_id"):
        PersistentStreamsOptions((external,))
    configured = PersistentStreamsOptions(
        (external,),
        runtime=PersistentStreamsRuntimeOptions(
            owner_id="replica-a", owner_id_is_replica_unique=True
        ),
    )
    assert configured.runtime.owner_id == "replica-a"


class LeaseProxy:
    def __init__(self, inner: PartitionLease) -> None:
        self.inner = inner

    @property
    def key(self):
        return self.inner.key

    @property
    def owner(self):
        return self.inner.owner

    @property
    def stopped(self):
        return self.inner.stopped

    async def next_record(self):
        return await self.inner.next_record()

    async def checkpoint(self, record):
        await self.inner.checkpoint(record)

    async def stop(self):
        await self.inner.stop()

    async def release(self):
        await self.inner.release()


class AdapterProxy:
    def __init__(self) -> None:
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
        return await self.inner.acquire(
            subscription, partition, strategy=strategy, transfer=transfer
        )

    async def close(self):
        await self.inner.close()


def configured(adapter: object):
    factory = InMemoryStreamAdapterFactory(cast(PersistentStreamAdapter, adapter))
    return InMemoryPersistentStreamsModule.for_root(factory)


async def wait_until(predicate, timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


@pytest.mark.asyncio
@pytest.mark.parametrize("persist_first", [True, False])
async def test_checkpoint_cancellation_blocks_with_unknown_outcome(
    persist_first: bool,
) -> None:
    checkpoint_started = asyncio.Event()

    class CheckpointLease(LeaseProxy):
        async def checkpoint(self, record):
            if persist_first:
                await self.inner.checkpoint(record)
            checkpoint_started.set()
            await asyncio.Event().wait()

    class CheckpointAdapter(AdapterProxy):
        async def acquire(self, subscription, partition, *, strategy, transfer=False):
            lease = await super().acquire(
                subscription, partition, strategy=strategy, transfer=transfer
            )
            return CheckpointLease(lease)

    @controller()
    class Projection:
        @stream_handler(stream="events", consumer_group="projection-v1")
        async def apply(self, payload: Annotated[Event, StreamPayload()]) -> None:
            del payload

    adapter = CheckpointAdapter()
    streams = PersistentStreamsModule.for_root(options(), adapter=configured(adapter))

    @module(imports=[streams], controllers=[Projection])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile(
        options=ApplicationOptions(
            shutdown_timeout=0.25,
            cancellation_grace=0.05,
            cleanup_reserve=0.05,
        )
    )
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    await publisher.publish("events", Event("value"))
    await asyncio.wait_for(checkpoint_started.wait(), 1.0)

    await application.close()

    status = runtime.statuses[0]
    assert status.state == "blocked"
    assert status.offset == 0
    assert status.diagnostic_code == "persistent_streams.checkpoint_outcome_unknown"


@pytest.mark.asyncio
async def test_publication_admission_is_fenced_before_quiesce_drain() -> None:
    append_started = asyncio.Event()
    append_release = asyncio.Event()
    quiesced = asyncio.Event()

    class BarrierAdapter(AdapterProxy):
        async def append(self, stream, request):
            append_started.set()
            await append_release.wait()
            return await super().append(stream, request)

        async def quiesce(self):
            await super().quiesce()
            quiesced.set()

    adapter = BarrierAdapter()
    streams = PersistentStreamsModule.for_root(options(), adapter=configured(adapter))

    @module(imports=[streams])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    accepted = asyncio.create_task(publisher.publish("events", Event("accepted")))
    await asyncio.wait_for(append_started.wait(), 1.0)
    closing = asyncio.create_task(application.close())
    await asyncio.wait_for(quiesced.wait(), 1.0)

    with pytest.raises(StreamRuntimeError, match="admission is closed"):
        await publisher.publish("events", Event("late"))
    assert not closing.done()

    append_release.set()
    assert (await accepted).record_id
    await closing


@pytest.mark.asyncio
async def test_quiesce_failure_still_drains_accepted_publications() -> None:
    append_started = asyncio.Event()
    append_release = asyncio.Event()

    class FailingQuiesceAdapter(AdapterProxy):
        async def append(self, stream, request):
            append_started.set()
            await append_release.wait()
            return await super().append(stream, request)

        async def quiesce(self):
            raise RuntimeError("quiesce failed")

    class Context:
        def remaining(self):
            return None

    adapter = FailingQuiesceAdapter()
    streams = PersistentStreamsModule.for_root(options(), adapter=configured(adapter))

    @module(imports=[streams])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    accepted = asyncio.create_task(publisher.publish("events", Event("accepted")))
    await asyncio.wait_for(append_started.wait(), 1.0)

    quiescing = asyncio.create_task(runtime.on_application_quiesce(Context()))  # type: ignore[arg-type]
    await asyncio.sleep(0)
    assert not quiescing.done()

    append_release.set()
    assert (await accepted).record_id
    with pytest.raises(RuntimeError, match="quiesce failed"):
        await quiescing
    await runtime.close()


@pytest.mark.asyncio
async def test_close_cancels_admitted_publications_before_adapter_close() -> None:
    append_started = asyncio.Event()
    append_finished = asyncio.Event()
    closed_after_append = False

    class CloseOrderingAdapter(AdapterProxy):
        async def append(self, stream, request):
            append_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                append_finished.set()

        async def close(self):
            nonlocal closed_after_append
            closed_after_append = append_finished.is_set()
            await super().close()

    adapter = CloseOrderingAdapter()
    streams = PersistentStreamsModule.for_root(options(), adapter=configured(adapter))

    @module(imports=[streams])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    accepted = asyncio.create_task(publisher.publish("events", Event("accepted")))
    await asyncio.wait_for(append_started.wait(), 1.0)

    await runtime.close()

    with pytest.raises(asyncio.CancelledError):
        await accepted
    assert closed_after_append


@pytest.mark.asyncio
async def test_publication_admission_rejects_above_configured_capacity() -> None:
    append_started = asyncio.Event()
    append_release = asyncio.Event()

    class BarrierAdapter(AdapterProxy):
        async def append(self, stream, request):
            append_started.set()
            await append_release.wait()
            return await super().append(stream, request)

    bounded = PersistentStreamsOptions(
        (binding(),),
        runtime=PersistentStreamsRuntimeOptions(
            poll_interval=0.001,
            max_pending_publications=1,
        ),
    )
    streams = PersistentStreamsModule.for_root(
        bounded, adapter=configured(BarrierAdapter())
    )

    @module(imports=[streams])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    with pytest.raises(StreamRuntimeError, match="unknown configured stream alias"):
        await publisher.publish("missing", Event("invalid"))
    accepted = asyncio.create_task(publisher.publish("events", Event("accepted")))
    await asyncio.wait_for(append_started.wait(), 1.0)

    with pytest.raises(StreamPublicationSaturatedError):
        await publisher.publish("events", Event("saturated"))

    append_release.set()
    assert (await accepted).record_id
    await application.close()


@pytest.mark.asyncio
async def test_bootstrap_waits_for_adapter_start_readiness() -> None:
    start_entered = asyncio.Event()
    start_release = asyncio.Event()

    class StartBarrierAdapter(AdapterProxy):
        async def start(self):
            start_entered.set()
            await start_release.wait()
            await super().start()

    adapter = StartBarrierAdapter()
    streams = PersistentStreamsModule.for_root(options(), adapter=configured(adapter))

    @module(imports=[streams])
    class AppModule:
        pass

    compiling = asyncio.create_task(TestingModule.create(AppModule).compile())
    await asyncio.wait_for(start_entered.wait(), 1.0)
    assert not compiling.done()
    start_release.set()
    application = await compiling
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    assert runtime.ready
    await application.close()


@pytest.mark.asyncio
async def test_partition_intake_failure_after_registration_degrades_readiness() -> None:
    closed = False

    class FailingLease(LeaseProxy):
        async def next_record(self):
            raise RuntimeError("intake failed")

    class FailingAdapter(AdapterProxy):
        async def acquire(self, subscription, partition, *, strategy, transfer=False):
            lease = await super().acquire(
                subscription, partition, strategy=strategy, transfer=transfer
            )
            return FailingLease(lease)

        async def close(self):
            nonlocal closed
            closed = True
            await super().close()

    @controller()
    class Projection:
        @stream_handler(stream="events", consumer_group="projection-v1")
        async def apply(self, payload: Annotated[Event, StreamPayload()]) -> None:
            del payload

    streams = PersistentStreamsModule.for_root(
        options(), adapter=configured(FailingAdapter())
    )

    @module(imports=[streams], controllers=[Projection])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    await wait_until(lambda: runtime.state.value == "degraded")
    assert runtime.statuses[0].diagnostic_code == "persistent_streams.partition_failed"
    await application.close()
    assert closed


@pytest.mark.asyncio
async def test_stopped_lease_after_registration_degrades_readiness() -> None:
    class StoppedLease(LeaseProxy):
        async def next_record(self):
            record = await self.inner.next_record()
            await self.inner.stop()
            return record

    class StoppedAdapter(AdapterProxy):
        async def acquire(self, subscription, partition, *, strategy, transfer=False):
            lease = await super().acquire(
                subscription, partition, strategy=strategy, transfer=transfer
            )
            return StoppedLease(lease)

    @controller()
    class Projection:
        @stream_handler(stream="events", consumer_group="projection-v1")
        async def apply(self, payload: Annotated[Event, StreamPayload()]) -> None:
            del payload

    streams = PersistentStreamsModule.for_root(
        options(), adapter=configured(StoppedAdapter())
    )

    @module(imports=[streams], controllers=[Projection])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    await wait_until(lambda: runtime.state.value == "degraded")
    assert runtime.statuses[0].diagnostic_code == "persistent_streams.partition_stopped"
    await application.close()


@pytest.mark.asyncio
async def test_natural_consumer_exit_degrades_readiness() -> None:
    stop_on_next_read = asyncio.Event()

    class StoppingLease(LeaseProxy):
        async def next_record(self):
            if stop_on_next_read.is_set():
                await self.inner.stop()
                return None
            return await self.inner.next_record()

    class StoppingAdapter(AdapterProxy):
        async def acquire(self, subscription, partition, *, strategy, transfer=False):
            lease = await super().acquire(
                subscription, partition, strategy=strategy, transfer=transfer
            )
            return StoppingLease(lease)

    @controller()
    class Projection:
        @stream_handler(stream="events", consumer_group="projection-v1")
        async def apply(self, payload: Annotated[Event, StreamPayload()]) -> None:
            del payload

    streams = PersistentStreamsModule.for_root(
        options(), adapter=configured(StoppingAdapter())
    )

    @module(imports=[streams], controllers=[Projection])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    stop_on_next_read.set()
    await wait_until(lambda: runtime.state.value == "degraded")

    assert not runtime.ready
    assert runtime.statuses[0].state == "blocked"
    assert runtime.statuses[0].diagnostic_code == "persistent_streams.partition_stopped"
    await application.close()


@pytest.mark.asyncio
async def test_adapter_start_failure_rolls_back_prepared_resources() -> None:
    closed = False

    class StartFailureAdapter(AdapterProxy):
        async def start(self):
            raise RuntimeError("start failed")

        async def close(self):
            nonlocal closed
            closed = True
            await super().close()

    streams = PersistentStreamsModule.for_root(
        options(), adapter=configured(StartFailureAdapter())
    )

    @module(imports=[streams])
    class AppModule:
        pass

    with pytest.raises(RuntimeError, match="start failed"):
        await TestingModule.create(AppModule).compile()
    assert closed


@pytest.mark.asyncio
async def test_async_runtime_factory_injects_imports_and_propagates_failure() -> None:
    @module(
        providers=[ValueProvider(OWNER_TOKEN, "injected-owner")],
        exports=[OWNER_TOKEN],
    )
    class ConfigurationModule:
        pass

    async def settings(
        owner: Annotated[str, Inject(OWNER_TOKEN)],
    ) -> PersistentStreamsRuntimeOptions:
        return PersistentStreamsRuntimeOptions(owner_id=owner)

    streams = PersistentStreamsModule.for_root_async(
        InMemoryPersistentStreamsModule.for_root(),
        bindings=(binding(),),
        use_factory=settings,
        imports=(ConfigurationModule,),
    )

    @module(imports=[streams])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    assert runtime.options.runtime.owner_id == "injected-owner"
    await application.close()

    async def failed_settings() -> PersistentStreamsRuntimeOptions:
        raise RuntimeError("settings failed")

    failed = PersistentStreamsModule.for_root_async(
        InMemoryPersistentStreamsModule.for_root(),
        bindings=(binding(),),
        use_factory=failed_settings,
    )

    @module(imports=[failed])
    class FailedModule:
        pass

    with pytest.raises(RuntimeError, match="settings failed"):
        await TestingModule.create(FailedModule).compile()


@pytest.mark.asyncio
async def test_async_runtime_owner_is_validated_only_after_factory_resolution() -> None:
    constrained = StreamBinding(
        "events",
        StreamDefinition(
            "events-v1",
            1,
            limits=StreamLimits(max_owner_chars=1),
        ),
        Event,
        Codec(),
        Key(),
    )

    async def settings() -> PersistentStreamsRuntimeOptions:
        return PersistentStreamsRuntimeOptions(owner_id="x", poll_interval=0.001)

    streams = PersistentStreamsModule.for_root_async(
        InMemoryPersistentStreamsModule.for_root(),
        bindings=(constrained,),
        use_factory=settings,
    )

    @module(imports=[streams])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    assert runtime.options.runtime.owner_id == "x"
    await application.close()


@pytest.mark.asyncio
async def test_handlers_resolve_dependencies_from_their_exact_owner_modules() -> None:
    resolved: list[str] = []

    @controller()
    class FirstProjection:
        @stream_handler(stream="events", consumer_group="first-v1")
        async def apply(
            self,
            payload: Annotated[Event, StreamPayload()],
            owner: Annotated[str, StreamInject(OWNER_MARKER)],
        ) -> None:
            resolved.append(f"{payload.value}:{owner}")

    @controller()
    class SecondProjection:
        @stream_handler(stream="events", consumer_group="second-v1")
        async def apply(
            self,
            payload: Annotated[Event, StreamPayload()],
            owner: Annotated[str, StreamInject(OWNER_MARKER)],
        ) -> None:
            resolved.append(f"{payload.value}:{owner}")

    @module(
        controllers=[FirstProjection],
        providers=[ValueProvider(OWNER_MARKER, "first")],
    )
    class FirstModule:
        pass

    @module(
        controllers=[SecondProjection],
        providers=[ValueProvider(OWNER_MARKER, "second")],
    )
    class SecondModule:
        pass

    streams = PersistentStreamsModule.for_root(
        options(), adapter=InMemoryPersistentStreamsModule.for_root()
    )

    @module(imports=[streams, FirstModule, SecondModule])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    await publisher.publish("events", Event("record"))
    await wait_until(lambda: len(resolved) == 2)
    assert set(resolved) == {"record:first", "record:second"}
    await application.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["decode", "dto"])
async def test_codec_and_dto_failures_block_without_checkpoint(mode: str) -> None:
    class FailingCodec(Codec):
        def decode(self, payload: bytes, target: type[object]) -> object:
            del payload, target
            if mode == "decode":
                raise ValueError("invalid payload")
            return object()

    failed_binding = StreamBinding(
        "events",
        StreamDefinition("events-v1", 1),
        Event,
        FailingCodec(),
        Key(),
    )

    @controller()
    class Projection:
        @stream_handler(stream="events", consumer_group="projection-v1")
        async def apply(self, payload: Annotated[Event, StreamPayload()]) -> None:
            del payload

    streams = PersistentStreamsModule.for_root(
        PersistentStreamsOptions(
            (failed_binding,),
            runtime=PersistentStreamsRuntimeOptions(poll_interval=0.001),
        ),
        adapter=InMemoryPersistentStreamsModule.for_root(),
    )

    @module(imports=[streams], controllers=[Projection])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    await publisher.publish("events", Event("bad"))
    await wait_until(lambda: not runtime.ready)
    assert runtime.statuses[0].offset == 0
    await application.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("component", ["guard", "pipe", "interceptor", "filter"])
async def test_pipeline_component_failures_block_without_checkpoint(
    component: str,
) -> None:
    class Guard:
        async def can_activate(self, context):
            del context
            raise RuntimeError("guard failed")

    class Pipe:
        async def transform(self, value, metadata):
            del value, metadata
            raise RuntimeError("pipe failed")

    class Interceptor:
        async def intercept(self, context, next):
            del context, next
            raise RuntimeError("interceptor failed")

    class Filter:
        async def catch(self, error, context):
            del error, context
            raise RuntimeError("filter failed")

    class Projection:
        @stream_handler(stream="events", consumer_group="projection-v1")
        async def apply(self, payload: Annotated[Event, StreamPayload()]) -> None:
            raise RuntimeError(payload.value)

    decorators = {
        "guard": use_guard(Guard()),
        "pipe": use_pipe(Pipe()),
        "interceptor": use_interceptor(Interceptor()),
        "filter": use_filter(Filter()),
    }
    Projection.apply = decorators[component](Projection.apply)
    Projection = controller()(Projection)
    streams = PersistentStreamsModule.for_root(
        options(), adapter=InMemoryPersistentStreamsModule.for_root()
    )

    @module(imports=[streams], controllers=[Projection])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    await publisher.publish("events", Event("failure"))
    await wait_until(lambda: not runtime.ready)
    assert runtime.statuses[0].offset == 0
    await application.close()


@pytest.mark.asyncio
async def test_work_scope_cleanup_failure_blocks_without_checkpoint() -> None:
    @injectable(scope=Scope.REQUEST)
    class Resource:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            del exc_type, exc, traceback
            raise RuntimeError("cleanup failed")

    @controller()
    class Projection:
        @stream_handler(stream="events", consumer_group="projection-v1")
        async def apply(
            self,
            payload: Annotated[Event, StreamPayload()],
            resource: Annotated[Resource, StreamInject(Resource)],
        ) -> None:
            del payload, resource

    Projection.apply.__annotations__["resource"] = Annotated[
        Resource, StreamInject(Resource)
    ]
    streams = PersistentStreamsModule.for_root(
        options(), adapter=InMemoryPersistentStreamsModule.for_root()
    )

    @module(imports=[streams], controllers=[Projection], providers=[Resource])
    class AppModule:
        pass

    application = await TestingModule.create(AppModule).compile()
    publisher = cast(StreamPublisher, await application.resolve(StreamPublisher))
    runtime = cast(StreamRuntime, await application.resolve(StreamRuntime))
    await publisher.publish("events", Event("cleanup"))
    await wait_until(lambda: not runtime.ready)
    assert runtime.statuses[0].offset == 0
    await application.close()

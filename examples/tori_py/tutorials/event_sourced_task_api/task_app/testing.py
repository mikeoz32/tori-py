"""Test-only adapters that preserve all four production composition roots."""

from __future__ import annotations

from dataclasses import dataclass

from tori_py import DeferredModule, ModuleSpec, ValueProvider
from tori_py_microservices import (
    InMemoryBroker,
    InMemoryClientTransport,
    InMemoryServerTransport,
    KeyedTransportFactoryReference,
    MicroservicesOptions,
    ServiceIdentity,
)
from tori_py_persistent_streams import StreamAdapterFactory
from tori_py_persistent_streams_core import (
    AppendRequest,
    AvailableBounds,
    CheckpointStrategy,
    ExternalCheckpointStrategy,
    InMemoryPersistentLog,
    PartitionLease,
    PublishReceipt,
    RecordPage,
    StartModeCapabilities,
    StreamDefinition,
    Subscription,
)


@dataclass(frozen=True, slots=True)
class InMemoryServerFactory:
    broker: InMemoryBroker

    def create(
        self,
        identity: ServiceIdentity,
        options: MicroservicesOptions,
    ) -> InMemoryServerTransport:
        return InMemoryServerTransport(
            self.broker,
            identity,
            prefetch=options.max_inflight_deliveries,
        )


@dataclass(frozen=True, slots=True)
class InMemoryClientFactory:
    broker: InMemoryBroker

    def create(self) -> InMemoryClientTransport:
        return InMemoryClientTransport(self.broker)


class InMemoryTransportModule:
    @classmethod
    def for_root(
        cls,
        broker: InMemoryBroker,
        reference: KeyedTransportFactoryReference,
    ) -> DeferredModule:
        server = InMemoryServerFactory(broker)
        client = InMemoryClientFactory(broker)

        def materialize() -> ModuleSpec:
            return ModuleSpec(
                providers=(
                    ValueProvider(reference.server_factory_token, server),
                    ValueProvider(reference.client_factory_token, client),
                ),
                exports=(
                    reference.server_factory_token,
                    reference.client_factory_token,
                ),
            )

        return DeferredModule(cls, reference.key, materialize)


class SharedPersistentLogHandle:
    """Application-owned handle whose shutdown never closes the shared log."""

    def __init__(self, log: InMemoryPersistentLog) -> None:
        self._log = log
        self.closed = False

    @property
    def start_mode_capabilities(self) -> StartModeCapabilities:
        return self._log.start_mode_capabilities

    async def declare_stream(self, definition: StreamDefinition) -> None:
        await self._log.declare_stream(definition)

    async def append(self, stream: str, request: AppendRequest) -> PublishReceipt:
        return await self._log.append(stream, request)

    async def bounds(
        self,
        stream: str,
        partition: int,
    ) -> AvailableBounds | None:
        return await self._log.bounds(stream, partition)

    async def read(
        self,
        stream: str,
        partition: int,
        from_offset: int,
        limit: int,
    ) -> RecordPage:
        return await self._log.read(stream, partition, from_offset, limit)

    async def acquire(
        self,
        subscription: Subscription,
        partition: int,
        *,
        strategy: CheckpointStrategy | ExternalCheckpointStrategy,
        transfer: bool = False,
    ) -> PartitionLease:
        return await self._log.acquire(
            subscription,
            partition,
            strategy=strategy,
            transfer=transfer,
        )

    async def start(self) -> None:
        await self._log.start()

    async def quiesce(self) -> None:
        # Another application can still publish or consume through its own handle.
        return None

    async def close(self) -> None:
        self.closed = True


@dataclass(slots=True)
class SharedStreamAdapterFactory:
    log: InMemoryPersistentLog
    handle: SharedPersistentLogHandle | None = None

    def create(self, bindings: tuple[object, ...]) -> SharedPersistentLogHandle:
        del bindings
        self.handle = SharedPersistentLogHandle(self.log)
        return self.handle


class SharedPersistentStreamsModule:
    @classmethod
    def for_root(
        cls,
        factory: SharedStreamAdapterFactory,
        *,
        key: str,
    ) -> DeferredModule:
        def materialize() -> ModuleSpec:
            return ModuleSpec(
                providers=(ValueProvider(StreamAdapterFactory, factory),),
                exports=(StreamAdapterFactory,),
            )

        return DeferredModule(cls, key, materialize)


class SharedPersistentStreamTestContext:
    """Own the central test log and close it exactly once after all handles."""

    def __init__(self) -> None:
        self.log = InMemoryPersistentLog()
        self.close_count = 0

    def factory(self) -> SharedStreamAdapterFactory:
        return SharedStreamAdapterFactory(self.log)

    async def close(self) -> None:
        if self.close_count == 0:
            self.close_count = 1
            await self.log.close()


__all__ = [
    "InMemoryClientFactory",
    "InMemoryServerFactory",
    "InMemoryTransportModule",
    "SharedPersistentLogHandle",
    "SharedPersistentStreamTestContext",
    "SharedPersistentStreamsModule",
    "SharedStreamAdapterFactory",
]

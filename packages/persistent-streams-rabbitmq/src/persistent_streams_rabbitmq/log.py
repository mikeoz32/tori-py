from __future__ import annotations

import asyncio

from persistent_streams import (
    AppendRequest,
    CheckpointKey,
    CheckpointStrategy,
    CheckpointStrategyError,
    ExternalCheckpointStrategy,
    InvalidPartitionError,
    LifecycleError,
    OwnershipError,
    OwnershipToken,
    PartitionLease,
    StreamDefinition,
    Subscription,
    UnknownStreamError,
    ValidationError,
)
from persistent_streams.validation import validate_append_request_limits
from rstream import Consumer, Producer
from rstream.recovery import BackOffRecoveryStrategy

from persistent_streams_rabbitmq._capabilities import RABBITMQ_START_MODE_CAPABILITIES
from persistent_streams_rabbitmq._rstream_compat import MetadataClient
from persistent_streams_rabbitmq._shared import best_effort_close
from persistent_streams_rabbitmq._state import PublisherSlot
from persistent_streams_rabbitmq.lease import RabbitMqPartitionLease
from persistent_streams_rabbitmq.options import RabbitMqPersistentStreamsOptions
from persistent_streams_rabbitmq.publishing import PublishingMixin
from persistent_streams_rabbitmq.reading import ReadingMixin
from persistent_streams_rabbitmq.topology import TopologyMixin, TopologyPreflight


class RabbitMqPersistentLog(TopologyMixin, PublishingMixin, ReadingMixin):
    start_mode_capabilities = RABBITMQ_START_MODE_CAPABILITIES

    def __init__(self, options: RabbitMqPersistentStreamsOptions) -> None:
        if not isinstance(options, RabbitMqPersistentStreamsOptions):
            raise TypeError("options must be RabbitMqPersistentStreamsOptions")
        self.options = options
        self._producer: Producer | None = None
        self._publisher_slots: dict[tuple[str, str | None], PublisherSlot] = {}
        self._tracker: Consumer | None = None
        self._metadata: MetadataClient | None = None
        self._definitions: dict[str, StreamDefinition] = {}
        self._topology: dict[str, TopologyPreflight] = {}
        self._leases: dict[CheckpointKey, RabbitMqPartitionLease] = {}
        self._generations: dict[CheckpointKey, int] = {}
        self._strategies: dict[tuple[str, str], object] = {}
        self._pending_strategies: dict[CheckpointKey, object] = {}
        self._pending: set[int] = set()
        self._pending_bytes = 0
        self._producer_coordinates: dict[
            tuple[str, int, str], tuple[int, AppendRequest]
        ] = {}
        self._admission_lock = asyncio.Lock()
        self._resource_lock = asyncio.Lock()
        self._declaration_lock = asyncio.Lock()
        self._closed = False
        self._failed = False
        self._resource_generation = 0
        self._quiescing = False
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    def unwrap(self) -> tuple[Producer | None, Consumer | None]:
        return self._producer, self._tracker

    async def start(self) -> None:
        self._require_open()
        async with self._resource_lock:
            if self._started:
                return
            self._resource_generation += 1
            generation = self._resource_generation
            kwargs = self.options.connection.driver_kwargs()
            callback = self._close_callback(generation)
            producer = Producer(
                **kwargs,
                on_close_handler=callback,
                recovery_strategy=BackOffRecoveryStrategy(False),
            )
            tracker = Consumer(
                **kwargs,
                on_close_handler=callback,
                recovery_strategy=BackOffRecoveryStrategy(False),
            )
            metadata = MetadataClient(
                self.options.connection.endpoint_host,
                self.options.connection.port,
                username=self.options.connection.username,
                password=self.options.connection.password,
                vhost=self.options.connection.vhost,
                ssl_context=kwargs["ssl_context"],
                heartbeat=self.options.connection.heartbeat,
                sasl_configuration_mechanism=kwargs["sasl_configuration_mechanism"],
                on_close_handler=callback,
            )
            attempted: list[object] = []
            try:
                for resource in (producer, tracker, metadata):
                    attempted.append(resource)
                    await self._within(resource.start())
            except BaseException:
                for resource in reversed(attempted):
                    await best_effort_close(resource)
                raise
            self._producer, self._tracker, self._metadata = producer, tracker, metadata
            self._started = True
            self._quiescing = False
            try:
                await asyncio.gather(
                    *(lease.initialize() for lease in tuple(self._leases.values()))
                )
            except BaseException:
                await self.close()
                raise

    def _close_callback(self, generation: int):
        def closed(info: object) -> None:
            del info
            if generation != self._resource_generation or self._closed:
                return
            self._resource_generation += 1
            self._failed = True
            self._quiescing = True
            for lease in tuple(self._leases.values()):
                lease.fail_closed(generation)

        return closed

    async def quiesce(self) -> None:
        self._quiescing = True
        async with asyncio.timeout(self.options.close_timeout):
            await asyncio.gather(
                *(lease._quiesce() for lease in tuple(self._leases.values()))
            )

    async def close(self) -> None:
        if self._closed:
            return
        self._quiescing = True
        leases = tuple(self._leases.values())
        try:
            async with asyncio.timeout(self.options.close_timeout):
                await asyncio.gather(
                    *(lease.release() for lease in leases), return_exceptions=True
                )
                resources = tuple(
                    resource
                    for resource in (
                        self._metadata,
                        self._tracker,
                        self._producer,
                        *(
                            slot.producer
                            for slot in self._publisher_slots.values()
                            if slot.producer is not None
                        ),
                    )
                    if resource is not None
                )
                await asyncio.gather(
                    *(resource.close() for resource in resources),
                    return_exceptions=True,
                )
        except TimeoutError:
            pass
        except asyncio.CancelledError:
            raise
        except BaseException:
            pass
        self._metadata = None
        self._tracker = None
        self._producer = None
        self._publisher_slots.clear()
        self._started = False
        self._closed = True

    async def acquire(
        self,
        subscription: Subscription,
        partition: int,
        *,
        strategy: CheckpointStrategy | ExternalCheckpointStrategy,
        transfer: bool = False,
    ) -> PartitionLease:
        self._require_open()
        if self._started:
            raise LifecycleError("leases must be acquired before adapter.start()")
        if (
            strategy is CheckpointStrategy.BROKER_MANAGED
            and not self.options.broker_managed_single_instance
        ):
            raise CheckpointStrategyError(
                "broker-managed checkpoints require explicit single-instance mode; "
                "multi-replica groups require a shared external checkpoint store"
            )
        definition = self._definition(subscription.stream)
        self._partition(definition, partition)
        if not self.start_mode_capabilities.supports(subscription.start):
            raise ValidationError("start position is not supported")
        key = CheckpointKey(subscription.stream, subscription.group, partition)
        current = self._leases.get(key)
        if current is not None and not transfer:
            raise OwnershipError("partition is already owned")
        if current is not None:
            current._revocation_requested = True
            try:
                if current._in_flight is not None:
                    async with asyncio.timeout(self.options.operation_timeout):
                        await current._delivery_completed.wait()
                async with asyncio.timeout(self.options.close_timeout):
                    await current.release()
            except BaseException:
                current._revocation_requested = False
                raise
        scope = (subscription.stream, subscription.group)
        strategy_identity: object = (
            strategy
            if strategy is CheckpointStrategy.BROKER_MANAGED
            else (strategy.identity, strategy.store)
        )
        prior = self._strategies.get(scope)
        if prior is not None and prior != strategy_identity:
            raise CheckpointStrategyError("consumer group checkpoint strategy changed")
        if any(
            pending != strategy_identity
            for pending_key, pending in self._pending_strategies.items()
            if pending_key.stream == key.stream and pending_key.group == key.group
        ):
            raise CheckpointStrategyError(
                "consumer group checkpoint strategy initialization is in progress"
            )
        self._pending_strategies[key] = strategy_identity
        generation = self._generations.get(key, 0) + 1
        self._generations[key] = generation
        lease = RabbitMqPartitionLease(
            self,
            subscription,
            key,
            OwnershipToken(subscription.owner_id, generation),
            strategy,
        )
        self._leases[key] = lease
        return lease

    def _physical(self, stream: str, partition: int) -> str:
        definition = self._definition(stream)
        return stream if definition.partition_count == 1 else f"{stream}-{partition}"

    @staticmethod
    def _validate_request(definition: StreamDefinition, request: AppendRequest) -> None:
        validate_append_request_limits(definition, request)

    def _definition(self, stream: str) -> StreamDefinition:
        try:
            return self._definitions[stream]
        except KeyError as error:
            raise UnknownStreamError(stream) from error

    @staticmethod
    def _partition(definition: StreamDefinition, partition: int) -> None:
        if (
            isinstance(partition, bool)
            or not isinstance(partition, int)
            or not 0 <= partition < definition.partition_count
        ):
            raise InvalidPartitionError("partition is outside the stream")

    def _require_open(self) -> None:
        if self._closed:
            raise LifecycleError("RabbitMQ persistent log is closed")

    def _require_available(self) -> None:
        self._require_open()
        if not self._started or self._quiescing or self._failed:
            raise LifecycleError("RabbitMQ persistent log is not accepting work")

    def _commit_strategy(self, key: CheckpointKey) -> None:
        strategy = self._pending_strategies.pop(key, None)
        if strategy is not None:
            self._strategies[(key.stream, key.group)] = strategy

    def _discard_strategy_reservation(self, key: CheckpointKey) -> None:
        self._pending_strategies.pop(key, None)

    def _require_metadata(self) -> MetadataClient:
        if self._metadata is None:
            raise LifecycleError("metadata client is unavailable")
        return self._metadata

    async def _within(self, operation):
        async with asyncio.timeout(self.options.operation_timeout):
            return await operation


__all__ = ["RabbitMqPartitionLease", "RabbitMqPersistentLog", "TopologyPreflight"]

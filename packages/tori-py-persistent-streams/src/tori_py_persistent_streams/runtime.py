"""Application-owned persistent stream lifecycle and partition runtime."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid4

from tori_py import (
    DiscoveryService,
    ModulesContainer,
    PipelineOptions,
    ProviderRef,
    ShutdownContext,
    WorkScopeFactory,
)
from tori_py_persistent_streams_core import (
    AppendRequest,
    PartitionLease,
    PersistentStreamAdapter,
    PublishReceipt,
    StoredRecord,
    Subscription,
)

from tori_py_persistent_streams.compiler import (
    compile_discovered_stream_handlers,
    validate_publisher_protocol,
)
from tori_py_persistent_streams.contracts import (
    PartitionKeyResolver,
    PublishingIdSource,
    StreamAdapterFactory,
    StreamCodec,
)
from tori_py_persistent_streams.errors import (
    StreamPublicationSaturatedError,
    StreamRuntimeError,
)
from tori_py_persistent_streams.invocation import StreamPipelineExecutor
from tori_py_persistent_streams.options import (
    PersistentStreamsOptions,
    PublisherRegistration,
    StreamBinding,
)
from tori_py_persistent_streams.plans import (
    StreamHandlerPlan,
    StreamHandlerRegistry,
    StreamPipelinePlan,
)


class StreamRuntimeState(StrEnum):
    CREATED = "created"
    PREPARED = "prepared"
    RUNNING = "running"
    DEGRADED = "degraded"
    QUIESCING = "quiescing"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class PartitionStatus:
    stream: str
    consumer_group: str
    partition: int
    state: str
    offset: int | None = None
    diagnostic_code: str | None = None


class StreamRuntime:
    """Own adapter resources, publishers, leases, tasks, and readiness."""

    def __init__(
        self,
        options: PersistentStreamsOptions,
        adapter_factory: object,
        discovery: DiscoveryService,
        modules: ModulesContainer,
        work_scopes: WorkScopeFactory,
        declared_publishers: tuple[PublisherRegistration, ...] | None = None,
    ) -> None:
        if not isinstance(options, PersistentStreamsOptions):
            raise StreamRuntimeError(
                "options factory did not return PersistentStreamsOptions"
            )
        if not isinstance(adapter_factory, StreamAdapterFactory):
            raise StreamRuntimeError(
                "configured adapter provider does not implement StreamAdapterFactory"
            )
        self.options = options
        publisher_inventory = (
            options.publishers if declared_publishers is None else declared_publishers
        )
        if options.publishers and options.publishers != publisher_inventory:
            raise StreamRuntimeError(
                "options publishers differ from the root publisher inventory"
            )
        self._adapter_factory = adapter_factory
        self._discovery = discovery
        self._modules = modules
        self._work_scopes = work_scopes
        self._bindings = {binding.alias: binding for binding in options.bindings}
        self._registry: StreamHandlerRegistry | None = None
        self._log: PersistentStreamAdapter | None = None
        self._leases: list[tuple[StreamHandlerPlan, StreamBinding, PartitionLease]] = []
        self._tasks: set[asyncio.Task[None]] = set()
        self._publications: set[asyncio.Task[object]] = set()
        self._semaphore = asyncio.Semaphore(options.runtime.max_concurrency)
        self._executor = StreamPipelineExecutor()
        self._statuses: dict[tuple[str, str, int], PartitionStatus] = {}
        self._state = StreamRuntimeState.CREATED
        self._accepting = False
        self._lock = asyncio.Lock()
        self._admission_lock = asyncio.Lock()

    @property
    def state(self) -> StreamRuntimeState:
        return self._state

    @property
    def ready(self) -> bool:
        return self._state is StreamRuntimeState.RUNNING and not any(
            status.state == "blocked" for status in self._statuses.values()
        )

    @property
    def registry(self) -> StreamHandlerRegistry | None:
        return self._registry

    @property
    def statuses(self) -> tuple[PartitionStatus, ...]:
        return tuple(self._statuses[key] for key in sorted(self._statuses))

    async def on_module_init(self) -> None:
        async with self._lock:
            if self._state is not StreamRuntimeState.CREATED:
                return
            registry = compile_discovered_stream_handlers(
                self._discovery,
                self._modules,
                known_streams=self._bindings,
            )
            for plan in registry.handlers:
                binding = self._bindings[plan.metadata.stream]
                if plan.payload_type is not binding.payload_type:
                    raise StreamRuntimeError(
                        f"handler {plan.handler_id} payload does not match binding"
                    )
            for registration in self.options.publishers:
                if registration.protocol is not None:
                    validate_publisher_protocol(
                        registration.protocol,
                        self._bindings[registration.stream].payload_type,
                    )
            self._executor.global_pipeline = _qualify_global_pipeline(
                self.options.runtime.global_pipeline,
                self._work_scopes,
                self._modules,
            )
            resolved_bindings = tuple(
                self._resolve_binding_components(binding)
                for binding in self.options.bindings
            )
            self._bindings = {binding.alias: binding for binding in resolved_bindings}
            created = self._adapter_factory.create(resolved_bindings)
            if inspect.isawaitable(created):
                created = await created
            if not isinstance(created, PersistentStreamAdapter):
                raise StreamRuntimeError(
                    "adapter factory did not create PersistentStreamAdapter"
                )
            self._log = created
            try:
                for binding in resolved_bindings:
                    await created.declare_stream(binding.definition)
                for plan in registry.handlers:
                    binding = self._bindings[plan.metadata.stream]
                    for partition in range(binding.definition.partition_count):
                        lease = await created.acquire(
                            Subscription(
                                binding.definition.name,
                                plan.metadata.consumer_group,
                                self.options.runtime.owner_id,
                                binding.start,
                            ),
                            partition,
                            strategy=binding.checkpoint_strategy,
                        )
                        self._leases.append((plan, binding, lease))
                        key = (
                            plan.metadata.stream,
                            plan.metadata.consumer_group,
                            partition,
                        )
                        self._statuses[key] = PartitionStatus(*key, "prepared")
            except BaseException:
                await self._close_resources(created)
                raise
            self._registry = registry
            self._state = StreamRuntimeState.PREPARED

    async def on_application_bootstrap(self) -> None:
        if self._state is StreamRuntimeState.CREATED:
            await self.on_module_init()
        if self._state is not StreamRuntimeState.PREPARED:
            raise StreamRuntimeError("stream runtime is not prepared")
        log = self._log
        if log is None:
            raise StreamRuntimeError("stream adapter is unavailable")
        started: list[asyncio.Future[None]] = []
        try:
            await log.start()
            async with self._admission_lock:
                self._accepting = True
            loop = asyncio.get_running_loop()
            for plan, binding, lease in self._leases:
                signal = loop.create_future()
                started.append(signal)
                task = asyncio.create_task(self._consume(plan, binding, lease, signal))
                self._tasks.add(task)
                task.add_done_callback(self._task_done)
            await asyncio.gather(*started)
        except BaseException:
            async with self._admission_lock:
                self._accepting = False
            await self.close()
            raise
        if self._state is StreamRuntimeState.PREPARED:
            self._state = StreamRuntimeState.RUNNING

    async def publish(
        self,
        stream: str,
        payload: object,
        *,
        record_id: UUID | None = None,
        headers: Mapping[str, bytes] | None = None,
    ) -> PublishReceipt:
        current = asyncio.current_task()
        async with self._admission_lock:
            if not self._accepting:
                raise StreamRuntimeError("stream publication admission is closed")
            if current is not None:
                if (
                    len(self._publications)
                    >= self.options.runtime.max_pending_publications
                ):
                    raise StreamPublicationSaturatedError(
                        "stream publication admission is saturated"
                    )
                self._publications.add(current)
        try:
            try:
                binding = self._bindings[stream]
            except KeyError as error:
                raise StreamRuntimeError("unknown configured stream alias") from error
            if not isinstance(payload, binding.payload_type):
                raise TypeError(
                    "payload does not satisfy the configured stream contract"
                )
            codec = cast(StreamCodec, binding.codec)
            encoded = codec.encode(payload)
            if not isinstance(encoded, bytes):
                raise StreamRuntimeError("stream codec encode must return bytes")
            resolver = cast(PartitionKeyResolver, binding.partition_key_resolver)
            partition_key = resolver.resolve(payload)
            if not isinstance(partition_key, bytes) or not partition_key:
                raise StreamRuntimeError(
                    "partition resolver must return non-empty bytes"
                )
            selected_id = uuid4() if record_id is None else record_id
            if not isinstance(selected_id, UUID):
                raise TypeError("record_id must be a UUID or None")
            publishing_id = (
                None
                if binding.publishing_id_source is None
                else cast(PublishingIdSource, binding.publishing_id_source).next_id(
                    selected_id, partition_key
                )
            )
            log = self._log
            if log is None:
                raise StreamRuntimeError("stream adapter is unavailable")
            return await log.append(
                binding.definition.name,
                AppendRequest(
                    selected_id,
                    partition_key,
                    encoded,
                    {} if headers is None else headers,
                    binding.producer_name,
                    publishing_id,
                ),
            )
        finally:
            if current is not None:
                self._publications.discard(current)

    async def on_application_quiesce(self, context: ShutdownContext) -> None:
        async with self._admission_lock:
            self._accepting = False
            if self._state in {StreamRuntimeState.CLOSED, StreamRuntimeState.CREATED}:
                return
            self._state = StreamRuntimeState.QUIESCING
        log = self._log
        primary: BaseException | None = None
        if log is not None:
            try:
                remaining = context.remaining()
                if remaining is None:
                    await log.quiesce()
                else:
                    async with asyncio.timeout(remaining):
                        await log.quiesce()
            except BaseException as error:
                primary = error
        try:
            await self._drain(context.remaining)
        except BaseException:
            if primary is None:
                raise
        if primary is not None:
            raise primary

    async def on_application_shutdown(self) -> None:
        await self.close()

    async def on_module_destroy(self) -> None:
        await self.close()

    async def close(self) -> None:
        async with self._lock:
            if self._state is StreamRuntimeState.CLOSED:
                return
            async with self._admission_lock:
                self._accepting = False
                publications = tuple(
                    task
                    for task in self._publications
                    if task is not asyncio.current_task()
                )
            tasks = tuple(self._tasks)
            for task in (*tasks, *publications):
                task.cancel()
            if tasks or publications:
                await asyncio.gather(*tasks, *publications, return_exceptions=True)
            log = self._log
            if log is not None:
                await self._close_resources(log)
            self._log = None
            self._state = StreamRuntimeState.CLOSED

    async def _consume(
        self,
        plan: StreamHandlerPlan,
        binding: StreamBinding,
        lease: PartitionLease,
        started: asyncio.Future[None],
    ) -> None:
        key = (plan.metadata.stream, plan.metadata.consumer_group, lease.key.partition)
        phase = "intake"
        record: StoredRecord | None = None
        try:
            self._statuses[key] = PartitionStatus(*key, "running")
            started.set_result(None)
            record = await lease.next_record()
            if lease.stopped:
                self._mark_partition_stopped(key, record)
                return
            while self._accepting and not lease.stopped:
                if record is None:
                    await asyncio.sleep(self.options.runtime.poll_interval)
                    if not self._accepting:
                        break
                    phase = "intake"
                    record = await lease.next_record()
                    continue
                phase = "processing"
                async with self._semaphore:
                    await self._executor.invoke(
                        self._work_scopes, plan, binding, record
                    )
                phase = "checkpoint"
                await lease.checkpoint(record)
                self._statuses[key] = PartitionStatus(
                    *key, "running", offset=record.offset
                )
                if not self._accepting:
                    break
                phase = "intake"
                record = await lease.next_record()
            if self._accepting and lease.stopped:
                self._mark_partition_stopped(key, record)
        except asyncio.CancelledError:
            if phase == "checkpoint":
                await self._mark_checkpoint_unknown(key, lease, record)
            if not started.done():
                started.cancel()
            raise
        except Exception as error:
            if not started.done():
                started.set_exception(error)
            try:
                await lease.stop()
            except BaseException:
                pass
            self._statuses[key] = PartitionStatus(
                *key,
                "blocked",
                offset=_record_offset(record),
                diagnostic_code=getattr(
                    error,
                    "diagnostic_code",
                    "tori_py_persistent_streams.partition_failed",
                ),
            )
            if self._state is not StreamRuntimeState.QUIESCING:
                self._state = StreamRuntimeState.DEGRADED
        finally:
            await lease.release()

    def _mark_partition_stopped(
        self,
        key: tuple[str, str, int],
        record: StoredRecord | None,
    ) -> None:
        self._statuses[key] = PartitionStatus(
            *key,
            "blocked",
            offset=_record_offset(record),
            diagnostic_code="tori_py_persistent_streams.partition_stopped",
        )
        if self._state is not StreamRuntimeState.QUIESCING:
            self._state = StreamRuntimeState.DEGRADED

    async def _mark_checkpoint_unknown(
        self,
        key: tuple[str, str, int],
        lease: PartitionLease,
        record: StoredRecord | None,
    ) -> None:
        self._statuses[key] = PartitionStatus(
            *key,
            "blocked",
            offset=_record_offset(record),
            diagnostic_code="tori_py_persistent_streams.checkpoint_outcome_unknown",
        )
        if self._state is not StreamRuntimeState.QUIESCING:
            self._state = StreamRuntimeState.DEGRADED
        try:
            await lease.stop()
        except BaseException:
            pass

    def _resolve_binding_components(self, binding: StreamBinding) -> StreamBinding:
        codec = self._resolve_component(binding.codec, StreamCodec, "codec")
        resolver = self._resolve_component(
            binding.partition_key_resolver,
            PartitionKeyResolver,
            "partition key resolver",
        )
        source = binding.publishing_id_source
        if source is not None:
            source = self._resolve_component(
                source, PublishingIdSource, "publishing ID source"
            )
        return replace(
            binding,
            codec=cast(StreamCodec, codec),
            partition_key_resolver=cast(PartitionKeyResolver, resolver),
            publishing_id_source=cast(PublishingIdSource | None, source),
        )

    def _resolve_component(
        self,
        value: object,
        contract: type[object],
        label: str,
    ) -> object:
        if isinstance(value, (str, type)):
            view = self._modules.provider(self._work_scopes.module_id, value)
            if view is None or not view.instance_created:
                raise StreamRuntimeError(
                    f"configured stream {label} provider is not available"
                )
            value = view.instance
        if not isinstance(value, contract):
            raise StreamRuntimeError(
                f"configured stream {label} does not implement its contract"
            )
        return value

    async def _drain(self, remaining: Callable[[], float | None]) -> None:
        tasks = tuple(
            task
            for task in self._tasks | self._publications
            if task is not asyncio.current_task() and not task.done()
        )
        if not tasks:
            return
        budget = remaining()
        graceful_timeout = None if budget is None else budget * 0.8
        _, pending = await asyncio.wait(tasks, timeout=graceful_timeout)
        for task in pending:
            task.cancel()
        if pending:
            _, lingering = await asyncio.wait(pending, timeout=remaining())
            if lingering:
                raise StreamRuntimeError(
                    f"{len(lingering)} stream task(s) exceeded shutdown deadline"
                )

    async def _close_resources(self, log: PersistentStreamAdapter) -> None:
        for _, _, lease in reversed(self._leases):
            try:
                await lease.release()
            except BaseException:
                pass
        self._leases.clear()
        await log.close()

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()


def _record_offset(value: object) -> int | None:
    return value.offset if isinstance(value, StoredRecord) else None


def _qualify_global_pipeline(
    options: PipelineOptions,
    work_scopes: WorkScopeFactory,
    modules: ModulesContainer,
) -> StreamPipelinePlan:
    values = {
        kind: tuple(getattr(options, kind))
        for kind in ("guards", "pipes", "interceptors", "filters")
    }
    refs: list[tuple[str, ProviderRef]] = []
    for kind, bindings in values.items():
        for binding in bindings:
            if not isinstance(binding, (str, type)):
                continue
            view = modules.provider(work_scopes.module_id, binding)
            if view is None:
                raise StreamRuntimeError(
                    f"global stream pipeline provider {binding!r} is not visible"
                )
            refs.append((kind, view.ref))
    return StreamPipelinePlan(
        values["guards"],
        values["pipes"],
        values["interceptors"],
        values["filters"],
        tuple(refs),
    )


__all__ = ["PartitionStatus", "StreamRuntime", "StreamRuntimeState"]

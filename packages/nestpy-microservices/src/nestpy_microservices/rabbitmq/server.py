"""Inbound RabbitMQ server transport with explicit private settlement state."""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, Literal
from uuid import UUID

from nestpy_microservices.errors import (
    DuplicateSettlementError,
    RabbitMqConnectionError,
    RabbitMqError,
    TransportCapacityError,
    TransportError,
    TransportIndeterminateError,
    TransportRejectedError,
    TransportStateError,
    TransportUnroutableError,
    WireDecodingError,
)
from nestpy_microservices.identities import ReplyRoute, ServiceIdentity, utc_now
from nestpy_microservices.invocation import (
    InvocationCompletion,
    SettlementRecommendation,
)
from nestpy_microservices.rabbitmq.connection import (
    RabbitMqChannelRole,
    RabbitMqConnectionManager,
)
from nestpy_microservices.rabbitmq.publisher import RabbitMqPublisher
from nestpy_microservices.rabbitmq.topology import (
    RabbitMqTopology,
    compile_event_topology,
    compile_rpc_topology,
    merge_topologies,
    retry_exchange_name,
)
from nestpy_microservices.transport import (
    DeliveryDispatcher,
    EncodedDelivery,
    EventSubscription,
    Publication,
    PublicationReceipt,
    ServerTransport,
    TransportStatus,
    TransportStatusEvent,
)


@dataclass(frozen=True, slots=True)
class RabbitMqDeliveryMetadata:
    """Read-only broker metadata intentionally excluding settlement methods."""

    exchange: str
    routing_key: str
    consumer_tag: str | None
    delivery_tag: int | None
    redelivered: bool


@dataclass(frozen=True, slots=True)
class _ConsumerSpec:
    subscription: EventSubscription | None
    retry_exchange: str | None
    exclusive: bool


@dataclass(frozen=True, slots=True)
class _SettlementState:
    message: Any
    retry_exchange: str | None
    generation: int


class RabbitMqServerTransport(ServerTransport):
    """One RabbitMQ service endpoint using manual ACK/NACK settlement."""

    def __init__(
        self,
        manager: RabbitMqConnectionManager,
        service: ServiceIdentity,
        *,
        prefetch: int = 1,
        retry_delay_ms: int | None = None,
        max_delivery_attempts: int | None = None,
    ) -> None:
        retry_delay_ms = (
            manager.options.retry_delay_ms if retry_delay_ms is None else retry_delay_ms
        )
        max_delivery_attempts = (
            manager.options.max_delivery_attempts
            if max_delivery_attempts is None
            else max_delivery_attempts
        )
        if not isinstance(prefetch, int) or prefetch <= 0:
            raise ValueError("prefetch must be positive")
        if (
            not isinstance(retry_delay_ms, int)
            or isinstance(retry_delay_ms, bool)
            or retry_delay_ms <= 0
        ):
            raise ValueError("retry_delay_ms must be positive")
        if (
            not isinstance(max_delivery_attempts, int)
            or isinstance(max_delivery_attempts, bool)
            or max_delivery_attempts <= 0
        ):
            raise ValueError("max_delivery_attempts must be positive")
        self.manager = manager
        self.service = service
        self.prefetch = prefetch
        self.retry_delay_ms = retry_delay_ms
        self.max_delivery_attempts = max_delivery_attempts
        self._status = TransportStatus.CREATED
        self._status_events: asyncio.Queue[TransportStatusEvent] = asyncio.Queue()
        self._topology: RabbitMqTopology | None = None
        self._consumer_specs: dict[str, _ConsumerSpec] = {}
        self._queues: dict[str, Any] = {}
        self._consumer_tags: dict[str, str] = {}
        self._deliveries: dict[int, _SettlementState] = {}
        self._callback_tasks: set[asyncio.Task[Any]] = set()
        self._dispatcher: DeliveryDispatcher | None = None
        self._admission_open = False
        self._recover_intake = False
        self._publisher = RabbitMqPublisher(manager)
        manager.register_recovery_listener(self)

    @property
    def status(self) -> TransportStatus:
        return self._status

    async def prepare(
        self,
        *,
        rpc_methods: Iterable[str] = (),
        subscriptions: Iterable[EventSubscription] = (),
    ) -> None:
        self._require(TransportStatus.CREATED)
        rpc_methods = tuple(rpc_methods)
        subscriptions = tuple(subscriptions)
        topologies: list[RabbitMqTopology] = []
        specs: dict[str, _ConsumerSpec] = {}
        if rpc_methods:
            rpc_topology = compile_rpc_topology(
                self.service,
                exchange=self.manager.options.rpc_exchange,
                retry_delay_ms=self.retry_delay_ms,
                delivery_limit=self.max_delivery_attempts,
            )
            topologies.append(rpc_topology)
            queue_name = rpc_topology.queues[0].name
            specs[queue_name] = _ConsumerSpec(
                None, retry_exchange_name(queue_name), False
            )
        for subscription in subscriptions:
            topology = compile_event_topology(
                subscription,
                retry_delay_ms=self.retry_delay_ms,
                delivery_limit=self.max_delivery_attempts,
            )
            topologies.append(topology)
            queue_name = topology.queues[0].name
            specs[queue_name] = _ConsumerSpec(
                subscription,
                retry_exchange=(
                    retry_exchange_name(queue_name)
                    if subscription.reliable is True
                    else None
                ),
                exclusive=(
                    subscription.mode == "broadcast" and subscription.reliable is True
                ),
            )
        if not topologies:
            raise ValueError("RabbitMQ server requires RPC methods or subscriptions")
        self._topology = merge_topologies(*topologies)
        self._consumer_specs = specs
        await self._declare_topology()
        self._set_status(TransportStatus.PREPARED)

    async def start(self, dispatcher: DeliveryDispatcher) -> None:
        self._require(TransportStatus.PREPARED)
        self._dispatcher = dispatcher
        self._admission_open = True
        try:
            await self._start_consumers()
        except BaseException as error:
            self._admission_open = False
            cleanup_errors = await self._cancel_consumers()
            for cleanup_error in cleanup_errors:
                error.add_note(
                    "consumer cleanup failure: "
                    f"{type(cleanup_error).__name__}: {cleanup_error}"
                )
            raise
        self._set_status(TransportStatus.RUNNING)

    async def settle(
        self, delivery: EncodedDelivery, outcome: SettlementRecommendation
    ) -> None:
        if not isinstance(outcome, SettlementRecommendation):
            raise ValueError("unsupported settlement recommendation")
        state = self._deliveries.pop(id(delivery), None)
        if state is None:
            raise DuplicateSettlementError("delivery was already settled")
        if outcome is SettlementRecommendation.UNSETTLED:
            await self.manager.fence_connection(
                TransportIndeterminateError(
                    "RabbitMQ delivery was intentionally left unsettled"
                ),
                generation=state.generation,
            )
            return
        if (
            outcome is SettlementRecommendation.RETRY
            and state.retry_exchange is not None
            and delivery.attempt < self.max_delivery_attempts
        ):
            try:
                await self._publisher.publish(
                    Publication(
                        message_id=delivery.message_id,
                        routing_key=delivery.routing_key,
                        body=delivery.body,
                        headers={
                            **delivery.headers,
                            "x-nestpy-retry-count": delivery.attempt,
                        },
                        mandatory=True,
                        correlation_id=delivery.correlation_id,
                        reply_to=delivery.reply_to,
                        native=(state.retry_exchange, delivery.routing_key),
                        expires_at=delivery.expires_at,
                    )
                )
            except TransportRejectedError, TransportUnroutableError:
                await self._settle_native(
                    state.message.reject(requeue=False),
                    "RabbitMQ terminal retry rejection",
                    state.generation,
                )
                return
            except asyncio.CancelledError as error:
                await self.manager.fence_connection(
                    error,
                    generation=state.generation,
                )
                error.add_note("RabbitMQ retry publication may be indeterminate")
                raise
            except Exception as error:
                uncertainty = (
                    error
                    if isinstance(error, TransportIndeterminateError)
                    else TransportIndeterminateError(
                        "RabbitMQ retry publication outcome is indeterminate"
                    )
                )
                await self.manager.fence_connection(
                    uncertainty,
                    generation=state.generation,
                )
                if uncertainty is error:
                    raise
                raise uncertainty from error
            await self._settle_native(
                state.message.ack(),
                "RabbitMQ retry handoff ACK",
                state.generation,
            )
            return
        operation = (
            state.message.ack()
            if outcome is SettlementRecommendation.ACK
            else state.message.reject(requeue=False)
        )
        await self._settle_native(
            operation,
            "RabbitMQ delivery settlement",
            state.generation,
        )

    async def publish_reply(self, publication: Publication) -> PublicationReceipt:
        self._require_open()
        return await self._publisher.publish(publication, persistent=False)

    async def stop_intake(self) -> None:
        if self._status in {TransportStatus.CREATED, TransportStatus.CLOSED}:
            return
        if self._status is not TransportStatus.QUIESCING:
            self._set_status(TransportStatus.QUIESCING)
        failures = await self._cancel_consumers()
        self._admission_open = False
        await _cross_scheduling_fence()
        drain_errors = await self._drain_callbacks()
        if failures or drain_errors:
            failure = RabbitMqConnectionError(
                "RabbitMQ server intake did not stop cleanly"
            )
            for error in (*failures, *drain_errors):
                failure.add_note(f"{type(error).__name__}: {error}")
            raise failure from (failures or drain_errors)[0]

    async def close(self) -> None:
        if self._status is TransportStatus.CLOSED:
            return
        primary: BaseException | None = None
        try:
            if self._status in {
                TransportStatus.PREPARED,
                TransportStatus.RUNNING,
                TransportStatus.QUIESCING,
            }:
                await self.stop_intake()
        except BaseException as error:
            primary = error
        self._admission_open = False
        await _cross_scheduling_fence()
        drain_errors = await self._drain_callbacks()
        self._deliveries.clear()
        self._queues.clear()
        self.manager.unregister_recovery_listener(self)
        self._set_status(TransportStatus.CLOSED)
        if primary is not None:
            for error in drain_errors:
                primary.add_note(f"callback drain failure: {error}")
            raise primary
        if drain_errors:
            failure = RabbitMqConnectionError(
                "RabbitMQ server callbacks did not drain cleanly"
            )
            for error in drain_errors:
                failure.add_note(f"{type(error).__name__}: {error}")
            raise failure from drain_errors[0]

    async def connection_lost(self, error: BaseException | None) -> None:
        del error
        if self._status is TransportStatus.CLOSED:
            return
        self._recover_intake = (
            self._recover_intake or self._status is TransportStatus.RUNNING
        )
        self._admission_open = False
        self._consumer_tags.clear()
        self._queues.clear()
        self._deliveries.clear()
        self._set_status(TransportStatus.QUIESCING)

    async def connection_recovered(self) -> None:
        if self._status is TransportStatus.CLOSED or self._topology is None:
            return
        await self._declare_topology()
        if self._recover_intake:
            self._admission_open = True
            try:
                await self._start_consumers()
            except BaseException as error:
                self._admission_open = False
                cleanup_errors = await self._cancel_consumers()
                for cleanup_error in cleanup_errors:
                    error.add_note(
                        "recovery consumer cleanup failure: "
                        f"{type(cleanup_error).__name__}: {cleanup_error}"
                    )
                raise
            self._set_status(TransportStatus.RUNNING)
            self._recover_intake = False
        else:
            self._set_status(TransportStatus.PREPARED)

    async def statuses(self) -> AsyncIterator[TransportStatusEvent]:
        while True:
            event = await self._status_events.get()
            yield event
            if event.status is TransportStatus.CLOSED:
                return

    def unwrap(self) -> object:
        return self.manager

    async def _declare_topology(self) -> None:
        topology = self._topology
        if topology is None:
            raise TransportStateError("RabbitMQ server topology is not compiled")
        declared = await self.manager.declare(
            topology,
            role=RabbitMqChannelRole.CONSUMER,
        )
        self._queues = {name: declared[name] for name in self._consumer_specs}

    async def _start_consumers(self) -> None:
        consumer_channel: Any = self.manager.channels.consumer
        consumer_count = len(self._consumer_specs)
        if consumer_count > self.prefetch:
            raise TransportCapacityError(
                "RabbitMQ consumer count exceeds the service prefetch bound"
            )
        await consumer_channel.set_qos(
            prefetch_count=self.prefetch // consumer_count,
            global_=False,
        )
        for queue_name, spec in self._consumer_specs.items():
            queue = self._queues[queue_name]
            tag = f"nestpy.{self.service.label}.{len(self._consumer_tags)}"
            callback = partial(
                self._handoff_message,
                subscription=spec.subscription,
                retry_exchange=spec.retry_exchange,
            )
            try:
                await queue.consume(
                    callback,
                    consumer_tag=tag,
                    no_ack=False,
                    exclusive=spec.exclusive,
                    robust=False,
                )
            except BaseException as error:
                try:
                    await queue.cancel(tag)
                except BaseException as cleanup_error:
                    error.add_note(
                        "failed consumer cancellation: "
                        f"{type(cleanup_error).__name__}: {cleanup_error}"
                    )
                raise
            self._consumer_tags[queue_name] = tag

    async def _cancel_consumers(self) -> list[BaseException]:
        failures: list[BaseException] = []
        consumers = tuple(self._consumer_tags.items())
        self._consumer_tags.clear()
        for queue_name, tag in consumers:
            try:
                await self._queues[queue_name].cancel(tag)
            except BaseException as error:
                failures.append(error)
        return failures

    async def _drain_callbacks(self) -> list[BaseException]:
        current = asyncio.current_task()
        tasks = tuple(task for task in self._callback_tasks if task is not current)
        if not tasks:
            return []
        _, pending = await asyncio.wait(
            tasks,
            timeout=self.manager.options.connection_timeout,
        )
        for task in pending:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [
            result
            for result in results
            if isinstance(result, BaseException)
            and not isinstance(result, asyncio.CancelledError)
        ]

    async def _settle_native(
        self,
        operation: Any,
        detail: str,
        generation: int,
    ) -> None:
        try:
            await operation
        except asyncio.CancelledError as error:
            await self.manager.fence_connection(error, generation=generation)
            error.add_note(f"{detail} may be indeterminate")
            raise
        except Exception as error:
            uncertainty = TransportIndeterminateError(f"{detail} is indeterminate")
            await self.manager.fence_connection(uncertainty, generation=generation)
            raise uncertainty from error

    async def _handoff_message(
        self,
        message: Any,
        *,
        subscription: EventSubscription | None,
        retry_exchange: str | None,
    ) -> None:
        generation = getattr(self.manager, "generation", 0)
        operation = (
            self._on_message(
                message,
                subscription=subscription,
                retry_exchange=retry_exchange,
            )
            if self._admission_open
            else self._requeue_unadmitted(message, generation)
        )
        task = asyncio.create_task(operation)
        self._callback_tasks.add(task)
        task.add_done_callback(self._callback_tasks.discard)
        await asyncio.shield(task)

    async def _requeue_unadmitted(self, message: Any, generation: int) -> None:
        await self._settle_native(
            message.nack(requeue=True),
            "RabbitMQ delivery rejected by closed admission",
            generation,
        )

    async def _on_message(
        self,
        message: Any,
        *,
        subscription: EventSubscription | None,
        retry_exchange: str | None,
    ) -> None:
        generation = getattr(self.manager, "generation", 0)
        try:
            delivery = _decode_message(
                message,
                kind="rpc" if subscription is None else "event",
                subscription=subscription,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            try:
                await message.reject(requeue=False)
            except asyncio.CancelledError as error:
                await self.manager.fence_connection(
                    error,
                    generation=generation,
                )
                error.add_note(
                    "malformed RabbitMQ delivery rejection may be indeterminate"
                )
                raise
            except Exception as error:
                uncertainty = TransportIndeterminateError(
                    "malformed RabbitMQ delivery rejection is indeterminate"
                )
                await self.manager.fence_connection(
                    uncertainty,
                    generation=generation,
                )
                raise uncertainty from error
            return
        self._deliveries[id(delivery)] = _SettlementState(
            message,
            retry_exchange,
            generation,
        )
        dispatcher = self._dispatcher
        if dispatcher is None:
            await self.settle(delivery, SettlementRecommendation.REJECT)
            return
        try:
            result = await dispatcher(delivery)
            outcome = (
                result.recommendation
                if isinstance(result, InvocationCompletion)
                else result
            )
            if not isinstance(outcome, SettlementRecommendation):
                outcome = SettlementRecommendation.REJECT
        except asyncio.CancelledError:
            state = self._deliveries.pop(id(delivery), None)
            if state is not None:
                await self._settle_native(
                    state.message.nack(requeue=True),
                    "RabbitMQ delivery cancelled during shutdown",
                    state.generation,
                )
            raise
        except TransportError, RabbitMqError:
            outcome = SettlementRecommendation.UNSETTLED
        except Exception:
            outcome = (
                SettlementRecommendation.RETRY
                if subscription is not None
                else SettlementRecommendation.REJECT
            )
        await self.settle(delivery, outcome)

    def _set_status(self, status: TransportStatus, detail: str = "") -> None:
        if self._status is status:
            return
        self._status = status
        self._status_events.put_nowait(
            TransportStatusEvent(status, datetime.now(UTC), detail)
        )

    def _require(self, expected: TransportStatus) -> None:
        if self._status is not expected:
            raise TransportStateError(
                f"expected {expected.value}, got {self._status.value}"
            )

    def _require_open(self) -> None:
        if self._status not in {
            TransportStatus.PREPARED,
            TransportStatus.RUNNING,
            TransportStatus.QUIESCING,
        }:
            raise TransportStateError("server transport is not available")


def _decode_message(
    message: Any,
    *,
    kind: Literal["rpc", "event", "reply"],
    subscription: EventSubscription | None = None,
) -> EncodedDelivery:
    broker_headers = message.headers if isinstance(message.headers, Mapping) else {}
    headers = {key: value for key, value in broker_headers.items() if key != "x-death"}
    received_at = utc_now()
    attempt = _delivery_attempt(broker_headers)
    redelivered = bool(message.redelivered) or attempt > 1
    if kind == "rpc":
        correlation_id = _required_uuid(message.correlation_id, "correlation_id")
        reply_to = _required_reply_route(message.reply_to)
    elif kind == "event":
        correlation_id = _optional_uuid(message.correlation_id, "correlation_id")
        reply_to = _absent_reply_route(message.reply_to, kind)
    else:
        correlation_id = _required_uuid(message.correlation_id, "correlation_id")
        reply_to = _absent_reply_route(message.reply_to, kind)
    return EncodedDelivery(
        message_id=_required_uuid(message.message_id, "message_id"),
        routing_key=message.routing_key,
        body=message.body,
        headers=headers,
        received_at=received_at,
        attempt=attempt,
        redelivered=redelivered,
        correlation_id=correlation_id,
        reply_to=reply_to,
        native=RabbitMqDeliveryMetadata(
            exchange=str(getattr(message, "exchange", "")),
            routing_key=message.routing_key,
            consumer_tag=getattr(message, "consumer_tag", None),
            delivery_tag=getattr(message, "delivery_tag", None),
            redelivered=redelivered,
        ),
        expires_at=_expires_at(getattr(message, "expiration", None), received_at),
        subscription=subscription,
    )


def _delivery_attempt(headers: Mapping[str, object]) -> int:
    counts: list[int] = []
    delivery_count = headers.get("x-delivery-count")
    if isinstance(delivery_count, int) and not isinstance(delivery_count, bool):
        counts.append(delivery_count)
    retry_count = headers.get("x-nestpy-retry-count")
    if isinstance(retry_count, int) and not isinstance(retry_count, bool):
        counts.append(retry_count)
    deaths = headers.get("x-death")
    if isinstance(deaths, (list, tuple)):
        for death in deaths:
            if isinstance(death, Mapping):
                count = death.get("count")
                if isinstance(count, int) and not isinstance(count, bool):
                    counts.append(count)
    return max(counts, default=0) + 1


def _required_uuid(value: object, field_name: str) -> UUID:
    parsed = _optional_uuid(value, field_name)
    if parsed is None:
        raise WireDecodingError(f"{field_name} is required")
    return parsed


def _optional_uuid(value: object, field_name: str) -> UUID | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise WireDecodingError(f"{field_name} must be a UUID string")
    try:
        return UUID(value)
    except ValueError as error:
        raise WireDecodingError(f"{field_name} must be a UUID string") from error


def _required_reply_route(value: object) -> ReplyRoute:
    if not isinstance(value, str):
        raise WireDecodingError("reply_to is required")
    try:
        return ReplyRoute(value)
    except ValueError as error:
        raise WireDecodingError("reply_to is invalid") from error


def _absent_reply_route(value: object, kind: Literal["event", "reply"]) -> None:
    if value is not None:
        if isinstance(value, str):
            try:
                ReplyRoute(value)
            except ValueError as error:
                raise WireDecodingError("reply_to is invalid") from error
        raise WireDecodingError(f"{kind} deliveries must not include reply_to")
    return None


def _expires_at(value: object, received_at: datetime) -> datetime | None:
    if value is None:
        return None
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        raise WireDecodingError("expiration is invalid")
    return received_at + timedelta(seconds=value)


async def _cross_scheduling_fence() -> None:
    loop = asyncio.get_running_loop()
    crossed = loop.create_future()
    loop.call_soon(crossed.set_result, None)
    await crossed


__all__ = ["RabbitMqDeliveryMetadata", "RabbitMqServerTransport"]

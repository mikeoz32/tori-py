"""Outbound RabbitMQ client transport for RPC, events, and validated replies."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from functools import partial
from typing import Any
from uuid import UUID

from nestpy_microservices.errors import (
    RabbitMqConnectionError,
    TransportCapacityError,
    TransportCorrelationError,
    TransportIndeterminateError,
    TransportStateError,
)
from nestpy_microservices.identities import (
    EventIdentity,
    ReplyRoute,
    RpcTarget,
    utc_now,
)
from nestpy_microservices.rabbitmq.connection import (
    RabbitMqChannelRole,
    RabbitMqConnectionManager,
    _put_coalescing_status,
)
from nestpy_microservices.rabbitmq.publisher import RabbitMqPublisher
from nestpy_microservices.rabbitmq.server import _decode_message
from nestpy_microservices.rabbitmq.topology import (
    compile_reply_topology,
    event_exchange_topology,
)
from nestpy_microservices.transport import (
    ClientTransport,
    EncodedDelivery,
    Publication,
    PublicationReceipt,
    ReplyProtocolFailure,
    TransportStatus,
    TransportStatusEvent,
)

type _ReplyItem = EncodedDelivery | ReplyProtocolFailure


class RabbitMqClientTransport(ClientTransport):
    """One bounded-reply RabbitMQ client endpoint."""

    def __init__(
        self,
        manager: RabbitMqConnectionManager,
        *,
        reply_to: ReplyRoute | None = None,
        max_pending_replies: int = 10_000,
    ) -> None:
        if not isinstance(max_pending_replies, int) or max_pending_replies <= 0:
            raise ValueError("max_pending_replies must be positive")
        self.manager = manager
        self._reply_to = reply_to or ReplyRoute.generate()
        self.max_pending_replies = max_pending_replies
        self._status = TransportStatus.CREATED
        self._status_events: asyncio.Queue[TransportStatusEvent] = asyncio.Queue(
            maxsize=8
        )
        self._reply_queue = self._new_reply_queue()
        self._reply_consumer: Any | None = None
        self._consumer_tag: str | None = None
        self._pending: set[UUID] = set()
        self._publishing: set[UUID] = set()
        self._reply_won_publications: set[UUID] = set()
        self._completed: deque[UUID] = deque(maxlen=max_pending_replies)
        self._settlements: dict[int, tuple[Any, int]] = {}
        self._callback_tasks: set[asyncio.Task[Any]] = set()
        self._admission_open = False
        self._recover_reply_route = False
        self._recover_event_transport = False
        self._ready = asyncio.Event()
        self._reply_stream_closed = asyncio.Event()
        self._reply_stream_closed.set()
        self._receive_replies = True
        self._lifecycle_lock = asyncio.Lock()
        self._publisher = RabbitMqPublisher(manager)
        manager.register_recovery_listener(self)

    @property
    def status(self) -> TransportStatus:
        return self._status

    @property
    def generation(self) -> int:
        return self.manager.generation

    @property
    def reply_to(self) -> ReplyRoute:
        return self._reply_to

    async def start(self, *, receive_replies: bool = True) -> None:
        if self._status is TransportStatus.QUIESCING:
            await self._ready.wait()
            self._require_running()
            return
        if self._status is not TransportStatus.CREATED:
            raise TransportStateError("client transport has already started")
        if not isinstance(receive_replies, bool):
            raise TypeError("receive_replies must be boolean")
        self._receive_replies = receive_replies
        self._admission_open = True
        try:
            if receive_replies:
                await self._start_reply_consumer()
        except BaseException:
            self._admission_open = False
            raise
        self._set_status(TransportStatus.RUNNING)
        self._ready.set()

    async def publish_rpc(
        self, target: RpcTarget, publication: Publication
    ) -> PublicationReceipt:
        self._require_running()
        if not self._receive_replies:
            raise TransportStateError("reply reception is disabled")
        if publication.routing_key != target.routing_key:
            raise ValueError("publication routing key does not match RPC target")
        correlation_id = publication.correlation_id
        if correlation_id is None or publication.reply_to != self.reply_to:
            raise TransportCorrelationError(
                "RPC publications require this client's reply route and "
                "a correlation ID"
            )
        self._reserve(correlation_id)
        self._publishing.add(correlation_id)
        try:
            return await self._publisher.publish(
                _with_publication(publication, mandatory=True),
                fence_on_cancel=lambda: (
                    correlation_id not in self._reply_won_publications
                ),
            )
        except BaseException:
            self._pending.discard(correlation_id)
            raise
        finally:
            self._publishing.discard(correlation_id)
            self._reply_won_publications.discard(correlation_id)

    async def publish_event(
        self, identity: EventIdentity, publication: Publication
    ) -> PublicationReceipt:
        self._require_running()
        if publication.routing_key != identity.routing_key:
            raise ValueError("publication routing key does not match event identity")
        await self.manager.declare(
            event_exchange_topology(identity.exchange_name),
            role=RabbitMqChannelRole.PUBLISHER,
        )
        return await self._publisher.publish(
            _with_publication(
                publication,
                native=(identity.exchange_name, identity.routing_key),
            )
        )

    async def replies(self) -> AsyncIterator[_ReplyItem]:
        self._require_running()
        if not self._receive_replies:
            raise TransportStateError("reply reception is disabled")
        reply_queue = self._reply_queue
        self._reply_stream_closed.clear()
        try:
            while True:
                reply = await reply_queue.get()
                if reply is None:
                    return
                correlation_id = reply.correlation_id
                if (
                    correlation_id is None
                    or correlation_id in self._completed
                    or correlation_id not in self._pending
                ):
                    await self._ack_reply(reply)
                    continue
                self._pending.remove(correlation_id)
                self._completed.append(correlation_id)
                try:
                    yield reply
                finally:
                    await self._ack_reply(reply)
        finally:
            self._reply_stream_closed.set()

    async def close(self) -> None:
        async with self._lifecycle_lock:
            await self._close()

    async def _close(self) -> None:
        if self._status is TransportStatus.CLOSED:
            return
        primary: BaseException | None = None
        try:
            await self._cancel_reply_consumer()
        except BaseException as error:
            primary = error
        self._admission_open = False
        await _cross_scheduling_fence()
        drain_errors = await self._drain_callbacks_and_replies()
        self._clear_reply_state()
        self.manager.unregister_recovery_listener(self)
        self._set_status(TransportStatus.CLOSED)
        self._ready.set()
        _signal_queue_closed(self._reply_queue)
        if primary is not None:
            for error in drain_errors:
                primary.add_note(f"reply callback cleanup failure: {error}")
            raise primary
        if drain_errors:
            failure = RabbitMqConnectionError(
                "RabbitMQ reply callbacks did not drain cleanly"
            )
            for error in drain_errors:
                failure.add_note(f"{type(error).__name__}: {error}")
            raise failure from drain_errors[0]

    def cancel_pending(self, correlation_id: UUID) -> None:
        self._pending.discard(correlation_id)

    def cancel_publication_after_reply(self, correlation_id: UUID) -> None:
        if correlation_id in self._publishing:
            self._reply_won_publications.add(correlation_id)

    async def connection_lost(self, error: BaseException | None) -> None:
        async with self._lifecycle_lock:
            await self._connection_lost(error)

    async def _connection_lost(self, error: BaseException | None) -> None:
        del error
        if self._status is TransportStatus.CLOSED:
            return
        if not self._receive_replies:
            if self._status is TransportStatus.RUNNING:
                self._admission_open = False
                self._recover_event_transport = True
                self._ready.clear()
                self._set_status(TransportStatus.QUIESCING)
            return
        self._recover_reply_route = (
            self._recover_reply_route or self._status is TransportStatus.RUNNING
        )
        if not self._recover_reply_route:
            return
        self._admission_open = False
        await _cross_scheduling_fence()
        old_reply_queue = self._reply_queue
        drain_errors = await self._drain_callbacks_and_replies(
            old_reply_queue, settle=False
        )
        self._clear_reply_state()
        self._reply_queue = self._new_reply_queue()
        _signal_queue_closed(old_reply_queue)
        self._ready.clear()
        self._set_status(TransportStatus.QUIESCING)
        if drain_errors:
            failure = RabbitMqConnectionError(
                "RabbitMQ reply callbacks did not drain before recovery"
            )
            for drain_error in drain_errors:
                failure.add_note(f"{type(drain_error).__name__}: {drain_error}")
            raise failure from drain_errors[0]

    async def connection_recovered(self) -> None:
        async with self._lifecycle_lock:
            await self._connection_recovered()

    async def _connection_recovered(self) -> None:
        if self._status is TransportStatus.CLOSED:
            return
        if not self._receive_replies:
            if not self._recover_event_transport:
                return
            self._admission_open = True
            self._recover_event_transport = False
            self._set_status(TransportStatus.RUNNING)
            self._ready.set()
            return
        if not self._recover_reply_route:
            return
        await asyncio.wait_for(
            self._reply_stream_closed.wait(),
            timeout=self.manager.options.connection_timeout,
        )
        self._reply_to = ReplyRoute.generate()
        self._admission_open = True
        try:
            await self._start_reply_consumer()
        except BaseException:
            self._admission_open = False
            raise
        self._set_status(TransportStatus.RUNNING)
        self._recover_reply_route = False
        self._ready.set()

    async def statuses(self) -> AsyncIterator[TransportStatusEvent]:
        while True:
            event = await self._status_events.get()
            yield event
            if event.status is TransportStatus.CLOSED:
                return

    def unwrap(self) -> object:
        return self.manager

    async def _start_reply_consumer(self) -> None:
        queues = await self.manager.declare(
            compile_reply_topology(
                self.reply_to.value,
                exchange=self.manager.options.rpc_exchange,
                expires_ms=self.manager.options.reply_queue_expires_ms,
            ),
            role=RabbitMqChannelRole.REPLY,
        )
        queue = queues[self.reply_to.value]
        route_name = self.reply_to.value.removeprefix("reply.")
        consumer_tag = f"nestpy.reply.{route_name}"
        reply_channel: Any = self.manager.channels.reply
        await reply_channel.set_qos(
            prefetch_count=self.max_pending_replies,
            global_=False,
        )
        self._reply_consumer = queue
        self._consumer_tag = consumer_tag
        try:
            await queue.consume(
                partial(
                    self._handoff_reply,
                    reply_queue=self._reply_queue,
                    generation=getattr(self.manager, "generation", 0),
                ),
                consumer_tag=consumer_tag,
                no_ack=False,
                robust=False,
            )
        except BaseException as error:
            try:
                await self._cancel_reply_consumer()
            except BaseException as cleanup_error:
                error.add_note(
                    "reply consumer cancellation failure: "
                    f"{type(cleanup_error).__name__}: {cleanup_error}"
                )
            raise

    async def _cancel_reply_consumer(self) -> None:
        queue = self._reply_consumer
        tag = self._consumer_tag
        if queue is not None and tag is not None:
            task = asyncio.create_task(queue.cancel(tag))
            try:
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=self.manager.options.connection_timeout,
                )
            except asyncio.CancelledError:
                task.cancel()
                task.add_done_callback(_observe_task)
                raise
            except TimeoutError as error:
                task.cancel()
                task.add_done_callback(_observe_task)
                raise RabbitMqConnectionError(
                    "RabbitMQ reply consumer cancellation timed out"
                ) from error
            except BaseException as error:
                raise RabbitMqConnectionError(
                    "RabbitMQ reply consumer cancellation failed"
                ) from error
            self._reply_consumer = None
            self._consumer_tag = None

    async def _handoff_reply(
        self,
        message: Any,
        *,
        reply_queue: asyncio.Queue[_ReplyItem | None],
        generation: int,
    ) -> None:
        task = asyncio.create_task(
            self._on_reply(
                message,
                reply_queue=reply_queue,
                generation=generation,
            )
        )
        self._callback_tasks.add(task)
        task.add_done_callback(self._callback_tasks.discard)
        await asyncio.shield(task)

    async def _on_reply(
        self,
        message: Any,
        *,
        reply_queue: asyncio.Queue[_ReplyItem | None] | None = None,
        generation: int | None = None,
    ) -> None:
        reply_queue = self._reply_queue if reply_queue is None else reply_queue
        generation = (
            getattr(self.manager, "generation", 0) if generation is None else generation
        )
        if not self._admission_open or reply_queue is not self._reply_queue:
            if reply_queue is self._reply_queue:
                await self._ack_message(
                    message,
                    generation,
                    "RabbitMQ reply discarded after admission closed",
                )
            return
        queued: _ReplyItem | None = None
        try:
            try:
                delivery = _decode_message(message, kind="reply")
            except asyncio.CancelledError:
                raise
            except Exception:
                correlation_id = _valid_correlation_id(message.correlation_id)
                if correlation_id is not None and correlation_id in self._pending:
                    failure = ReplyProtocolFailure(
                        correlation_id,
                        "malformed RPC reply metadata",
                    )
                    self._settlements[id(failure)] = (message, generation)
                    queued = failure
                    await reply_queue.put(failure)
                else:
                    await self._ack_message(
                        message,
                        generation,
                        "malformed RabbitMQ reply ACK",
                    )
                return
            self._settlements[id(delivery)] = (
                message,
                generation,
            )
            queued = delivery
            await reply_queue.put(delivery)
        except asyncio.CancelledError:
            if queued is not None:
                self._settlements.pop(id(queued), None)
            await self._ack_message(
                message,
                generation,
                "RabbitMQ reply cancelled during shutdown",
            )
            raise

    async def _ack_reply(self, delivery: _ReplyItem) -> None:
        state = self._settlements.pop(id(delivery), None)
        if state is None:
            return
        message, generation = state
        await self._ack_message(message, generation, "RabbitMQ reply ACK")

    async def _ack_message(
        self,
        message: Any,
        generation: int,
        detail: str,
    ) -> None:
        if generation != getattr(self.manager, "generation", 0):
            return
        try:
            await message.ack()
        except asyncio.CancelledError as error:
            try:
                await self.manager.fence_connection(error, generation=generation)
            except BaseException as fence_error:
                error.add_note(
                    f"{detail} fencing failed: "
                    f"{type(fence_error).__name__}: {fence_error}"
                )
            error.add_note(f"{detail} may be indeterminate")
            raise
        except Exception as error:
            uncertainty = TransportIndeterminateError(f"{detail} is indeterminate")
            try:
                await self.manager.fence_connection(uncertainty, generation=generation)
            except BaseException as fence_error:
                uncertainty.add_note(
                    f"{detail} fencing failed: "
                    f"{type(fence_error).__name__}: {fence_error}"
                )
            raise uncertainty from error

    async def _drain_callbacks_and_replies(
        self,
        reply_queue: asyncio.Queue[_ReplyItem | None] | None = None,
        *,
        settle: bool = True,
    ) -> list[BaseException]:
        reply_queue = self._reply_queue if reply_queue is None else reply_queue
        failures = await self._drain_reply_queue(reply_queue, settle=settle)
        current = asyncio.current_task()
        tasks = tuple(task for task in self._callback_tasks if task is not current)
        if tasks:
            done, pending = await asyncio.wait(
                tasks,
                timeout=self.manager.options.connection_timeout,
            )
            for task in pending:
                task.cancel()
            if pending:
                terminated, lingering = await asyncio.wait(
                    pending,
                    timeout=self.manager.options.connection_timeout,
                )
            else:
                terminated, lingering = set(), set()
            results = await asyncio.gather(*(done | terminated), return_exceptions=True)
            failures.extend(
                result
                for result in results
                if isinstance(result, BaseException)
                and not isinstance(result, asyncio.CancelledError)
            )
            if lingering:
                failures.append(
                    TimeoutError("RabbitMQ reply callbacks remained after cancellation")
                )
        failures.extend(await self._drain_reply_queue(reply_queue, settle=settle))
        return failures

    async def _drain_reply_queue(
        self,
        reply_queue: asyncio.Queue[_ReplyItem | None],
        *,
        settle: bool,
    ) -> list[BaseException]:
        failures: list[BaseException] = []
        while not reply_queue.empty():
            delivery = reply_queue.get_nowait()
            if delivery is not None:
                if settle:
                    try:
                        await self._ack_reply(delivery)
                    except BaseException as error:
                        failures.append(error)
                else:
                    self._settlements.pop(id(delivery), None)
        return failures

    def _reserve(self, correlation_id: UUID) -> None:
        if correlation_id in self._pending or correlation_id in self._completed:
            raise TransportCorrelationError("RPC correlation was already used")
        if len(self._pending) >= self.max_pending_replies:
            raise TransportCapacityError("pending reply map is full")
        self._pending.add(correlation_id)

    def _clear_reply_state(self) -> None:
        self._pending.clear()
        self._completed.clear()
        self._settlements.clear()
        self._reply_consumer = None
        self._consumer_tag = None

    def _new_reply_queue(self) -> asyncio.Queue[_ReplyItem | None]:
        return asyncio.Queue(maxsize=self.max_pending_replies)

    def _set_status(self, status: TransportStatus) -> None:
        if self._status is status:
            return
        self._status = status
        _put_coalescing_status(
            self._status_events,
            TransportStatusEvent(
                status,
                utc_now(),
                generation=getattr(self.manager, "generation", 0),
            ),
            key=lambda event: event.status,
        )

    def _require_running(self) -> None:
        if self._status is not TransportStatus.RUNNING:
            raise TransportStateError("client transport is not running")


def _clear_queue(queue: asyncio.Queue[_ReplyItem | None]) -> None:
    while not queue.empty():
        queue.get_nowait()


def _observe_task(task: asyncio.Task[Any]) -> None:
    if not task.cancelled():
        task.exception()


def _signal_queue_closed(queue: asyncio.Queue[_ReplyItem | None]) -> None:
    _clear_queue(queue)
    queue.put_nowait(None)


async def _cross_scheduling_fence() -> None:
    loop = asyncio.get_running_loop()
    crossed = loop.create_future()
    loop.call_soon(crossed.set_result, None)
    await crossed


def _valid_correlation_id(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _with_publication(
    publication: Publication,
    *,
    mandatory: bool | None = None,
    native: object | None = None,
) -> Publication:
    return Publication(
        message_id=publication.message_id,
        routing_key=publication.routing_key,
        body=publication.body,
        headers=publication.headers,
        mandatory=publication.mandatory if mandatory is None else mandatory,
        correlation_id=publication.correlation_id,
        reply_to=publication.reply_to,
        native=native,
        expires_at=publication.expires_at,
    )


__all__ = ["RabbitMqClientTransport"]

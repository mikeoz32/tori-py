"""Bounded in-process transport implementation."""

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4

from cqrs_core.envelope import DeliveryReceipt, Envelope, ReplyEnvelope
from cqrs_core.errors import (
    CqrsValidationError,
    EnvelopeValidationError,
    InvalidLifecycleTransitionError,
    InvalidReplyCorrelationError,
    InvalidTransportReplyError,
    QueueCapacityError,
    RequestTimeoutError,
    TransportNotStartedError,
    TransportStoppedError,
)
from cqrs_core.messages import Message
from cqrs_core.protocols import TransportConsumer

logger = logging.getLogger(__name__)


class TransportState(StrEnum):
    """Lifecycle state of an in-memory transport."""

    NEW = "new"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


type TransportErrorHandler = Callable[
    [BaseException, Envelope[Message] | None],
    Awaitable[object] | object,
]


@dataclass(slots=True)
class _RequestItem:
    envelope: Envelope[Message]
    reply: asyncio.Future[ReplyEnvelope[object]]


@dataclass(slots=True)
class _PublishItem:
    envelope: Envelope[Message]


type _QueueItem = _RequestItem | _PublishItem


class InMemoryTransport:
    """A bounded FIFO transport with one worker and request/reply support."""

    _CANCELLATION_GRACE = 0.1

    def __init__(
        self,
        *,
        max_queue_size: int = 1024,
        default_timeout: float | None = None,
        error_handler: TransportErrorHandler | None = None,
        name: str = "cqrs-inmemory",
    ) -> None:
        if max_queue_size < 1:
            raise CqrsValidationError("max_queue_size must be at least 1")
        if default_timeout is not None and default_timeout < 0:
            raise CqrsValidationError("default_timeout cannot be negative")

        self._queue: asyncio.Queue[_QueueItem] = asyncio.Queue(maxsize=max_queue_size)
        self._capacity = asyncio.Semaphore(max_queue_size)
        self._default_timeout = default_timeout
        self._error_handler = error_handler
        self._name = name
        self._consumer: TransportConsumer | None = None
        self._worker: asyncio.Task[None] | None = None
        self._active_request: _RequestItem | None = None
        self._worker_ready = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._shutdown_complete = asyncio.Event()
        self._lifecycle_lock = asyncio.Lock()
        self._state = TransportState.NEW

    @property
    def state(self) -> TransportState:
        """Return the current transport lifecycle state."""

        return self._state

    async def start(self, consumer: TransportConsumer) -> None:
        """Start one worker for the supplied transport consumer."""

        async with self._lifecycle_lock:
            if self._state is not TransportState.NEW:
                raise InvalidLifecycleTransitionError(
                    operation="start transport",
                    state=self._state,
                )
            self._consumer = consumer
            self._state = TransportState.STARTING
            worker = asyncio.create_task(
                self._worker_loop(),
                name=f"{self._name}-worker",
            )
            self._worker = worker
            try:
                await self._worker_ready.wait()
            except BaseException:
                self._stop_event.set()
                worker.cancel()
                try:
                    await self._wait_for_worker(worker)
                finally:
                    self._drain_pending()
                    self._state = TransportState.STOPPED
                    self._shutdown_complete.set()
                raise
            if self._state is not TransportState.STARTING:
                raise TransportStoppedError("transport stopped during startup")
            self._state = TransportState.RUNNING

    async def request(
        self,
        envelope: Envelope[Message],
        *,
        timeout: float | None = None,
    ) -> ReplyEnvelope[object]:
        """Enqueue a request and await a correlated reply."""

        self._require_running()
        correlation_id = envelope.correlation_id
        if correlation_id is None:
            raise EnvelopeValidationError("request envelope requires correlation_id")

        future: asyncio.Future[ReplyEnvelope[object]] = (
            asyncio.get_running_loop().create_future()
        )
        future.add_done_callback(_consume_future_exception)
        effective_timeout = self._effective_timeout(timeout)
        deadline = self._deadline(timeout)
        await self._enqueue(
            _RequestItem(envelope=envelope, reply=future),
            deadline=deadline,
            timeout=effective_timeout,
        )

        try:
            wait_timeout = None
            if deadline is not None:
                wait_timeout = deadline - asyncio.get_running_loop().time()
                if wait_timeout <= 0:
                    raise TimeoutError
            done, _ = await asyncio.wait((future,), timeout=wait_timeout)
            if not done:
                raise TimeoutError
            return future.result()
        except TimeoutError as error:
            raise RequestTimeoutError(
                message_id=envelope.message_id,
                correlation_id=correlation_id,
                timeout=effective_timeout,
            ) from error

    async def publish(
        self,
        envelope: Envelope[Message],
        *,
        timeout: float | None = None,
    ) -> DeliveryReceipt:
        """Enqueue a one-way message and return after acceptance."""

        self._require_running()
        effective_timeout = self._effective_timeout(timeout)
        deadline = self._deadline(timeout)
        await self._enqueue(
            _PublishItem(envelope=envelope),
            deadline=deadline,
            timeout=effective_timeout,
        )
        return DeliveryReceipt(
            message_id=envelope.message_id,
            delivery_id=envelope.delivery.delivery_id,
            enqueued_at=envelope.delivery.enqueued_at,
        )

    async def shutdown(self, *, timeout: float | None = None) -> None:
        """Stop intake, drain to the deadline, and cancel remaining work."""

        async with self._lifecycle_lock:
            if self._state is TransportState.STOPPED:
                return
            if self._state is TransportState.STOPPING:
                wait_for_completion = True
            else:
                wait_for_completion = False
            if self._state is TransportState.NEW:
                self._stop_event.set()
                self._state = TransportState.STOPPED
                self._shutdown_complete.set()
                return
            if not wait_for_completion:
                self._state = TransportState.STOPPING
                self._stop_event.set()
                worker = self._worker

        if wait_for_completion:
            if timeout is None:
                await self._shutdown_complete.wait()
                return
            try:
                await asyncio.wait_for(self._shutdown_complete.wait(), timeout)
            except TimeoutError:
                self._force_shutdown()
                await self._shutdown_complete.wait()
            return

        deadline = self._deadline(timeout, use_default=False)
        try:
            if worker is not None:
                if deadline is None:
                    await self._queue.join()
                else:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise TimeoutError
                    await asyncio.wait_for(self._queue.join(), remaining)
        except TimeoutError:
            pass
        except asyncio.CancelledError:
            raise
        finally:
            active = self._active_request
            if active is not None:
                _set_future_error(
                    active.reply,
                    TransportStoppedError("transport stopped"),
                )
            if worker is not None and not worker.done():
                worker.cancel()
            try:
                await self._wait_for_worker(worker)
            finally:
                self._drain_pending()
                self._state = TransportState.STOPPED
                self._shutdown_complete.set()

    def _require_running(self) -> None:
        if self._state is TransportState.NEW:
            raise TransportNotStartedError("transport has not been started")
        if self._state is TransportState.STOPPED:
            raise TransportStoppedError("transport has been stopped")
        if self._state is not TransportState.RUNNING:
            raise InvalidLifecycleTransitionError(
                operation="submit transport work",
                state=self._state,
            )

    def _deadline(
        self,
        timeout: float | None,
        *,
        use_default: bool = True,
    ) -> float | None:
        effective_timeout = self._effective_timeout(timeout) if use_default else timeout
        if effective_timeout is None:
            return None
        return asyncio.get_running_loop().time() + effective_timeout

    def _effective_timeout(self, timeout: float | None) -> float | None:
        return self._default_timeout if timeout is None else timeout

    async def _enqueue(
        self,
        item: _QueueItem,
        *,
        deadline: float | None,
        timeout: float | None,
    ) -> None:
        acquire_task = asyncio.create_task(self._capacity.acquire())
        stop_task = asyncio.create_task(self._stop_event.wait())
        capacity_acquired = False
        capacity_accounted = False
        queued = False
        try:
            wait_timeout = None
            if deadline is not None:
                wait_timeout = deadline - asyncio.get_running_loop().time()
                if wait_timeout <= 0:
                    raise TimeoutError
            done, _ = await asyncio.wait(
                {acquire_task, stop_task},
                timeout=wait_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise TimeoutError
            if acquire_task in done:
                capacity_acquired = acquire_task.result()
                capacity_accounted = True
            if not capacity_acquired:
                self._raise_submission_error()
            async with self._lifecycle_lock:
                if self._state is not TransportState.RUNNING:
                    self._capacity.release()
                    capacity_acquired = False
                    self._raise_submission_error()
                try:
                    self._queue.put_nowait(item)
                except asyncio.QueueFull as error:
                    self._capacity.release()
                    capacity_acquired = False
                    raise QueueCapacityError(timeout=timeout) from error
                queued = True
                capacity_acquired = False
        except TimeoutError as error:
            raise QueueCapacityError(timeout=timeout) from error
        finally:
            if capacity_acquired:
                self._capacity.release()
            elif (
                not capacity_accounted
                and not queued
                and acquire_task.done()
                and not acquire_task.cancelled()
            ):
                try:
                    if acquire_task.result():
                        self._capacity.release()
                except asyncio.CancelledError, Exception:
                    pass
            for task in (acquire_task, stop_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(acquire_task, stop_task, return_exceptions=True)

    def _raise_submission_error(self) -> None:
        if self._state is TransportState.STOPPED:
            raise TransportStoppedError("transport has been stopped")
        raise InvalidLifecycleTransitionError(
            operation="submit transport work",
            state=self._state,
        )

    def _force_shutdown(self) -> None:
        active = self._active_request
        if active is not None:
            _set_future_error(
                active.reply,
                TransportStoppedError("transport stopped"),
            )
        worker = self._worker
        if worker is not None and not worker.done():
            worker.cancel()
        self._drain_pending()

    async def _worker_loop(self) -> None:
        self._worker_ready.set()
        current_item: _QueueItem | None = None
        try:
            while True:
                if self._state in {TransportState.STOPPING, TransportState.STOPPED}:
                    if self._queue.empty():
                        return
                current_item = None
                current_item = await self._queue.get()
                self._capacity.release()
                try:
                    if isinstance(current_item, _RequestItem):
                        self._active_request = current_item
                        await self._process_request(current_item)
                    else:
                        await self._process_publish(current_item)
                finally:
                    self._active_request = None
                    self._queue.task_done()
        except asyncio.CancelledError:
            active = self._active_request
            if active is not None:
                _set_future_error(
                    active.reply,
                    TransportStoppedError("request cancelled by shutdown"),
                )
            raise
        except Exception as error:
            logger.exception("In-memory transport worker failed")
            if isinstance(current_item, _RequestItem):
                correlation_id = current_item.envelope.correlation_id
                if correlation_id is None:
                    _set_future_error(current_item.reply, error)
                elif not current_item.reply.done():
                    current_item.reply.set_result(
                        ReplyEnvelope(
                            reply_id=uuid4(),
                            correlation_id=correlation_id,
                            error=error,
                        )
                    )
            envelope = current_item.envelope if current_item is not None else None
            await self._report_error(error, envelope)
            self._drain_pending(error=error)
            self._state = TransportState.STOPPED

    async def _process_request(self, item: _RequestItem) -> None:
        consumer = self._consumer
        if consumer is None:
            _set_future_error(
                item.reply,
                TransportStoppedError("transport has no consumer"),
            )
            return
        correlation_id = item.envelope.correlation_id
        if correlation_id is None:
            _set_future_error(
                item.reply,
                EnvelopeValidationError("request envelope requires correlation_id"),
            )
            return

        try:
            reply = await consumer(item.envelope)
            if reply is None:
                raise InvalidTransportReplyError(
                    "request consumer returned no reply envelope"
                )
            if reply.correlation_id != correlation_id:
                raise InvalidReplyCorrelationError(
                    expected=correlation_id,
                    actual=reply.correlation_id,
                )
        except asyncio.CancelledError as error:
            if _current_task_is_cancelling():
                _set_future_error(
                    item.reply,
                    TransportStoppedError("request cancelled by shutdown"),
                )
                raise
            await self._complete_request_error(item, error, correlation_id)
            return
        except Exception as error:
            await self._complete_request_error(item, error, correlation_id)
            return

        if not item.reply.done():
            item.reply.set_result(reply)

    async def _process_publish(self, item: _PublishItem) -> None:
        consumer = self._consumer
        if consumer is None:
            return
        try:
            await consumer(item.envelope)
        except asyncio.CancelledError as error:
            if _current_task_is_cancelling():
                raise
            await self._report_error(error, item.envelope)
        except Exception as error:
            await self._report_error(error, item.envelope)

    async def _complete_request_error(
        self,
        item: _RequestItem,
        error: BaseException,
        correlation_id: UUID,
    ) -> None:
        try:
            await self._report_error(error, item.envelope)
        except asyncio.CancelledError:
            _set_future_error(
                item.reply,
                TransportStoppedError("request cancelled by shutdown"),
            )
            raise
        if not item.reply.done():
            item.reply.set_result(
                ReplyEnvelope(
                    reply_id=uuid4(),
                    correlation_id=correlation_id,
                    error=error,
                )
            )

    async def _report_error(
        self,
        error: BaseException,
        envelope: Envelope[Message] | None,
    ) -> None:
        logger.error(
            "In-memory transport operation failed for %s",
            envelope.message_type if envelope is not None else "transport",
            exc_info=(type(error), error, error.__traceback__),
        )
        if self._error_handler is None:
            return
        try:
            result = self._error_handler(error, envelope)
            if inspect.isawaitable(result):
                await result
        except Exception as hook_error:
            logger.error(
                "In-memory transport error handler failed",
                exc_info=(type(hook_error), hook_error, hook_error.__traceback__),
            )
        except asyncio.CancelledError as hook_error:
            current_task = asyncio.current_task()
            if current_task is not None and current_task.cancelling():
                raise
            logger.error(
                "In-memory transport error handler was cancelled",
                exc_info=(type(hook_error), hook_error, hook_error.__traceback__),
            )

    async def _wait_for_worker(
        self,
        worker: asyncio.Task[None] | None,
    ) -> None:
        if worker is None:
            return
        if not worker.done():
            worker.cancel()
        if worker.done():
            self._observe_worker(worker)
            return
        try:
            await asyncio.wait_for(asyncio.shield(worker), self._CANCELLATION_GRACE)
        except TimeoutError:
            logger.error("In-memory transport worker did not stop before deadline")
            self._observe_worker(worker)
        except asyncio.CancelledError:
            if worker.cancelled():
                return
            self._observe_worker(worker)
            raise
        except Exception:
            logger.exception("In-memory transport worker exited with an error")

    def _observe_worker(self, worker: asyncio.Task[None]) -> None:
        if not worker.done():
            worker.add_done_callback(_observe_worker_completion)
            return
        _observe_worker_completion(worker)

    def _drain_pending(self, *, error: BaseException | None = None) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            self._capacity.release()
            if isinstance(item, _RequestItem):
                _set_future_error(
                    item.reply,
                    error or TransportStoppedError("transport stopped"),
                )
            self._queue.task_done()


def _set_future_error(
    future: asyncio.Future[ReplyEnvelope[object]],
    error: BaseException,
) -> None:
    if not future.done():
        future.set_exception(error)


def _current_task_is_cancelling() -> bool:
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


def _consume_future_exception(future: asyncio.Future[ReplyEnvelope[object]]) -> None:
    if not future.cancelled():
        future.exception()


def _observe_worker_completion(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.error(
            "In-memory transport worker task failed",
            exc_info=(type(error), error, error.__traceback__),
        )

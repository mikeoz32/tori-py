"""Lifecycle relay from committed event-store records to persistent streams."""

from __future__ import annotations

import asyncio
from typing import Annotated

from tori_py import Inject
from tori_py_cqrs_event_sourcing import (
    get_event_store_token,
    get_schema_registry_token,
)
from tori_py_cqrs_event_sourcing_core import (
    CommitResult,
    EventSchemaRegistry,
    EventStore,
    StoredEvent,
)
from tori_py_persistent_streams import (
    StreamPublicationSaturatedError,
    StreamPublisher,
)
from tori_py_persistent_streams_core import PublishOutcome

from ..streams import TASK_EVENTS_ALIAS, TaskEventRecordV1
from .domain import TaskCreated, TaskRenamed

EVENT_SOURCING_KEY = "tasks"
_PAGE_SIZE = 100
_BACKPRESSURE_ATTEMPTS = 3


class RelayGate:
    """Normally-open gate overridden by deterministic system tests."""

    def __init__(self, *, open_: bool = True) -> None:
        self._open = asyncio.Event()
        if open_:
            self._open.set()

    def pause(self) -> None:
        self._open.clear()

    def release(self) -> None:
        self._open.set()

    async def wait(self) -> None:
        await self._open.wait()


class RelayPublicationError(RuntimeError):
    """A relay publication stopped without a safe retry decision."""


class RelayUnavailable(RuntimeError):
    """Raised when command admission observes a degraded relay."""


class TaskEventRelay:
    """Read committed global pages and advance only after broker confirmation."""

    def __init__(
        self,
        store: Annotated[
            EventStore,
            Inject(get_event_store_token(key=EVENT_SOURCING_KEY)),
        ],
        schemas: Annotated[
            EventSchemaRegistry,
            Inject(get_schema_registry_token(key=EVENT_SOURCING_KEY)),
        ],
        publisher: StreamPublisher,
        gate: RelayGate,
    ) -> None:
        self._store = store
        self._schemas = schemas
        self._publisher = publisher
        self._gate = gate
        self._wake = asyncio.Event()
        self._changed = asyncio.Condition()
        self._checkpoint = 0
        self._failure: BaseException | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def checkpoint(self) -> int:
        return self._checkpoint

    @property
    def failure(self) -> BaseException | None:
        return self._failure

    @property
    def degraded(self) -> bool:
        return self._failure is not None

    def require_available(self) -> None:
        """Reject new commands after this relay has degraded."""

        if self._failure is not None:
            raise RelayUnavailable("task event relay is unavailable") from self._failure

    def after_commit(self, result: CommitResult) -> None:
        """Wake the relay without publishing or waiting for consumers."""

        del result
        self._wake.set()

    async def wait_for_checkpoint(self, position: int, *, timeout: float) -> None:
        async with self._changed:
            await asyncio.wait_for(
                self._changed.wait_for(
                    lambda: self._checkpoint >= position or self.degraded
                ),
                timeout,
            )
        if self._checkpoint < position:
            raise RelayPublicationError("task event relay degraded") from self._failure

    async def on_application_bootstrap(self) -> None:
        self._task = asyncio.create_task(self._run())
        self._wake.set()

    async def on_application_shutdown(self) -> None:
        await self.close()

    async def on_module_destroy(self) -> None:
        await self.close()

    async def close(self) -> None:
        task = self._task
        if task is None:
            return
        self._task = None
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        try:
            while True:
                await self._wake.wait()
                self._wake.clear()
                await self._drain()
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            self._failure = error
            async with self._changed:
                self._changed.notify_all()

    async def _drain(self) -> None:
        while True:
            await self._gate.wait()
            page = await self._store.read_all(
                after_position=self._checkpoint,
                limit=_PAGE_SIZE,
            )
            if not page:
                return
            for stored in page:
                await self._gate.wait()
                record = self._record(stored)
                await self._publish_confirmed(record)
                async with self._changed:
                    self._checkpoint = stored.global_position
                    self._changed.notify_all()
            if len(page) < _PAGE_SIZE:
                return

    def _record(self, stored: StoredEvent) -> TaskEventRecordV1:
        if stored.stream_id.category != "task":
            raise RelayPublicationError("unsupported event-store category")
        recorded = self._schemas.decode(stored)
        match recorded.event:
            case TaskCreated(task_id=task_id, title=title):
                kind = "task-created"
            case TaskRenamed(task_id=task_id, title=title):
                kind = "task-renamed"
            case _:
                raise RelayPublicationError("unsupported task domain event")
        return TaskEventRecordV1(
            event_id=stored.event_id,
            kind=kind,
            task_id=task_id,
            title=title,
            aggregate_version=stored.stream_version,
            source_global_position=stored.global_position,
            occurred_at=stored.event.metadata.occurred_at,
        )

    async def _publish_confirmed(self, record: TaskEventRecordV1) -> None:
        for attempt in range(_BACKPRESSURE_ATTEMPTS):
            try:
                receipt = await self._publisher.publish(
                    TASK_EVENTS_ALIAS,
                    record,
                    record_id=record.event_id,
                )
            except StreamPublicationSaturatedError:
                if attempt + 1 == _BACKPRESSURE_ATTEMPTS:
                    raise RelayPublicationError(
                        "task event publication remained backpressured"
                    ) from None
                continue
            if receipt.outcome in {
                PublishOutcome.CONFIRMED,
                PublishOutcome.DEDUPLICATED,
            }:
                return
            if receipt.outcome is PublishOutcome.BACKPRESSURED:
                if attempt + 1 < _BACKPRESSURE_ATTEMPTS:
                    continue
                raise RelayPublicationError(
                    "task event publication remained backpressured"
                )
            raise RelayPublicationError(
                f"task event publication stopped with {receipt.outcome.value}"
            )
        raise AssertionError("bounded publication loop did not terminate")


__all__ = [
    "EVENT_SOURCING_KEY",
    "RelayGate",
    "RelayPublicationError",
    "RelayUnavailable",
    "TaskEventRelay",
]

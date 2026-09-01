"""Idempotent audit consumer and production stream-only root."""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from tori_py import ClassProvider, NestApplication, controller, module
from tori_py_persistent_streams import (
    PersistentStreamsModule,
    PersistentStreamsOptions,
    PersistentStreamsRuntimeOptions,
    StreamPayload,
    stream_handler,
)
from tori_py_persistent_streams_core import InMemoryCheckpointStore
from tori_py_persistent_streams_rabbitmq import RabbitMqPersistentStreamsModule

from ..infrastructure import rabbitmq_stream_options, serve
from ..streams import TASK_EVENTS_ALIAS, TaskEventRecordV1, task_event_binding

AUDIT_GROUP = "task-audit-v1"
AUDIT_CHECKPOINTS = InMemoryCheckpointStore()


class AuditEventConflict(RuntimeError):
    """Raised when an event ID is reused for different audit contents."""


class TaskAuditLog:
    """Count every delivery while storing each event identity only once."""

    def __init__(self) -> None:
        self._entries: dict[UUID, TaskEventRecordV1] = {}
        self.deliveries = 0
        self._changed = asyncio.Condition()

    @property
    def entries(self) -> tuple[TaskEventRecordV1, ...]:
        return tuple(self._entries.values())

    async def record(self, event: TaskEventRecordV1) -> None:
        async with self._changed:
            self.deliveries += 1
            existing = self._entries.get(event.event_id)
            if existing is not None and existing != event:
                self._changed.notify_all()
                raise AuditEventConflict(
                    "task event ID was reused with different contents"
                )
            self._entries.setdefault(event.event_id, event)
            self._changed.notify_all()

    async def wait_for_deliveries(self, count: int, *, timeout: float) -> None:
        async with self._changed:
            await asyncio.wait_for(
                self._changed.wait_for(lambda: self.deliveries >= count),
                timeout,
            )


@controller()
class TaskAuditController:
    def __init__(self, audit: TaskAuditLog) -> None:
        self._audit = audit

    @stream_handler(stream=TASK_EVENTS_ALIAS, consumer_group=AUDIT_GROUP)
    async def audit(
        self,
        record: Annotated[TaskEventRecordV1, StreamPayload()],
    ) -> None:
        await self._audit.record(record)


audit_stream_adapter = RabbitMqPersistentStreamsModule.for_root(
    rabbitmq_stream_options("event-sourced-task-audit-stream")
)
audit_streams = PersistentStreamsModule.for_root(
    PersistentStreamsOptions(
        bindings=(
            task_event_binding(
                AUDIT_CHECKPOINTS,
                checkpoint_identity="task-audit-v1-memory",
            ),
        ),
        runtime=PersistentStreamsRuntimeOptions(
            owner_id="task-audit-v1",
            single_instance_consumer_groups=True,
        ),
    ),
    imports=(audit_stream_adapter,),
)


@module(
    imports=(audit_streams,),
    providers=(ClassProvider(TaskAuditLog),),
    controllers=(TaskAuditController,),
    exports=(TaskAuditLog,),
)
class AuditAppModule:
    """The audit service's independent stream-only application root."""


async def create_application() -> NestApplication:
    return await NestApplication.create(AuditAppModule)


async def run() -> None:
    await serve(create_application)


if __name__ == "__main__":
    asyncio.run(run())


__all__ = [
    "AUDIT_CHECKPOINTS",
    "AUDIT_GROUP",
    "AuditEventConflict",
    "AuditAppModule",
    "TaskAuditController",
    "TaskAuditLog",
    "audit_stream_adapter",
    "create_application",
]

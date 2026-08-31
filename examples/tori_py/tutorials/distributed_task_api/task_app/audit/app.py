"""Idempotent audit consumer and production composition root."""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from tori_py import ClassProvider, NestApplication, controller, module
from tori_py_microservices import (
    EventDispatchMode,
    MicroservicesModule,
    Payload,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqTransport,
    event_handler,
)

from ..contracts import AUDIT, TASKS, TaskCreatedV1
from ..infrastructure import rabbitmq_url, serve


class AuditLog:
    """In-memory idempotent audit sink keyed by integration event ID."""

    def __init__(self) -> None:
        self._entries: dict[UUID, TaskCreatedV1] = {}
        self.deliveries = 0
        self._changed = asyncio.Condition()

    @property
    def entries(self) -> tuple[TaskCreatedV1, ...]:
        return tuple(self._entries.values())

    async def record(self, event: TaskCreatedV1) -> None:
        async with self._changed:
            self.deliveries += 1
            self._entries.setdefault(event.event_id, event)
            self._changed.notify_all()

    async def wait_for_deliveries(self, count: int, *, timeout: float) -> None:
        async with self._changed:
            await asyncio.wait_for(
                self._changed.wait_for(lambda: self.deliveries >= count),
                timeout,
            )


@controller()
class AuditController:
    def __init__(self, audit: AuditLog) -> None:
        self._audit = audit

    @event_handler(
        TASKS,
        "task-created",
        schema_version=1,
        mode=EventDispatchMode.SERVICE_POOL,
        subscription="task-audit",
    )
    async def task_created(
        self,
        payload: Annotated[TaskCreatedV1, Payload()],
    ) -> None:
        await self._audit.record(payload)


audit_transport = RabbitMqTransport()
audit_rabbit = RabbitMqModule.for_root(
    RabbitMqOptions(
        rabbitmq_url(),
        connection_name="distributed-task-audit",
    )
)
audit_microservices = MicroservicesModule.for_root(
    AUDIT,
    transport=audit_transport,
    imports=(audit_rabbit,),
)


@module(
    imports=(audit_microservices,),
    providers=(ClassProvider(AuditLog),),
    controllers=(AuditController,),
)
class AuditAppModule:
    """Composition root for the audit process."""


async def create_application() -> NestApplication:
    return await NestApplication.create(AuditAppModule)


async def run() -> None:
    await serve(create_application)


if __name__ == "__main__":
    asyncio.run(run())


__all__ = [
    "AuditAppModule",
    "AuditController",
    "AuditLog",
    "audit_rabbit",
    "audit_transport",
    "create_application",
]

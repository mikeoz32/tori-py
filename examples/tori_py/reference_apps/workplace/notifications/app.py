"""Idempotent booking-event notification consumer."""
# ruff: noqa: E501

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from sqlalchemy import DateTime, String, Text, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from tori_py import NestApplication, controller, module
from tori_py_microservices import (
    EventDispatchMode,
    Header,
    Payload,
    PublicRpcError,
    event_handler,
    rpc,
)
from tori_py_sqlalchemy import EntityManager, Repository, SqlAlchemyModule, repository

from ..common.contracts import (
    BookingCreated,
    BookingLifecycleEvent,
    Health,
    ListNotifications,
    Notification,
)
from ..common.infrastructure import rabbit_modules, serve, sql_module
from ..common.security import has_workplace_role
from ..common.services import BOOKINGS, NOTIFICATIONS, NotificationsService


class Base(DeclarativeBase):
    pass


class NotificationRow(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    event_id: Mapped[str] = mapped_column(String(128), unique=True)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@repository(NotificationRow)
class NotificationRepository(Repository[NotificationRow]):
    pass


@controller()
class NotificationsController:
    def __init__(
        self, entities: EntityManager, notifications: NotificationRepository
    ) -> None:
        self._entities, self._notifications = entities, notifications

    @event_handler(
        BOOKINGS,
        "booking-created",
        schema_version=1,
        mode=EventDispatchMode.SERVICE_POOL,
        subscription="notification-workers",
    )
    async def booking_created(
        self,
        payload: Annotated[BookingCreated, Payload()],
        event_id: Annotated[str, Header("outbox_event_id")],
    ) -> None:
        try:
            async with self._entities.transaction():
                if await self._notifications.find_one(
                    NotificationRow.event_id == event_id
                ):
                    return
                await self._notifications.add(
                    NotificationRow(
                        id=str(uuid4()),
                        tenant_id=payload.tenant_id,
                        event_id=event_id,
                        message=f"Booking {payload.booking_id} created",
                        created_at=datetime.now(UTC),
                    )
                )
        except IntegrityError:
            async with self._entities.transaction():
                if (
                    await self._notifications.find_one(
                        NotificationRow.event_id == event_id
                    )
                    is None
                ):
                    raise

    @event_handler(
        BOOKINGS,
        "booking-cancelled",
        schema_version=1,
        mode=EventDispatchMode.SERVICE_POOL,
        subscription="notification-workers",
    )
    async def booking_cancelled(
        self,
        payload: Annotated[BookingLifecycleEvent, Payload()],
        event_id: Annotated[str, Header("outbox_event_id")],
    ) -> None:
        await self._record_lifecycle(payload, event_id)

    @event_handler(
        BOOKINGS,
        "booking-checked-in",
        schema_version=1,
        mode=EventDispatchMode.SERVICE_POOL,
        subscription="notification-workers",
    )
    async def booking_checked_in(
        self,
        payload: Annotated[BookingLifecycleEvent, Payload()],
        event_id: Annotated[str, Header("outbox_event_id")],
    ) -> None:
        await self._record_lifecycle(payload, event_id)

    @event_handler(
        BOOKINGS,
        "booking-no-show",
        schema_version=1,
        mode=EventDispatchMode.SERVICE_POOL,
        subscription="notification-workers",
    )
    async def booking_no_show(
        self,
        payload: Annotated[BookingLifecycleEvent, Payload()],
        event_id: Annotated[str, Header("outbox_event_id")],
    ) -> None:
        await self._record_lifecycle(payload, event_id)

    @event_handler(
        BOOKINGS,
        "booking-completed",
        schema_version=1,
        mode=EventDispatchMode.SERVICE_POOL,
        subscription="notification-workers",
    )
    async def booking_completed(
        self,
        payload: Annotated[BookingLifecycleEvent, Payload()],
        event_id: Annotated[str, Header("outbox_event_id")],
    ) -> None:
        await self._record_lifecycle(payload, event_id)

    async def _record_lifecycle(
        self,
        payload: BookingLifecycleEvent,
        event_id: str,
    ) -> None:
        await self._record_notification(
            payload.tenant_id,
            event_id,
            f"Booking {payload.booking_id} {payload.status.replace('_', ' ')}",
        )

    async def _record_notification(
        self, tenant_id: str, event_id: str, message: str
    ) -> None:
        try:
            async with self._entities.transaction():
                if await self._notifications.find_one(
                    NotificationRow.event_id == event_id
                ):
                    return
                await self._notifications.add(
                    NotificationRow(
                        id=str(uuid4()),
                        tenant_id=tenant_id,
                        event_id=event_id,
                        message=message,
                        created_at=datetime.now(UTC),
                    )
                )
        except IntegrityError:
            async with self._entities.transaction():
                if (
                    await self._notifications.find_one(
                        NotificationRow.event_id == event_id
                    )
                    is None
                ):
                    raise

    @rpc(NotificationsService.list_notifications)
    async def list_notifications(
        self, payload: Annotated[ListNotifications, Payload()]
    ) -> list[Notification]:
        if not has_workplace_role(payload.principal):
            raise PublicRpcError("forbidden", "A workplace role is required.")
        rows = await self._notifications.find(
            NotificationRow.tenant_id == payload.principal.tenant_id,
            order_by=(NotificationRow.created_at.desc(),),
            limit=payload.limit,
        )
        return [
            Notification(
                row.id, row.tenant_id, row.event_id, row.message, row.created_at
            )
            for row in rows
        ]

    @rpc(NotificationsService.health)
    async def health(self, payload: Annotated[Health, Payload()]) -> dict[str, str]:
        del payload
        await self._entities.scalar(select(1))
        return {"status": "ok"}


notifications_sql = sql_module("notifications")
notifications_feature = SqlAlchemyModule.for_feature([NotificationRepository])
_, notifications_rabbit, notifications_service = rabbit_modules(NOTIFICATIONS)


@module(
    imports=(notifications_sql, notifications_feature, notifications_service),
    controllers=(NotificationsController,),
)
class NotificationsAppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(NotificationsAppModule)


async def run() -> None:
    await serve(create_application)


if __name__ == "__main__":
    asyncio.run(run())

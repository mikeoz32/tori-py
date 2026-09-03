"""Idempotent booking-event notification consumer."""
# ruff: noqa: E501

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated
from uuid import uuid4

import msgspec
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
    BookingRescheduled,
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


class NotificationInboxRow(Base):
    __tablename__ = "notification_inbox"
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    event_name: Mapped[str] = mapped_column(String(120))
    payload_fingerprint: Mapped[str] = mapped_column(String(64))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@repository(NotificationRow)
class NotificationRepository(Repository[NotificationRow]):
    pass


@repository(NotificationInboxRow)
class NotificationInboxRepository(Repository[NotificationInboxRow]):
    pass


class InboxConflict(Exception):
    pass


@controller()
class NotificationsController:
    def __init__(
        self,
        entities: EntityManager,
        notifications: NotificationRepository,
        inbox: NotificationInboxRepository,
    ) -> None:
        self._entities, self._notifications, self._inbox = (
            entities,
            notifications,
            inbox,
        )

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
        await self._record_notification(
            "booking-created",
            payload,
            event_id,
            f"Booking {payload.booking_id} created",
        )

    @event_handler(
        BOOKINGS,
        "booking-rescheduled",
        schema_version=1,
        mode=EventDispatchMode.SERVICE_POOL,
        subscription="notification-workers",
    )
    async def booking_rescheduled(
        self,
        payload: Annotated[BookingRescheduled, Payload()],
        event_id: Annotated[str, Header("outbox_event_id")],
    ) -> None:
        await self._record_notification(
            "booking-rescheduled",
            payload,
            event_id,
            f"Booking {payload.booking_id} rescheduled",
        )

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
        await self._record_lifecycle("booking-cancelled", payload, event_id)

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
        await self._record_lifecycle("booking-checked-in", payload, event_id)

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
        await self._record_lifecycle("booking-no-show", payload, event_id)

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
        await self._record_lifecycle("booking-completed", payload, event_id)

    async def _record_lifecycle(
        self,
        event_name: str,
        payload: BookingLifecycleEvent,
        event_id: str,
    ) -> None:
        if event_name != f"booking-{payload.status.replace('_', '-')}":
            raise InboxConflict("event type does not match lifecycle status")
        await self._record_notification(
            event_name,
            payload,
            event_id,
            f"Booking {payload.booking_id} {payload.status.replace('_', ' ')}",
        )

    async def _record_notification(
        self,
        event_name: str,
        payload: BookingCreated | BookingRescheduled | BookingLifecycleEvent,
        event_id: str,
        message: str,
    ) -> None:
        fingerprint = _event_fingerprint(event_name, payload)
        try:
            async with self._entities.transaction():
                processed = await self._inbox.find_one(
                    NotificationInboxRow.event_id == event_id
                )
                if processed is not None:
                    _validate_replay(
                        processed, payload.tenant_id, event_name, fingerprint
                    )
                    return

                existing_notification = await self._notifications.find_one(
                    NotificationRow.event_id == event_id
                )
                if existing_notification is not None:
                    _validate_legacy_notification(
                        existing_notification, payload.tenant_id, message
                    )
                    await self._inbox.add(
                        _inbox_row(event_id, payload.tenant_id, event_name, fingerprint)
                    )
                    return

                await self._inbox.add(
                    _inbox_row(event_id, payload.tenant_id, event_name, fingerprint)
                )
                await self._notifications.add(
                    NotificationRow(
                        id=str(uuid4()),
                        tenant_id=payload.tenant_id,
                        event_id=event_id,
                        message=message,
                        created_at=datetime.now(UTC),
                    )
                )
        except IntegrityError as error:
            if not _is_duplicate_event_violation(error):
                raise
            async with self._entities.transaction():
                processed = await self._inbox.find_one(
                    NotificationInboxRow.event_id == event_id
                )
                if processed is None:
                    raise
                _validate_replay(processed, payload.tenant_id, event_name, fingerprint)

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
notifications_feature = SqlAlchemyModule.for_feature(
    [NotificationRepository, NotificationInboxRepository]
)
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


def _event_fingerprint(
    event_name: str,
    payload: BookingCreated | BookingRescheduled | BookingLifecycleEvent,
) -> str:
    return sha256(
        event_name.encode() + b"\0" + msgspec.json.encode(payload)
    ).hexdigest()


def _inbox_row(
    event_id: str, tenant_id: str, event_name: str, fingerprint: str
) -> NotificationInboxRow:
    return NotificationInboxRow(
        event_id=event_id,
        tenant_id=tenant_id,
        event_name=event_name,
        payload_fingerprint=fingerprint,
        processed_at=datetime.now(UTC),
    )


def _validate_replay(
    processed: NotificationInboxRow,
    tenant_id: str,
    event_name: str,
    fingerprint: str,
) -> None:
    if (
        processed.tenant_id != tenant_id
        or processed.event_name != event_name
        or processed.payload_fingerprint != fingerprint
    ):
        raise InboxConflict("event id belongs to a different event")


def _validate_legacy_notification(
    notification: NotificationRow, tenant_id: str, message: str
) -> None:
    """Validate the durable event fields available before inbox deployment."""

    if notification.tenant_id != tenant_id or notification.message != message:
        raise InboxConflict("event id belongs to a different notification")


def _is_duplicate_event_violation(error: IntegrityError) -> bool:
    constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint in {"notification_inbox_pkey", "notifications_event_id_key"}:
        return True
    detail = str(error.orig)
    return (
        "UNIQUE constraint failed: notification_inbox.event_id" in detail
        or "UNIQUE constraint failed: notifications.event_id" in detail
    )


if __name__ == "__main__":
    asyncio.run(run())

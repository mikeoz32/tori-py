"""Durable order-event consumer with its own notification database."""

from __future__ import annotations

import asyncio
from typing import Annotated

from nestpy import NestApplication, controller, module
from nestpy_sqlalchemy import EntityManager, Repository, SqlAlchemyModule, repository
from sqlalchemy import String, Text, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from examples.nestpy.microservices_app.common.contracts import (
    ListNotifications,
    Notification,
    OrderCreated,
)
from examples.nestpy.microservices_app.common.infrastructure import (
    database_url,
    rabbit_modules,
    serve,
    sql_module,
)
from examples.nestpy.microservices_app.common.services import (
    HealthCheck,
    NotificationsService,
)
from nestpy_microservices import (
    EventDispatchMode,
    Header,
    Payload,
    ServiceIdentity,
    event_handler,
    rpc,
)

SERVICE = ServiceIdentity("demo", "notifications", 1)
ORDERS = ServiceIdentity("demo", "orders", 1)


class Base(DeclarativeBase):
    """Notification-owned metadata."""


class NotificationRow(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    message: Mapped[str] = mapped_column(Text)


@repository(NotificationRow)
class NotificationRepository(Repository[NotificationRow]):
    pass


@controller()
class NotificationsController:
    def __init__(
        self,
        entities: EntityManager,
        notifications: NotificationRepository,
    ) -> None:
        self._entities = entities
        self._notifications = notifications

    @event_handler(
        ORDERS,
        "order-created",
        schema_version=1,
        mode=EventDispatchMode.SERVICE_POOL,
        subscription="notification-workers",
    )
    async def order_created(
        self,
        payload: Annotated[OrderCreated, Payload()],
        event_id: Annotated[str, Header("outbox_event_id")],
    ) -> None:
        try:
            async with self._entities.transaction():
                existing = await self._notifications.find_one(
                    NotificationRow.event_id == event_id
                )
                if existing is not None:
                    return
                await self._notifications.add(
                    NotificationRow(
                        event_id=event_id,
                        message=(
                            f"Order {payload.order_id} created for "
                            f"{payload.total_cents} cents"
                        ),
                    )
                )
        except IntegrityError:
            # A concurrent duplicate won the unique event-id insert race.
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
        self,
        payload: Annotated[ListNotifications, Payload()],
    ) -> list[Notification]:
        rows = await self._notifications.find(
            order_by=(NotificationRow.id.desc(),),
            limit=payload.limit,
        )
        return [Notification(row.id, row.event_id, row.message) for row in rows]

    @rpc(NotificationsService.health)
    async def health(
        self,
        payload: Annotated[HealthCheck, Payload()],
    ) -> dict[str, str]:
        del payload
        await self._entities.scalar(select(1))
        return {"status": "ok"}


notifications_sql = sql_module(database_url("notifications"))
notifications_feature = SqlAlchemyModule.for_feature([NotificationRepository])
_, notifications_rabbit, notifications_service = rabbit_modules(SERVICE)


@module(
    imports=(
        notifications_sql,
        notifications_feature,
        notifications_service,
    ),
    controllers=(NotificationsController,),
)
class NotificationsAppModule:
    """Composition root for the notification consumer."""


async def create_application() -> NestApplication:
    return await NestApplication.create(NotificationsAppModule)


async def run() -> None:
    await serve(create_application)


if __name__ == "__main__":
    asyncio.run(run())

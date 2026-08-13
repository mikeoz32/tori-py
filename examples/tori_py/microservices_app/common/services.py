"""Typed service contracts shared by the example's RPC clients and servers."""

from __future__ import annotations

from typing import Protocol

import msgspec
from tori_py_microservices import ServiceIdentity, rpc_call, service_contract

from examples.tori_py.microservices_app.common.contracts import (
    CatalogItem,
    CreateCatalogItem,
    CreateOrder,
    GetCatalogItem,
    GetOrder,
    ListNotifications,
    Notification,
    Order,
)

CATALOG = ServiceIdentity("demo", "catalog", 1)
ORDERS = ServiceIdentity("demo", "orders", 1)
NOTIFICATIONS = ServiceIdentity("demo", "notifications", 1)


class HealthCheck(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Empty request used by service readiness RPCs."""


class CatalogItemLookup(Protocol):
    """Orders-owned dependency on catalog item lookup."""

    async def get_item(self, item_id: int) -> CatalogItem: ...


@service_contract(CATALOG)
class CatalogService(CatalogItemLookup, Protocol):
    @rpc_call("create-item", payload=CreateCatalogItem)
    async def create_item(
        self,
        name: str,
        price_cents: int,
    ) -> CatalogItem: ...

    @rpc_call("get-item", payload=GetCatalogItem)
    async def get_item(self, item_id: int) -> CatalogItem: ...

    @rpc_call("health", payload=HealthCheck, timeout=2)
    async def health(self) -> dict[str, str]: ...


@service_contract(ORDERS)
class OrdersService(Protocol):
    @rpc_call("create-order", payload=CreateOrder)
    async def create_order(
        self,
        item_id: int,
        quantity: int,
    ) -> Order: ...

    @rpc_call("get-order", payload=GetOrder)
    async def get_order(self, order_id: int) -> Order: ...

    @rpc_call("health", payload=HealthCheck, timeout=2)
    async def health(self) -> dict[str, str]: ...


@service_contract(NOTIFICATIONS)
class NotificationsService(Protocol):
    @rpc_call("list-notifications", payload=ListNotifications)
    async def list_notifications(self, limit: int = 100) -> list[Notification]: ...

    @rpc_call("health", payload=HealthCheck, timeout=2)
    async def health(self) -> dict[str, str]: ...


__all__ = [
    "CATALOG",
    "NOTIFICATIONS",
    "ORDERS",
    "CatalogService",
    "CatalogItemLookup",
    "HealthCheck",
    "NotificationsService",
    "OrdersService",
]

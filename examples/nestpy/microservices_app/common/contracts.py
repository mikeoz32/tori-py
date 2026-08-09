"""Versioned contracts exchanged by the example services."""

from __future__ import annotations

from typing import Annotated

import msgspec

type DatabaseId = Annotated[int, msgspec.Meta(ge=1, le=2_147_483_647)]
type CatalogName = Annotated[
    str,
    msgspec.Meta(min_length=1, max_length=120, pattern=r"^[^\x00]+$"),
]
type PositiveInteger = Annotated[int, msgspec.Meta(ge=1, le=2_147_483_647)]


class CatalogItem(msgspec.Struct, frozen=True):
    """Public catalog representation."""

    id: int
    name: str
    price_cents: int


class CreateCatalogItem(msgspec.Struct, forbid_unknown_fields=True):
    """Gateway input for catalog item creation."""

    name: CatalogName
    price_cents: PositiveInteger


class GetCatalogItem(msgspec.Struct, forbid_unknown_fields=True):
    """RPC input for catalog lookup."""

    item_id: DatabaseId


class Order(msgspec.Struct, frozen=True):
    """Public order representation."""

    id: int
    item_id: DatabaseId
    quantity: PositiveInteger
    unit_price_cents: int
    status: str


class CreateOrder(msgspec.Struct, forbid_unknown_fields=True):
    """Gateway input for order creation."""

    item_id: DatabaseId
    quantity: PositiveInteger


class GetOrder(msgspec.Struct, forbid_unknown_fields=True):
    """RPC input for order lookup."""

    order_id: DatabaseId


class OrderCreated(msgspec.Struct, frozen=True):
    """Integration event payload published by the orders service."""

    order_id: int
    item_id: int
    quantity: int
    total_cents: int


class Notification(msgspec.Struct, frozen=True):
    """Public notification representation."""

    id: int
    event_id: str
    message: str


class ListNotifications(msgspec.Struct, forbid_unknown_fields=True):
    """Bounded notification-list request."""

    limit: Annotated[int, msgspec.Meta(ge=1, le=100)] = 100


__all__ = [
    "CatalogItem",
    "CreateCatalogItem",
    "CreateOrder",
    "GetCatalogItem",
    "GetOrder",
    "ListNotifications",
    "Notification",
    "OrderCreated",
    "Order",
]

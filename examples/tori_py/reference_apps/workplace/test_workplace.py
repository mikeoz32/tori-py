"""Application-level specifications for the workplace reference app."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from sqlite3 import IntegrityError as SQLiteIntegrityError
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tori_py_sqlalchemy import EntityManager

from examples.tori_py.reference_apps.workplace.bookings.app import (
    Base as BookingsBase,
)
from examples.tori_py.reference_apps.workplace.bookings.app import (
    BookingConflict,
    BookingRepository,
    BookingRow,
    CreateBookingCommand,
    CreateBookingHandler,
    GetBookingHandler,
    GetBookingQuery,
    IdempotencyConflict,
    OutboxRepository,
    OutboxRow,
    _is_idempotency_violation,
)
from examples.tori_py.reference_apps.workplace.bookings.app import (
    create_application as create_bookings_application,
)
from examples.tori_py.reference_apps.workplace.common.contracts import (
    CreateBookingRequest,
    Principal,
)
from examples.tori_py.reference_apps.workplace.gateway.app import (
    GatewayController,
    _principal_from_claims,
)
from examples.tori_py.reference_apps.workplace.gateway.app import (
    create_application as create_gateway_application,
)
from examples.tori_py.reference_apps.workplace.notifications.app import (
    create_application as create_notifications_application,
)
from examples.tori_py.reference_apps.workplace.spaces.app import (
    Base as SpacesBase,
)
from examples.tori_py.reference_apps.workplace.spaces.app import (
    CreateResourceCommand,
    CreateResourceHandler,
    ListResourcesHandler,
    ListResourcesQuery,
    ResourceRepository,
    ResourceRow,
)
from examples.tori_py.reference_apps.workplace.spaces.app import (
    create_application as create_spaces_application,
)


@pytest.fixture
async def booking_components():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(BookingsBase.metadata.create_all)
    entities = EntityManager(async_sessionmaker(engine, expire_on_commit=False))
    bookings = BookingRepository(BookingRow, entities)
    outbox = OutboxRepository(OutboxRow, entities)
    try:
        yield (
            bookings,
            outbox,
            CreateBookingHandler(entities, bookings, outbox),
            GetBookingHandler(bookings),
        )
    finally:
        await engine.dispose()


@pytest.fixture
async def space_components():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(SpacesBase.metadata.create_all)
    entities = EntityManager(async_sessionmaker(engine, expire_on_commit=False))
    resources = ResourceRepository(ResourceRow, entities)
    try:
        yield (
            CreateResourceHandler(entities, resources),
            ListResourcesHandler(resources),
        )
    finally:
        await engine.dispose()


def booking_command(
    *,
    tenant_id: str = "tenant-north",
    actor_id: str = "employee-1",
    resource_id: str = "desk-17",
    idempotency_key: str = "booking-request-1",
    starts_at: datetime | None = None,
) -> CreateBookingCommand:
    start = starts_at or datetime(2026, 9, 2, 9, tzinfo=UTC)
    return CreateBookingCommand(
        tenant_id=tenant_id,
        actor_id=actor_id,
        resource_id=resource_id,
        starts_at=start,
        ends_at=start + timedelta(hours=2),
        idempotency_key=idempotency_key,
    )


@pytest.mark.asyncio
async def test_repeating_the_same_request_returns_the_original_booking(
    booking_components,
) -> None:
    repository, outbox, create, _ = booking_components

    first = await create.handle(booking_command())
    repeated = await create.handle(booking_command())

    assert repeated == first
    assert await repository.count() == 1
    assert await outbox.count() == 1


@pytest.mark.asyncio
async def test_reusing_an_idempotency_key_for_another_request_is_rejected(
    booking_components,
) -> None:
    _, _, create, _ = booking_components
    await create.handle(booking_command())

    with pytest.raises(IdempotencyConflict):
        await create.handle(
            booking_command(starts_at=datetime(2026, 9, 2, 13, tzinfo=UTC))
        )


def test_sqlite_idempotency_constraint_is_classified() -> None:
    error = IntegrityError(
        None,
        None,
        SQLiteIntegrityError(
            "UNIQUE constraint failed: bookings.tenant_id, bookings.idempotency_key"
        ),
    )

    assert _is_idempotency_violation(error)


@pytest.mark.asyncio
async def test_overlapping_bookings_are_isolated_by_tenant(booking_components) -> None:
    _, _, create, _ = booking_components
    await create.handle(booking_command())

    with pytest.raises(BookingConflict):
        await create.handle(booking_command(idempotency_key="overlap"))

    other_tenant = await create.handle(
        booking_command(tenant_id="tenant-south", idempotency_key="other-tenant")
    )
    assert other_tenant.tenant_id == "tenant-south"


@pytest.mark.asyncio
async def test_booking_lookup_never_crosses_the_tenant_boundary(
    booking_components,
) -> None:
    _, _, create, get = booking_components
    booking = await create.handle(booking_command())

    with pytest.raises(LookupError):
        await get.handle(
            GetBookingQuery("tenant-south", "employee-1", ("employee",), booking.id)
        )


@pytest.mark.asyncio
async def test_employee_cannot_read_another_actors_booking(booking_components) -> None:
    _, _, create, get = booking_components
    booking = await create.handle(booking_command())

    with pytest.raises(LookupError):
        await get.handle(
            GetBookingQuery("tenant-north", "employee-2", ("employee",), booking.id)
        )

    visible = await get.handle(
        GetBookingQuery("tenant-north", "admin-1", ("facilities-admin",), booking.id)
    )
    assert visible == booking


@pytest.mark.asyncio
async def test_resource_listing_never_crosses_the_tenant_boundary(
    space_components,
) -> None:
    create, list_resources = space_components
    for tenant_id in ("tenant-north", "tenant-south"):
        await create.handle(
            CreateResourceCommand(
                tenant_id,
                "building-n",
                "level-03",
                f"{tenant_id} desk",
                "desk",
                100,
                200,
            )
        )

    north = await list_resources.handle(ListResourcesQuery("tenant-north", "level-03"))

    assert [resource.tenant_id for resource in north] == ["tenant-north"]


def test_keycloak_claims_only_trust_the_web_clients_roles() -> None:
    principal = _principal_from_claims(
        {
            "tenant_id": "tenant-north",
            "sub": "employee-1",
            "realm_access": {"roles": ["facilities-admin"]},
            "resource_access": {
                "tori-space-web": {"roles": ["employee"]},
                "other-client": {"roles": ["facilities-admin"]},
            },
        }
    )

    assert principal == Principal("tenant-north", "employee-1", ("employee",))


@pytest.mark.asyncio
async def test_gateway_adds_trusted_identity_to_booking_rpc() -> None:
    principal = Principal("tenant-north", "employee-1", ("employee",))
    calls: list[tuple[object, ...]] = []

    class Bookings:
        async def create_booking(self, *args):
            calls.append(args)
            return "created"

    context = SimpleNamespace(
        headers={"idempotency-key": "request-1"},
        request=SimpleNamespace(state=SimpleNamespace(principal=principal)),
    )
    controller = GatewayController(SimpleNamespace(), Bookings(), SimpleNamespace())
    body = CreateBookingRequest(
        "desk-17",
        datetime(2026, 9, 2, 9, tzinfo=UTC),
        datetime(2026, 9, 2, 11, tzinfo=UTC),
    )

    result = await controller.create_booking(body, context)

    assert result == "created"
    assert calls == [
        (
            principal,
            "desk-17",
            body.starts_at,
            body.ends_at,
            "request-1",
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "factory",
    (
        create_spaces_application,
        create_bookings_application,
        create_notifications_application,
        create_gateway_application,
    ),
)
async def test_each_workplace_process_has_an_independent_application_root(
    factory,
) -> None:
    application = await factory()
    assert application.state.value == "compiled"

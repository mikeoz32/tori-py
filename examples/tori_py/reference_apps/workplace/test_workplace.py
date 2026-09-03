"""Application-level specifications for the workplace reference app."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from sqlite3 import IntegrityError as SQLiteIntegrityError
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tori_py.http import HttpException
from tori_py_microservices import EventDispatcher, PublicRpcError
from tori_py_sqlalchemy import EntityManager

from examples.tori_py.reference_apps.workplace.bookings.app import (
    AuditRepository,
    AuditRow,
    AvailabilityHandler,
    AvailabilityQuery,
    BookingConflict,
    BookingExpiryService,
    BookingRepository,
    BookingRow,
    BookingStatusTransitionError,
    CreateBookingCommand,
    CreateBookingHandler,
    FacilitiesDashboardHandler,
    FacilityDashboardQuery,
    GetBookingHandler,
    GetBookingQuery,
    IdempotencyConflict,
    ListBookingsHandler,
    ListBookingsQuery,
    OutboxRelay,
    OutboxRepository,
    OutboxRow,
    SetBookingStatusCommand,
    SetBookingStatusHandler,
    _is_idempotency_violation,
)
from examples.tori_py.reference_apps.workplace.bookings.app import (
    Base as BookingsBase,
)
from examples.tori_py.reference_apps.workplace.bookings.app import (
    create_application as create_bookings_application,
)
from examples.tori_py.reference_apps.workplace.bookings.migrate import migrate
from examples.tori_py.reference_apps.workplace.common.contracts import (
    AdminRequest,
    Availability,
    CleanupOutbox,
    CreateBookingRequest,
    Principal,
)
from examples.tori_py.reference_apps.workplace.gateway.app import (
    GatewayController,
    StaticController,
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
    ResourceEquipmentRepository,
    ResourceEquipmentRow,
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
    audit = AuditRepository(AuditRow, entities)
    try:
        yield (
            bookings,
            outbox,
            audit,
            CreateBookingHandler(entities, bookings, outbox, audit),
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
    equipment = ResourceEquipmentRepository(ResourceEquipmentRow, entities)
    try:
        yield (
            CreateResourceHandler(entities, resources, equipment),
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
    repository, outbox, _, create, _ = booking_components

    first = await create.handle(booking_command())
    repeated = await create.handle(booking_command())

    assert repeated == first
    assert await repository.count() == 1
    assert await outbox.count() == 1


@pytest.mark.asyncio
async def test_reusing_an_idempotency_key_for_another_request_is_rejected(
    booking_components,
) -> None:
    _, _, _, create, _ = booking_components
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
    _, _, _, create, _ = booking_components
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
    _, _, _, create, get = booking_components
    booking = await create.handle(booking_command())

    with pytest.raises(LookupError):
        await get.handle(
            GetBookingQuery("tenant-south", "employee-1", ("employee",), booking.id)
        )


@pytest.mark.asyncio
async def test_employee_cannot_read_another_actors_booking(booking_components) -> None:
    _, _, _, create, get = booking_components
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
async def test_booking_listing_has_stable_bounded_pages(booking_components) -> None:
    bookings, _, _, create, _ = booking_components
    starts = (
        datetime(2026, 9, 2, 9, tzinfo=UTC),
        datetime(2026, 9, 2, 12, tzinfo=UTC),
        datetime(2026, 9, 2, 15, tzinfo=UTC),
    )
    for index, starts_at in enumerate(starts):
        await create.handle(
            booking_command(idempotency_key=f"page-{index}", starts_at=starts_at)
        )

    page = await ListBookingsHandler(bookings).handle(
        ListBookingsQuery(
            "tenant-north",
            "employee-1",
            ("employee",),
            None,
            offset=1,
            limit=1,
        )
    )

    assert len(page) == 1
    assert page[0].starts_at == starts[1]


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


@pytest.mark.asyncio
async def test_availability_excludes_active_overlaps_and_is_tenant_scoped(
    booking_components,
) -> None:
    _, _, _, create, _ = booking_components
    booking = await create.handle(booking_command())
    entities = create._entities
    availability = AvailabilityHandler(BookingRepository(BookingRow, entities))

    unavailable = await availability.handle(
        AvailabilityQuery(
            "tenant-north", booking.starts_at, booking.ends_at, ("desk-17", "desk-18")
        )
    )
    other_tenant = await availability.handle(
        AvailabilityQuery(
            "tenant-south", booking.starts_at, booking.ends_at, ("desk-17",)
        )
    )

    assert unavailable == [
        Availability("desk-17", False, (booking.id,)),
        Availability("desk-18", True, ()),
    ]
    assert other_tenant == [Availability("desk-17", True, ())]


@pytest.mark.asyncio
async def test_status_transitions_write_lifecycle_event_and_immutable_audit(
    booking_components,
) -> None:
    bookings, outbox, audit, create, _ = booking_components
    booking = await create.handle(booking_command())
    entities = create._entities
    set_status = SetBookingStatusHandler(entities, bookings, outbox, audit)

    checked_in = await set_status.handle(
        SetBookingStatusCommand(
            "tenant-north", "employee-1", ("employee",), booking.id, "checked_in"
        )
    )

    assert checked_in.status == "checked_in"
    events = await outbox.find()
    assert [event.event_name for event in events] == [
        "booking-created",
        "booking-checked-in",
    ]
    rows = await audit.find(order_by=(AuditRow.created_at,))
    assert [(row.action, row.from_status, row.to_status) for row in rows] == [
        ("booking-created", None, "booked"),
        ("booking-checked-in", "booked", "checked_in"),
    ]


@pytest.mark.asyncio
async def test_only_legal_lifecycle_transitions_are_accepted(
    booking_components,
) -> None:
    bookings, outbox, audit, create, _ = booking_components
    booking = await create.handle(booking_command())
    set_status = SetBookingStatusHandler(create._entities, bookings, outbox, audit)

    with pytest.raises(BookingStatusTransitionError):
        await set_status.handle(
            SetBookingStatusCommand(
                "tenant-north", "employee-1", ("employee",), booking.id, "completed"
            )
        )


@pytest.mark.asyncio
async def test_expiry_moves_booked_and_checked_in_bookings_deterministically(
    booking_components,
) -> None:
    bookings, outbox, audit, create, _ = booking_components
    booked = await create.handle(
        booking_command(starts_at=datetime(2026, 9, 1, 8, tzinfo=UTC))
    )
    checked_in = await create.handle(
        booking_command(
            idempotency_key="checked",
            resource_id="room-1",
            starts_at=datetime(2026, 9, 1, 8, tzinfo=UTC),
        )
    )
    set_status = SetBookingStatusHandler(create._entities, bookings, outbox, audit)
    await set_status.handle(
        SetBookingStatusCommand(
            "tenant-north", "employee-1", ("employee",), checked_in.id, "checked_in"
        )
    )

    changed = await BookingExpiryService(
        create._entities, bookings, outbox, audit
    ).expire(datetime(2026, 9, 1, 10, 16, tzinfo=UTC))

    assert {booking.id: booking.status for booking in changed} == {
        booked.id: "no_show",
        checked_in.id: "completed",
    }


@pytest.mark.asyncio
async def test_facilities_dashboard_counts_active_lifecycle_states(
    booking_components,
) -> None:
    bookings, outbox, audit, create, _ = booking_components
    booking = await create.handle(booking_command())
    await SetBookingStatusHandler(create._entities, bookings, outbox, audit).handle(
        SetBookingStatusCommand(
            "tenant-north", "employee-1", ("employee",), booking.id, "cancelled"
        )
    )

    dashboard = await FacilitiesDashboardHandler(bookings, outbox).handle(
        FacilityDashboardQuery("tenant-north")
    )

    assert dashboard.active_bookings == 0
    assert dashboard.no_shows == 0
    assert dashboard.outbox_pending == 2


@pytest.mark.asyncio
async def test_availability_rejects_naive_and_invalid_intervals(
    booking_components,
) -> None:
    _, _, _, create, _ = booking_components
    controller = GatewayController(
        SimpleNamespace(), SimpleNamespace(), SimpleNamespace()
    )
    principal = Principal("tenant-north", "employee-1", ("employee",))
    context = SimpleNamespace(
        request=SimpleNamespace(state=SimpleNamespace(principal=principal))
    )

    with pytest.raises(HttpException, match="timezone-aware"):
        await controller.availability(
            datetime(2026, 9, 2, 9), datetime(2026, 9, 2, 10), context
        )
    del create


@pytest.mark.asyncio
async def test_outbox_relay_records_backoff_and_dead_letters_after_five_attempts(
    booking_components,
) -> None:
    _, outbox, _, create, _ = booking_components
    booking = await create.handle(booking_command())

    class FailingEvents:
        async def publish(self, *args, **kwargs):
            raise RuntimeError("broker unavailable")

    relay = OutboxRelay(
        create._entities, outbox, cast(EventDispatcher, FailingEvents())
    )
    for attempt in range(5):
        with pytest.raises(RuntimeError, match="broker unavailable"):
            await relay.publish_once()
        row = await outbox.find_one(OutboxRow.tenant_id == booking.tenant_id)
        assert row is not None
        assert row.attempts == attempt + 1
        if attempt < 4:
            async with create._entities.transaction():
                row = await outbox.find_one(OutboxRow.tenant_id == booking.tenant_id)
                assert row is not None
                row.next_attempt_at = datetime(2020, 1, 1, tzinfo=UTC)
                await create._entities.flush()

    assert row.dead_lettered_at is not None
    assert row.last_error == "broker unavailable"


@pytest.mark.asyncio
async def test_dashboard_and_outbox_diagnostics_are_tenant_scoped(
    booking_components,
) -> None:
    _, outbox, _, create, _ = booking_components
    await create.handle(booking_command(tenant_id="tenant-north"))
    await create.handle(
        booking_command(tenant_id="tenant-south", idempotency_key="south")
    )
    controller = GatewayController(
        SimpleNamespace(), SimpleNamespace(), SimpleNamespace()
    )
    del controller

    diagnostics = await FacilitiesDashboardHandler(create._bookings, outbox).handle(
        FacilityDashboardQuery("tenant-north")
    )
    assert diagnostics.outbox_pending == 1


@pytest.mark.asyncio
async def test_expiry_background_task_is_cancelled_on_shutdown(
    booking_components,
) -> None:
    bookings, outbox, audit, create, _ = booking_components
    expiry = BookingExpiryService(
        create._entities, bookings, outbox, audit, poll_interval=60
    )

    await expiry.on_application_bootstrap()
    task = expiry._task
    await expiry.on_application_shutdown()

    assert task is not None and task.cancelled()


@pytest.mark.asyncio
async def test_forged_non_admin_rpc_principal_cannot_access_admin_operations(
    booking_components,
) -> None:
    bookings, outbox, audit, create, _ = booking_components
    controller = __import__(
        "examples.tori_py.reference_apps.workplace.bookings.app",
        fromlist=["BookingsController"],
    ).BookingsController(
        SimpleNamespace(),
        SimpleNamespace(),
        create._entities,
        SimpleNamespace(),
        audit,
        outbox,
    )
    principal = Principal("tenant-north", "employee-1", ("employee",))

    with pytest.raises(PublicRpcError, match="Facilities administrator"):
        await controller.outbox_diagnostics(AdminRequest(principal))
    with pytest.raises(PublicRpcError, match="Facilities administrator"):
        await controller.cleanup_outbox(
            CleanupOutbox(principal, datetime(2026, 9, 1, tzinfo=UTC))
        )
    del bookings


@pytest.mark.asyncio
async def test_gateway_rejects_naive_outbox_cleanup_timestamp() -> None:
    principal = Principal("tenant-north", "admin-1", ("facilities-admin",))
    context = SimpleNamespace(
        request=SimpleNamespace(state=SimpleNamespace(principal=principal))
    )

    class Bookings:
        async def cleanup_outbox(self, *args):
            return 0

    controller = GatewayController(SimpleNamespace(), Bookings(), SimpleNamespace())
    from examples.tori_py.reference_apps.workplace.common.contracts import (
        CleanupOutboxRequest,
    )

    with pytest.raises(HttpException, match="timezone-aware"):
        await controller.cleanup_outbox(
            CleanupOutboxRequest(datetime(2026, 9, 1)), context
        )


@pytest.mark.asyncio
async def test_static_controller_allows_only_declared_component_assets() -> None:
    controller = StaticController()

    for asset in (
        "admin-panel.js",
        "api-client.js",
        "app.js",
        "auth.js",
        "booking-calendar.js",
        "booking-list.js",
        "calendar.js",
        "floor-plan.js",
        "styles.css",
        "workplace-app.js",
    ):
        response = await controller.web_asset(asset)
        assert response.path.name == asset

    for asset in ("keycloak.js", "lit-core.min.js"):
        response = await controller.vendor_asset(asset)
        assert response.path.name == asset

    with pytest.raises(HttpException, match="not found"):
        await controller.web_asset("secrets.txt")
    with pytest.raises(HttpException, match="not found"):
        await controller.vendor_asset("other.js")


@pytest.mark.asyncio
async def test_sqlite_migration_makes_audit_rows_immutable(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = (tmp_path / "bookings.sqlite3").as_posix()
    database_url = f"sqlite+aiosqlite:///{database_path}"
    monkeypatch.setenv("WORKPLACE_BOOKINGS_DATABASE_URL", database_url)
    await migrate()

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("""
                    INSERT INTO booking_audit (
                      id, tenant_id, booking_id, resource_id, actor_id,
                      action, from_status, to_status, created_at
                    ) VALUES (
                      'audit-1', 'tenant-north', 'booking-1', 'desk-17',
                      'employee-1', 'booking-created', NULL, 'booked',
                      '2026-09-01T00:00:00+00:00'
                    )
                """)
            )

        with pytest.raises(IntegrityError, match="booking audit rows are immutable"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE booking_audit SET action = 'changed' "
                        "WHERE id = 'audit-1'"
                    )
                )

        with pytest.raises(IntegrityError, match="booking audit rows are immutable"):
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM booking_audit WHERE id = 'audit-1'")
                )
    finally:
        await engine.dispose()

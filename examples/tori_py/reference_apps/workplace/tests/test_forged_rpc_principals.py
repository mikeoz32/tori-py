"""Authorization checks at the bookings RPC trust boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from tori_py_microservices import PublicRpcError

from examples.tori_py.reference_apps.workplace.bookings.app import BookingsController
from examples.tori_py.reference_apps.workplace.common.contracts import (
    AdminRequest,
    AvailabilityQuery,
    CancelBooking,
    CheckInBooking,
    CleanupOutbox,
    CreateBooking,
    CreateRecurringBooking,
    GetBooking,
    ListAudit,
    ListBookings,
    ListResources,
    Principal,
    RescheduleBooking,
)
from examples.tori_py.reference_apps.workplace.spaces.app import SpacesController


@pytest.fixture
def controller() -> BookingsController:
    return BookingsController(
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
    )


def _forged_principal() -> Principal:
    return Principal("tenant-north", "attacker", ("untrusted",))


def _normal_payloads() -> tuple[object, ...]:
    principal = _forged_principal()
    starts_at = datetime(2026, 9, 2, 9, tzinfo=UTC)
    ends_at = datetime(2026, 9, 2, 10, tzinfo=UTC)
    return (
        CreateBooking(principal, "desk-17", starts_at, ends_at, "request-1"),
        CreateRecurringBooking(
            principal, "desk-17", starts_at, ends_at, "weekly", 2, "series-1"
        ),
        RescheduleBooking(principal, "booking-1", starts_at, ends_at, "reschedule-1"),
        GetBooking(principal, "booking-1"),
        ListBookings(principal),
        AvailabilityQuery(principal, starts_at, ends_at),
        CancelBooking(principal, "booking-1", "one", "cancel-1"),
        CheckInBooking(principal, "booking-1"),
    )


@pytest.mark.asyncio
async def test_forged_principal_without_workplace_role_is_rejected_by_booking_endpoints(
    controller: BookingsController,
) -> None:
    create, recurring, reschedule, get, listing, availability, cancel, check_in = (
        _normal_payloads()
    )
    operations = (
        controller.create_booking(create),
        controller.create_recurring_booking(recurring),
        controller.reschedule_booking(reschedule),
        controller.get_booking(get),
        controller.list_bookings(listing),
        controller.availability(availability),
        controller.cancel_booking(cancel),
        controller.check_in_booking(check_in),
    )

    for operation in operations:
        with pytest.raises(PublicRpcError, match="workplace role") as error:
            await operation
        assert error.value.code == "forbidden"


@pytest.mark.asyncio
async def test_non_admin_rpc_cannot_list_inactive_resources() -> None:
    controller = SpacesController(
        SimpleNamespace(), SimpleNamespace(), SimpleNamespace()
    )
    principal = Principal("tenant-north", "employee-1", ("employee",))

    with pytest.raises(PublicRpcError, match="Facilities administrator") as error:
        await controller.list_resources(ListResources(principal, include_inactive=True))

    assert error.value.code == "forbidden"


@pytest.mark.asyncio
async def test_forged_non_admin_principal_is_rejected_by_admin_booking_endpoints(
    controller: BookingsController,
) -> None:
    principal = Principal("tenant-north", "employee-1", ("employee",))
    operations = (
        controller.facilities_dashboard(AdminRequest(principal)),
        controller.list_audit(ListAudit(principal)),
        controller.outbox_diagnostics(AdminRequest(principal)),
        controller.cleanup_outbox(
            CleanupOutbox(principal, datetime(2026, 9, 3, tzinfo=UTC))
        ),
    )

    for operation in operations:
        with pytest.raises(PublicRpcError, match="Facilities administrator") as error:
            await operation
        assert error.value.code == "forbidden"

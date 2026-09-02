"""Gateway specifications for resource and booking extension routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest
from tori_py.http import HttpException
from tori_py_microservices import PublicRpcError

from examples.tori_py.reference_apps.workplace.bookings.app import (
    BookingConflict,
    BookingsController,
    CreateBookingCommand,
    RescheduleBookingCommand,
)
from examples.tori_py.reference_apps.workplace.common.contracts import (
    Availability,
    AvailabilityQuery,
    Booking,
    CancelBookingRequest,
    CreateBooking,
    CreateRecurringBookingRequest,
    OfficePolicy,
    OfficePolicyUpdate,
    Principal,
    RescheduleBooking,
    RescheduleBookingRequest,
    Resource,
    UpdateResource,
)
from examples.tori_py.reference_apps.workplace.gateway.app import GatewayController


def _context(principal: Principal, *, idempotency_key: str = "") -> SimpleNamespace:
    headers = {"idempotency-key": idempotency_key} if idempotency_key else {}
    return SimpleNamespace(
        headers=headers,
        request=SimpleNamespace(state=SimpleNamespace(principal=principal)),
    )


def _resource(resource_id: str, *, active: bool = True) -> Resource:
    return Resource(
        resource_id,
        "tenant-north",
        "office-north",
        "floor-3",
        resource_id,
        "desk",
        10,
        20,
        ("monitor",),
        2,
        active,
    )


@pytest.mark.asyncio
async def test_resource_filters_are_forwarded_to_spaces() -> None:
    principal = Principal("tenant-north", "admin-1", ("facilities-admin",))
    calls: list[tuple[object, ...]] = []

    class Spaces:
        async def list_resources(self, *args: object) -> list[Resource]:
            calls.append(args)
            return [_resource("desk-17")]

    controller = GatewayController(Spaces(), SimpleNamespace(), SimpleNamespace())

    resources = await controller.list_resources(
        _context(principal),
        office_id="office-north",
        floor_id="floor-3",
        kind="desk",
        equipment=("monitor", "whiteboard"),
        min_capacity=2,
        include_inactive=True,
    )

    assert resources == [_resource("desk-17")]
    assert calls == [
        (
            principal,
            "office-north",
            "floor-3",
            "desk",
            ("monitor", "whiteboard"),
            2,
            True,
            0,
            50,
        )
    ]


@pytest.mark.asyncio
async def test_single_equipment_query_value_is_normalized_for_rpc() -> None:
    principal = Principal("tenant-north", "employee-1", ("employee",))
    calls: list[tuple[object, ...]] = []

    class Spaces:
        async def list_resources(self, *args: object) -> list[Resource]:
            calls.append(args)
            return []

    controller = GatewayController(Spaces(), SimpleNamespace(), SimpleNamespace())

    await controller.list_resources(_context(principal), equipment="monitor")

    assert calls[0][4] == ("monitor",)


@pytest.mark.asyncio
async def test_availability_filter_uses_one_bulk_booking_result() -> None:
    principal = Principal("tenant-north", "employee-1", ("employee",))
    starts_at = datetime(2026, 9, 2, 9, tzinfo=UTC)
    ends_at = starts_at + timedelta(hours=2)
    space_calls: list[tuple[object, ...]] = []
    booking_calls: list[tuple[object, ...]] = []

    class Spaces:
        async def list_resources(self, *args: object) -> list[Resource]:
            space_calls.append(args)
            return [
                _resource("desk-free"),
                _resource("desk-busy"),
                _resource("desk-other"),
            ]

    class Bookings:
        async def availability(self, *args: object) -> list[Availability]:
            booking_calls.append(args)
            return [
                Availability("desk-free", True, ()),
                Availability("desk-busy", False, ("booking-1",)),
                Availability("not-a-candidate", True, ()),
            ]

    controller = GatewayController(Spaces(), Bookings(), SimpleNamespace())

    resources = await controller.list_resources(
        _context(principal),
        kind="desk",
        availability_from=starts_at,
        availability_to=ends_at,
    )

    assert [resource.id for resource in resources] == ["desk-free"]
    assert space_calls == [(principal, None, None, "desk", (), None, False, 0, 100)]
    assert booking_calls == [
        (
            principal,
            starts_at,
            ends_at,
            None,
            ("desk-free", "desk-busy", "desk-other"),
        )
    ]


@pytest.mark.asyncio
async def test_availability_filter_paginates_after_filtering() -> None:
    principal = Principal("tenant-north", "employee-1", ("employee",))
    starts_at = datetime(2026, 9, 2, 9, tzinfo=UTC)
    ends_at = starts_at + timedelta(hours=2)
    candidates = [_resource(f"desk-{index:03}") for index in range(101)]

    class Spaces:
        async def list_resources(self, *args: object) -> list[Resource]:
            offset, limit = args[-2:]
            assert isinstance(offset, int)
            assert isinstance(limit, int)
            return candidates[offset : offset + limit]

    class Bookings:
        async def availability(self, *args: object) -> list[Availability]:
            resource_ids = cast(tuple[str, ...], args[-1])
            return [
                Availability(resource_id, resource_id in {"desk-099", "desk-100"}, ())
                for resource_id in resource_ids
            ]

    controller = GatewayController(Spaces(), Bookings(), SimpleNamespace())

    resources = await controller.list_resources(
        _context(principal),
        availability_from=starts_at,
        availability_to=ends_at,
        offset=1,
        limit=1,
    )

    assert [resource.id for resource in resources] == ["desk-100"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("availability_from", "availability_to"),
    (
        (datetime(2026, 9, 2, 9, tzinfo=UTC), None),
        (None, datetime(2026, 9, 2, 11, tzinfo=UTC)),
        (datetime(2026, 9, 2, 9), datetime(2026, 9, 2, 11, tzinfo=UTC)),
    ),
)
async def test_resource_availability_filters_reject_partial_or_naive_intervals(
    availability_from: datetime | None, availability_to: datetime | None
) -> None:
    controller = GatewayController(
        SimpleNamespace(), SimpleNamespace(), SimpleNamespace()
    )
    principal = Principal("tenant-north", "employee-1", ("employee",))

    with pytest.raises(HttpException, match="Availability"):
        await controller.list_resources(
            _context(principal),
            availability_from=availability_from,
            availability_to=availability_to,
        )


@pytest.mark.asyncio
async def test_admin_update_forwards_trusted_identity_and_update() -> None:
    principal = Principal("tenant-north", "admin-1", ("facilities-admin",))
    update = UpdateResource(name="Quiet desk", capacity=4)
    calls: list[tuple[object, ...]] = []

    class Spaces:
        async def update_resource(self, *args: object) -> str:
            calls.append(args)
            return "updated"

    controller = GatewayController(Spaces(), SimpleNamespace(), SimpleNamespace())

    assert (
        await controller.update_resource("desk-17", update, _context(principal))
        == "updated"
    )
    assert calls == [(principal, "desk-17", update)]


@pytest.mark.asyncio
async def test_admin_deactivation_is_an_active_false_resource_update() -> None:
    principal = Principal("tenant-north", "admin-1", ("facilities-admin",))
    calls: list[tuple[object, ...]] = []

    class Spaces:
        async def update_resource(self, *args: object) -> str:
            calls.append(args)
            return "deactivated"

    controller = GatewayController(Spaces(), SimpleNamespace(), SimpleNamespace())

    assert (
        await controller.deactivate_resource("desk-17", _context(principal))
        == "deactivated"
    )
    assert calls == [(principal, "desk-17", UpdateResource(active=False))]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ("update_resource", "deactivate_resource"))
async def test_employees_cannot_update_or_deactivate_resources(method: str) -> None:
    principal = Principal("tenant-north", "employee-1", ("employee",))
    calls: list[tuple[object, ...]] = []

    class Spaces:
        async def update_resource(self, *args: object) -> None:
            calls.append(args)

    controller = GatewayController(Spaces(), SimpleNamespace(), SimpleNamespace())

    with pytest.raises(HttpException, match="Facilities administrator"):
        if method == "update_resource":
            await controller.update_resource(
                "desk-17", UpdateResource(name="Forbidden"), _context(principal)
            )
        else:
            await controller.deactivate_resource("desk-17", _context(principal))

    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ("reschedule_booking", "create_recurring_booking"))
async def test_booking_extension_routes_require_an_idempotency_key(method: str) -> None:
    principal = Principal("tenant-north", "employee-1", ("employee",))
    bookings = SimpleNamespace()
    controller = GatewayController(SimpleNamespace(), bookings, SimpleNamespace())
    starts_at = datetime(2026, 9, 2, 9, tzinfo=UTC)

    with pytest.raises(HttpException, match="Idempotency-Key is required"):
        if method == "reschedule_booking":
            await controller.reschedule_booking(
                "booking-1",
                RescheduleBookingRequest(starts_at, starts_at + timedelta(hours=2)),
                _context(principal),
            )
        else:
            await controller.create_recurring_booking(
                CreateRecurringBookingRequest(
                    "desk-17", starts_at, starts_at + timedelta(hours=2), "weekly", 3
                ),
                _context(principal),
            )


@pytest.mark.asyncio
async def test_booking_extension_routes_forward_trusted_request() -> None:
    principal = Principal("tenant-north", "employee-1", ("employee",))
    starts_at = datetime(2026, 9, 2, 9, tzinfo=UTC)
    reschedule = RescheduleBookingRequest(starts_at, starts_at + timedelta(hours=2))
    recurring = CreateRecurringBookingRequest(
        "desk-17", starts_at, starts_at + timedelta(hours=2), "weekly", 3
    )
    calls: list[tuple[str, tuple[object, ...]]] = []

    class Bookings:
        async def reschedule_booking(self, *args: object) -> str:
            calls.append(("reschedule", args))
            return "rescheduled"

        async def create_recurring_booking(self, *args: object) -> list[str]:
            calls.append(("recurring", args))
            return ["recurring"]

    controller = GatewayController(SimpleNamespace(), Bookings(), SimpleNamespace())
    context = _context(principal, idempotency_key="extension-request-1")

    assert (
        await controller.reschedule_booking("booking-1", reschedule, context)
        == "rescheduled"
    )
    assert await controller.create_recurring_booking(recurring, context) == [
        "recurring"
    ]
    assert calls == [
        (
            "reschedule",
            (
                principal,
                "booking-1",
                reschedule.starts_at,
                reschedule.ends_at,
                "extension-request-1",
            ),
        ),
        (
            "recurring",
            (
                principal,
                recurring.resource_id,
                recurring.starts_at,
                recurring.ends_at,
                recurring.recurrence,
                recurring.occurrence_count,
                "extension-request-1",
            ),
        ),
    ]


@pytest.mark.asyncio
async def test_resource_pagination_and_office_policy_routes_are_forwarded() -> None:
    principal = Principal("tenant-north", "admin-1", ("facilities-admin",))
    policy_update = OfficePolicyUpdate(
        "Europe/London", "08:00", "18:00", (0, 1, 2, 3, 4)
    )
    calls: list[tuple[str, tuple[object, ...]]] = []

    class Spaces:
        async def list_resources(self, *args: object) -> list[Resource]:
            calls.append(("list", args))
            return []

        async def get_office_policy(self, *args: object) -> OfficePolicy:
            calls.append(("get-policy", args))
            return OfficePolicy("office-north", "UTC", "08:00", "18:00", (0,))

        async def update_office_policy(self, *args: object) -> OfficePolicy:
            calls.append(("update-policy", args))
            return OfficePolicy("office-north", "Europe/London", "08:00", "18:00", (0,))

    controller = GatewayController(Spaces(), SimpleNamespace(), SimpleNamespace())
    context = _context(principal)

    await controller.list_resources(context, offset=20, limit=10)
    with pytest.raises(HttpException, match="outside the supported range"):
        await controller.list_resources(context, offset=10_001)
    await controller.get_office_policy("office-north", context)
    await controller.update_office_policy("office-north", policy_update, context)

    assert calls == [
        ("list", (principal, None, None, None, (), None, False, 20, 10)),
        ("get-policy", (principal, "office-north")),
        ("update-policy", (principal, "office-north", policy_update)),
    ]


@pytest.mark.asyncio
async def test_scoped_cancellation_requires_idempotency_and_forwards_scope() -> None:
    principal = Principal("tenant-north", "employee-1", ("employee",))
    calls: list[tuple[object, ...]] = []

    class Bookings:
        async def cancel_booking(self, *args: object) -> list[str]:
            calls.append(args)
            return ["cancelled"]

    controller = GatewayController(SimpleNamespace(), Bookings(), SimpleNamespace())
    with pytest.raises(HttpException, match="Idempotency-Key is required"):
        await controller.cancel_booking(
            "booking-1", CancelBookingRequest("entire-series"), _context(principal)
        )

    result = await controller.cancel_booking(
        "booking-1",
        CancelBookingRequest("this-and-following"),
        _context(principal, idempotency_key="cancel-1"),
    )

    assert result == ["cancelled"]
    assert calls == [(principal, "booking-1", "this-and-following", "cancel-1")]


@pytest.mark.asyncio
async def test_bookings_controller_rejects_inactive_resources() -> None:
    principal = Principal("tenant-north", "employee-1", ("employee",))
    commands = SimpleNamespace()
    spaces = SimpleNamespace()
    dispatched: list[bool] = []

    async def get_resource(*args: object) -> Resource:
        assert args == (principal, "desk-17")
        return _resource("desk-17", active=False)

    spaces.get_resource = get_resource

    async def execute(command: object) -> None:
        assert isinstance(command, CreateBookingCommand)
        dispatched.append(command.resource_active)
        raise BookingConflict("resource is inactive")

    commands.execute = execute
    controller = BookingsController(
        commands,
        SimpleNamespace(),
        SimpleNamespace(),
        spaces,
        SimpleNamespace(),
        SimpleNamespace(),
    )
    payload = CreateBooking(
        principal,
        "desk-17",
        datetime(2026, 9, 2, 9, tzinfo=UTC),
        datetime(2026, 9, 2, 11, tzinfo=UTC),
        "booking-request-1",
    )

    with pytest.raises(PublicRpcError, match="resource is inactive"):
        await controller.create_booking(payload)
    assert dispatched == [False]


@pytest.mark.asyncio
async def test_bookings_controller_rejects_rescheduling_an_inactive_resource() -> None:
    principal = Principal("tenant-north", "employee-1", ("employee",))
    starts_at = datetime(2026, 9, 2, 9, tzinfo=UTC)
    commands = SimpleNamespace()
    queries = SimpleNamespace()
    spaces = SimpleNamespace()
    dispatched: list[bool] = []

    async def execute_query(*args: object) -> Booking:
        return Booking(
            "booking-1",
            principal.tenant_id,
            principal.actor_id,
            "desk-17",
            starts_at,
            starts_at + timedelta(hours=2),
            "booked",
            "create-1",
        )

    async def get_resource(*args: object) -> Resource:
        assert args == (principal, "desk-17")
        return _resource("desk-17", active=False)

    queries.execute = execute_query
    spaces.get_resource = get_resource

    async def execute(command: object) -> None:
        assert isinstance(command, RescheduleBookingCommand)
        dispatched.append(command.resource_active)
        raise BookingConflict("resource is inactive")

    commands.execute = execute
    controller = BookingsController(
        commands,
        queries,
        SimpleNamespace(),
        spaces,
        SimpleNamespace(),
        SimpleNamespace(),
    )

    with pytest.raises(PublicRpcError, match="resource is inactive"):
        await controller.reschedule_booking(
            RescheduleBooking(
                principal,
                "booking-1",
                starts_at + timedelta(days=1),
                starts_at + timedelta(days=1, hours=2),
                "reschedule-1",
            )
        )
    assert dispatched == [False]


@pytest.mark.asyncio
async def test_bookings_controller_reports_inactive_resource_as_unavailable() -> None:
    principal = Principal("tenant-north", "employee-1", ("employee",))
    starts_at = datetime(2026, 9, 2, 9, tzinfo=UTC)
    queries = SimpleNamespace()
    spaces = SimpleNamespace()

    async def execute_query(*args: object) -> None:
        raise AssertionError("inactive resource must not reach booking availability")

    async def get_resource(*args: object) -> Resource:
        assert args == (principal, "desk-17")
        return _resource("desk-17", active=False)

    queries.execute = execute_query
    spaces.get_resource = get_resource
    controller = BookingsController(
        SimpleNamespace(),
        queries,
        SimpleNamespace(),
        spaces,
        SimpleNamespace(),
        SimpleNamespace(),
    )

    result = await controller.availability(
        AvailabilityQuery(
            principal,
            starts_at,
            starts_at + timedelta(hours=2),
            "desk-17",
        )
    )

    assert result == [Availability("desk-17", False, ())]


@pytest.mark.asyncio
async def test_bookings_controller_reports_inactive_batch_resource_as_unavailable() -> (
    None
):
    principal = Principal("tenant-north", "employee-1", ("employee",))
    starts_at = datetime(2026, 9, 2, 9, tzinfo=UTC)
    queries = SimpleNamespace()
    spaces = SimpleNamespace()

    async def execute_query(*args: object) -> list[Availability]:
        return [
            Availability("desk-active", True, ()),
            Availability("desk-inactive", True, ()),
        ]

    async def get_resources(*args: object) -> list[Resource]:
        assert args == (principal, ("desk-active", "desk-inactive"))
        return [
            _resource("desk-active"),
            _resource("desk-inactive", active=False),
        ]

    async def get_office_policy(*args: object) -> OfficePolicy:
        return OfficePolicy("office-north", "UTC", "08:00", "18:00", (0, 1, 2, 3, 4))

    queries.execute = execute_query
    spaces.get_resources = get_resources
    spaces.get_office_policy = get_office_policy
    controller = BookingsController(
        SimpleNamespace(),
        queries,
        SimpleNamespace(),
        spaces,
        SimpleNamespace(),
        SimpleNamespace(),
    )

    result = await controller.availability(
        AvailabilityQuery(
            principal,
            starts_at,
            starts_at + timedelta(hours=1),
            resource_ids=("desk-active", "desk-inactive"),
        )
    )

    assert result == [
        Availability("desk-active", True, ()),
        Availability("desk-inactive", False, ()),
    ]


@pytest.mark.asyncio
async def test_bookings_controller_reports_closed_office_as_unavailable() -> None:
    principal = Principal("tenant-north", "employee-1", ("employee",))
    starts_at = datetime(2026, 9, 7, 7, tzinfo=UTC)
    queries = SimpleNamespace()
    spaces = SimpleNamespace()

    async def execute_query(*args: object) -> list[Availability]:
        return [Availability("desk-17", True, ())]

    async def get_resource(*args: object) -> Resource:
        return _resource("desk-17")

    async def get_office_policy(*args: object) -> OfficePolicy:
        return OfficePolicy(
            "office-north", "Europe/London", "09:00", "17:00", (0, 1, 2, 3, 4)
        )

    queries.execute = execute_query
    spaces.get_resource = get_resource
    spaces.get_office_policy = get_office_policy
    controller = BookingsController(
        SimpleNamespace(),
        queries,
        SimpleNamespace(),
        spaces,
        SimpleNamespace(),
        SimpleNamespace(),
    )

    result = await controller.availability(
        AvailabilityQuery(
            principal,
            starts_at,
            starts_at + timedelta(hours=1),
            "desk-17",
        )
    )

    assert result == [Availability("desk-17", False, ())]

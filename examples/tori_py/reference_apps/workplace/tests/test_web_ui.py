"""Browser contract checks for the no-build workplace desk."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.skipif(
    not os.getenv("WORKPLACE_E2E_URL"),
    reason="set WORKPLACE_E2E_URL to a running workplace gateway",
)


def test_admin_calendar_and_retry_idempotency_are_responsive(page: Page) -> None:
    base_url = os.environ["WORKPLACE_E2E_URL"].rstrip("/")
    start = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=1)
    monday = start.date() - timedelta(days=start.weekday())
    overnight_start = datetime.combine(monday, datetime.min.time(), UTC) + timedelta(
        hours=23
    )
    booking_attempts: list[str] = []
    cleanup_requests: list[dict[str, str]] = []

    page.route(
        "**/assets/keycloak.js",
        lambda route: route.fulfill(
            content_type="text/javascript",
            body="""
                export default class Keycloak {
                  constructor() {
                    this.token = "test-token";
                    this.tokenParsed = {
                      preferred_username: "north.admin",
                      tenant_id: "tenant-north",
                    };
                    this.resourceAccess = {
                      "tori-space-web": {roles: ["facilities-admin"]},
                    };
                  }
                  async init() { return true; }
                  async updateToken() { return false; }
                  logout() {}
                }
            """,
        ),
    )

    def api(route: Route) -> None:
        request = route.request
        path = request.url.split("/api/", 1)[1]
        if path.startswith("resources"):
            route.fulfill(
                json=[
                    {
                        "id": "desk-17",
                        "name": "Desk 17",
                        "kind": "desk",
                        "office_id": "building-n",
                        "floor_id": "level-03",
                    }
                ]
            )
        elif path.startswith("availability?"):
            route.fulfill(
                json=[
                    {
                        "resource_id": "desk-17",
                        "available": True,
                        "conflicting_booking_ids": [],
                    }
                ]
            )
        elif path == "bookings" and request.method == "POST":
            booking_attempts.append(request.headers["idempotency-key"])
            if len(booking_attempts) < 3:
                route.fulfill(status=503, json={"detail": "retry later"})
            else:
                route.fulfill(
                    status=201,
                    json={
                        "id": "booking-1",
                        "resource_id": "desk-17",
                        "starts_at": start.isoformat(),
                        "ends_at": (start + timedelta(hours=1)).isoformat(),
                        "status": "booked",
                    },
                )
        elif path.startswith("bookings?"):
            route.fulfill(
                json=[
                    {
                        "id": "booking-overnight",
                        "resource_id": "desk-17",
                        "starts_at": overnight_start.isoformat(),
                        "ends_at": (overnight_start + timedelta(hours=2)).isoformat(),
                        "status": "booked",
                    }
                ]
            )
        elif path == "facilities/dashboard":
            route.fulfill(
                json={
                    "active_bookings": 1,
                    "no_shows": 0,
                    "outbox_pending": 0,
                    "outbox_dead_letter": 0,
                    "outbox_failures": 0,
                    "outbox_lag_seconds": None,
                }
            )
        elif path == "outbox/diagnostics":
            route.fulfill(
                json={
                    "pending": 0,
                    "dead_letter": 0,
                    "failures": 0,
                    "lag_seconds": None,
                }
            )
        elif path == "audit":
            route.fulfill(
                json=[
                    {
                        "id": "audit-1",
                        "tenant_id": "tenant-north",
                        "booking_id": "booking-1",
                        "resource_id": "desk-17",
                        "actor_id": "north.admin",
                        "action": "booking-created",
                        "from_status": None,
                        "to_status": "booked",
                        "occurred_at": start.isoformat(),
                    }
                ]
            )
        elif path == "offices/building-n/policy":
            route.fulfill(
                json={
                    "office_id": "building-n",
                    "time_zone": "UTC",
                    "opens_at": "00:00",
                    "closes_at": "23:59",
                    "weekdays": [0, 1, 2, 3, 4, 5, 6],
                }
            )
        elif path == "outbox/cleanup" and request.method == "POST":
            payload = request.post_data_json
            assert isinstance(payload, dict)
            cleanup_requests.append(payload)
            route.fulfill(json=2)
        else:
            route.fulfill(json=[])

    page.route("**/api/**", api)
    page.goto(f"{base_url}/web/")

    expect(page.locator("workplace-app")).to_have_count(1)
    assert (
        page.locator("workplace-app").evaluate("element => element.constructor.name")
        == "WorkplaceApp"
    )
    expect(page.locator("#identity-text")).to_contain_text("north.admin")
    expect(page.locator("#admin-panel")).to_be_visible()
    expect(page.locator("#dashboard-metrics")).to_contain_text("Active")
    expect(page.locator("#audit-log")).to_contain_text("booking-created")
    cleanup_before = "2026-08-01T12:30"
    page.on("dialog", lambda dialog: dialog.accept())
    page.locator("#outbox-cleanup-before").fill(cleanup_before)
    page.get_by_role("button", name="Clean delivered outbox records").click()
    expect(page.locator("#outbox-response")).to_contain_text("Removed 2")
    assert datetime.fromisoformat(
        cleanup_requests[0]["before"].replace("Z", "+00:00")
    ) == (datetime.fromisoformat(cleanup_before).astimezone(UTC))
    page.locator("#timezone").select_option("UTC")
    expect(page.locator(".calendar-entry")).to_have_count(2)

    page.get_by_role("button", name="Desk 17").last.click()
    page.locator("#starts-at").fill(start.astimezone().strftime("%Y-%m-%dT%H:%M"))
    page.locator("#ends-at").fill(
        (start + timedelta(hours=1)).astimezone().strftime("%Y-%m-%dT%H:%M")
    )
    page.get_by_role("button", name="Check availability").click()
    expect(page.locator("#resource-status")).to_have_text("Available for this interval")

    page.get_by_role("button", name="Mark this time").click()
    expect(page.locator("#booking-response")).to_contain_text("retry later")
    page.get_by_role("button", name="Mark this time").click()
    expect(page.locator("#booking-response")).to_contain_text("retry later")
    assert booking_attempts[0] == booking_attempts[1]

    page.locator("#ends-at").fill(
        (start + timedelta(hours=2)).astimezone().strftime("%Y-%m-%dT%H:%M")
    )
    page.get_by_role("button", name="Mark this time").click()
    expect(page.locator("#booking-response")).to_contain_text("accepted")
    assert booking_attempts[2] != booking_attempts[1]

    page.set_viewport_size({"width": 390, "height": 844})
    overflow: dict[str, Any] = page.evaluate(
        """() => ({
          documentWidth: document.documentElement.scrollWidth,
          viewportWidth: window.innerWidth,
        })"""
    )
    assert overflow["documentWidth"] <= overflow["viewportWidth"]


def test_resource_extensions_use_filters_and_idempotent_booking_operations(
    page: Page,
) -> None:
    base_url = os.environ["WORKPLACE_E2E_URL"].rstrip("/")
    start = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=2)
    end = start + timedelta(hours=1)
    resource_queries: list[dict[str, list[str]]] = []
    recurring_keys: list[str] = []
    reschedule_keys: list[str] = []
    resource_changes: list[tuple[str, str, dict[str, Any] | None]] = []
    policy_changes: list[dict[str, Any]] = []
    cancellation_requests: list[tuple[str, dict[str, Any]]] = []

    page.route(
        "**/assets/keycloak.js",
        lambda route: route.fulfill(
            content_type="text/javascript",
            body="""
                export default class Keycloak {
                  constructor() {
                    this.token = "test-token";
                    this.tokenParsed = {
                      preferred_username: "north.admin", tenant_id: "tenant-north",
                    };
                    this.resourceAccess = {
                      "tori-space-web": {roles: ["facilities-admin"]},
                    };
                  }
                  async init() { return true; }
                  async updateToken() { return false; }
                  logout() {}
                }
            """,
        ),
    )

    def api(route: Route) -> None:
        request = route.request
        path = request.url.split("/api/", 1)[1]
        if path.startswith("resources") and request.method == "GET":
            resource_queries.append(parse_qs(urlsplit(request.url).query))
            route.fulfill(
                json=[
                    {
                        "id": "desk-17",
                        "name": "Desk 17",
                        "kind": "desk",
                        "office_id": "building-n",
                        "floor_id": "level-03",
                        "x": 160,
                        "y": 580,
                        "equipment": ["monitor", "power"],
                        "capacity": 1,
                        "active": True,
                    },
                    {
                        "id": "room-03",
                        "name": "Meet 03",
                        "kind": "room",
                        "office_id": "building-n",
                        "floor_id": "level-03",
                        "x": 710,
                        "y": 240,
                        "equipment": ["screen", "whiteboard"],
                        "capacity": 8,
                        "active": False,
                    },
                ]
            )
        elif path == "bookings/recurring" and request.method == "POST":
            recurring_keys.append(request.headers["idempotency-key"])
            if len(recurring_keys) == 1:
                route.fulfill(status=503, json={"detail": "retry later"})
            else:
                route.fulfill(status=201, json=[])
        elif path == "bookings/booking-1/reschedule" and request.method == "POST":
            reschedule_keys.append(request.headers["idempotency-key"])
            if len(reschedule_keys) == 1:
                route.fulfill(status=503, json={"detail": "retry later"})
            else:
                route.fulfill(json={"id": "booking-1"})
        elif path == "bookings/booking-1/cancel" and request.method == "POST":
            payload = request.post_data_json
            assert isinstance(payload, dict)
            cancellation_requests.append((request.headers["idempotency-key"], payload))
            route.fulfill(json=[{"id": "booking-1", "status": "cancelled"}])
        elif path == "offices/building-n/policy" and request.method == "PATCH":
            payload = request.post_data_json
            assert isinstance(payload, dict)
            policy_changes.append(payload)
            route.fulfill(json={"office_id": "building-n", **payload})
        elif path == "offices/building-n/policy":
            route.fulfill(
                json={
                    "office_id": "building-n",
                    "time_zone": "UTC",
                    "opens_at": "08:00",
                    "closes_at": "18:00",
                    "weekdays": [0, 1, 2, 3, 4],
                }
            )
        elif path.startswith("resources/") and request.method in {"PATCH", "DELETE"}:
            payload = request.post_data_json if request.method == "PATCH" else None
            resource_changes.append((request.method, path, payload))
            route.fulfill(json={"id": path.rsplit("/", 1)[1], "name": "Desk 17"})
        elif path.startswith("bookings?"):
            route.fulfill(
                json=[
                    {
                        "id": "booking-1",
                        "resource_id": "desk-17",
                        "starts_at": start.isoformat(),
                        "ends_at": end.isoformat(),
                        "status": "booked",
                        "series_id": "series-1",
                        "occurrence_index": 1,
                    }
                ]
            )
        elif path.startswith("availability?"):
            route.fulfill(json=[])
        elif path in {"facilities/dashboard", "outbox/diagnostics"}:
            route.fulfill(json={})
        elif path == "audit":
            route.fulfill(json=[])
        else:
            route.fulfill(json=[])

    page.route("**/api/**", api)
    page.goto(f"{base_url}/web/")
    expect(page.locator("#resource-list")).to_contain_text("Desk 17")
    expect(page.locator("#floorplan [data-id='room-03']")).to_be_hidden()

    page.locator("#resource-office-filter").fill("building-n")
    page.locator("#resource-floor-filter").fill("level-03")
    page.locator("#resource-kind-filter").select_option("desk")
    page.locator("#resource-equipment-filter").fill("monitor, power")
    page.locator("#resource-min-capacity-filter").fill("1")
    page.locator("#availability-from-filter").fill(
        start.astimezone().strftime("%Y-%m-%dT%H:%M")
    )
    page.locator("#availability-to-filter").fill(
        end.astimezone().strftime("%Y-%m-%dT%H:%M")
    )
    page.get_by_role("button", name="Apply resource filters").click()
    expect(page.locator("#resource-list")).to_contain_text("monitor")
    query = resource_queries[-1]
    assert query["office_id"] == ["building-n"]
    assert query["floor_id"] == ["level-03"]
    assert query["kind"] == ["desk"]
    assert query["equipment"] == ["monitor", "power"]
    assert query["min_capacity"] == ["1"]
    assert query["offset"] == ["0"]
    assert query["limit"] == ["20"]
    assert "availability_from" in query and "availability_to" in query

    page.get_by_role("button", name="Clear resource filters").click()
    expect(page.locator("#resource-office-filter")).to_have_value("")
    assert resource_queries[-1] == {
        "include_inactive": ["true"],
        "offset": ["0"],
        "limit": ["20"],
    }
    page.get_by_role("button", name="Meet 03", exact=True).click()
    expect(page.locator("#resource-status")).to_have_text(
        "Inactive resources cannot be booked"
    )
    expect(page.locator("#booking-submit")).to_be_disabled()

    page.get_by_role("button", name="Desk 17").last.click()
    page.locator("#starts-at").fill(start.astimezone().strftime("%Y-%m-%dT%H:%M"))
    page.locator("#ends-at").fill(end.astimezone().strftime("%Y-%m-%dT%H:%M"))
    page.locator("#recurrence").select_option("weekly")
    page.locator("#recurrence-count").fill("2")
    page.get_by_role("button", name="Book recurring time").click()
    expect(page.locator("#booking-response")).to_contain_text("retry later")
    page.get_by_role("button", name="Book recurring time").click()
    assert recurring_keys[0] == recurring_keys[1]

    page.get_by_role("button", name="Reschedule").click()
    reschedule_start = (
        (start + timedelta(days=1)).astimezone().strftime("%Y-%m-%dT%H:%M")
    )
    reschedule_end = (end + timedelta(days=1)).astimezone().strftime("%Y-%m-%dT%H:%M")
    page.locator("#reschedule-starts-at").fill(reschedule_start)
    page.locator("#reschedule-ends-at").fill(reschedule_end)
    page.get_by_role("button", name="Save reschedule").click()
    expect(page.locator("#bookings-response")).to_contain_text("retry later")
    page.get_by_role("button", name="Save reschedule").click()
    assert reschedule_keys[0] == reschedule_keys[1]

    page.on("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Cancel entire series").click()
    assert cancellation_requests[0][1] == {"scope": "entire-series"}
    assert cancellation_requests[0][0]

    page.locator("#office-policy-form input[name='opens_at']").fill("09:00")
    page.get_by_role("button", name="Save office policy").click()
    expect(page.locator("#office-policy-response")).to_contain_text("updated")
    assert policy_changes[0]["opens_at"] == "09:00"

    page.locator("#resource-edit-name-desk-17").fill("Desk 17A")
    page.get_by_role("button", name="Save Desk 17").click()
    expect(page.locator("#resource-response")).to_contain_text("updated")
    page.get_by_role("button", name="Deactivate Desk 17").click()
    expect(page.locator("#resource-response")).to_contain_text("deactivated")
    page.get_by_role("button", name="Reactivate Meet 03").click()
    expect(page.locator("#resource-response")).to_contain_text("reactivated")
    assert (
        "PATCH",
        "resources/desk-17",
        {
            "name": "Desk 17A",
            "office_id": "building-n",
            "floor_id": "level-03",
            "kind": "desk",
            "x": 160,
            "y": 580,
            "equipment": ["monitor", "power"],
            "capacity": 1,
        },
    ) in resource_changes
    assert ("DELETE", "resources/desk-17", None) in resource_changes
    assert ("PATCH", "resources/room-03", {"active": True}) in resource_changes

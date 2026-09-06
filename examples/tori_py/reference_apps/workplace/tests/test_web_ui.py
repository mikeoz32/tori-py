"""Browser contract checks for the no-build workplace desk."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.skipif(
    not os.getenv("WORKPLACE_E2E_URL"),
    reason="set WORKPLACE_E2E_URL to a running workplace gateway",
)


def test_facilities_uses_a_separate_role_gated_application(page: Page) -> None:
    base_url = os.environ["WORKPLACE_E2E_URL"].rstrip("/")
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
        path = route.request.url.split("/api/", 1)[1]
        if path.startswith("resources"):
            query = parse_qs(urlsplit(route.request.url).query)
            offset = int(query.get("offset", ["0"])[0])
            count = 20 if offset == 0 else 1
            route.fulfill(
                json=[
                    {
                        "id": f"space-{offset + index + 1}",
                        "name": f"Space {offset + index + 1}",
                        "kind": "desk",
                        "office_id": "building-n",
                        "floor_id": "level-03",
                        "x": 160,
                        "y": 580,
                        "capacity": 1,
                        "equipment": ["monitor"],
                        "active": True,
                    }
                    for index in range(count)
                ]
            )
        elif path == "facilities/dashboard":
            route.fulfill(
                json={
                    "active_bookings": 8,
                    "no_shows": 2,
                    "outbox_pending": 3,
                    "outbox_dead_letter": 1,
                    "outbox_failures": 1,
                    "outbox_lag_seconds": 12,
                }
            )
        elif path == "outbox/diagnostics":
            route.fulfill(
                json={"pending": 3, "dead_letter": 1, "failures": 1, "lag_seconds": 12}
            )
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
        else:
            route.fulfill(json=[])

    page.route("**/api/**", api)
    page.goto(f"{base_url}/live/facilities")

    expect(page.locator("facilities-app")).to_have_count(1)
    expect(page.locator("workplace-app")).to_have_count(0)
    assert (
        page.locator("facilities-app").evaluate("element => element.constructor.name")
        == "FacilitiesApp"
    )
    expect(page.locator("#facilities-navigation")).to_be_visible()
    expect(page.get_by_role("button", name="Overview", exact=True)).to_have_attribute(
        "aria-current", "page"
    )
    expect(page.locator("#facilities-overview")).to_contain_text("Needs attention")
    expect(page.locator("#facilities-overview")).to_contain_text("2 no-shows")
    expect(page.get_by_role("button", name="Reserve space")).to_have_count(0)

    page.get_by_role("button", name="Spaces", exact=True).click()
    expect(page.locator("#facilities-spaces")).to_be_visible()
    expect(page.get_by_role("button", name="Next resources")).to_be_enabled()
    page.get_by_role("button", name="Next resources").click()
    expect(page.get_by_label("Facilities resource pages")).to_contain_text("Page 2")
    expect(page.locator("#facilities-spaces")).to_contain_text("Space 21")
    page.get_by_role("button", name="Policies", exact=True).click()
    expect(page.locator("#facilities-policies")).to_be_visible()
    page.get_by_role("button", name="Audit", exact=True).click()
    expect(page.locator("#facilities-audit")).to_be_visible()
    page.get_by_role("button", name="System health", exact=True).click()
    expect(page.locator("#facilities-system")).to_be_visible()
    expect(page.locator("#outbox-metrics")).to_contain_text("Dead letter")

    admin_state: dict[str, Any] = page.locator("facilities-app").evaluate(
        """async (app) => {
          const requests = [];
          app.api.request = (path) => new Promise((resolve) => {
            requests.push({path, resolve});
          });
          const response = (path, marker) => {
            if (path === "/api/facilities/dashboard") {
              return {active_bookings: marker};
            }
            if (path === "/api/audit") return [{id: marker}];
            if (path.startsWith("/api/offices/")) {
              return {office_id: "building-n", time_zone: "UTC", weekdays: []};
            }
            return {pending: marker};
          };
          const older = app.loadAdmin();
          const newer = app.loadAdmin();
          requests.slice(4).forEach(({path, resolve}) => resolve(response(path, 2)));
          await newer;
          requests.slice(0, 4).forEach(({path, resolve}) => resolve(response(path, 1)));
          await older;
          return {
            activeBookings: app.dashboard.active_bookings,
            pending: app.diagnostics.pending,
            auditId: app.auditEntries[0].id,
            loading: app.adminLoading,
          };
        }"""
    )
    assert admin_state == {
        "activeBookings": 2,
        "pending": 2,
        "auditId": 2,
        "loading": False,
    }

    policy_state: dict[str, Any] = page.locator("facilities-app").evaluate(
        """async (app) => {
          let resolveOlderPolicy;
          let policyCalls = 0;
          app.api.request = (path) => {
            if (path.startsWith("/api/offices/")) {
              policyCalls += 1;
              if (policyCalls === 1) {
                return new Promise((resolve) => { resolveOlderPolicy = resolve; });
              }
              return Promise.resolve({
                office_id: "building-n", time_zone: "UTC", opens_at: "10:00",
                closes_at: "18:00", weekdays: [],
              });
            }
            if (path === "/api/audit") return Promise.resolve([]);
            return Promise.resolve({});
          };
          const olderPolicy = app.loadAdminOfficePolicy();
          const overview = app.loadAdmin();
          await overview;
          resolveOlderPolicy({
            office_id: "building-n", time_zone: "UTC", opens_at: "08:00",
            closes_at: "18:00", weekdays: [],
          });
          await olderPolicy;
          return {
            opensAt: app.officePolicy.opens_at,
            busy: app.officePolicyBusy,
          };
        }"""
    )
    assert policy_state == {"opensAt": "10:00", "busy": False}


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
    page.goto(f"{base_url}/live/workplace")

    expect(page.locator(".liveview-bridge")).to_have_attribute(
        "data-live-state", "connected"
    )
    expect(page.locator("workplace-app")).to_have_count(1)
    assert (
        page.locator("workplace-app").evaluate("element => element.constructor.name")
        == "WorkplaceApp"
    )
    page.locator("workplace-app").evaluate(
        "element => { window.workplaceLitInstance = element; }"
    )
    page.locator(".live-diagnostics > summary").click()
    page.get_by_role("button", name="Check LiveView bridge").click()
    expect(page.locator("#liveview-bridge-checks")).to_have_text("Patch 1")
    assert page.evaluate(
        "window.workplaceLitInstance === document.querySelector('workplace-app')"
    )
    expect(page.locator("#identity-text")).to_contain_text("north.admin")
    expect(page.locator("#workspace-navigation")).to_be_visible()
    expect(page.get_by_role("button", name="Reserve space")).to_have_attribute(
        "aria-current", "page"
    )

    page.get_by_role("button", name="Desk 17").last.click()
    expect(page.locator(".inspector")).not_to_have_attribute("aria-live", "polite")
    expect(page.locator("#resource-status")).to_have_attribute("role", "status")
    page.locator("#starts-at").fill(start.astimezone().strftime("%Y-%m-%dT%H:%M"))
    page.locator("#ends-at").fill(
        (start + timedelta(hours=1)).astimezone().strftime("%Y-%m-%dT%H:%M")
    )
    page.get_by_role("button", name="Recheck availability").click()
    expect(page.locator("#resource-status")).to_have_text("Available for this interval")

    page.get_by_role("button", name="Reserve this time").click()
    expect(page.locator("#booking-response")).to_contain_text("retry later")
    page.get_by_role("button", name="Reserve this time").click()
    expect(page.locator("#booking-response")).to_contain_text("retry later")
    assert booking_attempts[0] == booking_attempts[1]

    page.locator("#ends-at").fill(
        (start + timedelta(hours=2)).astimezone().strftime("%Y-%m-%dT%H:%M")
    )
    page.get_by_role("button", name="Reserve this time").click()
    expect(page.locator("#booking-response")).to_contain_text("accepted")
    assert booking_attempts[2] != booking_attempts[1]

    page.get_by_role("button", name="My schedule").click()
    expect(page.get_by_role("button", name="My schedule")).to_have_attribute(
        "aria-current", "page"
    )
    expect(page.locator("#schedule-workspace")).to_be_visible()
    page.locator("#timezone").select_option("UTC")
    expect(page.locator(".calendar-entry")).to_have_count(2)
    expect(page.locator(".calendar-entry").first).to_contain_text("Desk 17")

    page.goto(f"{base_url}/live/facilities")
    expect(page.locator("facilities-app")).to_be_visible()
    expect(page.locator("#admin-panel")).to_be_visible()
    expect(page.locator("#dashboard-metrics")).to_contain_text("Active")
    page.get_by_role("button", name="Audit", exact=True).click()
    expect(page.locator("#audit-log")).to_contain_text("booking-created")
    page.get_by_role("button", name="System health", exact=True).click()
    cleanup_before = "2026-08-01T12:30"
    page.on("dialog", lambda dialog: dialog.accept())
    page.locator(".maintenance-panel > summary").click()
    page.locator("#outbox-cleanup-before").fill(cleanup_before)
    page.get_by_role("button", name="Clean delivered outbox records").click()
    expect(page.locator("#outbox-response")).to_contain_text("Removed 2")
    assert datetime.fromisoformat(
        cleanup_requests[0]["before"].replace("Z", "+00:00")
    ) == (datetime.fromisoformat(cleanup_before).astimezone(UTC))

    page.set_viewport_size({"width": 390, "height": 844})
    overflow: dict[str, Any] = page.evaluate(
        """() => ({
          documentWidth: document.documentElement.scrollWidth,
          viewportWidth: window.innerWidth,
        })"""
    )
    assert overflow["documentWidth"] <= overflow["viewportWidth"]
    page.set_viewport_size({"width": 320, "height": 720})
    overflow = page.evaluate(
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
    past_start = start - timedelta(days=7)
    past_end = end - timedelta(days=7)
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
                    },
                    {
                        "id": "booking-past",
                        "resource_id": "desk-17",
                        "starts_at": past_start.isoformat(),
                        "ends_at": past_end.isoformat(),
                        "status": "booked",
                    },
                    {
                        "id": "booking-cancelled",
                        "resource_id": "desk-17",
                        "starts_at": past_start.isoformat(),
                        "ends_at": past_end.isoformat(),
                        "status": "cancelled",
                    },
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
    expect(page.get_by_role("button", name="Reserve space")).to_have_attribute(
        "aria-current", "page"
    )
    expect(page.locator(".availability-search")).to_be_visible()
    expect(
        page.locator(".resource-filters input[type='datetime-local']")
    ).to_have_count(0)
    expect(page.locator("#resource-list")).to_contain_text("Desk 17")
    expect(page.locator("#floorplan [data-id='room-03']")).to_be_hidden()

    page.locator(".filter-drawer > summary").click()
    page.locator("#resource-office-filter").fill("building-n")
    page.locator("#resource-floor-filter").fill("level-03")
    page.locator("#resource-kind-filter").select_option("desk")
    page.locator("#resource-equipment-filter").fill("monitor, power")
    page.locator("#resource-min-capacity-filter").fill("1")
    page.locator("#starts-at").fill(start.astimezone().strftime("%Y-%m-%dT%H:%M"))
    page.locator("#ends-at").fill(end.astimezone().strftime("%Y-%m-%dT%H:%M"))
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
    assert (
        resource_queries[-1].keys()
        == {
            "availability_from": ["value checked separately"],
            "availability_to": ["value checked separately"],
            "offset": ["0"],
            "limit": ["20"],
        }.keys()
    )
    page.get_by_role("button", name="Meet 03", exact=True).click()
    expect(page.locator("#resource-status")).to_have_text(
        "Inactive resources cannot be booked"
    )
    expect(page.locator("#booking-submit")).to_be_disabled()

    page.get_by_role("button", name="Desk 17").last.click()
    page.locator("#starts-at").fill(start.astimezone().strftime("%Y-%m-%dT%H:%M"))
    page.locator("#ends-at").fill(end.astimezone().strftime("%Y-%m-%dT%H:%M"))
    page.locator(".recurrence-panel summary").click()
    page.locator("#recurrence").select_option("weekly")
    page.locator("#recurrence-count").fill("2")
    page.get_by_role("button", name="Book recurring time").click()
    expect(page.locator("#booking-response")).to_contain_text("retry later")
    page.get_by_role("button", name="Book recurring time").click()
    assert recurring_keys[0] == recurring_keys[1]

    page.get_by_role("button", name="My schedule").click()
    expect(page.locator("#schedule-workspace")).to_be_visible()
    expect(page.locator(".booking-history summary")).to_contain_text("(2)")
    expect(page.locator(".booking-history .booking-actions button")).to_have_count(0)
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

    page.goto(f"{base_url}/live/facilities")
    expect(page.locator("facilities-app")).to_be_visible()
    page.get_by_role("button", name="Policies", exact=True).click()
    page.locator("#office-policy-form input[name='opens_at']").fill("09:00")
    page.get_by_role("button", name="Save office policy").click()
    expect(page.locator("#office-policy-response")).to_contain_text("updated")
    assert policy_changes[0]["opens_at"] == "09:00"

    page.get_by_role("button", name="Spaces", exact=True).click()
    desk_control = page.locator(".resource-control").filter(has_text="Desk 17")
    desk_control.locator("summary").click()
    page.locator("#resource-edit-name-desk-17").fill("Desk 17A")
    page.get_by_role("button", name="Save Desk 17").click()
    expect(page.locator("#resource-response")).to_contain_text("updated")
    page.get_by_role("button", name="Deactivate Desk 17").click()
    expect(page.locator("#resource-response")).to_contain_text("deactivated")
    room_control = page.locator(".resource-control").filter(has_text="Meet 03")
    room_control.locator("summary").click()
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


def test_latest_resource_and_availability_requests_own_the_view(page: Page) -> None:
    base_url = os.environ["WORKPLACE_E2E_URL"].rstrip("/")
    api_requests: list[str] = []
    page.route(
        "**/assets/keycloak.js",
        lambda route: route.fulfill(
            content_type="text/javascript",
            body="""
                export default class Keycloak {
                  constructor() {
                    this.token = "test-token";
                    this.tokenParsed = {
                      preferred_username: "north.employee",
                      tenant_id: "tenant-north",
                    };
                    this.resourceAccess = {};
                  }
                  async init() { return true; }
                  async updateToken() { return false; }
                  logout() {}
                }
            """,
        ),
    )

    def empty_api(route: Route) -> None:
        path = route.request.url.split("/api/", 1)[1]
        api_requests.append(path)
        if path == "offices/building-n/policy":
            route.fulfill(
                json={
                    "office_id": "building-n",
                    "time_zone": "UTC",
                    "opens_at": "08:00",
                    "closes_at": "18:00",
                    "weekdays": [0, 1, 2, 3, 4],
                }
            )
        else:
            route.fulfill(json=[])

    page.route("**/api/**", empty_api)
    page.clock.set_fixed_time(datetime(2026, 9, 6, 21, 45, tzinfo=UTC))
    page.goto(f"{base_url}/web/")
    policy_interval: list[str] = page.evaluate(
        """async () => {
          const {nextPolicyInterval} = await import("/web/calendar.js");
          const interval = nextPolicyInterval({
            time_zone: "UTC",
            opens_at: "08:00",
            closes_at: "18:00",
            weekdays: [0, 1, 2, 3, 4],
          }, new Date("2026-09-06T21:45:00Z"));
          return [interval.startsAt.toISOString(), interval.endsAt.toISOString()];
        }"""
    )
    assert policy_interval == ["2026-09-07T08:00:00.000Z", "2026-09-07T09:00:00.000Z"]
    expect(page.locator("#api-status")).to_have_text("GATEWAY LINKED")
    resource_query = parse_qs(
        urlsplit(
            next(path for path in api_requests if path.startswith("resources?"))
        ).query
    )
    assert resource_query["availability_from"] == ["2026-09-07T08:00:00.000Z"]
    assert resource_query["availability_to"] == ["2026-09-07T09:00:00.000Z"]
    expect(page.locator("[data-workspace='facilities']")).to_have_count(0)
    expect(page.locator("#facilities-workspace")).to_have_count(0)

    page.locator("workplace-app").evaluate(
        """async (app) => {
          app.resources = [{
            id: "desk-a", name: "Desk A", kind: "desk", office_id: "north",
            floor_id: "one", x: 100, y: 100, active: true,
          }];
          await app.updateComplete;
        }"""
    )
    page.set_viewport_size({"width": 320, "height": 720})
    expect(page.get_by_role("button", name="List view")).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(page.locator(".results-list")).to_be_visible()
    expect(page.locator(".results-map")).to_be_hidden()
    page.locator(".results-list button[aria-label='Desk A']").click()
    expect(page.locator(".results-list .resource-item.selected")).to_have_count(1)
    page.get_by_role("button", name="Map view").click()
    expect(page.get_by_role("button", name="Map view")).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(page.locator(".results-map")).to_be_visible()
    expect(page.locator(".results-list")).to_be_hidden()
    expect(page.locator(".results-map [data-id='desk-a']")).to_have_class(
        re.compile(r"\bselected\b")
    )

    resource_ids: list[str] = page.locator("workplace-app").evaluate(
        """async (app) => {
          const resolvers = [];
          app.api.request = (path) => {
            if (!path.startsWith("/api/resources")) return Promise.resolve([]);
            return new Promise((resolve) => resolvers.push(resolve));
          };
          const older = app.loadResources();
          const newer = app.loadResources();
          resolvers[1]([{id: "newer", name: "Newer result", active: true}]);
          await newer;
          resolvers[0]([{id: "older", name: "Older result", active: true}]);
          await older;
          await app.updateComplete;
          return app.resources.map((resource) => resource.id);
        }"""
    )
    assert resource_ids == ["newer"]

    availability_state: dict[str, Any] = page.locator("workplace-app").evaluate(
        """async (app) => {
          const first = {
            id: "desk-a", name: "Desk A", office_id: "north", active: true,
          };
          const second = {
            id: "desk-b", name: "Desk B", office_id: "north", active: true,
          };
          app.resources = [first, second];
          app.selectResource(first);
          app.bookingStarts = "2026-09-03T09:00";
          app.bookingEnds = "2026-09-03T10:00";
          let resolveAvailability;
          app.api.request = (path) => {
            if (path.startsWith("/api/availability")) {
              return new Promise((resolve) => { resolveAvailability = resolve; });
            }
            return Promise.resolve({
              opens_at: "08:00", closes_at: "18:00", time_zone: "UTC",
            });
          };
          const pending = app.checkAvailability();
          app.selectResource(second);
          resolveAvailability([
            {resource_id: "desk-a", available: true, conflicting_booking_ids: []},
          ]);
          await pending;
          await app.updateComplete;
          return {
            selected: app.selected.id,
            availability: app.availability,
            busy: app.availabilityBusy,
          };
        }"""
    )
    assert availability_state == {
        "selected": "desk-b",
        "availability": None,
        "busy": False,
    }

    request_count = len(api_requests)
    page.goto(f"{base_url}/live/facilities")
    expect(page.locator(".access-denied")).to_contain_text(
        "Facilities administrator role required"
    )
    expect(page.locator("#admin-panel")).to_have_count(0)
    expect(page.get_by_role("button", name="Overview", exact=True)).to_be_disabled()
    assert len(api_requests) == request_count

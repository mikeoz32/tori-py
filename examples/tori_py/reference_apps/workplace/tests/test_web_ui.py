"""Browser contract checks for the no-build workplace desk."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

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
        if path == "resources":
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

"""End-to-end local smoke using Keycloak Authorization Code + PKCE."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime, timedelta
from datetime import time as clock_time
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen
from zoneinfo import ZoneInfo

GATEWAY = "http://localhost:8010"
KEYCLOAK = "http://localhost:8080"
REALM = "tori-space"
CLIENT_ID = "tori-space-web"
REDIRECT_URI = f"{GATEWAY}/web/"


class _LoginForm(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None
        self.fields: dict[str, str] = {}
        self._inside = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form" and attributes.get("id") == "kc-form-login":
            self.action = attributes.get("action")
            self._inside = True
        elif tag == "input" and self._inside:
            name = attributes.get("name")
            if name:
                self.fields[name] = attributes.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._inside:
            self._inside = False


def _login(username: str, password: str) -> str:
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    authorization_url = (
        f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/auth?"
        + urlencode(
            {
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "scope": "openid",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )
    cookies = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookies))
    with opener.open(authorization_url) as response:
        parser = _LoginForm()
        parser.feed(response.read().decode())
    if parser.action is None:
        raise RuntimeError("Keycloak login form was not found")

    parser.fields.update({"username": username, "password": password})
    request = Request(
        urljoin(authorization_url, parser.action),
        data=urlencode(parser.fields).encode(),
        headers={"Cookie": "; ".join(f"{c.name}={c.value}" for c in cookies)},
        method="POST",
    )
    try:
        with opener.open(request) as response:
            final_url = response.geturl()
            final_body = response.read().decode()
            code = parse_qs(urlparse(final_url).query).get("code", [None])[0]
    except HTTPError as error:
        detail = error.read().decode()
        raise RuntimeError(
            f"Keycloak login returned {error.code}; action={parser.action}: {detail}"
        ) from error
    if code is None:
        raise RuntimeError(
            f"Keycloak did not return an authorization code for {username}; "
            f"url={final_url}; response={final_body[:500]}"
        )

    token_request = Request(
        f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/token",
        data=urlencode(
            {
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "code": code,
                "code_verifier": verifier,
            }
        ).encode(),
        method="POST",
    )
    with urlopen(token_request) as response:  # noqa: S310 - fixed local demo URL
        return json.load(response)["access_token"]


def _api(
    token: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    method: str | None = None,
) -> Any:
    request_headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        **(headers or {}),
    }
    data = None
    request_method = method or "GET"
    if body is not None:
        data = json.dumps(body).encode()
        request_headers["Content-Type"] = "application/json"
        request_method = method or "POST"
    request = Request(
        f"{GATEWAY}{path}", data=data, headers=request_headers, method=request_method
    )
    try:
        with urlopen(request) as response:  # noqa: S310 - fixed local demo URL
            return json.load(response)
    except HTTPError as error:
        detail = error.read().decode()
        raise RuntimeError(
            f"{request_method} {path} returned {error.code}: {detail}"
        ) from error


def _booking_slots(
    policy: dict[str, Any],
) -> tuple[datetime, datetime, datetime, timedelta]:
    zone = ZoneInfo(policy["time_zone"])
    opens_hour, opens_minute = map(int, policy["opens_at"].split(":"))
    closes_hour, closes_minute = map(int, policy["closes_at"].split(":"))
    opens = opens_hour * 60 + opens_minute
    closes = closes_hour * 60 + closes_minute
    duration_minutes = max(1, min(60, (closes - opens) // 3))
    start_minute = opens + duration_minutes
    now = datetime.now(UTC)
    local_today = now.astimezone(zone).date()
    weekdays = set(policy["weekdays"])
    for offset in range(15):
        candidate_date = local_today + timedelta(days=offset)
        if candidate_date.weekday() not in weekdays:
            continue
        candidate = datetime.combine(
            candidate_date,
            clock_time(start_minute // 60, start_minute % 60),
            zone,
        ).astimezone(UTC)
        if candidate > now + timedelta(hours=1):
            rescheduled = datetime.combine(
                candidate_date + timedelta(days=7),
                clock_time(start_minute // 60, start_minute % 60),
                zone,
            ).astimezone(UTC)
            recurring = datetime.combine(
                candidate_date + timedelta(days=14),
                clock_time(start_minute // 60, start_minute % 60),
                zone,
            ).astimezone(UTC)
            return (
                candidate,
                rescheduled,
                recurring,
                timedelta(minutes=duration_minutes),
            )
    raise RuntimeError("office policy has no future smoke-test slot")


def smoke() -> None:
    north_token = _login("north.admin", "north-admin-demo-only")
    resources = _api(north_token, "/api/resources")
    if not resources:
        raise RuntimeError("north tenant has no seeded resources")

    policy_path = f"/api/offices/{resources[0]['office_id']}/policy"
    policy = _api(north_token, policy_path)
    updated_policy = _api(
        north_token,
        policy_path,
        body={
            "time_zone": policy["time_zone"],
            "opens_at": policy["opens_at"],
            "closes_at": policy["closes_at"],
            "weekdays": policy["weekdays"],
        },
        method="PATCH",
    )
    if updated_policy != policy:
        raise RuntimeError(f"office policy round trip failed: {updated_policy}")
    start, rescheduled_start, recurring_start, duration = _booking_slots(policy)
    filtered_query = urlencode(
        {
            "office_id": resources[0]["office_id"],
            "floor_id": resources[0]["floor_id"],
            "kind": resources[0]["kind"],
            "equipment": resources[0]["equipment"],
            "min_capacity": resources[0]["capacity"],
            "availability_from": start.isoformat(),
            "availability_to": (start + duration).isoformat(),
            "offset": 0,
            "limit": 20,
        },
        doseq=True,
    )
    filtered = _api(north_token, f"/api/resources?{filtered_query}")
    if resources[0]["id"] not in {resource["id"] for resource in filtered}:
        raise RuntimeError(
            f"resource filters excluded the matching resource: {filtered}"
        )

    managed = _api(
        north_token,
        "/api/resources",
        body={
            "office_id": "building-n",
            "floor_id": "level-03",
            "name": f"Smoke resource {secrets.token_hex(4)}",
            "kind": "room",
            "x": 90,
            "y": 90,
            "equipment": ["screen"],
            "capacity": 6,
        },
    )
    updated = _api(
        north_token,
        f"/api/resources/{managed['id']}",
        body={"name": f"{managed['name']} updated", "capacity": 8},
        method="PATCH",
    )
    if updated["capacity"] != 8:
        raise RuntimeError(f"resource update failed: {updated}")
    deactivated = _api(north_token, f"/api/resources/{managed['id']}", method="DELETE")
    if deactivated["active"]:
        raise RuntimeError("resource deactivation did not persist")
    if managed["id"] in {
        resource["id"] for resource in _api(north_token, "/api/resources")
    }:
        raise RuntimeError("inactive resource remained in the default listing")
    inactive = _api(north_token, "/api/resources?include_inactive=true")
    if not any(
        resource["id"] == managed["id"] and not resource["active"]
        for resource in inactive
    ):
        raise RuntimeError("inactive resource is unavailable to facilities admin")
    reactivated = _api(
        north_token,
        f"/api/resources/{managed['id']}",
        body={"active": True},
        method="PATCH",
    )
    if not reactivated["active"]:
        raise RuntimeError("resource reactivation did not persist")

    request_body = {
        "resource_id": resources[0]["id"],
        "starts_at": start.isoformat(),
        "ends_at": (start + duration).isoformat(),
    }
    interval_query = urlencode(
        {
            "resource_id": resources[0]["id"],
            "starts_at": request_body["starts_at"],
            "ends_at": request_body["ends_at"],
        }
    )
    available = _api(north_token, f"/api/availability?{interval_query}")
    if available != [
        {
            "resource_id": resources[0]["id"],
            "available": True,
            "conflicting_booking_ids": [],
        }
    ]:
        raise RuntimeError(f"unexpected initial availability: {available}")

    key = secrets.token_urlsafe(24)
    booking = _api(
        north_token,
        "/api/bookings",
        body=request_body,
        headers={"Idempotency-Key": key},
    )
    repeated = _api(
        north_token,
        "/api/bookings",
        body=request_body,
        headers={"Idempotency-Key": key},
    )
    if booking != repeated:
        raise RuntimeError("idempotent replay returned a different booking")

    unavailable = _api(north_token, f"/api/availability?{interval_query}")
    if unavailable[0]["available"] or unavailable[0]["conflicting_booking_ids"] != [
        booking["id"]
    ]:
        raise RuntimeError(f"booking did not update availability: {unavailable}")

    reschedule_body = {
        "starts_at": rescheduled_start.isoformat(),
        "ends_at": (rescheduled_start + duration).isoformat(),
    }
    reschedule_key = secrets.token_urlsafe(24)
    rescheduled = _api(
        north_token,
        f"/api/bookings/{booking['id']}/reschedule",
        body=reschedule_body,
        headers={"Idempotency-Key": reschedule_key},
    )
    repeated_reschedule = _api(
        north_token,
        f"/api/bookings/{booking['id']}/reschedule",
        body=reschedule_body,
        headers={"Idempotency-Key": reschedule_key},
    )
    if rescheduled != repeated_reschedule or rescheduled["id"] != booking["id"]:
        raise RuntimeError("idempotent reschedule did not preserve booking identity")

    recurring_body = {
        "resource_id": resources[0]["id"],
        "starts_at": recurring_start.isoformat(),
        "ends_at": (recurring_start + duration).isoformat(),
        "recurrence": "weekly",
        "occurrence_count": 2,
    }
    recurring_key = secrets.token_urlsafe(24)
    recurring = _api(
        north_token,
        "/api/bookings/recurring",
        body=recurring_body,
        headers={"Idempotency-Key": recurring_key},
    )
    repeated_recurring = _api(
        north_token,
        "/api/bookings/recurring",
        body=recurring_body,
        headers={"Idempotency-Key": recurring_key},
    )
    if recurring != repeated_recurring or len(recurring) != 2:
        raise RuntimeError("idempotent recurring booking replay failed")
    if len({item["series_id"] for item in recurring}) != 1 or [
        item["occurrence_index"] for item in recurring
    ] != [0, 1]:
        raise RuntimeError(f"recurring booking metadata is invalid: {recurring}")

    checked_in = _api(
        north_token, f"/api/bookings/{booking['id']}/check-in", method="POST"
    )
    if checked_in["status"] != "checked_in":
        raise RuntimeError("check-in lifecycle transition failed")
    cancelled = _api(
        north_token,
        f"/api/bookings/{booking['id']}/cancel",
        body={"scope": "one"},
        headers={"Idempotency-Key": secrets.token_urlsafe(24)},
    )
    if len(cancelled) != 1 or cancelled[0]["status"] != "cancelled":
        raise RuntimeError("cancellation lifecycle transition failed")
    cancelled_series = _api(
        north_token,
        f"/api/bookings/{recurring[1]['id']}/cancel",
        body={"scope": "entire-series"},
        headers={"Idempotency-Key": secrets.token_urlsafe(24)},
    )
    if len(cancelled_series) != 2 or any(
        item["status"] != "cancelled" for item in cancelled_series
    ):
        raise RuntimeError("scoped recurring cancellation failed")

    for _ in range(20):
        notifications = _api(north_token, "/api/notifications")
        booking_messages = [
            item["message"]
            for item in notifications
            if booking["id"] in item["message"]
        ]
        if len(booking_messages) >= 4:
            break
        time.sleep(0.25)
    else:
        raise RuntimeError("booking lifecycle notifications were not delivered")

    dashboard = _api(north_token, "/api/facilities/dashboard")
    if dashboard["active_bookings"] != 0 or dashboard["outbox_pending"] != 0:
        raise RuntimeError(f"unexpected facilities dashboard: {dashboard}")
    audit = _api(north_token, "/api/audit")
    actions = {row["action"] for row in audit if row["booking_id"] == booking["id"]}
    if actions != {
        "booking-created",
        "booking-rescheduled",
        "booking-checked-in",
        "booking-cancelled",
    }:
        raise RuntimeError(f"incomplete booking audit trail: {actions}")
    diagnostics = _api(north_token, "/api/outbox/diagnostics")
    if diagnostics["pending"] != 0 or diagnostics["dead_letter"] != 0:
        raise RuntimeError(f"unexpected outbox diagnostics: {diagnostics}")
    cleaned = _api(
        north_token,
        "/api/outbox/cleanup",
        body={"before": (datetime.now(UTC) + timedelta(minutes=1)).isoformat()},
    )
    if cleaned < 8:
        raise RuntimeError(f"expected delivered outbox cleanup, got {cleaned}")

    south_token = _login("south.employee", "south-employee-demo-only")
    if _api(south_token, "/api/bookings"):
        raise RuntimeError("south employee can see north tenant bookings")
    if _api(south_token, "/api/notifications"):
        raise RuntimeError("south employee can see north tenant notifications")
    print("workplace smoke passed")


if __name__ == "__main__":
    smoke()

"""End-to-end local smoke using Keycloak Authorization Code + PKCE."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

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
) -> Any:
    request_headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        **(headers or {}),
    }
    data = None
    method = "GET"
    if body is not None:
        data = json.dumps(body).encode()
        request_headers["Content-Type"] = "application/json"
        method = "POST"
    request = Request(
        f"{GATEWAY}{path}", data=data, headers=request_headers, method=method
    )
    try:
        with urlopen(request) as response:  # noqa: S310 - fixed local demo URL
            return json.load(response)
    except HTTPError as error:
        detail = error.read().decode()
        raise RuntimeError(
            f"{method} {path} returned {error.code}: {detail}"
        ) from error


def smoke() -> None:
    north_token = _login("north.admin", "north-admin-demo-only")
    resources = _api(north_token, "/api/resources")
    if not resources:
        raise RuntimeError("north tenant has no seeded resources")

    start = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=1)
    request_body = {
        "resource_id": resources[0]["id"],
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=1)).isoformat(),
    }
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

    for _ in range(20):
        notifications = _api(north_token, "/api/notifications")
        if any(booking["id"] in item["message"] for item in notifications):
            break
        time.sleep(0.25)
    else:
        raise RuntimeError("booking-created notification was not delivered")

    south_token = _login("south.employee", "south-employee-demo-only")
    if _api(south_token, "/api/bookings"):
        raise RuntimeError("south employee can see north tenant bookings")
    if _api(south_token, "/api/notifications"):
        raise RuntimeError("south employee can see north tenant notifications")
    print("workplace smoke passed")


if __name__ == "__main__":
    smoke()

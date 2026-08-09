"""Exercise the running Compose stack through the HTTP gateway."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import msgspec

from examples.nestpy.microservices_app.common.contracts import (
    CatalogItem,
    Notification,
    Order,
)

BASE_URL = "http://127.0.0.1:8000"


def call_gateway[ResponseT](
    path: str,
    response_type: type[ResponseT],
    body: object | None = None,
    headers: dict[str, str] | None = None,
) -> ResponseT:
    data = None if body is None else json.dumps(body).encode()
    method = "GET" if data is None else "POST"
    request_headers = {"content-type": "application/json"}
    request_headers.update(headers or {})
    request = Request(
        f"{BASE_URL}{path}",
        data=data,
        headers=request_headers,
        method=method,
    )
    with urlopen(request, timeout=10) as response:
        return msgspec.json.decode(response.read(), type=response_type)


def wait_until_ready() -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if call_gateway("/ready", dict[str, str]) == {"status": "ready"}:
                return
        except HTTPError, URLError, TimeoutError:
            pass
        time.sleep(0.5)
    raise SystemExit("gateway dependencies did not become ready")


def expect_gateway_error(
    path: str,
    status_code: int,
    body: object,
    headers: dict[str, str],
) -> None:
    try:
        call_gateway(path, dict[str, object], body, headers)
    except HTTPError as error:
        assert error.code == status_code
        return
    raise AssertionError(f"{path} did not return HTTP {status_code}")


def concurrently[ResponseT](call: Callable[[], ResponseT]) -> list[ResponseT]:
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(call) for _ in range(4)]
        return [future.result() for future in futures]


def main() -> None:
    wait_until_ready()
    suffix = str(time.time_ns())
    item_idempotency_key = f"smoke-item-{suffix}"
    items = concurrently(
        lambda: call_gateway(
            "/catalog/items",
            CatalogItem,
            {"name": f"Keyboard-{suffix}", "price_cents": 9900},
            headers={"idempotency-key": item_idempotency_key},
        )
    )
    item = items[0]
    assert items == [item] * 4
    expect_gateway_error(
        "/catalog/items",
        409,
        {"name": f"Keyboard-{suffix}", "price_cents": 12000},
        {"idempotency-key": item_idempotency_key},
    )
    idempotency_key = f"smoke-{suffix}"
    orders = concurrently(
        lambda: call_gateway(
            "/orders",
            Order,
            {"item_id": item.id, "quantity": 2},
            headers={"idempotency-key": idempotency_key},
        )
    )
    order = orders[0]
    assert orders == [order] * 4
    expect_gateway_error(
        "/orders",
        409,
        {"item_id": item.id, "quantity": 3},
        {"idempotency-key": idempotency_key},
    )
    assert call_gateway(f"/catalog/items/{item.id}", CatalogItem) == item
    assert call_gateway(f"/orders/{order.id}", Order) == order

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        notifications = call_gateway("/notifications", list[Notification])
        matching = [
            notification
            for notification in notifications
            if f"Order {order.id} created" in notification.message
        ]
        if matching:
            assert len(matching) == 1
            print(
                msgspec.json.encode(
                    {"item": item, "order": order, "notifications": notifications}
                ).decode()
            )
            return
        time.sleep(0.2)
    raise SystemExit("order-created notification was not observed")


if __name__ == "__main__":
    main()

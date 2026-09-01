"""Create the local demo's RabbitMQ application identities idempotently."""

from __future__ import annotations

import base64
import json
import os
import re
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

API = os.getenv("RABBITMQ_MANAGEMENT_URL", "http://rabbitmq:15672/api")
ADMIN_USER = os.getenv("RABBITMQ_ADMIN_USER", "rabbitmq_demo")
ADMIN_PASSWORD = os.getenv("RABBITMQ_ADMIN_PASSWORD", "rabbitmq-demo-only")
REPLY = r"reply\.[0-9a-f]{32}"
RPC = "tori_py.rpc"
DEAD_LETTER = "tori_py.dead-letter"


def _request(path: str, payload: object) -> None:
    token = base64.b64encode(f"{ADMIN_USER}:{ADMIN_PASSWORD}".encode()).decode()
    request = Request(
        f"{API}{path}",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        },
        method="PUT",
    )
    for attempt in range(30):
        try:
            with urlopen(  # noqa: S310 -- fixed Compose-local endpoint
                request, timeout=10
            ):
                return
        except HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise RuntimeError(f"RabbitMQ setup rejected {path}: {detail}") from error
        except OSError:
            if attempt == 29:
                raise
            time.sleep(1)


def _pattern(*names: str) -> str:
    return rf"^(?:{'|'.join(re.escape(name) for name in names)})$"


def _resource_pattern(*names: str, extra: tuple[str, ...] = ()) -> str:
    return rf"^(?:{'|'.join((*map(re.escape, names), *extra))})$"


def _set_permissions(user: str, *, configure: str, write: str, read: str) -> None:
    encoded_user = quote(user, safe="")
    _request(
        f"/permissions/%2F/{encoded_user}",
        {"configure": configure, "write": write, "read": read},
    )


def _set_topic_permissions(user: str, exchange: str, *, write: str, read: str) -> None:
    _request(
        f"/topic-permissions/%2F/{quote(user, safe='')}",
        {"exchange": exchange, "write": write, "read": read},
    )


def _add_user(name: str, password: str) -> None:
    _request(f"/users/{quote(name, safe='')}", {"password": password, "tags": ""})


def _add_exchange(name: str) -> None:
    _request(
        f"/exchanges/%2F/{quote(name, safe='')}",
        {
            "type": "topic",
            "durable": True,
            "auto_delete": False,
            "internal": False,
            "arguments": {},
        },
    )


def _rpc_service(name: str, *, outbound: str = "") -> None:
    queue = f"tori_py.rpc.workplace.{name}.v1"
    retry = f"{queue}.retry"
    client_resources = (REPLY,) if outbound else ()
    resources = _resource_pattern(
        RPC,
        DEAD_LETTER,
        queue,
        f"{queue}.retry",
        f"{queue}.dead-letter",
        extra=client_resources,
    )
    _set_permissions(
        f"{name}_demo",
        configure=resources,
        write=resources,
        read=resources,
    )
    _set_topic_permissions(
        f"{name}_demo",
        RPC,
        write=rf"^(?:{REPLY}|{outbound})$" if outbound else rf"^{REPLY}$",
        read=(
            rf"^(?:workplace\.{name}\.v1\..*|{REPLY})$"
            if outbound
            else rf"^workplace\.{name}\.v1\..*$"
        ),
    )
    _set_topic_permissions(
        f"{name}_demo",
        DEAD_LETTER,
        write=rf"^{re.escape(queue)}$",
        read=rf"^{re.escape(queue)}$",
    )
    _set_topic_permissions(
        f"{name}_demo",
        retry,
        write=rf"^workplace\.{name}\.v1\..*$",
        read=rf"^workplace\.{name}\.v1\..*$",
    )


def _notification_event_queue(event: str) -> str:
    return (
        f"tori_py.event.workplace.bookings.v1.{event}.v1"
        "--pool.workplace.notifications.v1.notification-workers"
    )


def main() -> None:
    passwords = {
        "gateway_demo": "gateway-demo-only",
        "spaces_demo": "spaces-demo-only",
        "bookings_demo": "bookings-demo-only",
        "notifications_demo": "notifications-demo-only",
    }
    for user, password in passwords.items():
        _add_user(user, password)

    events = (
        "booking-created",
        "booking-cancelled",
        "booking-checked-in",
        "booking-no-show",
        "booking-completed",
    )
    event_exchange = "tori_py.events.workplace.bookings.v1"
    event_queues = tuple(_notification_event_queue(event) for event in events)
    event_retries = tuple(f"{queue}.retry" for queue in event_queues)
    for exchange in (
        RPC,
        DEAD_LETTER,
        event_exchange,
        *(
            f"tori_py.rpc.workplace.{name}.v1.retry"
            for name in ("spaces", "bookings", "notifications")
        ),
        *event_retries,
    ):
        _add_exchange(exchange)

    _set_permissions(
        "gateway_demo",
        configure=rf"^(?:{re.escape(RPC)}|{REPLY})$",
        write=rf"^(?:{re.escape(RPC)}|{REPLY})$",
        read=rf"^(?:{re.escape(RPC)}|{REPLY})$",
    )
    _set_topic_permissions(
        "gateway_demo",
        RPC,
        write=r"^workplace\.(?:spaces|bookings|notifications)\.v1\..*$",
        read=rf"^{REPLY}$",
    )

    _rpc_service("spaces")
    _rpc_service("bookings", outbound=r"workplace\.spaces\.v1\..*")
    _rpc_service("notifications")

    event_routes = r"booking-(?:created|cancelled|checked-in|no-show|completed)\.v1"
    bookings_resources = _resource_pattern(
        RPC,
        DEAD_LETTER,
        "tori_py.rpc.workplace.bookings.v1",
        "tori_py.rpc.workplace.bookings.v1.retry",
        "tori_py.rpc.workplace.bookings.v1.dead-letter",
        event_exchange,
        extra=(REPLY,),
    )
    _set_permissions(
        "bookings_demo",
        configure=bookings_resources,
        write=bookings_resources,
        read=bookings_resources,
    )
    _set_topic_permissions(
        "bookings_demo", event_exchange, write=rf"^{event_routes}$", read=r"^$"
    )

    notification_resources = (
        r"^tori_py\.(?:rpc|dead-letter|events\.workplace\.bookings\.v1|"
        r"rpc\.workplace\.notifications\.v1(?:\..*)?|"
        r"event\.workplace\.bookings\.v1\..*--pool\.workplace\."
        r"notifications\.v1\.notification-workers(?:\..*)?)$"
    )
    _set_permissions(
        "notifications_demo",
        configure=notification_resources,
        write=notification_resources,
        read=notification_resources,
    )
    _set_topic_permissions(
        "notifications_demo", event_exchange, write=r"^$", read=rf"^{event_routes}$"
    )
    dead_letter_routes = (
        r"^(?:tori_py\.rpc\.workplace\.notifications\.v1|"
        r"tori_py\.event\.workplace\.bookings\.v1\..*--pool\.workplace\."
        r"notifications\.v1\.notification-workers)$"
    )
    _set_topic_permissions(
        "notifications_demo",
        DEAD_LETTER,
        write=dead_letter_routes,
        read=dead_letter_routes,
    )
    for retry in event_retries:
        _set_topic_permissions(
            "notifications_demo",
            retry,
            write=rf"^{event_routes}$",
            read=rf"^{event_routes}$",
        )


if __name__ == "__main__":
    main()

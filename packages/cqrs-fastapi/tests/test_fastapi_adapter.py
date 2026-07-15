import asyncio
import json
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any

import pytest
from cqrs_core import Command, CqrsBuilder, CqrsBuses, InMemoryTransport
from cqrs_fastapi import (
    FastAPIAdapter,
    FastAPIConfigurationError,
    FastAPIHandlerProvider,
    get_command_bus,
)
from cqrs_fastapi.profile import create_profile_app
from fastapi import FastAPI


def empty_buses() -> CqrsBuses:
    return (
        CqrsBuilder()
        .with_command_transport(InMemoryTransport(name="command-fixture"))
        .with_query_transport(InMemoryTransport(name="query-fixture"))
        .with_event_transport(InMemoryTransport(name="event-fixture"))
        .build()
    )


async def asgi_json(
    app: FastAPI,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    body = b"" if payload is None else json.dumps(payload).encode()
    received = False
    messages: list[MutableMapping[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("test", 50000),
        "server": ("test", 80),
    }
    await app(scope, receive, send)
    response = next(
        message for message in messages if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return response["status"], json.loads(response_body)


def test_uninitialized_dependency_helper_fails_clearly() -> None:
    app = FastAPI()
    request = {
        "type": "http",
        "app": app,
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "server": ("test", 80),
        "client": ("test", 50000),
        "scheme": "http",
        "http_version": "1.1",
    }

    from starlette.requests import Request

    with pytest.raises(FastAPIConfigurationError, match="not ready"):
        get_command_bus(Request(request))


@pytest.mark.asyncio
async def test_concurrent_first_access_builds_one_graph() -> None:
    calls = 0

    def factory() -> CqrsBuses:
        nonlocal calls
        calls += 1
        return empty_buses()

    app = FastAPI()
    adapter = FastAPIAdapter(factory)
    buses = await asyncio.gather(*(adapter.get_buses(app) for _ in range(10)))

    assert calls == 1
    assert all(bus is buses[0] for bus in buses)


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_all_transports() -> None:
    app = create_profile_app()

    async with app.router.lifespan_context(app):
        buses = app.state.cqrs_buses
        assert app.state.cqrs_ready is True
        assert buses.command_bus._lifecycle.transport.state.value == "running"
        assert buses.query_bus._lifecycle.transport.state.value == "running"
        assert buses.event_bus._lifecycle.transport.state.value == "running"

    assert app.state.cqrs_ready is False
    assert buses.command_bus._lifecycle.transport.state.value == "stopped"
    assert buses.query_bus._lifecycle.transport.state.value == "stopped"
    assert buses.event_bus._lifecycle.transport.state.value == "stopped"


@pytest.mark.asyncio
async def test_profile_routes_execute_command_query_and_drained_event() -> None:
    app = create_profile_app()

    async with app.router.lifespan_context(app):
        status, created = await asgi_json(
            app,
            "POST",
            "/profiles",
            {"username": "alice"},
        )
        assert status == 200
        profile_id = created["profile_id"]

        status, profile = await asgi_json(app, "GET", f"/profiles/{profile_id}")
        assert status == 200
        assert profile == {"id": profile_id, "username": "alice"}

        await asyncio.sleep(0)
        await app.state.cqrs_buses.event_bus.drain(timeout=1)
        assert app.state.profile_event_log == [profile_id]


@pytest.mark.asyncio
async def test_startup_failure_shuts_down_previously_started_buses() -> None:
    class FailingStartTransport(InMemoryTransport):
        async def start(self, consumer) -> None:
            raise RuntimeError("startup failure")

    command_transport = InMemoryTransport(name="started-command")
    query_transport = FailingStartTransport(name="failed-query")
    event_transport = InMemoryTransport(name="not-started-event")
    buses = (
        CqrsBuilder()
        .with_command_transport(command_transport)
        .with_query_transport(query_transport)
        .with_event_transport(event_transport)
        .build()
    )
    adapter = FastAPIAdapter(lambda: buses)
    app = FastAPI(lifespan=adapter.lifespan)

    with pytest.raises(RuntimeError, match="startup failure"):
        async with app.router.lifespan_context(app):
            pass

    assert command_transport.state.value == "stopped"
    assert query_transport.state.value == "stopped"
    assert event_transport.state.value == "stopped"


@pytest.mark.asyncio
async def test_partial_transport_start_is_cleaned_up_after_failure() -> None:
    class PartialStartTransport(InMemoryTransport):
        async def start(self, consumer) -> None:
            await super().start(consumer)
            raise RuntimeError("partial startup failure")

    command_transport = InMemoryTransport(name="partial-command")
    query_transport = PartialStartTransport(name="partial-query")
    event_transport = InMemoryTransport(name="partial-event")
    buses = (
        CqrsBuilder()
        .with_command_transport(command_transport)
        .with_query_transport(query_transport)
        .with_event_transport(event_transport)
        .build()
    )
    adapter = FastAPIAdapter(lambda: buses)
    app = FastAPI(lifespan=adapter.lifespan)

    with pytest.raises(RuntimeError, match="partial startup failure"):
        async with app.router.lifespan_context(app):
            pass

    assert query_transport.state.value == "stopped"
    assert query_transport._worker is not None
    assert query_transport._worker.done()


@pytest.mark.asyncio
async def test_provider_closes_dispatch_scoped_handler_after_execution() -> None:
    @dataclass(frozen=True, slots=True)
    class Ping(Command[int]):
        value: int

    class DisposableHandler:
        def __init__(self) -> None:
            self.closed = False

        async def handle(self, message: Ping) -> int:
            return message.value

        async def aclose(self) -> None:
            self.closed = True

    handler = DisposableHandler()
    provider = FastAPIHandlerProvider()
    builder = (
        CqrsBuilder()
        .add_command_handler_factory(Ping, lambda: handler)
        .with_command_transport(InMemoryTransport(name="provider-command"))
        .with_query_transport(InMemoryTransport(name="provider-query"))
        .with_event_transport(InMemoryTransport(name="provider-event"))
        .with_handler_provider(provider)
    )
    buses = builder.build()
    adapter = FastAPIAdapter(lambda: buses, provider=provider)
    app = FastAPI(lifespan=adapter.lifespan)

    async with app.router.lifespan_context(app):
        assert await buses.command_bus.execute(Ping(value=7)) == 7
        assert handler.closed is True


@pytest.mark.asyncio
async def test_provider_defers_slow_app_resource_cleanup() -> None:
    class SlowResource:
        def __init__(self) -> None:
            self.release = asyncio.Event()
            self.closed = False

        async def aclose(self) -> None:
            await self.release.wait()
            self.closed = True

    provider = FastAPIHandlerProvider()
    key = object()
    resource = SlowResource()
    provider.register_app_resource(key, resource)

    with pytest.raises(TimeoutError):
        await provider.close(timeout=0)
    assert resource.closed is False
    with pytest.raises(RuntimeError, match="closed"):
        provider.register_app_resource(object(), object())

    resource.release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert resource.closed is True

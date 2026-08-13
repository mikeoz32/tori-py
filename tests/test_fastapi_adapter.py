import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from tori_py_cqrs_core import Command, InMemoryTransport
from tori_py_cqrs_fastapi import (
    FastAPIAdapter,
    FastAPIConfigurationError,
    FastAPIHandlerProvider,
    get_command_bus,
)

from examples.profile_app import create_profile_app


async def asgi_json(
    app: FastAPI,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = (
            await client.request(method, path)
            if payload is None
            else await client.request(method, path, json=payload)
        )
    return response.status_code, response.json()


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
    app = FastAPI()
    adapter = FastAPIAdapter()
    buses = await asyncio.gather(*(adapter.get_buses(app) for _ in range(10)))

    assert all(bus is buses[0] for bus in buses)


@pytest.mark.asyncio
async def test_adapter_registers_factory_handlers() -> None:
    @dataclass(frozen=True, slots=True)
    class Ping(Command[int]):
        value: int

    class Handler:
        async def handle(self, message: Ping) -> int:
            return message.value

    adapter = FastAPIAdapter()

    @adapter.command_handler_factory(Ping)
    def make_handler() -> Handler:
        return Handler()

    app = FastAPI(lifespan=adapter.lifespan)
    async with app.router.lifespan_context(app):
        assert await app.state.cqrs_buses.command_bus.execute(Ping(9)) == 9


@pytest.mark.asyncio
async def test_registered_app_resource_is_available_for_constructor_injection() -> None:
    @dataclass(frozen=True, slots=True)
    class Ping(Command[int]):
        value: int

    class Dependency:
        multiplier = 3

    class Handler:
        def __init__(self, dependency: Dependency) -> None:
            self._dependency = dependency

        async def handle(self, message: Ping) -> int:
            return message.value * self._dependency.multiplier

    provider = FastAPIHandlerProvider()
    dependency = Dependency()
    provider.register_app_resource(Dependency, dependency)
    adapter = FastAPIAdapter(provider=provider)
    adapter.command_handler(Ping)(Handler)
    app = FastAPI(lifespan=adapter.lifespan)

    async with app.router.lifespan_context(app):
        assert await app.state.cqrs_buses.command_bus.execute(Ping(4)) == 12


@pytest.mark.asyncio
async def test_provider_construction_failure_is_returned_by_dispatch() -> None:
    @dataclass(frozen=True, slots=True)
    class Ping(Command[int]):
        value: int

    class BrokenHandler:
        def __init__(self) -> None:
            raise RuntimeError("construction failure")

        async def handle(self, message: Ping) -> int:
            return message.value

    provider = FastAPIHandlerProvider()
    adapter = FastAPIAdapter(provider=provider)
    adapter.command_handler(Ping)(BrokenHandler)
    app = FastAPI(lifespan=adapter.lifespan)

    async with app.router.lifespan_context(app):
        with pytest.raises(RuntimeError, match="construction failure"):
            await app.state.cqrs_buses.command_bus.execute(Ping(1))


@pytest.mark.asyncio
async def test_provider_cleanup_preserves_error_and_closes_remaining_resources() -> (
    None
):
    class Resource:
        def __init__(self, *, fails: bool) -> None:
            self.fails = fails
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True
            if self.fails:
                raise RuntimeError("resource cleanup failure")

    provider = FastAPIHandlerProvider()
    remaining = Resource(fails=False)
    failing = Resource(fails=True)
    provider.register_app_resource("remaining", remaining)
    provider.register_app_resource("failing", failing)

    with pytest.raises(RuntimeError, match="resource cleanup failure"):
        await provider.close()

    assert failing.closed is True
    assert remaining.closed is True


@pytest.mark.asyncio
async def test_lifespan_setup_failure_closes_provider_resources() -> None:
    class Resource:
        def __init__(self) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    provider = FastAPIHandlerProvider()
    resource = Resource()
    provider.register_app_resource("resource", resource)

    def fail_after_build(buses: object) -> None:
        del buses
        raise RuntimeError("setup failure")

    adapter = FastAPIAdapter(provider=provider, on_buses_built=fail_after_build)
    app = FastAPI(lifespan=adapter.lifespan)

    with pytest.raises(RuntimeError, match="setup failure"):
        async with app.router.lifespan_context(app):
            pass

    assert resource.closed is True


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

        deadline = asyncio.get_running_loop().time() + 1
        while not app.state.profile_event_log:
            if asyncio.get_running_loop().time() >= deadline:
                pytest.fail("profile event was not handled before timeout")
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
    adapter = FastAPIAdapter(
        command_transport=command_transport,
        query_transport=query_transport,
        event_transport=event_transport,
    )
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
    adapter = FastAPIAdapter(
        command_transport=command_transport,
        query_transport=query_transport,
        event_transport=event_transport,
    )
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
        latest = None

        def __init__(self) -> None:
            self.closed = False
            type(self).latest = self

        async def handle(self, message: Ping) -> int:
            return message.value

        async def aclose(self) -> None:
            self.closed = True

    provider = FastAPIHandlerProvider()
    adapter = FastAPIAdapter(
        command_transport=InMemoryTransport(name="provider-command"),
        query_transport=InMemoryTransport(name="provider-query"),
        event_transport=InMemoryTransport(name="provider-event"),
        provider=provider,
    )
    adapter.command_handler(Ping)(DisposableHandler)
    app = FastAPI(lifespan=adapter.lifespan)

    async with app.router.lifespan_context(app):
        buses = app.state.cqrs_buses
        assert await buses.command_bus.execute(Ping(value=7)) == 7
        assert DisposableHandler.latest is not None
        assert DisposableHandler.latest.closed is True


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


@pytest.mark.asyncio
async def test_provider_cancellation_defers_app_resource_cleanup() -> None:
    class SlowResource:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.closed = False

        async def aclose(self) -> None:
            self.started.set()
            await self.release.wait()
            self.closed = True

    provider = FastAPIHandlerProvider()
    resource = SlowResource()
    provider.register_app_resource(object(), resource)
    close_task = asyncio.create_task(provider.close())
    await resource.started.wait()

    close_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await close_task
    assert resource.closed is False

    resource.release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert resource.closed is True

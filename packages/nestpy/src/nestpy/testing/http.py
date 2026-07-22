"""Optional HTTPX client for production-equivalent Nestpy test applications."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from nestpy.application import NestApplication
from nestpy.core.errors import ApplicationStateError, BootstrapError
from nestpy.core.runtime import ApplicationState
from nestpy.testing.runtime import TestingApplication

if TYPE_CHECKING:
    import httpx


@asynccontextmanager
async def http_client(
    application: NestApplication | TestingApplication,
    *,
    base_url: str = "http://testserver",
    raise_app_exceptions: bool = False,
    client_address: tuple[str, int] = ("testclient", 50000),
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield an HTTPX client for an already-started Starlette application."""

    nest_application = (
        application.application
        if isinstance(application, TestingApplication)
        else application
    )
    if nest_application.state is not ApplicationState.STARTED:
        raise ApplicationStateError("HTTP test client requires a started application")
    try:
        import httpx
    except ModuleNotFoundError as error:
        if error.name != "httpx":
            raise
        raise BootstrapError(
            "HTTP testing requires the nestpy[testing] optional dependency",
            code="testing.httpx_unavailable",
        ) from error

    from nestpy.starlette import StarletteAdapter

    transport = httpx.ASGITransport(
        app=nest_application.get_adapter(StarletteAdapter).app,
        raise_app_exceptions=raise_app_exceptions,
        client=client_address,
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url=base_url,
    ) as client:
        yield client


__all__ = ["http_client"]

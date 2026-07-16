"""Starlette application factory, driver binder, and request-scope wrapper."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from nestpy.core.compiler import CompiledGraph, ModuleId, compile_graph
from nestpy.core.options import ApplicationOptions, StarletteOptions
from nestpy.core.runtime import ApplicationKernel, ApplicationState
from nestpy.logging import use_log_context
from nestpy.starlette.context import (
    RequestContext,
    _reset_context,
    _reset_scope,
    _set_context,
    _set_scope,
)
from nestpy.starlette.errors import (
    HttpException,
    method_not_allowed_handler,
    not_found_handler,
    problem_response,
    server_error_handler,
)
from nestpy.starlette.routes import build_starlette_routes, compile_routes

logger = logging.getLogger("nestpy.starlette")


class StarletteBinder:
    """Driver binder that creates routes only after the kernel is starting."""

    def __init__(
        self,
        graph: CompiledGraph,
        http_options: StarletteOptions,
    ) -> None:
        self.graph = graph
        self.http_options = http_options
        self.plans = compile_routes(graph)
        self.app: ASGIApp | None = None
        self._kernel: ApplicationKernel | None = None

    async def bind(self, kernel: ApplicationKernel) -> None:
        self._kernel = kernel
        application_id = graph_label(self.graph)
        routes = build_starlette_routes(
            self.plans,
            kernel,
            application_id=application_id,
            body_size_limit=self.http_options.body_size_limit,
        )
        starlette_app = Starlette(
            routes=routes,
            exception_handlers={
                HttpException: _http_exception_handler,
                404: not_found_handler,
                405: method_not_allowed_handler,
                Exception: server_error_handler,
            },
        )
        self.app = RequestScopeMiddleware(
            starlette_app,
            kernel,
            self.graph.root,
            application_id=application_id,
        )

    async def close(self) -> None:
        self.app = None
        self._kernel = None


class RequestScopeMiddleware:
    """Keep one request scope open until the complete ASGI response finishes."""

    def __init__(
        self,
        app: ASGIApp,
        kernel: ApplicationKernel,
        root_module: ModuleId,
        *,
        application_id: str,
    ) -> None:
        self.app = app
        self.kernel = kernel
        self.root_module = root_module
        self.application_id = application_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = request_id_from_scope(scope)
        scope["nestpy_request_id"] = request_id
        request_scope = self.kernel.request_scope(self.root_module)
        async with request_scope:
            scope_token = _set_scope(request_scope)
            request = Request(scope, receive)
            context_token = _set_context(
                RequestContext(
                    request=request,
                    scope=request_scope,
                    module_identity=self.root_module,
                    application=self.application_id,
                    route=None,
                    request_id_value=request_id,
                )
            )
            try:
                with use_log_context(
                    application=self.application_id,
                    request_id=request_id,
                    scope="request",
                ):
                    await self.app(scope, receive, send)
            finally:
                _reset_context(context_token)
                _reset_scope(scope_token)


class NestApplication:
    """Compiled, driver-bound application with explicit lifecycle control."""

    def __init__(self, kernel: ApplicationKernel, binder: StarletteBinder) -> None:
        self.kernel = kernel
        self.binder = binder

    @classmethod
    async def create(
        cls,
        root: type[object],
        *,
        options: ApplicationOptions | None = None,
        http: StarletteOptions | None = None,
    ) -> NestApplication:
        graph = await compile_graph(root)
        binder = StarletteBinder(graph, http or StarletteOptions())
        kernel = ApplicationKernel(graph, options=options, binder=binder)
        return cls(kernel, binder)

    @property
    def state(self) -> ApplicationState:
        return self.kernel.state

    @property
    def http_app(self) -> ASGIApp:
        if self.binder.app is None:
            raise RuntimeError("NestApplication has not started")
        return self.binder.app

    async def start(self) -> None:
        await self.kernel.start()

    async def shutdown(self) -> None:
        await self.kernel.shutdown()


class _ASGIState(StrEnum):
    CREATED = "created"
    STARTED = "started"
    STOPPED = "stopped"
    FAILED = "failed"


class ASGIApplication:
    """ASGI3 wrapper that owns one factory-created NestApplication."""

    def __init__(self, factory: Callable[[], Awaitable[NestApplication]]) -> None:
        self.factory = factory
        self.application: NestApplication | None = None
        self.state = _ASGIState.CREATED
        self._lock = asyncio.Lock()
        self._lifespan_seen = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
            return
        if scope["type"] == "http" and self.state is _ASGIState.STARTED:
            application = self.application
            if application is not None:
                await application.http_app(scope, receive, send)
                return
        if scope["type"] == "http":
            await _send_problem(send, 503, "Application is not ready.")
            return
        await _send_empty(send, 204)

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        message = await receive()
        if message["type"] != "lifespan.startup":
            await send(
                {
                    "type": "lifespan.startup.failed",
                    "message": "Expected lifespan.startup.",
                }
            )
            return
        async with self._lock:
            if self._lifespan_seen:
                await send(
                    {
                        "type": "lifespan.startup.failed",
                        "message": "Application lifespan cannot be restarted.",
                    }
                )
                return
            self._lifespan_seen = True
            try:
                result = self.factory()
                if not inspect.isawaitable(result):
                    raise TypeError("application factory must return an awaitable")
                application = await result
                if not isinstance(application, NestApplication):
                    raise TypeError("application factory must yield NestApplication")
                await application.start()
                self.application = application
                self.state = _ASGIState.STARTED
            except Exception as error:
                self.state = _ASGIState.FAILED
                await send(
                    {
                        "type": "lifespan.startup.failed",
                        "message": str(error),
                    }
                )
                return
            await send({"type": "lifespan.startup.complete"})
        shutdown = await receive()
        if shutdown["type"] != "lifespan.shutdown":
            return
        async with self._lock:
            try:
                if self.application is not None:
                    await self.application.shutdown()
                self.state = _ASGIState.STOPPED
            except Exception as error:
                self.state = _ASGIState.FAILED
                await send(
                    {
                        "type": "lifespan.shutdown.failed",
                        "message": str(error),
                    }
                )
                return
            await send({"type": "lifespan.shutdown.complete"})


def asgi(
    factory: Callable[[], Awaitable[NestApplication]],
) -> ASGIApplication:
    """Return an ASGI wrapper that starts the factory during lifespan startup."""

    return ASGIApplication(factory)


async def _http_exception_handler(request: Request, error: Exception):
    if not isinstance(error, HttpException):
        return await server_error_handler(request, error)
    return problem_response(
        error.status_code,
        error.detail,
        request=request,
        title=error.title,
        headers=error.headers,
    )


def request_id_from_scope(scope: Scope) -> str:
    values = [
        value for name, value in scope.get("headers", []) if name == b"x-request-id"
    ]
    if len(values) == 1:
        try:
            candidate = values[0].decode("ascii")
        except UnicodeDecodeError:
            candidate = ""
        if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", candidate):
            return candidate
    if values:
        logger.warning("Invalid or duplicate X-Request-ID replaced")
    uuid7 = getattr(uuid, "uuid7", uuid.uuid4)
    return str(uuid7())


async def _send_problem(send: Send, status_code: int, detail: str) -> None:
    response = problem_response(status_code, detail)
    await response({"type": "http", "method": "GET", "path": "/"}, _empty_receive, send)


async def _send_empty(send: Send, status_code: int) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [],
        }
    )
    await send({"type": "http.response.body", "body": b""})


async def _empty_receive() -> dict[str, Any]:
    return {"type": "http.disconnect"}


def graph_label(graph: CompiledGraph) -> str:
    return graph.root.module.__qualname__


__all__ = ["ASGIApplication", "NestApplication", "StarletteBinder", "asgi"]

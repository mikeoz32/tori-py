"""Starlette application factory, driver binder, and request-scope wrapper."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from enum import StrEnum
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import BaseRoute
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tori_py.application import (
    ApplicationAdapter,
    ApplicationBinder,
    ApplicationRuntime,
)
from tori_py.application import (
    NestApplication as _NestApplication,
)
from tori_py.core.compiler import CompiledGraph, ModuleId
from tori_py.core.errors import ApplicationStateError, BootstrapError
from tori_py.core.modules import ModuleSpec
from tori_py.core.options import PipelineOptions
from tori_py.core.providers import ProviderDeclaration
from tori_py.http._observability import log_http_emergency
from tori_py.http.errors import HttpException
from tori_py.http.pipeline import PipelineExecutor
from tori_py.http.routes import bind_routes, compile_routes
from tori_py.logging import use_log_context
from tori_py.starlette.context import (
    RequestContext,
    _reset_context,
    _set_context,
    current_request_context,
)
from tori_py.starlette.errors import problem_response
from tori_py.starlette.options import StarletteOptions
from tori_py.starlette.pipeline import StarlettePipelineAdapter
from tori_py.starlette.routes import build_starlette_routes, validate_context_bindings
from tori_py.starlette.websockets import (
    StarletteWebSocketPipelineAdapter,
    build_starlette_websocket_routes,
    validate_websocket_bindings,
)
from tori_py.websocket.pipeline import WebSocketPipelineExecutor
from tori_py.websocket.routes import bind_websocket_routes, compile_websocket_routes

logger = logging.getLogger("tori_py.starlette")


class _StarletteBinder:
    """Driver binder that creates routes only after the kernel is starting."""

    def __init__(
        self,
        graph: CompiledGraph,
        http_options: StarletteOptions,
        pipeline_options: PipelineOptions,
    ) -> None:
        self.graph = graph
        self.http_options = http_options
        self.plans = compile_routes(graph)
        validate_context_bindings(self.plans)
        self.websocket_plans = compile_websocket_routes(graph)
        validate_websocket_bindings(self.websocket_plans)
        self.pipeline = PipelineExecutor(
            graph,
            global_tokens=pipeline_options,
            transport=StarlettePipelineAdapter(),
        )
        self.plans = self.pipeline.qualify(self.plans)
        self.websocket_pipeline = WebSocketPipelineExecutor(
            graph,
            global_tokens=pipeline_options,
            transport=StarletteWebSocketPipelineAdapter(),
        )
        self.websocket_plans = self.websocket_pipeline.qualify(self.websocket_plans)
        self.app: ASGIApp | None = None

    def configure_pipeline(self, pipeline: PipelineOptions) -> None:
        if self.app is not None:
            raise ApplicationStateError(
                "Starlette pipeline cannot be configured after binding"
            )
        self.pipeline.configure_global(pipeline)
        self.websocket_pipeline.configure_global(pipeline)

    async def bind(self, runtime: ApplicationRuntime) -> None:
        application_id = graph_label(self.graph)
        plans = await bind_routes(self.plans, runtime.resolver)
        routes: list[BaseRoute] = list(
            build_starlette_routes(
                plans,
                self.pipeline,
                application_id=application_id,
                body_size_limit=self.http_options.body_size_limit,
            )
        )
        websocket_plans = await bind_websocket_routes(
            self.websocket_plans,
            runtime.resolver,
        )
        routes.extend(
            build_starlette_websocket_routes(
                websocket_plans,
                self.websocket_pipeline,
                runtime,
                application_id=application_id,
            )
        )
        starlette_app = Starlette(
            routes=routes,
            exception_handlers={
                HttpException: _pipeline_http_exception_handler(self.pipeline),
                404: _pipeline_status_handler(self.pipeline, 404),
                405: _pipeline_status_handler(self.pipeline, 405),
                Exception: _pipeline_exception_handler(self.pipeline),
            },
        )
        self.app = RequestScopeMiddleware(
            starlette_app,
            runtime,
            self.graph.root,
            application_id=application_id,
        )

    async def close(self) -> None:
        self.app = None


class StarletteAdapter(ApplicationAdapter):
    """Bind one driver-neutral application to Starlette HTTP and WebSockets."""

    def __init__(self, options: StarletteOptions | None = None) -> None:
        self.options = StarletteOptions() if options is None else options
        self._binder: _StarletteBinder | None = None

    def collect_fallback_providers(
        self,
        module_id: ModuleId,
        spec: ModuleSpec,
        is_root: bool,
        pipeline: PipelineOptions,
    ) -> tuple[ProviderDeclaration, ...]:
        del module_id, spec, is_root, pipeline
        return ()

    def create_binder(
        self,
        graph: CompiledGraph,
        pipeline: PipelineOptions,
    ) -> ApplicationBinder:
        if self._binder is not None:
            raise ApplicationStateError(
                "StarletteAdapter cannot be reused across applications"
            )
        self._binder = _StarletteBinder(graph, self.options, pipeline)
        return self._binder

    def configure_pipeline(self, pipeline: PipelineOptions) -> None:
        if self._binder is None:
            raise ApplicationStateError(
                "StarletteAdapter is not attached to an application"
            )
        self._binder.configure_pipeline(pipeline)

    @property
    def app(self) -> ASGIApp:
        if self._binder is None or self._binder.app is None:
            raise BootstrapError(
                "StarletteAdapter is not started",
                code="application.invalid_state",
            )
        return self._binder.app


class RequestScopeMiddleware:
    """Keep one request scope open until the complete ASGI response finishes."""

    def __init__(
        self,
        app: ASGIApp,
        runtime: ApplicationRuntime,
        root_module: ModuleId,
        *,
        application_id: str,
    ) -> None:
        self.app = app
        self.runtime = runtime
        self.root_module = root_module
        self.application_id = application_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = request_id_from_scope(scope)
        scope["tori_py_request_id"] = request_id
        request_scope = self.runtime.request_scope(self.root_module)
        context_token = None
        with use_log_context(
            application=self.application_id,
            request_id=request_id,
            scope="request",
        ):
            try:
                async with request_scope:
                    response_complete = asyncio.Event()
                    request_task = asyncio.current_task()
                    if request_task is None:
                        raise RuntimeError("HTTP handling requires an asyncio task")
                    disconnect_cancellation = object()
                    monitor: asyncio.Task[None] | None = None

                    async def monitor_disconnect() -> None:
                        while True:
                            message = await receive()
                            if message["type"] == "http.disconnect":
                                if (
                                    not response_complete.is_set()
                                    and request_task.cancelling() == 0
                                ):
                                    request_task.cancel(disconnect_cancellation)
                                return

                    async def direct_receive() -> Message:
                        nonlocal monitor
                        message = await receive()
                        if (
                            message["type"] == "http.request"
                            and not message.get("more_body", False)
                            and monitor is None
                        ):
                            # The body consumer is finished, so monitoring can take
                            # exclusive ownership of receive without prefetching.
                            monitor = asyncio.create_task(monitor_disconnect())
                        return message

                    request = Request(scope, direct_receive)
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
                    response_started = False

                    async def tracked_send(
                        message: MutableMapping[str, Any],
                    ) -> None:
                        nonlocal response_started
                        if message.get("type") == "http.response.start":
                            response_started = True
                            headers = [
                                (name, value)
                                for name, value in message.get("headers", [])
                                if name.lower() != b"x-request-id"
                            ]
                            headers.append(
                                (b"x-request-id", request_id.encode("ascii"))
                            )
                            message["headers"] = headers
                        elif message.get(
                            "type"
                        ) == "http.response.body" and not message.get(
                            "more_body", False
                        ):
                            response_complete.set()
                        await send(message)

                    try:
                        await self.app(scope, direct_receive, tracked_send)
                    except asyncio.CancelledError as error:
                        if (
                            len(error.args) == 1
                            and error.args[0] is disconnect_cancellation
                            and request_task.cancelling() == 1
                        ):
                            request_task.uncancel()
                        else:
                            raise
                    except Exception:
                        if response_started:
                            log_http_emergency(
                                logger,
                                "tori_py.http.response_transmission_failed",
                            )
                        raise
                    finally:
                        if monitor is not None:
                            monitor.cancel()
                            await asyncio.gather(monitor, return_exceptions=True)
            finally:
                if context_token is not None:
                    _reset_context(context_token)


class _ASGIState(StrEnum):
    CREATED = "created"
    STARTED = "started"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class ASGIApplication:
    """ASGI3 wrapper that owns one factory-created NestApplication."""

    def __init__(self, factory: Callable[[], Awaitable[_NestApplication]]) -> None:
        self.factory = factory
        self.application: _NestApplication | None = None
        self._http_app: ASGIApp | None = None
        self.state = _ASGIState.CREATED
        self._lock = asyncio.Lock()
        self._lifespan_seen = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
            return
        if scope["type"] in {"http", "websocket"} and self.state is _ASGIState.STARTED:
            http_app = self._http_app
            if http_app is not None:
                await http_app(scope, receive, send)
                return
        if scope["type"] == "http":
            await _send_problem(send, 503, "Application is not ready.", scope)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1013, "reason": ""})
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
                if not isinstance(application, _NestApplication):
                    raise TypeError("application factory must yield NestApplication")
                adapter = application.get_adapter(StarletteAdapter)
                await application.start()
                self.application = application
                self._http_app = adapter.app
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
            self.state = _ASGIState.STOPPING
            self._http_app = None
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
    factory: Callable[[], Awaitable[_NestApplication]],
) -> ASGIApplication:
    """Return an ASGI wrapper that starts the factory during lifespan startup."""

    return ASGIApplication(factory)


def _pipeline_http_exception_handler(pipeline: PipelineExecutor):
    async def handle(request: Request, error: Exception):
        if not isinstance(error, HttpException):
            return await _pipeline_exception_handler(pipeline)(request, error)
        return await _pipeline_error_response(pipeline, request, error)

    return handle


def _pipeline_status_handler(pipeline: PipelineExecutor, status_code: int):
    async def handle(request: Request, error: Exception):
        detail = (
            "The requested resource was not found."
            if status_code == 404
            else "The HTTP method is not allowed."
        )
        headers = getattr(error, "headers", None)
        return await _pipeline_error_response(
            pipeline,
            request,
            HttpException(status_code, detail, headers=headers),
        )

    return handle


def _pipeline_exception_handler(pipeline: PipelineExecutor):
    async def handle(request: Request, error: Exception):
        return await _pipeline_error_response(
            pipeline,
            request,
            error,
        )

    return handle


async def _pipeline_error_response(
    pipeline: PipelineExecutor,
    request: Request,
    error: Exception,
):
    context = current_request_context()
    if context is None:
        if isinstance(error, HttpException):
            return problem_response(error.status_code, error.detail, request=request)
        return problem_response(500, "Internal server error.", request=request)
    from tori_py.starlette.routes import _encode_pipeline_result

    async def encode(result: object):
        return await _encode_pipeline_result(result, 200, request)

    return await pipeline.handle_routing_error(
        error,
        context,
        context.scope,
        encode_result=encode,
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


async def _send_problem(
    send: Send,
    status_code: int,
    detail: str,
    scope: Scope,
) -> None:
    request_scope = dict(scope)
    request_scope["tori_py_request_id"] = request_id_from_scope(scope)
    request = Request(request_scope, _empty_receive)
    response = problem_response(status_code, detail, request=request)
    await response(request_scope, _empty_receive, send)


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


__all__ = ["ASGIApplication", "StarletteAdapter", "asgi"]

"""Native ASGI application adapter and lifecycle wrapper."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from enum import StrEnum
from typing import Any

from tori_py.application import (
    ApplicationAdapter,
    ApplicationBinder,
    ApplicationRuntime,
)
from tori_py.application import NestApplication as _NestApplication
from tori_py.asgi.context import (
    AsgiScope,
    Receive,
    RequestContext,
    _AsgiRequest,
    _reset_context,
    _set_context,
)
from tori_py.asgi.errors import problem_response
from tori_py.asgi.options import AsgiOptions
from tori_py.asgi.pipeline import AsgiPipelineAdapter
from tori_py.asgi.routes import (
    AsgiRouter,
    RouteMatch,
    _encode_pipeline_result,
    compile_endpoint,
    monitor_bodyless_handlers,
    validate_context_bindings,
)
from tori_py.core.compiler import CompiledGraph, ModuleId
from tori_py.core.errors import ApplicationStateError, BootstrapError
from tori_py.core.modules import ModuleSpec
from tori_py.core.options import PipelineOptions
from tori_py.core.providers import ProviderDeclaration
from tori_py.core.runtime import RequestScope
from tori_py.http._observability import log_http_emergency
from tori_py.http.endpoints import CompiledEndpoint
from tori_py.http.errors import HttpException
from tori_py.http.pipeline import PipelineExecutor
from tori_py.http.response import HttpResponse
from tori_py.http.routes import bind_routes, compile_routes
from tori_py.logging import use_log_context

type Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
type ASGIApp = Callable[[AsgiScope, Receive, Send], Awaitable[None]]

logger = logging.getLogger("tori_py.asgi")


class _AsgiBinder:
    def __init__(
        self,
        graph: CompiledGraph,
        http_options: AsgiOptions,
        pipeline_options: PipelineOptions,
    ) -> None:
        self.graph = graph
        self.http_options = http_options
        self.plans = compile_routes(graph)
        validate_context_bindings(self.plans)
        self.pipeline = PipelineExecutor(
            graph,
            global_tokens=pipeline_options,
            transport=AsgiPipelineAdapter(),
        )
        self.plans = self.pipeline.qualify(self.plans)
        self.app: ASGIApp | None = None

    def configure_pipeline(self, pipeline: PipelineOptions) -> None:
        if self.app is not None:
            raise ApplicationStateError(
                "native ASGI pipeline cannot be configured after binding"
            )
        self.pipeline.configure_global(pipeline)
        self.plans = self.pipeline.qualify(self.plans)

    async def bind(self, runtime: ApplicationRuntime) -> None:
        plans = await bind_routes(self.plans, runtime.resolver)
        plans = monitor_bodyless_handlers(plans)
        endpoints = tuple(
            compile_endpoint(
                plan,
                self.pipeline,
                body_size_limit=self.http_options.body_size_limit,
            )
            for plan in plans
        )
        self.app = _NativeHttpApplication(
            runtime,
            self.graph.root,
            endpoints,
            self.pipeline,
            application_id=_graph_label(self.graph),
            body_size_limit=self.http_options.body_size_limit,
        )

    async def close(self) -> None:
        self.app = None


class AsgiAdapter(ApplicationAdapter):
    """Bind one driver-neutral application directly to the ASGI HTTP protocol."""

    def __init__(self, options: AsgiOptions | None = None) -> None:
        self.options = AsgiOptions() if options is None else options
        self._binder: _AsgiBinder | None = None

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
                "AsgiAdapter cannot be reused across applications"
            )
        self._binder = _AsgiBinder(graph, self.options, pipeline)
        return self._binder

    def configure_pipeline(self, pipeline: PipelineOptions) -> None:
        if self._binder is None:
            raise ApplicationStateError("AsgiAdapter is not attached to an application")
        self._binder.configure_pipeline(pipeline)

    @property
    def app(self) -> ASGIApp:
        if self._binder is None or self._binder.app is None:
            raise BootstrapError(
                "AsgiAdapter is not started",
                code="application.invalid_state",
            )
        return self._binder.app


class _NativeHttpApplication:
    def __init__(
        self,
        runtime: ApplicationRuntime,
        root_module: ModuleId,
        endpoints: tuple[CompiledEndpoint[HttpResponse], ...],
        pipeline: PipelineExecutor,
        *,
        application_id: str,
        body_size_limit: int,
    ) -> None:
        self.runtime = runtime
        self.root_module = root_module
        self.router = AsgiRouter(endpoints)
        self.pipeline = pipeline
        self.application_id = application_id
        self.body_size_limit = body_size_limit

    async def __call__(self, scope: AsgiScope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1003, "reason": ""})
            return
        if scope["type"] != "http":
            raise RuntimeError("native ASGI adapter only supports HTTP scopes")
        await self._handle_http(scope, receive, send)

    async def _handle_http(
        self,
        scope: AsgiScope,
        receive: Receive,
        send: Send,
    ) -> None:
        request_id = request_id_from_scope(scope)
        request_scope = self.runtime.request_scope(self.root_module)
        baseline_context_token = _set_context(None)
        with use_log_context(
            application=self.application_id,
            request_id=request_id,
            scope="request",
        ):
            try:
                async with request_scope:
                    await self._dispatch(
                        scope,
                        receive,
                        send,
                        request_scope,
                        request_id,
                    )
            finally:
                _reset_context(baseline_context_token)

    async def _dispatch(
        self,
        scope: AsgiScope,
        receive: Receive,
        send: Send,
        request_scope: RequestScope,
        request_id: str,
    ) -> None:
        path = str(scope["path"])
        method = str(scope["method"])
        matched = self.router.match(path, method)
        request = _AsgiRequest(scope, receive, matched.path_params)
        plan = matched.plan
        context = RequestContext(
            request=request,
            scope=request_scope,
            module_identity=self.root_module if plan is None else plan.module_id,
            application=self.application_id,
            route=None if plan is None else plan.route_id,
            request_id_value=request_id,
        )
        context_token = _set_context(context)
        response_complete = asyncio.Event()
        request_task = asyncio.current_task()
        if request_task is None:
            raise RuntimeError("HTTP handling requires an asyncio task")
        disconnect_cancellation = object()
        monitor: asyncio.Task[None] | None = None
        monitor_start: asyncio.Handle | None = None

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

        async def direct_receive() -> MutableMapping[str, Any]:
            nonlocal monitor
            message = await receive()
            if (
                message["type"] == "http.request"
                and not message.get("more_body", False)
                and monitor is None
            ):
                monitor = asyncio.create_task(monitor_disconnect())
            return message

        request.receive = direct_receive

        def schedule_monitor() -> None:
            nonlocal monitor_start
            if monitor is not None or monitor_start is not None:
                return

            def start_monitor() -> None:
                nonlocal monitor
                if not response_complete.is_set():
                    monitor = asyncio.create_task(monitor_disconnect())

            # Avoid allocating a monitor task when the handler and send path do
            # not yield control before completing the response.
            monitor_start = asyncio.get_running_loop().call_soon(start_monitor)

        def stop_monitor() -> None:
            if monitor_start is not None:
                monitor_start.cancel()
            if monitor is not None:
                monitor.cancel()

        request.on_handler_end = stop_monitor
        request.on_handler_start = schedule_monitor
        try:
            try:
                response = await self._response_for_match(
                    matched,
                    request,
                    context,
                    request_scope,
                )
                await _send_response(
                    send,
                    response,
                    request_id,
                    omit_body=method == "HEAD",
                )
                response_complete.set()
            except asyncio.CancelledError as error:
                if (
                    len(error.args) == 1
                    and error.args[0] is disconnect_cancellation
                    and request_task.cancelling() == 1
                ):
                    request_task.uncancel()
                else:
                    raise
            except OSError:
                return
            except Exception:
                log_http_emergency(
                    logger,
                    "tori_py.http.response_transmission_failed",
                )
                raise
        finally:
            if monitor_start is not None:
                monitor_start.cancel()
            if monitor is not None:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
            _reset_context(context_token)

    async def _response_for_match(
        self,
        matched: RouteMatch,
        request: _AsgiRequest,
        context: RequestContext,
        request_scope: RequestScope,
    ) -> HttpResponse:
        if matched.redirect_path is not None:
            return HttpResponse(
                b"",
                status_code=307,
                headers={"location": matched.redirect_path},
            )
        endpoint = matched.endpoint
        if endpoint is not None:
            return await endpoint.execute(request, context, request_scope)
        if matched.allowed_methods:
            error = HttpException(
                405,
                "The HTTP method is not allowed.",
                headers={"allow": ", ".join(matched.allowed_methods)},
            )
        else:
            error = HttpException(404, "The requested resource was not found.")

        async def encode(result: object) -> HttpResponse:
            return _encode_pipeline_result(result, 200)

        response = await self.pipeline.handle_routing_error(
            error,
            context,
            request_scope,
            encode_result=encode,
        )
        if not isinstance(response, HttpResponse):
            raise RuntimeError("routing pipeline did not produce an HTTP response")
        return response


class _ASGIState(StrEnum):
    CREATED = "created"
    STARTED = "started"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class ASGIApplication:
    """ASGI3 wrapper that owns one native adapter application."""

    def __init__(self, factory: Callable[[], Awaitable[_NestApplication]]) -> None:
        self.factory = factory
        self.application: _NestApplication | None = None
        self._http_app: ASGIApp | None = None
        self.state = _ASGIState.CREATED
        self._lock = asyncio.Lock()
        self._lifespan_seen = False

    async def __call__(self, scope: AsgiScope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
            return
        if scope["type"] == "http" and self.state is _ASGIState.STARTED:
            http_app = self._http_app
            if http_app is not None:
                await http_app(scope, receive, send)
                return
        if scope["type"] == "http":
            await _send_response(
                send,
                problem_response(503, "Application is not ready."),
                request_id_from_scope(scope),
            )
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1003, "reason": ""})
            return
        raise RuntimeError("unsupported ASGI scope")

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
                adapter = application.get_adapter(AsgiAdapter)
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


def request_id_from_scope(scope: AsgiScope) -> str:
    values = [
        bytes(value)
        for name, value in scope.get("headers", [])
        if bytes(name).lower() == b"x-request-id"
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


async def _send_response(
    send: Send,
    response: HttpResponse,
    request_id: str,
    *,
    omit_body: bool = False,
) -> None:
    headers = [
        (name.encode("ascii"), value.encode("latin-1"))
        for name, value in response.headers.items()
        if name.casefold() != "x-request-id"
    ]
    if response.status_code not in {204, 304}:
        headers.append((b"content-length", str(len(response.content)).encode("ascii")))
    headers.append((b"x-request-id", request_id.encode("ascii")))
    await send(
        {
            "type": "http.response.start",
            "status": response.status_code,
            "headers": headers,
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": b"" if omit_body else response.content,
        }
    )


def _graph_label(graph: CompiledGraph) -> str:
    return graph.root.module.__qualname__


__all__ = ["ASGIApplication", "AsgiAdapter", "asgi"]

"""Register framework WebSocket plans with native Starlette routing."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from starlette.routing import WebSocketRoute
from starlette.types import Message, Receive, Scope, Send
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from tori_py.application import ApplicationRuntime
from tori_py.core.errors import BootstrapError
from tori_py.core.providers import Token
from tori_py.logging import use_log_context
from tori_py.websocket.context import (
    WebSocketContext,
    _reset_websocket_context,
    _set_websocket_context,
)
from tori_py.websocket.errors import WebSocketForbidden
from tori_py.websocket.pipeline import WebSocketPipelineExecutor
from tori_py.websocket.routes import WebSocketParameterPlan, WebSocketPlan


@dataclass(frozen=True, slots=True)
class WebSocketRequestContext(WebSocketContext):
    """WebSocket context exposing the native Starlette connection."""

    socket: WebSocket

    @property
    def metadata(self) -> MappingProxyType[str, object]:
        return MappingProxyType(
            {
                "path": self.socket.url.path,
                "headers": self.socket.headers,
                "query": self.socket.query_params,
                "path_params": MappingProxyType(dict(self.socket.path_params)),
                "subprotocols": tuple(self.socket.scope.get("subprotocols", ())),
            }
        )


class StarletteWebSocketPipelineAdapter:
    def is_abort_exception(self, error: BaseException) -> bool:
        return isinstance(
            error,
            (asyncio.CancelledError, WebSocketDisconnect, WebSocketForbidden),
        )


def validate_websocket_bindings(plans: tuple[WebSocketPlan, ...]) -> None:
    for plan in plans:
        for parameter in plan.parameters:
            annotation = parameter.annotation
            if parameter.kind == "socket" and (
                not isinstance(annotation, type)
                or not issubclass(WebSocket, annotation)
            ):
                raise BootstrapError(
                    f"WebSocket parameter {parameter.name} is not compatible "
                    "with Starlette WebSocket",
                    code="gateway.invalid_binding",
                )
            if parameter.kind == "context" and (
                not isinstance(annotation, type)
                or not issubclass(WebSocketRequestContext, annotation)
            ):
                raise BootstrapError(
                    f"WebSocket context parameter {parameter.name} is not "
                    "compatible with Starlette WebSocketRequestContext",
                    code="gateway.invalid_binding",
                )


def build_starlette_websocket_routes(
    plans: tuple[WebSocketPlan, ...],
    pipeline: WebSocketPipelineExecutor,
    runtime: ApplicationRuntime,
    *,
    application_id: str,
) -> list[WebSocketRoute]:
    return [
        WebSocketRoute(
            plan.path,
            endpoint=_StarletteWebSocketEndpoint(
                _endpoint(
                    plan,
                    pipeline,
                    runtime,
                    application_id=application_id,
                )
            ),
        )
        for plan in plans
    ]


class _StarletteWebSocketEndpoint:
    def __init__(
        self,
        handler: Callable[[WebSocket], Awaitable[None]],
    ) -> None:
        self.handler = handler

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        async def send_or_disconnect(message: Message) -> None:
            try:
                await send(message)
            except OSError as error:
                raise WebSocketDisconnect(code=1006) from error

        await self.handler(WebSocket(scope, receive, send_or_disconnect))


def _endpoint(
    plan: WebSocketPlan,
    pipeline: WebSocketPipelineExecutor,
    runtime: ApplicationRuntime,
    *,
    application_id: str,
):
    async def handle(socket: WebSocket) -> None:
        connection_id = _connection_id(socket)
        request_scope = runtime.request_scope(plan.module_id)
        context_token = None
        with use_log_context(
            application=application_id,
            request_id=connection_id,
            scope="websocket",
        ):
            try:
                async with request_scope:
                    context = WebSocketRequestContext(
                        socket=socket,
                        scope=request_scope,
                        module_identity=plan.module_id,
                        application=application_id,
                        gateway=plan.route_id,
                        connection_id_value=connection_id,
                    )
                    context_token = _set_websocket_context(context)

                    async def bind_arguments() -> dict[str, object]:
                        return await _bind_arguments(plan, socket, context)

                    await pipeline.run(
                        plan,
                        context,
                        request_scope,
                        bind_arguments=bind_arguments,
                    )
                    if socket.application_state is not WebSocketState.DISCONNECTED:
                        await socket.close()
            except WebSocketForbidden:
                if socket.application_state is not WebSocketState.DISCONNECTED:
                    try:
                        await socket.close(code=1008)
                    except OSError, WebSocketDisconnect:
                        pass
            except WebSocketDisconnect:
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                if socket.application_state is not WebSocketState.DISCONNECTED:
                    try:
                        await socket.close(code=1011)
                    except OSError, WebSocketDisconnect:
                        pass
                raise
            finally:
                if context_token is not None:
                    _reset_websocket_context(context_token)

    return handle


async def _bind_arguments(
    plan: WebSocketPlan,
    socket: WebSocket,
    context: WebSocketRequestContext,
) -> dict[str, object]:
    arguments: dict[str, object] = {}
    for parameter in plan.parameters:
        if parameter.kind == "socket":
            value: object = socket
        elif parameter.kind == "context":
            value = context
        elif parameter.kind == "inject":
            value = await context.resolver.resolve(cast(Token, parameter.token))
        else:
            value = _read_handshake_value(socket, parameter)
        if value is _MISSING:
            if parameter.has_default:
                value = parameter.default
            else:
                raise ValueError(
                    f"Missing required {parameter.kind} value '{parameter.name}'."
                )
        arguments[parameter.name] = value
    return arguments


def _read_handshake_value(
    socket: WebSocket,
    parameter: WebSocketParameterPlan,
) -> object:
    source = cast(str, parameter.source)
    if parameter.kind == "path":
        return socket.path_params.get(source, _MISSING)
    if parameter.kind == "query":
        return _collapse_values(socket.query_params.getlist(source))
    if parameter.kind == "header":
        return _collapse_values(socket.headers.getlist(source))
    if parameter.kind == "cookie":
        return socket.cookies.get(source, _MISSING)
    raise RuntimeError("unknown WebSocket binding kind")


def _collapse_values(values: list[str]) -> object:
    if not values:
        return _MISSING
    return values[0] if len(values) == 1 else values


def _connection_id(socket: WebSocket) -> str:
    values = socket.headers.getlist("x-request-id")
    if len(values) == 1 and _REQUEST_ID_PATTERN.fullmatch(values[0]):
        return values[0]
    if values:
        logger.warning("Invalid or duplicate X-Request-ID replaced")
    return str(uuid.uuid7())


logger = logging.getLogger("tori_py.starlette.websockets")
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")
_MISSING = object()


__all__ = [
    "StarletteWebSocketPipelineAdapter",
    "WebSocketRequestContext",
    "build_starlette_websocket_routes",
    "validate_websocket_bindings",
]

from __future__ import annotations

import asyncio
import html
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, cast

from starlette.datastructures import QueryParams
from starlette.requests import Request
from starlette.websockets import WebSocket, WebSocketDisconnect
from tori_py import Context, Socket, WebSocketContext, websocket_gateway
from tori_py.http import HttpContext, HttpResponse

from tori_py_liveview.errors import (
    LiveViewConfigurationError,
    UnknownEventError,
)
from tori_py_liveview.options import LiveViewOptions, normalize_origin
from tori_py_liveview.page import LiveView, MountContext
from tori_py_liveview.rendering import Rendered
from tori_py_liveview.tokens import InvalidMountTokenError, MountTokenCodec

_LOGGER = logging.getLogger(__name__)
_MAX_SAFE_INTEGER = 2**53 - 1


@dataclass(frozen=True, slots=True)
class _Registry:
    pages: Mapping[str, type[LiveView]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "pages", MappingProxyType(dict(self.pages)))


@dataclass(frozen=True, slots=True)
class _CloseConnection(Exception):
    code: int


class _ClientDisconnected(Exception):
    pass


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _render(page: LiveView) -> Rendered:
    result = page.render()
    if isinstance(result, Rendered):
        return result
    if isinstance(result, str):
        return Rendered((result,), ())
    raise TypeError("LiveView.render must return Rendered or str")


def _resource(request: Request) -> str:
    path = request.url.path
    query = request.url.query
    return path if not query else f"{path}?{query}"


def _render_message(
    rendered: Rendered,
    version: int,
    *,
    title: str | None,
    previous: Rendered | None = None,
    ref: int | None = None,
    status: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "render",
        "protocol": 2,
        "version": version,
    }
    diff = None if previous is None else rendered.diff(previous)
    if diff is None:
        payload["rendered"] = {
            "fingerprint": rendered.fingerprint,
            "statics": list(rendered.statics),
            "dynamics": list(rendered.dynamics),
        }
    else:
        payload["fingerprint"] = rendered.fingerprint
        payload["diff"] = {str(index): value for index, value in diff.items()}
    if title is not None:
        payload["title"] = title
    if ref is not None:
        payload["ref"] = ref
    if status is not None:
        payload["status"] = status
    return payload


async def initial_response(
    context: HttpContext,
    page_type: type[LiveView],
    options: LiveViewOptions,
) -> HttpResponse:
    request = cast(Request, context.request)
    page = cast(LiveView, await context.resolver.resolve(page_type))
    resource = _resource(request)
    params = dict(request.path_params)
    await page.mount(
        MountContext(
            request,
            params,
            resource,
            False,
            QueryParams(resource.partition("?")[2]),
        )
    )
    token = MountTokenCodec(options.secret, max_age_ms=options.token_max_age_ms).sign(
        f"{page_type.__module__}.{page_type.__qualname__}",
        params,
        resource,
    )
    root = (
        '<div id="opal-live-root" data-opal-live-root '
        f'data-opal-token="{html.escape(token, quote=True)}" '
        f'data-opal-socket="{html.escape(options.socket_path, quote=True)}">'
        f"{_render(page).to_html()}</div>"
    )
    client_script = (
        '<script type="module" '
        f'src="{html.escape(options.client_path, quote=True)}"></script>'
    )
    document = page.render_document(root, client_script)
    return HttpResponse(
        document.encode(),
        headers={
            "content-type": "text/html; charset=utf-8",
            "cache-control": "no-store",
        },
    )


def _allowed(socket: WebSocket, options: LiveViewOptions) -> bool:
    origins = socket.headers.getlist("origin")
    if len(origins) != 1:
        return False
    origin = origins[0]
    try:
        normalized = normalize_origin(origin)
    except LiveViewConfigurationError:
        return False
    if options.allowed_origins:
        return normalized in options.allowed_origins

    hosts = socket.headers.getlist("host")
    if len(hosts) != 1 or not hosts[0]:
        return False
    host = hosts[0]
    scheme = "https" if socket.url.scheme == "wss" else "http"
    try:
        expected = normalize_origin(f"{scheme}://{host}")
    except LiveViewConfigurationError:
        return False
    return normalized == expected


async def _message(
    socket: WebSocket,
    *,
    timeout: float,
    timeout_code: int,
    max_message_bytes: int,
) -> dict[str, object]:
    try:
        data = await asyncio.wait_for(socket.receive(), timeout=timeout)
    except TimeoutError as error:
        raise _CloseConnection(timeout_code) from error
    except WebSocketDisconnect as error:
        raise _ClientDisconnected from error
    if data.get("type") == "websocket.disconnect":
        raise _ClientDisconnected
    if data.get("type") != "websocket.receive":
        raise _CloseConnection(1002)
    if data.get("bytes") is not None:
        raise _CloseConnection(1003)
    text = data.get("text")
    if not isinstance(text, str):
        raise _CloseConnection(1002)
    try:
        encoded_size = len(text.encode("utf-8"))
    except UnicodeError as error:
        raise _CloseConnection(1002) from error
    if encoded_size > max_message_bytes:
        raise _CloseConnection(1009)
    try:
        parsed = json.loads(text, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, UnicodeError, ValueError, RecursionError) as error:
        raise _CloseConnection(1002) from error
    if not isinstance(parsed, dict):
        raise _CloseConnection(1002)
    return cast(dict[str, object], parsed)


def _non_negative_int(value: object) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_SAFE_INTEGER:
        raise _CloseConnection(1002)
    return value


def _positive_int(value: object) -> int:
    if type(value) is not int or not 0 < value <= _MAX_SAFE_INTEGER:
        raise _CloseConnection(1002)
    return value


async def _close(socket: WebSocket, code: int) -> None:
    try:
        await socket.close(code)
    except OSError, RuntimeError, WebSocketDisconnect:
        pass


def gateway_type(options: LiveViewOptions, registry: _Registry) -> type[object]:
    class LiveGateway:
        async def handle(
            self,
            socket: Annotated[WebSocket, Socket()],
            context: Annotated[WebSocketContext, Context()],
        ) -> None:
            if not _allowed(socket, options):
                await _close(socket, 1008)
                return
            await socket.accept()
            page: LiveView | None = None
            try:
                join = await _message(
                    socket,
                    timeout=options.join_timeout_seconds,
                    timeout_code=1008,
                    max_message_bytes=options.max_message_bytes,
                )
                token = join.get("token")
                if (
                    join.get("type") != "join"
                    or join.get("protocol") != 2
                    or not isinstance(token, str)
                ):
                    raise _CloseConnection(1002)
                try:
                    name, params, resource = MountTokenCodec(
                        options.secret,
                        max_age_ms=options.token_max_age_ms,
                    ).verify(token)
                    page_type = registry.pages[name]
                except (InvalidMountTokenError, KeyError) as error:
                    raise _CloseConnection(1008) from error

                page = cast(LiveView, await context.resolver.resolve(page_type))
                await page.mount(
                    MountContext(
                        socket,
                        params,
                        resource,
                        True,
                        QueryParams(resource.partition("?")[2]),
                    )
                )
                current = _render(page)
                version = 0
                await socket.send_json(
                    _render_message(current, version, title=page.title())
                )

                while True:
                    message = await _message(
                        socket,
                        timeout=options.idle_timeout_seconds,
                        timeout_code=1001,
                        max_message_bytes=options.max_message_bytes,
                    )
                    kind = message.get("type")
                    if kind == "heartbeat":
                        ref = _positive_int(message.get("ref"))
                        await socket.send_json({"type": "heartbeat", "ref": ref})
                        continue
                    if kind != "event":
                        raise _CloseConnection(1002)

                    event = message.get("event")
                    if not isinstance(event, str) or not event:
                        raise _CloseConnection(1002)
                    event_version = _non_negative_int(message.get("version"))
                    ref = _positive_int(message.get("ref"))
                    target = message.get("target")
                    if target is not None:
                        _positive_int(target)

                    if event_version != version:
                        await socket.send_json(
                            _render_message(
                                current,
                                version,
                                title=page.title(),
                                previous=current,
                                ref=ref,
                                status="stale",
                            )
                        )
                        continue
                    if target is not None:
                        await socket.send_json(
                            {"type": "error", "reason": "unknown_target", "ref": ref}
                        )
                        continue
                    try:
                        await page.handle_event(event, message.get("value"))
                    except UnknownEventError:
                        await socket.send_json(
                            {"type": "error", "reason": "unknown_event", "ref": ref}
                        )
                        continue

                    updated = _render(page)
                    version += 1
                    await socket.send_json(
                        _render_message(
                            updated,
                            version,
                            title=page.title(),
                            previous=current,
                            ref=ref,
                            status="ok",
                        )
                    )
                    current = updated
            except _ClientDisconnected:
                pass
            except _CloseConnection as error:
                await _close(socket, error.code)
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Unhandled LiveView WebSocket session failure")
                await _close(socket, 1011)
            finally:
                if page is not None:
                    try:
                        await page.disconnect()
                    except Exception:
                        _LOGGER.exception("LiveView disconnect hook failed")

    LiveGateway.__module__ = __name__
    return websocket_gateway(options.socket_path)(LiveGateway)


__all__ = ["_Registry", "gateway_type", "initial_response"]

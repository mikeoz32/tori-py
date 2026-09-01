from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, cast
from urllib.parse import parse_qsl

from starlette.datastructures import QueryParams
from starlette.requests import Request
from starlette.websockets import WebSocket, WebSocketDisconnect
from tori_py import Context, Socket, WebSocketContext, websocket_gateway
from tori_py.http import HttpContext, HttpResponse

from tori_py_liveview.errors import (
    LiveViewConfigurationError,
    UnknownEventError,
)
from tori_py_liveview.options import LiveViewOptions, normalize_origin, websocket_path
from tori_py_liveview.page import LiveView, MountContext, _UnknownComponentError
from tori_py_liveview.rendering import (
    Rendered,
    _ComponentRendered,
    _StreamRendered,
)
from tori_py_liveview.tokens import InvalidMountTokenError, MountTokenCodec

_LOGGER = logging.getLogger(__name__)
_LIVEVIEW_VERSION = "1.2.11"
_ROOT_ID = "tori-live-root"
_TOPIC = f"lv:{_ROOT_ID}"
_MAX_SAFE_INTEGER = 2**53 - 1


@dataclass(frozen=True, slots=True)
class _Registry:
    pages: Mapping[str, type[LiveView]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "pages", MappingProxyType(dict(self.pages)))


@dataclass(frozen=True, slots=True)
class _ChannelMessage:
    join_ref: str | None
    ref: str | None
    topic: str
    event: str
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class _CloseConnection(Exception):
    code: int


class _ClientDisconnected(Exception):
    pass


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


async def _render(page: LiveView) -> Rendered:
    return await page._render_liveview()


def _resource(request: Request) -> str:
    path = request.url.path
    query = request.url.query
    return path if not query else f"{path}?{query}"


def _stream_tree(rendered: _StreamRendered) -> dict[str, object]:
    keyed: dict[str, object] = {"kc": len(rendered.inserts)}
    insert_metadata: list[list[object]] = []
    for index, insert in enumerate(rendered.inserts):
        keyed[str(index)] = {"0": insert.html}
        insert_metadata.append([insert.item_id, insert.at, insert.limit, None])
    stream: list[object] = [
        rendered.ref,
        insert_metadata,
        list(rendered.delete_ids),
    ]
    if rendered.reset:
        stream.append(True)
    return {"s": ["", ""], "k": keyed, "stream": stream}


def _rendered_tree(
    rendered: Rendered,
    components: dict[str, object],
    *,
    root: bool = False,
) -> dict[str, object]:
    tree: dict[str, object] = {"s": list(rendered.statics)}
    if root:
        tree["r"] = 1
    for index, dynamic in enumerate(rendered.dynamics):
        key = str(index)
        if isinstance(dynamic, _ComponentRendered):
            tree[key] = dynamic.cid
            component = Rendered(dynamic.statics, dynamic.dynamics)
            components[str(dynamic.cid)] = _rendered_tree(
                component,
                components,
                root=True,
            )
        elif isinstance(dynamic, _StreamRendered):
            tree[key] = _stream_tree(dynamic)
        elif isinstance(dynamic, Rendered):
            tree[key] = _rendered_tree(dynamic, components)
        else:
            tree[key] = dynamic
    return tree


def _render_message(rendered: Rendered, *, title: str | None) -> dict[str, object]:
    components: dict[str, object] = {}
    if isinstance(rendered, _ComponentRendered):
        rendered = Rendered(("", ""), (rendered,))
    payload = _rendered_tree(rendered, components)
    if components:
        payload["c"] = components
    payload["t"] = "" if title is None else title
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
    await page._mount_liveview(
        MountContext(
            request,
            params,
            resource,
            False,
            QueryParams(resource.partition("?")[2]),
        )
    )
    try:
        token = MountTokenCodec(
            options.secret,
            max_age_ms=options.token_max_age_ms,
        ).sign(
            f"{page_type.__module__}.{page_type.__qualname__}",
            params,
            resource,
        )
        root = (
            f'<div id="{_ROOT_ID}" data-phx-main '
            f'data-phx-session="{html.escape(token, quote=True)}" '
            'data-phx-static="" '
            f'data-tori-live-socket="{html.escape(options.socket_path, quote=True)}">'
            f"{(await _render(page)).to_html()}</div>"
        )
        client_script = (
            "<script defer "
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
    finally:
        await page._disconnect_liveview_components()


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


def _ref(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise _CloseConnection(1002)
    return value


def _channel_message(value: object) -> _ChannelMessage:
    if not isinstance(value, list) or len(value) != 5:
        raise _CloseConnection(1002)
    join_ref, ref, topic, event, payload = value
    if (
        not isinstance(topic, str)
        or not topic
        or not isinstance(event, str)
        or not event
        or not isinstance(payload, dict)
    ):
        raise _CloseConnection(1002)
    return _ChannelMessage(
        _ref(join_ref),
        _ref(ref),
        topic,
        event,
        cast(dict[str, object], payload),
    )


async def _message(
    socket: WebSocket,
    *,
    timeout: float,
    timeout_code: int,
    max_message_bytes: int,
) -> _ChannelMessage:
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
    return _channel_message(parsed)


async def _send(
    socket: WebSocket,
    join_ref: str | None,
    ref: str | None,
    topic: str,
    event: str,
    payload: dict[str, object],
) -> None:
    await socket.send_json([join_ref, ref, topic, event, payload])


async def _reply(
    socket: WebSocket,
    message: _ChannelMessage,
    status: str,
    response: dict[str, object],
) -> None:
    await _send(
        socket,
        message.join_ref,
        message.ref,
        message.topic,
        "phx_reply",
        {"status": status, "response": response},
    )


def _positive_int(value: object) -> int:
    if type(value) is not int or not 0 < value <= _MAX_SAFE_INTEGER:
        raise _CloseConnection(1002)
    return value


def _query_tokens(key: str) -> list[str]:
    match = re.fullmatch(r"([^\[\]]+)((?:\[[^\[\]]*\])*)", key)
    if match is None:
        return [key]
    tokens = [match[1], *re.findall(r"\[([^\[\]]*)\]", match[2])]
    if len(tokens) > 32:
        raise _CloseConnection(1002)
    return tokens


def _path_available(target: dict[str, object], tokens: list[str]) -> bool:
    key = tokens[0]
    if key not in target:
        return True
    if len(tokens) == 1:
        return False
    child = target[key]
    return isinstance(child, dict) and _path_available(
        cast(dict[str, object], child),
        tokens[1:],
    )


def _assign_query_value(
    target: dict[str, object],
    tokens: list[str],
    value: str,
) -> None:
    key = tokens[0]
    if len(tokens) == 1:
        target[key] = value
        return

    if tokens[1] == "":
        stored = target.get(key)
        if stored is None:
            child: list[object] = []
            target[key] = child
        elif isinstance(stored, list):
            child = cast(list[object], stored)
        else:
            raise _CloseConnection(1002)
        remaining = tokens[2:]
        if not remaining:
            child.append(value)
            return
        candidate = (
            cast(dict[str, object], child[-1])
            if child and isinstance(child[-1], dict)
            else None
        )
        if candidate is None or not _path_available(candidate, remaining):
            candidate = {}
            child.append(candidate)
        _assign_query_value(candidate, remaining, value)
        return

    stored = target.get(key)
    if stored is None:
        child_dict: dict[str, object] = {}
        target[key] = child_dict
    elif isinstance(stored, dict):
        child_dict = cast(dict[str, object], stored)
    else:
        raise _CloseConnection(1002)
    _assign_query_value(child_dict, tokens[1:], value)


def _event_value(payload: dict[str, object]) -> object:
    value = payload.get("value")
    if payload.get("type") != "form":
        return value
    if not isinstance(value, str):
        raise _CloseConnection(1002)
    decoded: dict[str, object] = {}
    try:
        pairs = parse_qsl(value, keep_blank_values=True, max_num_fields=1024)
    except ValueError as error:
        raise _CloseConnection(1002) from error
    for key, item in pairs:
        _assign_query_value(decoded, _query_tokens(key), item)
    meta = payload.get("meta", {})
    if not isinstance(meta, dict):
        raise _CloseConnection(1002)
    for key, item in meta.items():
        if not isinstance(key, str):
            raise _CloseConnection(1002)
        if key == "_target" and isinstance(item, str):
            decoded[key] = [part for part in _query_tokens(item) if part]
        else:
            decoded[key] = item
    return decoded


def _destroyed_cids(payload: dict[str, object]) -> list[int]:
    cids = payload.get("cids")
    if not isinstance(cids, list):
        raise _CloseConnection(1002)
    return [_positive_int(cid) for cid in cids]


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
                token = join.payload.get("session")
                if (
                    join.event != "phx_join"
                    or join.topic != _TOPIC
                    or join.join_ref is None
                    or join.join_ref != join.ref
                    or not isinstance(token, str)
                ):
                    raise _CloseConnection(1002)
                try:
                    name, params, resource = MountTokenCodec(
                        options.secret,
                        max_age_ms=options.token_max_age_ms,
                    ).verify(token)
                    page_type = registry.pages[name]
                except InvalidMountTokenError, KeyError:
                    await _reply(socket, join, "error", {"reason": "unauthorized"})
                    return

                page = cast(LiveView, await context.resolver.resolve(page_type))
                await page._mount_liveview(
                    MountContext(
                        socket,
                        params,
                        resource,
                        True,
                        QueryParams(resource.partition("?")[2]),
                    )
                )
                current = await _render(page)
                rendered = _render_message(current, title=page.title())
                page._clear_liveview_stream_operations()
                await _reply(
                    socket,
                    join,
                    "ok",
                    {
                        "rendered": rendered,
                        "liveview_version": _LIVEVIEW_VERSION,
                    },
                )

                while True:
                    message = await _message(
                        socket,
                        timeout=options.idle_timeout_seconds,
                        timeout_code=1001,
                        max_message_bytes=options.max_message_bytes,
                    )
                    if message.topic == "phoenix" and message.event == "heartbeat":
                        if message.join_ref is not None or message.ref is None:
                            raise _CloseConnection(1002)
                        await _reply(socket, message, "ok", {})
                        continue
                    if (
                        message.topic != _TOPIC
                        or message.join_ref != join.join_ref
                        or message.ref is None
                    ):
                        raise _CloseConnection(1002)
                    if message.event == "phx_leave":
                        await _reply(socket, message, "ok", {})
                        return
                    if message.event == "cids_will_destroy":
                        page._prepare_liveview_component_destruction(
                            _destroyed_cids(message.payload)
                        )
                        await _reply(socket, message, "ok", {})
                        continue
                    if message.event == "cids_destroyed":
                        destroyed = await page._destroy_liveview_components(
                            _destroyed_cids(message.payload)
                        )
                        await _reply(socket, message, "ok", {"cids": destroyed})
                        continue
                    if message.event != "event":
                        raise _CloseConnection(1002)

                    event = message.payload.get("event")
                    event_type = message.payload.get("type")
                    if (
                        not isinstance(event, str)
                        or not event
                        or not isinstance(event_type, str)
                        or not event_type
                    ):
                        raise _CloseConnection(1002)
                    target_value = message.payload.get("cid")
                    target = (
                        None if target_value is None else _positive_int(target_value)
                    )
                    try:
                        await page._handle_liveview_event(
                            target,
                            event,
                            _event_value(message.payload),
                        )
                    except _UnknownComponentError:
                        page._clear_liveview_stream_operations()
                        await _reply(
                            socket,
                            message,
                            "ok",
                            {"reason": "unknown_target"},
                        )
                        continue
                    except UnknownEventError:
                        page._clear_liveview_stream_operations()
                        await _reply(
                            socket,
                            message,
                            "ok",
                            {"reason": "unknown_event"},
                        )
                        continue

                    updated = await _render(page)
                    diff = _render_message(updated, title=page.title())
                    page._clear_liveview_stream_operations()
                    await _reply(socket, message, "ok", {"diff": diff})
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
                        await page._disconnect_liveview()
                    except Exception:
                        _LOGGER.exception("LiveView disconnect hook failed")

    LiveGateway.__module__ = __name__
    return websocket_gateway(websocket_path(options.socket_path))(LiveGateway)


__all__ = ["_Registry", "gateway_type", "initial_response"]

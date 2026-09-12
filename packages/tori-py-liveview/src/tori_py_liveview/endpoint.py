from __future__ import annotations

import asyncio
import html
import inspect
import json
import logging
import re
import sys
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Annotated, cast
from urllib.parse import parse_qsl, urlsplit

from starlette.datastructures import QueryParams
from starlette.requests import Request
from starlette.websockets import WebSocket, WebSocketDisconnect
from tori_py import (
    Context,
    ScopedResolver,
    Socket,
    WebSocketContext,
    WorkScopeFactory,
    websocket_gateway,
)
from tori_py.http import HttpContext, HttpResponse

from tori_py_liveview.errors import (
    LiveViewConfigurationError,
    LiveViewError,
    UnknownEventError,
)
from tori_py_liveview.metadata import LiveViewMetadata
from tori_py_liveview.options import LiveViewOptions, normalize_origin, websocket_path
from tori_py_liveview.page import LiveView, MountContext, _Info, _UnknownComponentError
from tori_py_liveview.rendering import (
    Rendered,
    _ComponentRendered,
    _StreamRendered,
)
from tori_py_liveview.routing import (
    CompiledLiveRoute,
    LiveRoute,
    compile_live_routes,
    match_live_url,
    same_origin,
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
    routes: tuple[LiveRoute, ...] = ()
    sessions: Mapping[str, tuple[Callable[..., object], ...]] = field(
        default_factory=dict
    )
    compiled: tuple[CompiledLiveRoute, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "pages", MappingProxyType(dict(self.pages)))
        object.__setattr__(self, "sessions", MappingProxyType(dict(self.sessions)))
        object.__setattr__(self, "compiled", compile_live_routes(self.routes))


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
    route: LiveViewMetadata,
    hooks: tuple[Callable[..., object], ...] = (),
    compiled: tuple[CompiledLiveRoute, ...] = (),
) -> HttpResponse:
    request = cast(Request, context.request)
    page = cast(LiveView, await context.resolver.resolve(page_type))
    try:
        page._liveview_action = route.action
        resource = _resource(request)
        params = {name: str(value) for name, value in request.path_params.items()}
        mount_context = MountContext(
            request,
            params,
            resource,
            False,
            QueryParams(resource.partition("?")[2]),
        )
        await _run_on_mount(hooks, page, mount_context)
        await page._mount_liveview(mount_context)
        await page.handle_params(
            {**dict(QueryParams(resource.partition("?")[2])), **params},
            str(request.url),
        )
        drained = await _drain_navigation(
            page,
            compiled,
            f"{page_type.__module__}.{page_type.__qualname__}",
            route.session,
            host=request.headers.get("host", ""),
            scheme=request.url.scheme,
        )
        if drained is not None and drained[0] != "patch":
            return HttpResponse(b"", status_code=302, headers={"location": drained[1]})
        token = MountTokenCodec(
            options.secret,
            max_age_ms=options.token_max_age_ms,
        ).sign(
            f"{page_type.__module__}.{page_type.__qualname__}",
            params,
            resource,
            route.action,
            route.session,
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


def _resolve_navigate(
    registry: _Registry, session: str, target: str
) -> LiveRoute | None:
    """Return the navigate target route, or None when a full reload applies."""
    resolved = match_live_url(registry.compiled, target)
    if resolved is None:
        raise LiveViewError("unknown navigate target")
    route = resolved[0]
    return route if route.session == session else None


def _url_allowed(socket: WebSocket, url: str) -> bool:
    hosts = socket.headers.getlist("host")
    scheme = "https" if socket.url.scheme == "wss" else "http"
    return len(hosts) == 1 and same_origin(hosts[0], url, scheme=scheme)


async def _disconnect_page(page: LiveView) -> None:
    page._detach_liveview()
    try:
        await page._disconnect_liveview()
    except Exception:
        _LOGGER.exception("LiveView disconnect hook failed")


async def _open_page(
    scopes: WorkScopeFactory,
    page_type: type[LiveView],
) -> tuple[AbstractAsyncContextManager[ScopedResolver], LiveView]:
    scope = scopes.open()
    try:
        resolver = await scope.__aenter__()
        page = cast(LiveView, await resolver.resolve(page_type))
    except BaseException:
        await scope.__aexit__(*sys.exc_info())
        raise
    return scope, page


async def _close_page(
    page: LiveView | None,
    scope: AbstractAsyncContextManager[ScopedResolver] | None,
) -> None:
    try:
        if page is not None:
            await _disconnect_page(page)
    finally:
        if scope is not None:
            await scope.__aexit__(None, None, None)


async def _drain_navigation(
    page: LiveView,
    compiled: tuple[CompiledLiveRoute, ...],
    page_identity: str,
    session: str,
    *,
    host: str,
    scheme: str,
) -> tuple[str, str, str] | None:
    """Consume queued navigation; run handle_params for patch chains."""
    pending = page._take_liveview_pending_redirect()
    if pending is None:
        return None
    patch: tuple[str, str] | None = None
    for _ in range(20):
        navigation, target, kind = pending
        if navigation in {"patch", "navigate"} and not same_origin(
            host, target, scheme=scheme
        ):
            raise LiveViewError("live navigation target must be same-origin")
        if navigation != "patch":
            return (navigation, target, kind)
        resolved = match_live_url(compiled, target)
        if (
            resolved is None
            or resolved[0].page != page_identity
            or resolved[0].session != session
        ):
            raise LiveViewError("push_patch target must resolve to the current page")
        live_route, url_params, uri = resolved
        page._liveview_action = live_route.action
        await page.handle_params(url_params, uri)
        patch = (target, kind)
        pending = page._take_liveview_pending_redirect()
        if pending is None:
            if patch is None:
                raise LiveViewError("patch navigation state was lost")
            return ("patch", patch[0], patch[1])
    raise LiveViewError("too many patch redirects")


async def _run_on_mount(
    hooks: tuple[Callable[..., object], ...],
    page: LiveView,
    mount_context: MountContext,
) -> None:
    for hook in hooks:
        result = hook(page, mount_context)
        if inspect.isawaitable(result):
            await result


def _url_resource(url: str) -> str:
    split = urlsplit(url)
    if split.query:
        return f"{split.path}?{split.query}"
    return split.path


async def _close(socket: WebSocket, code: int) -> None:
    try:
        await socket.close(code)
    except OSError, RuntimeError, WebSocketDisconnect:
        pass


def gateway_type(options: LiveViewOptions, registry: _Registry) -> type[object]:
    class LiveGateway:
        def __init__(self, scopes: WorkScopeFactory) -> None:
            self._scopes = scopes

        async def handle(
            self,
            socket: Annotated[WebSocket, Socket()],
            context: Annotated[WebSocketContext, Context()],
        ) -> None:
            if not _allowed(socket, options):
                await _close(socket, 1008)
                return
            await socket.accept()
            origin_host = socket.headers.get("host", "")
            origin_scheme = "https" if socket.url.scheme == "wss" else "http"
            page: LiveView | None = None
            page_scope: AbstractAsyncContextManager[ScopedResolver] | None = None
            incoming_task: asyncio.Task[_ChannelMessage] | None = None
            info_task: asyncio.Task[_Info] | None = None
            join_source: asyncio.Task[_ChannelMessage] | None = None
            first_join = True
            name = ""
            session = ""

            def incoming_message_task() -> asyncio.Task[_ChannelMessage]:
                return asyncio.create_task(
                    _message(
                        socket,
                        timeout=options.idle_timeout_seconds,
                        timeout_code=1001,
                        max_message_bytes=options.max_message_bytes,
                    )
                )

            async def close_current_page() -> None:
                nonlocal page, page_scope
                closing_page = page
                closing_scope = page_scope
                page = None
                page_scope = None
                await _close_page(closing_page, closing_scope)

            try:
                while True:
                    if join_source is None:
                        join = await _message(
                            socket,
                            timeout=(
                                options.join_timeout_seconds
                                if first_join
                                else options.idle_timeout_seconds
                            ),
                            timeout_code=1008 if first_join else 1001,
                            max_message_bytes=options.max_message_bytes,
                        )
                    else:
                        join = await join_source
                        join_source = None
                    if (
                        not first_join
                        and join.topic == _TOPIC
                        and join.event == "phx_leave"
                    ):
                        await _reply(socket, join, "ok", {})
                        join = await _message(
                            socket,
                            timeout=options.idle_timeout_seconds,
                            timeout_code=1001,
                            max_message_bytes=options.max_message_bytes,
                        )
                    first_join = False
                    token = join.payload.get("session")
                    redirect_url = join.payload.get("redirect")
                    url = join.payload.get("url")
                    if (
                        join.event != "phx_join"
                        or join.topic != _TOPIC
                        or join.join_ref is None
                        or join.join_ref != join.ref
                        or not isinstance(token, str)
                    ):
                        raise _CloseConnection(1002)
                    try:
                        mounted = MountTokenCodec(
                            options.secret,
                            max_age_ms=options.token_max_age_ms,
                        ).verify(token)
                        if redirect_url is not None:
                            if (
                                not isinstance(redirect_url, str)
                                or not redirect_url
                                or not _url_allowed(socket, redirect_url)
                            ):
                                raise _CloseConnection(1002)
                            resolved = match_live_url(registry.compiled, redirect_url)
                            if (
                                resolved is None
                                or resolved[0].session != mounted.session
                            ):
                                raise InvalidMountTokenError("unauthorized navigate")
                            live_route, mount_params, uri = resolved
                            action = live_route.action
                            resource = _url_resource(redirect_url)
                            join_params = dict(mount_params)
                        else:
                            if not isinstance(url, str) or not _url_allowed(
                                socket, url
                            ):
                                raise _CloseConnection(1002)
                            resolved = match_live_url(registry.compiled, url)
                            if resolved is None:
                                raise InvalidMountTokenError("unknown live route")
                            live_route, url_params, uri = resolved
                            if (
                                live_route.page != mounted.page
                                or live_route.action != mounted.action
                                or live_route.session != mounted.session
                                or _url_resource(url) != mounted.resource
                                or any(
                                    url_params.get(name) != value
                                    for name, value in mounted.params.items()
                                )
                            ):
                                raise InvalidMountTokenError("stale live session")
                            action = mounted.action
                            mount_params = mounted.params
                            resource = mounted.resource
                            join_params = url_params
                        page_type = registry.pages[live_route.page]
                    except InvalidMountTokenError, KeyError:
                        await _reply(socket, join, "error", {"reason": "unauthorized"})
                        return

                    name = live_route.page
                    session = live_route.session
                    page_scope, page = await _open_page(self._scopes, page_type)
                    page._liveview_action = action
                    page._connect_liveview()
                    mount_context = MountContext(
                        socket,
                        mount_params,
                        resource,
                        True,
                        QueryParams(resource.partition("?")[2]),
                    )
                    await _run_on_mount(
                        registry.sessions.get(session, ()), page, mount_context
                    )
                    await page._mount_liveview(mount_context)
                    await page.handle_params(join_params, uri)
                    drained = await _drain_navigation(
                        page,
                        registry.compiled,
                        name,
                        session,
                        host=origin_host,
                        scheme=origin_scheme,
                    )
                    if drained is not None and drained[0] != "patch":
                        navigation, target, kind = drained
                        await close_current_page()
                        if navigation == "navigate":
                            target_route = _resolve_navigate(registry, session, target)
                            if target_route is not None:
                                await _reply(
                                    socket,
                                    join,
                                    "error",
                                    {
                                        "live_redirect": {
                                            "kind": kind,
                                            "to": target,
                                        }
                                    },
                                )
                                continue
                        await _reply(
                            socket, join, "error", {"redirect": {"to": target}}
                        )
                        return
                    current = await _render(page)
                    rendered = _render_message(current, title=page.title())
                    page._clear_liveview_stream_operations()
                    join_reply: dict[str, object] = {
                        "rendered": rendered,
                        "liveview_version": _LIVEVIEW_VERSION,
                    }
                    if drained is not None:
                        _, patch_to, patch_kind = drained
                        join_reply["live_patch"] = {
                            "kind": patch_kind,
                            "to": patch_to,
                        }
                    await _reply(socket, join, "ok", join_reply)

                    incoming_task = incoming_message_task()
                    info_task = asyncio.create_task(page._receive_liveview_info())
                    while True:
                        if incoming_task is None:
                            incoming_task = incoming_message_task()
                        done, _ = await asyncio.wait(
                            (incoming_task, info_task),
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if incoming_task in done:
                            message = incoming_task.result()
                            incoming_task = None
                            if (
                                message.topic == "phoenix"
                                and message.event == "heartbeat"
                            ):
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
                                if info_task is None:
                                    raise LiveViewError(
                                        "LiveView receive tasks are missing"
                                    )
                                info_task.cancel()
                                await asyncio.gather(info_task, return_exceptions=True)
                                info_task = None
                                join_source = incoming_message_task()
                                await close_current_page()
                                break
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
                            if message.event == "live_patch":
                                patch_url = message.payload.get("url")
                                if (
                                    not isinstance(patch_url, str)
                                    or not patch_url
                                    or not _url_allowed(socket, patch_url)
                                ):
                                    raise _CloseConnection(1002)
                                patch_resolved = match_live_url(
                                    registry.compiled, patch_url
                                )
                                if (
                                    patch_resolved is None
                                    or patch_resolved[0].page != name
                                    or patch_resolved[0].session != session
                                ):
                                    await _reply(
                                        socket,
                                        message,
                                        "ok",
                                        {"link_redirect": True},
                                    )
                                    continue
                                patch_route, patch_params, patch_uri = patch_resolved
                                page._liveview_action = patch_route.action
                                await page.handle_params(patch_params, patch_uri)
                                drained = await _drain_navigation(
                                    page,
                                    registry.compiled,
                                    name,
                                    session,
                                    host=origin_host,
                                    scheme=origin_scheme,
                                )
                                if drained is not None and drained[0] != "patch":
                                    navigation, target, kind = drained
                                    if navigation == "redirect":
                                        await _reply(
                                            socket,
                                            message,
                                            "ok",
                                            {"redirect": {"to": target}},
                                        )
                                        return
                                    target_route = _resolve_navigate(
                                        registry, session, target
                                    )
                                    if target_route is None:
                                        await _reply(
                                            socket,
                                            message,
                                            "ok",
                                            {"redirect": {"to": target}},
                                        )
                                        return
                                    await _reply(
                                        socket,
                                        message,
                                        "ok",
                                        {
                                            "live_redirect": {
                                                "kind": kind,
                                                "to": target,
                                            }
                                        },
                                    )
                                    if info_task is None:
                                        raise LiveViewError(
                                            "LiveView receive tasks are missing"
                                        )
                                    join_source = incoming_message_task()
                                    info_task.cancel()
                                    await asyncio.gather(
                                        info_task, return_exceptions=True
                                    )
                                    info_task = None
                                    await close_current_page()
                                    break
                                updated = await _render(page)
                                diff = _render_message(updated, title=page.title())
                                page._clear_liveview_stream_operations()
                                if drained is not None:
                                    _, patch_to, patch_kind = drained
                                    await _send(
                                        socket,
                                        join.join_ref,
                                        None,
                                        join.topic,
                                        "live_patch",
                                        {"kind": patch_kind, "to": patch_to},
                                    )
                                await _reply(socket, message, "ok", {"diff": diff})
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
                                None
                                if target_value is None
                                else _positive_int(target_value)
                            )
                            try:
                                await page._handle_liveview_event(
                                    target,
                                    event,
                                    _event_value(message.payload),
                                )
                            except _UnknownComponentError:
                                page._take_liveview_pending_redirect()
                                page._clear_liveview_stream_operations()
                                await _reply(
                                    socket,
                                    message,
                                    "ok",
                                    {"reason": "unknown_target"},
                                )
                                continue
                            except UnknownEventError:
                                page._take_liveview_pending_redirect()
                                page._clear_liveview_stream_operations()
                                await _reply(
                                    socket,
                                    message,
                                    "ok",
                                    {"reason": "unknown_event"},
                                )
                                continue

                            drained = await _drain_navigation(
                                page,
                                registry.compiled,
                                name,
                                session,
                                host=origin_host,
                                scheme=origin_scheme,
                            )
                            if drained is None or drained[0] == "patch":
                                updated = await _render(page)
                                diff = _render_message(updated, title=page.title())
                                page._clear_liveview_stream_operations()
                                if drained is not None:
                                    _, patch_to, patch_kind = drained
                                    await _send(
                                        socket,
                                        join.join_ref,
                                        None,
                                        join.topic,
                                        "live_patch",
                                        {"kind": patch_kind, "to": patch_to},
                                    )
                                await _reply(socket, message, "ok", {"diff": diff})
                                continue
                            navigation, target, kind = drained
                            if navigation == "redirect":
                                await _reply(
                                    socket,
                                    message,
                                    "ok",
                                    {"redirect": {"to": target}},
                                )
                                return
                            target_route = _resolve_navigate(registry, session, target)
                            if target_route is None:
                                await _reply(
                                    socket,
                                    message,
                                    "ok",
                                    {"redirect": {"to": target}},
                                )
                                return
                            await _reply(
                                socket,
                                message,
                                "ok",
                                {"live_redirect": {"kind": kind, "to": target}},
                            )
                            if info_task is None:
                                raise LiveViewError(
                                    "LiveView receive tasks are missing"
                                )
                            info_task.cancel()
                            await asyncio.gather(info_task, return_exceptions=True)
                            info_task = None
                            join_source = incoming_message_task()
                            await close_current_page()
                            break
                        else:
                            if info_task is None:
                                raise LiveViewError("LiveView info task is missing")
                            info = info_task.result()
                            info_task = asyncio.create_task(
                                page._receive_liveview_info()
                            )
                            try:
                                await page.handle_info(info.name, info.value)
                            except Exception as error:
                                _LOGGER.exception(
                                    "LiveView info failed: page=%s info=%s",
                                    type(page).__qualname__,
                                    info.name,
                                )
                                raise _CloseConnection(1011) from error
                            drained = await _drain_navigation(
                                page,
                                registry.compiled,
                                name,
                                session,
                                host=origin_host,
                                scheme=origin_scheme,
                            )
                            if drained is None or drained[0] == "patch":
                                updated = await _render(page)
                                diff = _render_message(updated, title=page.title())
                                page._clear_liveview_stream_operations()
                                if drained is not None:
                                    _, patch_to, patch_kind = drained
                                    await _send(
                                        socket,
                                        join.join_ref,
                                        None,
                                        join.topic,
                                        "live_patch",
                                        {"kind": patch_kind, "to": patch_to},
                                    )
                                await _send(
                                    socket,
                                    join.join_ref,
                                    None,
                                    join.topic,
                                    "diff",
                                    diff,
                                )
                                continue
                            navigation, target, kind = drained
                            if navigation == "redirect":
                                await _send(
                                    socket,
                                    join.join_ref,
                                    None,
                                    join.topic,
                                    "redirect",
                                    {"to": target},
                                )
                                return
                            target_route = _resolve_navigate(registry, session, target)
                            if target_route is None:
                                await _send(
                                    socket,
                                    join.join_ref,
                                    None,
                                    join.topic,
                                    "redirect",
                                    {"to": target},
                                )
                                return
                            await _send(
                                socket,
                                join.join_ref,
                                None,
                                join.topic,
                                "live_redirect",
                                {"kind": kind, "to": target},
                            )
                            if info_task is None:
                                raise LiveViewError(
                                    "LiveView receive tasks are missing"
                                )
                            if incoming_task is not None:
                                incoming_task.cancel()
                                await asyncio.gather(
                                    incoming_task, return_exceptions=True
                                )
                                incoming_task = None
                            join_source = incoming_message_task()
                            info_task.cancel()
                            await asyncio.gather(info_task, return_exceptions=True)
                            info_task = None
                            await close_current_page()
                            break
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
                    page._detach_liveview()
                tasks = [
                    task
                    for task in (incoming_task, info_task, join_source)
                    if task is not None
                ]
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                if page is not None or page_scope is not None:
                    try:
                        await close_current_page()
                    except Exception:
                        _LOGGER.exception("LiveView scope cleanup failed")

    LiveGateway.__module__ = __name__
    return websocket_gateway(websocket_path(options.socket_path))(LiveGateway)


__all__ = ["_Registry", "gateway_type", "initial_response"]

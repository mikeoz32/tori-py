from __future__ import annotations

import asyncio
import html
import inspect
import json
import logging
import re
import sys
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from functools import partial
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
from tori_py.http import HttpContext, HttpException, HttpResponse

from tori_py_liveview._diff import _RenderState
from tori_py_liveview.errors import (
    LiveViewConfigurationError,
    LiveViewError,
    UnknownEventError,
)
from tori_py_liveview.metadata import LiveViewMetadata
from tori_py_liveview.options import LiveViewOptions, normalize_origin, websocket_path
from tori_py_liveview.page import (
    _ROOT_VIEW_ID,
    LiveView,
    MountContext,
    _AsyncTask,
    _Info,
    _json_object,
    _UnknownComponentError,
)
from tori_py_liveview.rendering import (
    Rendered,
    _ChildRendered,
    _dynamic_html,
)
from tori_py_liveview.routing import (
    CompiledLiveRoute,
    LiveRoute,
    compile_live_routes,
    match_live_url,
    redirect_host_allowed,
    same_origin,
)
from tori_py_liveview.tokens import (
    ChildTokenCodec,
    FlashTokenCodec,
    InvalidMountTokenError,
    MountTokenCodec,
    ReloadTokenCodec,
    new_view_nonce,
)

_LOGGER = logging.getLogger(__name__)
_LIVEVIEW_VERSION = "1.2.11"
_ROOT_ID = _ROOT_VIEW_ID
_TOPIC = f"lv:{_ROOT_ID}"
# Child LiveViews may nest this deep under the main view.
_MAX_CHILD_DEPTH = 8
_MAX_SAFE_INTEGER = 2**53 - 1
# The official client stores a redirect's flash token in this cookie for 60s.
_FLASH_COOKIE = "__phoenix_flash__"
_FLASH_COOKIE_MAX_AGE = 60
# The official client stores a `reload` join error's token here before reloading.
_RELOAD_COOKIE = "__phoenix_reload_status__"


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


def _child_signer(
    codec: ChildTokenCodec,
    pages: Mapping[str, type[LiveView]],
    *,
    parent_id: str,
    parent_nonce: str,
    resource: str,
    session: str,
) -> Callable[[type[LiveView], str, Mapping[str, str]], str]:
    """Sign child views a page renders; only registered pages may be children.

    The tokens bind to this mount of the page through ``parent_nonce``.
    """
    identities = {page_type: identity for identity, page_type in pages.items()}

    def sign(page_type: type[LiveView], view_id: str, params: Mapping[str, str]) -> str:
        identity = identities.get(page_type)
        if identity is None:
            raise LiveViewError(
                f"child LiveView {page_type.__qualname__} is not registered with "
                "LiveViewModule"
            )
        return codec.sign(
            identity, view_id, parent_id, parent_nonce, params, resource, session
        )

    return sign


def _child_containers(rendered: Rendered) -> list[_ChildRendered]:
    children: list[_ChildRendered] = []
    for value in rendered.dynamics:
        if isinstance(value, _ChildRendered):
            children.append(value)
        elif isinstance(value, Rendered):
            children.extend(_child_containers(value))
    return children


def _html_with_children(rendered: Rendered, contents: Mapping[str, str]) -> str:
    """Render HTML with each child view's disconnected render in its container."""
    parts: list[str] = []
    for index, static in enumerate(rendered.statics):
        parts.append(static)
        if index == len(rendered.dynamics):
            break
        value = rendered.dynamics[index]
        if isinstance(value, _ChildRendered):
            parts.append(f"{value.open_tag}{contents[value.view_id]}</div>")
        elif isinstance(value, Rendered):
            parts.append(_html_with_children(value, contents))
        else:
            parts.append(_dynamic_html(value))
    return "".join(parts)


def _resource(request: Request) -> str:
    path = request.url.path
    query = request.url.query
    return path if not query else f"{path}?{query}"


def _render_payload(
    page: LiveView,
    rendered: Rendered,
    state: _RenderState,
) -> dict[str, object]:
    """Encode a render's changes and consume its stream, event, and flash effects."""
    payload = state.encode(rendered, page.title())
    page._clear_liveview_stream_operations()
    page._take_liveview_flash_changes()
    events = page._take_liveview_events()
    if events:
        payload["e"] = events
    return payload


@dataclass(eq=False, slots=True)
class _View:
    """One joined LiveView channel: the main view or a child view."""

    view_id: str
    join: _ChannelMessage
    page: LiveView
    render_state: _RenderState
    name: str
    # The mount nonce the tokens of this view's children bind to.
    nonce: str
    parent_id: str | None = None
    # A child view runs on a task of its own; the main view needs none.
    task: _ChildTask | None = None
    info_task: asyncio.Task[_Info | _AsyncTask] | None = None


@dataclass(frozen=True, slots=True)
class _SiteFlash:
    """Sign navigation flash for one connection's own site."""

    codec: FlashTokenCodec
    host: str
    scheme: str

    def follows(self, target: str) -> bool:
        # Flash leaving the site would sit in the cookie for the next page.
        return same_origin(self.host, target, scheme=self.scheme)


def _with_flash(
    navigation: dict[str, object],
    flash: Mapping[str, str],
    site: _SiteFlash,
) -> dict[str, object]:
    """Attach the flash put before a navigation as a signed Phoenix flash token."""
    target = navigation["to"]
    if flash and isinstance(target, str) and site.follows(target):
        navigation["flash"] = site.codec.sign(flash)
    return navigation


def _cookie(name: str, value: str, *, max_age: int, secure: bool) -> str:
    # Not HttpOnly: the official client writes these cookies with
    # document.cookie, which cannot replace an HttpOnly cookie of the same name.
    cookie = f"{name}={value}; Max-Age={max_age}; Path=/; SameSite=Lax"
    return f"{cookie}; Secure" if secure else cookie


def _first_mount(connect_params: Mapping[str, object]) -> bool:
    mounts = connect_params.get("_mounts")
    return type(mounts) is int and mounts == 0


async def initial_response(
    context: HttpContext,
    page_type: type[LiveView],
    options: LiveViewOptions,
    route: LiveViewMetadata,
    hooks: tuple[Callable[..., object], ...] = (),
    compiled: tuple[CompiledLiveRoute, ...] = (),
    *,
    scopes: WorkScopeFactory,
    pages: Mapping[str, type[LiveView]],
) -> HttpResponse:
    request = cast(Request, context.request)
    flash_codec = FlashTokenCodec(options.secret)
    child_codec = ChildTokenCodec(options.secret, max_age_ms=options.token_max_age_ms)
    flash_cookie = request.cookies.get(_FLASH_COOKIE)
    secure = request.url.scheme == "https"
    identity = f"{page_type.__module__}.{page_type.__qualname__}"
    resource = _resource(request)
    reload_status = ReloadTokenCodec(options.secret).verify(
        request.cookies.get(_RELOAD_COOKIE), identity, resource
    )
    if reload_status is not None:
        # The connected mount of this page failed after this request's HTTP
        # mount succeeded; answering with its error ends the reload loop.
        raise HttpException(
            reload_status,
            "The live page could not be mounted.",
            headers={
                "set-cookie": _cookie(_RELOAD_COOKIE, "", max_age=0, secure=secure)
            },
        )
    query = QueryParams(resource.partition("?")[2])
    # The official client joins children with the tokens of their parent's
    # connected render, so the tokens of this render never join.
    root_nonce = new_view_nonce()

    def signer(
        parent_id: str, parent_nonce: str
    ) -> Callable[[type[LiveView], str, Mapping[str, str]], str]:
        return _child_signer(
            child_codec,
            pages,
            parent_id=parent_id,
            parent_nonce=parent_nonce,
            resource=resource,
            session=route.session,
        )

    async def render_html(rendered: Rendered, depth: int) -> str:
        contents: dict[str, str] = {}
        for child in _child_containers(rendered):
            contents[child.view_id] = await render_child(child, depth + 1)
        return _html_with_children(rendered, contents)

    async def render_child(child: _ChildRendered, depth: int) -> str:
        if depth > _MAX_CHILD_DEPTH:
            raise LiveViewError("child LiveViews are nested too deeply")
        # Each child gets its own scope, so two children of one type stay apart.
        child_scope, child_page = await _open_page(
            scopes, cast(type[LiveView], child.page_type)
        )
        try:
            child_page._liveview_view_id = child.view_id
            child_page._liveview_child_signer = signer(
                child.view_id, child_codec.verify(child.session).nonce
            )
            child_page._set_liveview_flash({})
            await child_page._mount_liveview(
                MountContext(request, dict(child.params), resource, False, query)
            )
            if child_page._take_liveview_pending_redirect() is not None:
                raise LiveViewError(
                    "child LiveViews cannot navigate during the HTTP render"
                )
            return await render_html(await _render(child_page), depth)
        finally:
            try:
                await child_page._disconnect_liveview_components()
            finally:
                await child_scope.__aexit__(None, None, None)

    page = cast(LiveView, await context.resolver.resolve(page_type))
    try:
        page._liveview_action = route.action
        page._liveview_child_signer = signer(_ROOT_ID, root_nonce)
        page._set_liveview_flash(flash_codec.verify(flash_cookie))
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
            identity,
            route.session,
            host=request.headers.get("host", ""),
            scheme=request.url.scheme,
            redirect_hosts=options.redirect_hosts,
        )
        if drained is not None and drained[0] != "patch":
            redirect_headers = {"location": drained[1]}
            # Nothing has displayed the page yet, so all of its flash, including
            # flash received from the previous page, follows the redirect, as
            # long as the redirect stays on this site.
            site = _SiteFlash(
                flash_codec, request.headers.get("host", ""), request.url.scheme
            )
            flash = dict(page.flash) if site.follows(drained[1]) else {}
            if flash:
                redirect_headers["set-cookie"] = _cookie(
                    _FLASH_COOKIE,
                    flash_codec.sign(flash),
                    max_age=_FLASH_COOKIE_MAX_AGE,
                    secure=secure,
                )
            elif flash_cookie is not None:
                redirect_headers["set-cookie"] = _cookie(
                    _FLASH_COOKIE, "", max_age=0, secure=secure
                )
            return HttpResponse(b"", status_code=302, headers=redirect_headers)
        token = MountTokenCodec(
            options.secret,
            max_age_ms=options.token_max_age_ms,
        ).sign(
            identity,
            params,
            resource,
            route.action,
            route.session,
            flash=page.flash,
        )
        root = (
            f'<div id="{_ROOT_ID}" data-phx-main '
            f'data-phx-session="{html.escape(token, quote=True)}" '
            'data-phx-static="" '
            f'data-tori-live-socket="{html.escape(options.socket_path, quote=True)}">'
            f"{await render_html(await _render(page), 0)}</div>"
        )
        client_script = (
            "<script defer "
            f'src="{html.escape(options.client_path, quote=True)}"></script>'
        )
        document = page.render_document(root, client_script)
        headers = {
            "content-type": "text/html; charset=utf-8",
            "cache-control": "no-store",
        }
        if flash_cookie is not None:
            headers["set-cookie"] = _cookie(_FLASH_COOKIE, "", max_age=0, secure=secure)
        return HttpResponse(document.encode(), headers=headers)
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


type _Call = tuple[Callable[[], Awaitable[object]], asyncio.Future[object]]


class _ChildTask:
    """Run one child view's scope and callbacks on a task of its own.

    Entering a work scope makes it the active scope in the entering task's
    context, and only that task may resolve from it. The main view's scope
    stays on the gateway task, so each child opens, uses, and closes its scope
    on its own task, where its scoped interceptors and dependencies see that
    scope rather than whichever view opened one last. The gateway awaits every
    call, so the views of one connection still run one at a time.
    """

    __slots__ = ("_calls", "_ended", "_page", "_scope", "_task")

    def __init__(self) -> None:
        self._calls: asyncio.Queue[_Call | None] = asyncio.Queue()
        self._ended = False
        self._page: LiveView | None = None
        self._scope: AbstractAsyncContextManager[ScopedResolver] | None = None
        self._task = asyncio.create_task(self._serve())

    async def open(
        self, scopes: WorkScopeFactory, page_type: type[LiveView]
    ) -> LiveView:
        """Open the child's scope and resolve its page on the child's task."""

        async def open_page() -> LiveView:
            self._scope, self._page = await _open_page(scopes, page_type)
            return self._page

        return await self.call(open_page)

    async def call[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        """Run one operation on the child's task and return its result."""
        if self._ended:
            raise LiveViewError("the child LiveView has ended")
        result: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        self._calls.put_nowait((operation, result))
        try:
            return cast(T, await result)
        except asyncio.CancelledError:
            # The connection is going away, so the child stops with it.
            self._task.cancel()
            raise

    async def close(self) -> None:
        """Disconnect the page and close its scope on the child's task."""
        self._calls.put_nowait(None)
        # Waiting does not cancel the task, so its cleanup finishes regardless.
        await asyncio.wait((self._task,))
        if not self._task.cancelled() and (error := self._task.exception()):
            raise error

    async def _serve(self) -> None:
        try:
            while (call := await self._calls.get()) is not None:
                operation, result = call
                try:
                    value = await operation()
                except asyncio.CancelledError:
                    if not result.done():
                        result.set_exception(
                            LiveViewError("the child LiveView was cancelled")
                        )
                    raise
                except BaseException as error:
                    if not result.done():
                        result.set_exception(error)
                    if not isinstance(error, Exception):
                        raise
                else:
                    if not result.done():
                        result.set_result(value)
        finally:
            self._ended = True
            while not self._calls.empty():
                pending = self._calls.get_nowait()
                if pending is not None and not pending[1].done():
                    pending[1].set_exception(
                        LiveViewError("the child LiveView has ended")
                    )
            page, scope = self._page, self._scope
            self._page = self._scope = None
            await _close_page(page, scope)


async def _drain_navigation(
    page: LiveView,
    compiled: tuple[CompiledLiveRoute, ...],
    page_identity: str,
    session: str,
    *,
    host: str,
    scheme: str,
    redirect_hosts: tuple[str, ...],
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
        if navigation == "redirect" and not redirect_host_allowed(
            host, target, redirect_hosts
        ):
            raise LiveViewError("redirect target host is not allowed")
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
    flash_codec = FlashTokenCodec(options.secret)
    reload_codec = ReloadTokenCodec(options.secret)
    child_codec = ChildTokenCodec(options.secret, max_age_ms=options.token_max_age_ms)
    mount_codec = MountTokenCodec(options.secret, max_age_ms=options.token_max_age_ms)

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
            site_flash = _SiteFlash(flash_codec, origin_host, origin_scheme)
            page: LiveView | None = None
            page_scope: AbstractAsyncContextManager[ScopedResolver] | None = None
            incoming_task: asyncio.Task[_ChannelMessage] | None = None
            info_task: asyncio.Task[_Info | _AsyncTask] | None = None
            join_source: asyncio.Task[_ChannelMessage] | None = None
            # Child views joined under the main view, by view id.
            children: dict[str, _View] = {}
            first_join = True
            name = ""
            session = ""
            resource = ""
            root_nonce = ""

            def incoming_message_task() -> asyncio.Task[_ChannelMessage]:
                return asyncio.create_task(
                    _message(
                        socket,
                        timeout=options.idle_timeout_seconds,
                        timeout_code=1001,
                        max_message_bytes=options.max_message_bytes,
                    )
                )

            async def close_children(view_ids: list[str]) -> None:
                """Close every child view in turn, even when one fails to close.

                The first failure is raised once all of them closed; any later
                ones are logged.
                """
                failure: Exception | None = None
                for view_id in view_ids:
                    try:
                        await close_child(view_id)
                    except Exception as error:
                        if failure is None:
                            failure = error
                        else:
                            _LOGGER.exception("LiveView child cleanup failed")
                if failure is not None:
                    raise failure

            async def close_child(view_id: str) -> None:
                child = children.pop(view_id, None)
                if child is None:
                    return
                try:
                    # A child's own children end first.
                    await close_children(
                        [
                            view.view_id
                            for view in children.values()
                            if view.parent_id == view_id
                        ]
                    )
                finally:
                    if child.info_task is not None:
                        child.info_task.cancel()
                        await asyncio.gather(child.info_task, return_exceptions=True)
                    if child.task is not None:
                        await child.task.close()

            async def close_current_page() -> None:
                nonlocal page, page_scope
                closing_page = page
                closing_scope = page_scope
                page = None
                page_scope = None
                try:
                    # Child views end with the main view that rendered them.
                    await close_children(list(reversed(children)))
                finally:
                    await _close_page(closing_page, closing_scope)

            async def drain(view: _View) -> tuple[str, str, str] | None:
                return await _drain_navigation(
                    view.page,
                    registry.compiled,
                    view.name,
                    session,
                    host=origin_host,
                    scheme=origin_scheme,
                    redirect_hosts=options.redirect_hosts,
                )

            async def deliver(
                view: _View,
                message: _ChannelMessage | None,
                drained: tuple[str, str, str] | None,
                reply_payload: dict[str, object] | None = None,
            ) -> str:
                """Render a view's changes, or send its navigation.

                Returns ``continue``, ``navigated`` for a live redirect, or
                ``redirect`` for a full page load.
                """
                join_ref, topic = view.join.join_ref, view.join.topic
                if drained is None or drained[0] == "patch":
                    diff = _render_payload(
                        view.page, await _render(view.page), view.render_state
                    )
                    if reply_payload is not None:
                        diff["r"] = reply_payload
                    if drained is not None:
                        _, patch_to, patch_kind = drained
                        await _send(
                            socket,
                            join_ref,
                            None,
                            topic,
                            "live_patch",
                            {"kind": patch_kind, "to": patch_to},
                        )
                    if message is not None:
                        await _reply(socket, message, "ok", {"diff": diff})
                    elif diff:
                        # Like Phoenix, push nothing when nothing changed.
                        await _send(socket, join_ref, None, topic, "diff", diff)
                    return "continue"
                navigation, target, kind = drained
                flash = view.page._take_liveview_flash_changes()
                if navigation == "redirect" or (
                    _resolve_navigate(registry, session, target) is None
                ):
                    event = "redirect"
                    payload = _with_flash({"to": target}, flash, site_flash)
                else:
                    event = "live_redirect"
                    payload = _with_flash(
                        {"kind": kind, "to": target}, flash, site_flash
                    )
                if message is not None:
                    await _reply(socket, message, "ok", {event: payload})
                else:
                    await _send(socket, join_ref, None, topic, event, payload)
                return "redirect" if event == "redirect" else "navigated"

            async def run_event(view: _View, message: _ChannelMessage) -> str:
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
                target = None if target_value is None else _positive_int(target_value)
                try:
                    reply = await view.page._handle_liveview_event(
                        target, event, _event_value(message.payload)
                    )
                except _UnknownComponentError:
                    view.page._discard_liveview_effects()
                    await _reply(socket, message, "ok", {"reason": "unknown_target"})
                    return "continue"
                except UnknownEventError:
                    view.page._discard_liveview_effects()
                    await _reply(socket, message, "ok", {"reason": "unknown_event"})
                    return "continue"
                reply_payload = (
                    None
                    if reply is None
                    else _json_object("LiveView event reply", reply)
                )
                return await deliver(view, message, await drain(view), reply_payload)

            async def run_info(view: _View, server_message: _Info | _AsyncTask) -> str:
                if isinstance(server_message, _Info):
                    try:
                        await view.page.handle_info(
                            server_message.name, server_message.value
                        )
                    except Exception as error:
                        _LOGGER.exception(
                            "LiveView info failed: page=%s info=%s",
                            type(view.page).__qualname__,
                            server_message.name,
                        )
                        raise _CloseConnection(1011) from error
                else:
                    try:
                        delivered = await view.page._settle_liveview_async(
                            server_message
                        )
                    except Exception as error:
                        _LOGGER.exception(
                            "LiveView async result failed: owner=%s async=%s",
                            type(server_message.owner).__qualname__,
                            server_message.name,
                        )
                        raise _CloseConnection(1011) from error
                    if not delivered:
                        return "continue"
                return await deliver(view, None, await drain(view))

            async def run_live_patch(view: _View, message: _ChannelMessage) -> str:
                patch_url = message.payload.get("url")
                if (
                    not isinstance(patch_url, str)
                    or not patch_url
                    or not _url_allowed(socket, patch_url)
                ):
                    raise _CloseConnection(1002)
                patch_resolved = match_live_url(registry.compiled, patch_url)
                if (
                    patch_resolved is None
                    or patch_resolved[0].page != view.name
                    or patch_resolved[0].session != session
                ):
                    await _reply(socket, message, "ok", {"link_redirect": True})
                    return "continue"
                patch_route, patch_params, patch_uri = patch_resolved
                view.page._liveview_action = patch_route.action
                await view.page.handle_params(patch_params, patch_uri)
                return await deliver(view, message, await drain(view))

            async def join_child(message: _ChannelMessage, view_id: str) -> None:
                token = message.payload.get("session")
                connect_params = message.payload.get("params", {})
                flash_token = message.payload.get("flash")
                if (
                    message.join_ref is None
                    or message.join_ref != message.ref
                    or view_id == _ROOT_ID
                    or view_id in children
                    or not isinstance(token, str)
                    or not isinstance(connect_params, dict)
                    or not isinstance(flash_token, str | None)
                ):
                    raise _CloseConnection(1002)
                try:
                    child_token = child_codec.verify(token)
                    child_type = registry.pages[child_token.page]
                except InvalidMountTokenError, KeyError:
                    await _reply(socket, message, "error", {"reason": "unauthorized"})
                    return
                # A child joins only under the very mount of a view joined on
                # this connection that rendered it, not any view with that id.
                parent = children.get(child_token.parent_id)
                parent_nonce = (
                    root_nonce
                    if child_token.parent_id == _ROOT_ID
                    else None
                    if parent is None
                    else parent.nonce
                )
                if (
                    child_token.view_id != view_id
                    or child_token.session != session
                    or parent_nonce is None
                    or child_token.parent_nonce != parent_nonce
                ):
                    await _reply(socket, message, "error", {"reason": "unauthorized"})
                    return
                child_task = _ChildTask()
                try:
                    child_page = await child_task.open(self._scopes, child_type)
                except BaseException:
                    await child_task.close()
                    raise
                child = _View(
                    view_id,
                    message,
                    child_page,
                    _RenderState(main=False),
                    child_token.page,
                    child_token.nonce,
                    parent_id=child_token.parent_id,
                    task=child_task,
                )
                child_page._liveview_view_id = view_id
                child_page._liveview_child_signer = _child_signer(
                    child_codec,
                    registry.pages,
                    parent_id=view_id,
                    parent_nonce=child_token.nonce,
                    resource=child_token.resource,
                    session=session,
                )
                child_page._set_liveview_flash(
                    {} if flash_token is None else flash_codec.verify(flash_token)
                )
                child_page._connect_liveview(
                    async_cancel_timeout=options.async_cancel_timeout_seconds
                )
                mount_context = MountContext(
                    socket,
                    child_token.params,
                    child_token.resource,
                    True,
                    QueryParams(child_token.resource.partition("?")[2]),
                    cast(dict[str, object], connect_params),
                )

                async def mount_child() -> tuple[
                    tuple[str, str, str] | None, dict[str, object] | None
                ]:
                    await child_page._mount_liveview(mount_context)
                    drained = await drain(child)
                    if drained is not None:
                        return drained, None
                    return None, _render_payload(
                        child_page, await _render(child_page), child.render_state
                    )

                try:
                    drained, rendered = await child_task.call(mount_child)
                except HttpException as error:
                    await child_task.close()
                    if not 400 <= error.status_code < 500:
                        raise
                    # The reload renders the main page, which answers with this
                    # error, as Phoenix does for any view's connected mount.
                    await _reply(
                        socket,
                        message,
                        "error",
                        {
                            "reason": "reload",
                            "status": error.status_code,
                            "token": reload_codec.sign(
                                name, resource, error.status_code
                            ),
                        },
                    )
                    return
                except BaseException:
                    await child_task.close()
                    raise
                if drained is not None:
                    navigation, target, kind = drained
                    # The child never rendered, so its whole flash travels on.
                    flash = dict(child_page.flash)
                    await child_task.close()
                    error_payload: dict[str, object]
                    if navigation == "navigate" and (
                        _resolve_navigate(registry, session, target) is not None
                    ):
                        error_payload = {
                            "live_redirect": _with_flash(
                                {"kind": kind, "to": target}, flash, site_flash
                            )
                        }
                    else:
                        error_payload = {
                            "redirect": _with_flash({"to": target}, flash, site_flash)
                        }
                    await _reply(socket, message, "error", error_payload)
                    return
                child.info_task = asyncio.create_task(
                    child_page._receive_liveview_info()
                )
                children[view_id] = child
                await _reply(
                    socket,
                    message,
                    "ok",
                    {"rendered": rendered, "liveview_version": _LIVEVIEW_VERSION},
                )

            async def run_child_event(child: _View, message: _ChannelMessage) -> str:
                """Handle a child's channel event; runs on the child's task."""
                if message.event == "cids_will_destroy":
                    child.page._prepare_liveview_component_destruction(
                        _destroyed_cids(message.payload)
                    )
                    await _reply(socket, message, "ok", {})
                    return "continue"
                if message.event == "cids_destroyed":
                    destroyed = await child.page._destroy_liveview_components(
                        _destroyed_cids(message.payload)
                    )
                    child.render_state.forget(destroyed)
                    await _reply(socket, message, "ok", {"cids": destroyed})
                    return "continue"
                return await run_event(child, message)

            async def run_child_message(message: _ChannelMessage) -> str:
                if not message.topic.startswith("lv:") or message.ref is None:
                    raise _CloseConnection(1002)
                view_id = message.topic.removeprefix("lv:")
                if message.event == "phx_join":
                    await join_child(message, view_id)
                    return "continue"
                child = children.get(view_id)
                if child is None or message.join_ref != child.join.join_ref:
                    # The view already left or navigated away; Phoenix answers
                    # other messages for a topic it does not hold the same way.
                    if message.event == "phx_leave":
                        await _reply(socket, message, "ok", {})
                    else:
                        await _reply(
                            socket, message, "error", {"reason": "unmatched topic"}
                        )
                    return "continue"
                if message.event == "phx_leave":
                    await _reply(socket, message, "ok", {})
                    await close_child(view_id)
                    return "continue"
                if message.event not in {
                    "cids_will_destroy",
                    "cids_destroyed",
                    "event",
                }:
                    raise _CloseConnection(1002)
                outcome = await cast(_ChildTask, child.task).call(
                    partial(run_child_event, child, message)
                )
                if outcome == "navigated":
                    # The client now replaces the main view; this child is done.
                    await close_child(view_id)
                return outcome

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
                    # After a join error the official client leaves that join
                    # more than once (from the error handler and again when it
                    # replaces the view), and its 30 second heartbeat may land
                    # between joins, so acknowledge both until the next join;
                    # the idle deadline still bounds the wait. The first join
                    # must arrive within the join deadline with nothing before.
                    while not first_join and (
                        (join.topic.startswith("lv:") and join.event == "phx_leave")
                        or (join.topic == "phoenix" and join.event == "heartbeat")
                    ):
                        if join.topic == "phoenix" and (
                            join.join_ref is not None or join.ref is None
                        ):
                            raise _CloseConnection(1002)
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
                    connect_params = join.payload.get("params", {})
                    flash_token = join.payload.get("flash")
                    if (
                        join.event != "phx_join"
                        or join.topic != _TOPIC
                        or join.join_ref is None
                        or join.join_ref != join.ref
                        or not isinstance(token, str)
                        or not isinstance(connect_params, dict)
                        or not isinstance(flash_token, str | None)
                    ):
                        raise _CloseConnection(1002)
                    connect_params = cast(dict[str, object], connect_params)
                    try:
                        mounted = mount_codec.verify(token)
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

                    # A navigation's flash token wins. The disconnected render's
                    # flash shows only on the first mount of the HTTP page, not
                    # on reconnects or live navigation.
                    if flash_token is not None:
                        initial_flash = flash_codec.verify(flash_token)
                    elif redirect_url is None and _first_mount(connect_params):
                        initial_flash = mounted.flash
                    else:
                        initial_flash = {}
                    name = live_route.page
                    session = live_route.session
                    # Each join mounts the page afresh, and the child tokens it
                    # renders bind to this mount alone, as Phoenix binds them to
                    # the parent process. The official client joins children,
                    # also after a reconnect, with the tokens of the latest join.
                    root_nonce = new_view_nonce()
                    page_scope, root_page = await _open_page(self._scopes, page_type)
                    page = root_page
                    # Each join starts the client's render tree afresh.
                    render_state = _RenderState()
                    root_page._liveview_action = action
                    root_page._liveview_child_signer = _child_signer(
                        child_codec,
                        registry.pages,
                        parent_id=_ROOT_ID,
                        parent_nonce=root_nonce,
                        resource=resource,
                        session=session,
                    )
                    root_page._set_liveview_flash(initial_flash)
                    root_page._connect_liveview(
                        async_cancel_timeout=options.async_cancel_timeout_seconds
                    )
                    mount_context = MountContext(
                        socket,
                        mount_params,
                        resource,
                        True,
                        QueryParams(resource.partition("?")[2]),
                        connect_params,
                    )
                    try:
                        await _run_on_mount(
                            registry.sessions.get(session, ()), root_page, mount_context
                        )
                        await root_page._mount_liveview(mount_context)
                        await root_page.handle_params(join_params, uri)
                        drained = await _drain_navigation(
                            root_page,
                            registry.compiled,
                            name,
                            session,
                            host=origin_host,
                            scheme=origin_scheme,
                            redirect_hosts=options.redirect_hosts,
                        )
                        navigating = drained is not None and drained[0] != "patch"
                        rendered = (
                            {}
                            if navigating
                            else _render_payload(
                                root_page, await _render(root_page), render_state
                            )
                        )
                    except HttpException as error:
                        # Phoenix reloads the page so the HTTP pipeline renders
                        # the client error the connected mount raised, whether
                        # from mounting, a patch the mount queued, or the join
                        # render.
                        if not 400 <= error.status_code < 500:
                            raise
                        await close_current_page()
                        # The client stores the token in the reload cookie, so
                        # the reloaded HTTP render answers with this error even
                        # when its own disconnected mount would succeed.
                        reload_token = reload_codec.sign(
                            name, resource, error.status_code
                        )
                        await _reply(
                            socket,
                            join,
                            "error",
                            {
                                "reason": "reload",
                                "status": error.status_code,
                                "token": reload_token,
                            },
                        )
                        return
                    if drained is not None and drained[0] != "patch":
                        navigation, target, kind = drained
                        # This connected page never rendered, so its whole flash,
                        # including a navigation's incoming flash, travels on.
                        flash = dict(root_page.flash)
                        await close_current_page()
                        if navigation == "navigate":
                            target_route = _resolve_navigate(registry, session, target)
                            if target_route is not None:
                                await _reply(
                                    socket,
                                    join,
                                    "error",
                                    {
                                        "live_redirect": _with_flash(
                                            {"kind": kind, "to": target},
                                            flash,
                                            site_flash,
                                        )
                                    },
                                )
                                continue
                        await _reply(
                            socket,
                            join,
                            "error",
                            {
                                "redirect": _with_flash(
                                    {"to": target}, flash, site_flash
                                )
                            },
                        )
                        return
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

                    root = _View(
                        _ROOT_ID, join, root_page, render_state, name, root_nonce
                    )
                    incoming_task = incoming_message_task()
                    info_task = asyncio.create_task(root_page._receive_liveview_info())
                    while True:
                        if incoming_task is None:
                            incoming_task = incoming_message_task()
                        if info_task is None:
                            raise LiveViewError("LiveView info task is missing")
                        child_tasks = {
                            child.info_task: child
                            for child in children.values()
                            if child.info_task is not None
                        }
                        done, _ = await asyncio.wait(
                            (incoming_task, info_task, *child_tasks),
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
                            if message.topic != _TOPIC:
                                if await run_child_message(message) == "redirect":
                                    return
                                continue
                            if message.join_ref != join.join_ref or message.ref is None:
                                raise _CloseConnection(1002)
                            if message.event == "phx_leave":
                                await _reply(socket, message, "ok", {})
                                outcome = "left"
                            elif message.event == "cids_will_destroy":
                                root_page._prepare_liveview_component_destruction(
                                    _destroyed_cids(message.payload)
                                )
                                await _reply(socket, message, "ok", {})
                                continue
                            elif message.event == "cids_destroyed":
                                destroyed = (
                                    await root_page._destroy_liveview_components(
                                        _destroyed_cids(message.payload)
                                    )
                                )
                                # The client prunes exactly the CIDs in this reply.
                                render_state.forget(destroyed)
                                await _reply(socket, message, "ok", {"cids": destroyed})
                                continue
                            elif message.event == "live_patch":
                                outcome = await run_live_patch(root, message)
                            elif message.event == "event":
                                outcome = await run_event(root, message)
                            else:
                                raise _CloseConnection(1002)
                        elif info_task in done:
                            server_message = info_task.result()
                            info_task = asyncio.create_task(
                                root_page._receive_liveview_info()
                            )
                            outcome = await run_info(root, server_message)
                        else:
                            child = next(
                                child
                                for task, child in child_tasks.items()
                                if task in done
                            )
                            server_message = cast(
                                asyncio.Task[_Info | _AsyncTask], child.info_task
                            ).result()
                            child.info_task = asyncio.create_task(
                                child.page._receive_liveview_info()
                            )
                            outcome = await cast(_ChildTask, child.task).call(
                                partial(run_info, child, server_message)
                            )
                            if outcome == "navigated":
                                await close_child(child.view_id)
                                continue
                        if outcome == "redirect":
                            return
                        if outcome == "continue":
                            continue
                        # The main view left or navigated: wait for the next join.
                        info_task.cancel()
                        await asyncio.gather(info_task, return_exceptions=True)
                        info_task = None
                        join_source = (
                            incoming_task
                            if incoming_task is not None
                            else incoming_message_task()
                        )
                        incoming_task = None
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

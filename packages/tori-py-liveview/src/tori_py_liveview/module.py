from __future__ import annotations

from collections.abc import Callable, Iterable
from importlib.resources import files
from typing import Annotated

from tori_py import (
    ClassProvider,
    Context,
    DeferredModule,
    ModuleImport,
    ModuleSpec,
    Scope,
    ValueProvider,
    controller,
    get,
)
from tori_py.http import HttpContext, HttpResponse

from tori_py_liveview.endpoint import _Registry, gateway_type, initial_response
from tori_py_liveview.errors import LiveViewConfigurationError
from tori_py_liveview.metadata import LiveViewMetadata
from tori_py_liveview.options import LiveViewOptions, websocket_path
from tori_py_liveview.page import LiveView
from tori_py_liveview.routing import CompiledLiveRoute, LiveRoute
from tori_py_liveview.session import LiveSession, normalize_sessions

_STATIC = files("tori_py_liveview").joinpath("static")
_PHOENIX = _STATIC.joinpath("phoenix-1.8.13.min.js").read_bytes()
_PHOENIX_LIVE_VIEW = _STATIC.joinpath("phoenix_live_view-1.2.11.min.js").read_bytes()
_BOOTSTRAP = b"""
;(() => {
  const root = document.querySelector("[data-phx-session][data-tori-live-socket]");
  if (!root) return;
  const liveSocket = new LiveView.LiveSocket(
    root.dataset.toriLiveSocket,
    Phoenix.Socket,
  );
  liveSocket.connect();
  globalThis.liveSocket = liveSocket;
})();
"""
_CLIENT = b"\n".join((_PHOENIX, _PHOENIX_LIVE_VIEW, _BOOTSTRAP))


def _routes(page: type[object]) -> tuple[LiveViewMetadata, ...]:
    routes = page.__dict__.get("__tori_py_liveview_routes__")
    if not isinstance(routes, tuple) or not routes:
        raise LiveViewConfigurationError("pages require an explicit @live_view(path)")
    return routes


def _metadata(page: type[object]) -> LiveViewMetadata:
    return _routes(page)[0]


def _page_controller(
    page: type[LiveView],
    route: LiveViewMetadata,
    options: LiveViewOptions,
    hooks: tuple[Callable[..., object], ...],
    compiled: tuple[CompiledLiveRoute, ...],
) -> type[object]:
    class PageController:
        async def initial(
            self, context: Annotated[HttpContext, Context()]
        ) -> HttpResponse:
            return await initial_response(
                context, page, options, route, hooks, compiled
            )

    PageController.__module__ = __name__
    get(route.path)(PageController.initial)
    return controller()(PageController)


def _asset_controller(options: LiveViewOptions) -> type[object]:
    class AssetController:
        async def client(
            self, context: Annotated[HttpContext, Context()]
        ) -> HttpResponse:
            del context
            return HttpResponse(
                _CLIENT, headers={"content-type": "text/javascript; charset=utf-8"}
            )

    AssetController.__module__ = __name__
    get(options.client_path)(AssetController.client)
    return controller()(AssetController)


class LiveViewModule:
    @classmethod
    def for_root(
        cls,
        options: LiveViewOptions,
        *,
        pages: Iterable[type[LiveView]],
        imports: Iterable[ModuleImport] = (),
        sessions: Iterable[LiveSession] = (),
        key: str = "default",
    ) -> DeferredModule:
        if not isinstance(options, LiveViewOptions):
            raise LiveViewConfigurationError("options must be LiveViewOptions")
        try:
            declared = tuple(pages)
            imported = tuple(imports)
        except TypeError as error:
            raise LiveViewConfigurationError(
                "pages and imports must be iterable"
            ) from error
        if not declared:
            raise LiveViewConfigurationError("at least one LiveView page is required")
        known_sessions = normalize_sessions(sessions)
        paths: set[str] = set()
        registry: dict[str, type[LiveView]] = {}
        live_routes: list[LiveRoute] = []
        seen_pages: list[type[LiveView]] = []
        for page in declared:
            if not isinstance(page, type) or not issubclass(page, LiveView):
                raise LiveViewConfigurationError("pages must be LiveView subclasses")
            identity = f"{page.__module__}.{page.__qualname__}"
            if identity in registry:
                raise LiveViewConfigurationError(
                    "page identities must be unique within a LiveView module"
                )
            registry[identity] = page
            seen_pages.append(page)
            for route in _routes(page):
                if route.path in paths or route.path in {
                    options.socket_path,
                    websocket_path(options.socket_path),
                    options.client_path,
                }:
                    raise LiveViewConfigurationError(
                        "page paths must be unique and not conflict "
                        "with LiveView endpoints"
                    )
                if route.session not in known_sessions and route.session != "":
                    raise LiveViewConfigurationError(
                        f"unknown session {route.session!r} for {route.path}"
                    )
                paths.add(route.path)
                live_routes.append(
                    LiveRoute(route.path, route.action, identity, route.session)
                )
        route_registry = _Registry(registry, tuple(live_routes), known_sessions)
        gateway = gateway_type(options, route_registry)
        controllers = tuple(
            _page_controller(
                page,
                route,
                options,
                known_sessions.get(route.session, ()),
                route_registry.compiled,
            )
            for page in seen_pages
            for route in _routes(page)
        ) + (_asset_controller(options),)

        def materialize() -> ModuleSpec:
            return ModuleSpec(
                imports=imported,
                providers=(
                    ValueProvider(LiveViewOptions, options),
                    *(ClassProvider(page, scope=Scope.REQUEST) for page in seen_pages),
                    ClassProvider(gateway),
                ),
                controllers=controllers,
            )

        return DeferredModule(cls, key, materialize)

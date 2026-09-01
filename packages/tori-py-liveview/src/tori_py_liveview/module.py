from __future__ import annotations

from collections.abc import Iterable
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


def _metadata(page: type[object]) -> LiveViewMetadata:
    metadata = page.__dict__.get("__tori_py_liveview_metadata__")
    if not isinstance(metadata, LiveViewMetadata):
        raise LiveViewConfigurationError("pages require an explicit @live_view(path)")
    return metadata


def _page_controller(page: type[LiveView], options: LiveViewOptions) -> type[object]:
    class PageController:
        async def initial(
            self, context: Annotated[HttpContext, Context()]
        ) -> HttpResponse:
            return await initial_response(context, page, options)

    PageController.__module__ = __name__
    get(_metadata(page).path)(PageController.initial)
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
        paths: set[str] = set()
        registry: dict[str, type[LiveView]] = {}
        for page in declared:
            if not isinstance(page, type) or not issubclass(page, LiveView):
                raise LiveViewConfigurationError("pages must be LiveView subclasses")
            metadata = _metadata(page)
            if metadata.path in paths or metadata.path in {
                options.socket_path,
                websocket_path(options.socket_path),
                options.client_path,
            }:
                raise LiveViewConfigurationError(
                    "page paths must be unique and not conflict with LiveView endpoints"
                )
            paths.add(metadata.path)
            identity = f"{page.__module__}.{page.__qualname__}"
            if identity in registry:
                raise LiveViewConfigurationError(
                    "page identities must be unique within a LiveView module"
                )
            registry[identity] = page
        gateway = gateway_type(options, _Registry(registry))
        controllers = tuple(_page_controller(page, options) for page in declared) + (
            _asset_controller(options),
        )

        def materialize() -> ModuleSpec:
            return ModuleSpec(
                imports=imported,
                providers=(
                    ValueProvider(LiveViewOptions, options),
                    *(ClassProvider(page, scope=Scope.REQUEST) for page in declared),
                    ClassProvider(gateway),
                ),
                controllers=controllers,
            )

        return DeferredModule(cls, key, materialize)

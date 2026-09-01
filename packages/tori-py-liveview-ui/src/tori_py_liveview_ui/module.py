"""The bundled stylesheet endpoint and themed LiveView base class."""

from __future__ import annotations

from hashlib import sha256
from importlib.resources import files

from tori_py import DeferredModule, ModuleSpec, controller, get
from tori_py.http import HttpResponse
from tori_py_liveview import LiveView, SafeHtml, raw

_STYLESHEET = (
    files("tori_py_liveview_ui").joinpath("static/tori_liveview_ui.css").read_bytes()
)
_STYLESHEET_DIGEST = sha256(_STYLESHEET).hexdigest()
STYLESHEET_PATH = f"/_tori/liveview-ui/{_STYLESHEET_DIGEST[:12]}.css"
_STYLESHEET_RESPONSE = HttpResponse(
    _STYLESHEET,
    headers={
        "content-type": "text/css; charset=utf-8",
        "cache-control": "public, max-age=31536000, immutable",
        "etag": f'"{_STYLESHEET_DIGEST}"',
    },
)


def stylesheet_link() -> SafeHtml:
    """Return the immutable stylesheet tag for a page document head."""
    return raw(f'<link rel="stylesheet" href="{STYLESHEET_PATH}">')


def _stylesheet_controller() -> type[object]:
    class StylesheetController:
        async def stylesheet(self) -> HttpResponse:
            return _STYLESHEET_RESPONSE

    StylesheetController.__module__ = __name__
    get(STYLESHEET_PATH)(StylesheetController.stylesheet)
    return controller()(StylesheetController)


class LiveViewUiModule:
    """Expose the immutable bundled UI stylesheet as a ToriPy module."""

    @classmethod
    def for_root(cls, *, key: str = "default") -> DeferredModule:
        stylesheet_controller = _stylesheet_controller()

        def materialize() -> ModuleSpec:
            return ModuleSpec(controllers=(stylesheet_controller,))

        return DeferredModule(cls, key, materialize)


class UiLiveView(LiveView):
    """A LiveView whose document opts into the bundled UI theme."""

    def ui_theme(self) -> str:
        return "auto"

    def render_document(self, live_root: str, client_script: str) -> str:
        theme = self.ui_theme()
        if theme not in {"auto", "light", "dark"}:
            raise ValueError("UI theme must be 'auto', 'light', or 'dark'")
        document = super().render_document(live_root, client_script)
        document = document.replace("<html>", f'<html data-tori-ui-theme="{theme}">', 1)
        return document.replace("<head>", f"<head>{stylesheet_link().value}", 1)


__all__ = ["STYLESHEET_PATH", "LiveViewUiModule", "UiLiveView", "stylesheet_link"]

from __future__ import annotations

import hashlib
import re
from importlib.resources import files
from typing import Literal

from tori_py import DeferredModule, HttpResponse, ModuleSpec, controller, get
from tori_py_liveview import LiveView, SafeHtml, raw

_STYLESHEET = (
    files("tori_py_liveview_ui")
    .joinpath(
        "static",
        "tori_liveview_ui.css",
    )
    .read_bytes()
)
_STYLESHEET_DIGEST = hashlib.sha256(_STYLESHEET).hexdigest()
STYLESHEET_PATH = f"/_tori/liveview-ui/{_STYLESHEET_DIGEST[:12]}.css"
_STYLESHEET_HEADERS = {
    "cache-control": "public, max-age=31536000, immutable",
    "content-type": "text/css; charset=utf-8",
    "etag": f'"{_STYLESHEET_DIGEST}"',
}
type UiTheme = Literal["auto", "light", "dark"]
_THEMES = frozenset({"auto", "light", "dark"})
_SKIN_NAME = re.compile(r"[a-z][a-z0-9-]{0,63}")


@controller()
class _StylesheetController:
    @get(STYLESHEET_PATH)
    async def stylesheet(self) -> HttpResponse:
        return HttpResponse(
            _STYLESHEET,
            headers=_STYLESHEET_HEADERS,
        )


class LiveViewUiModule:
    @classmethod
    def for_root(cls, *, key: str = "default") -> DeferredModule:
        if not isinstance(key, str):
            raise TypeError("LiveView UI key must be a string")
        if not key:
            raise ValueError("LiveView UI key cannot be empty")

        def materialize() -> ModuleSpec:
            return ModuleSpec(controllers=(_StylesheetController,))

        return DeferredModule(cls, key, materialize)


def stylesheet_link() -> SafeHtml:
    return raw(f'<link rel="stylesheet" href="{STYLESHEET_PATH}">')


class UiLiveView(LiveView):
    def ui_theme(self) -> UiTheme:
        return "auto"

    def ui_skin(self) -> str:
        return "editorial"

    def render_document(self, live_root: str, client_script: str) -> str:
        theme = self.ui_theme()
        if theme not in _THEMES:
            choices = ", ".join(sorted(_THEMES))
            raise ValueError(f"LiveView UI theme must be one of: {choices}")
        skin = self.ui_skin()
        if not isinstance(skin, str):
            raise TypeError("LiveView UI skin must be a string")
        if _SKIN_NAME.fullmatch(skin) is None:
            raise ValueError("LiveView UI skin must match [a-z][a-z0-9-]{0,63}")
        document = super().render_document(live_root, client_script)
        document = document.replace(
            "<html>",
            f'<html data-tori-ui-theme="{theme}" data-tori-ui-skin="{skin}">',
            1,
        )
        return document.replace(
            "</head>",
            f"{stylesheet_link().value}</head>",
            1,
        )


__all__ = [
    "STYLESHEET_PATH",
    "LiveViewUiModule",
    "UiLiveView",
    "stylesheet_link",
]

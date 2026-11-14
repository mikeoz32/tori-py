from __future__ import annotations

import hashlib
import re
from importlib.resources import files
from typing import Literal

from tori_py import DeferredModule, HttpResponse, ModuleSpec, controller, get
from tori_py_liveview import LiveView, SafeHtml, raw

from tori_py_liveview_ui.theming import _bundled_css

_STATIC = files("tori_py_liveview_ui").joinpath("static")
# The stylesheet is the generated token rules of the bundled definitions
# followed by the component rules, with one line ending on every platform.
_STYLESHEET = _bundled_css().encode("utf-8") + (
    _STATIC.joinpath("tori_liveview_ui.css").read_bytes().replace(b"\r\n", b"\n")
)
_STYLESHEET_DIGEST = hashlib.sha256(_STYLESHEET).hexdigest()
STYLESHEET_PATH = f"/_tori/liveview-ui/{_STYLESHEET_DIGEST[:12]}.css"
_STYLESHEET_HEADERS = {
    "cache-control": "public, max-age=31536000, immutable",
    "content-type": "text/css; charset=utf-8",
    "etag": f'"{_STYLESHEET_DIGEST}"',
}
_SCRIPT = _STATIC.joinpath("tori_liveview_ui.js").read_bytes()
_SCRIPT_DIGEST = hashlib.sha256(_SCRIPT).hexdigest()
SCRIPT_PATH = f"/_tori/liveview-ui/{_SCRIPT_DIGEST[:12]}.js"
_SCRIPT_HEADERS = {
    "cache-control": "public, max-age=31536000, immutable",
    "content-type": "text/javascript; charset=utf-8",
    "etag": f'"{_SCRIPT_DIGEST}"',
}
type UiMode = Literal["auto", "light", "dark"]
_MODES = frozenset({"auto", "light", "dark"})
_NAME = re.compile(r"[a-z][a-z0-9-]{0,63}")


@controller()
class _AssetController:
    @get(STYLESHEET_PATH)
    async def stylesheet(self) -> HttpResponse:
        return HttpResponse(
            _STYLESHEET,
            headers=_STYLESHEET_HEADERS,
        )

    @get(SCRIPT_PATH)
    async def script(self) -> HttpResponse:
        return HttpResponse(
            _SCRIPT,
            headers=_SCRIPT_HEADERS,
        )


class LiveViewUiModule:
    @classmethod
    def for_root(cls, *, key: str = "default") -> DeferredModule:
        if not isinstance(key, str):
            raise TypeError("LiveView UI key must be a string")
        if not key:
            raise ValueError("LiveView UI key cannot be empty")

        def materialize() -> ModuleSpec:
            return ModuleSpec(controllers=(_AssetController,))

        return DeferredModule(cls, key, materialize)


def stylesheet_link() -> SafeHtml:
    return raw(f'<link rel="stylesheet" href="{STYLESHEET_PATH}">')


def script_tag() -> SafeHtml:
    """Return the tag that loads the hooks before the LiveView client runs.

    The script registers its hooks once the document is parsed, so it belongs
    in ``<head>`` without ``defer`` or ``async``.
    """
    return raw(f'<script src="{SCRIPT_PATH}"></script>')


class UiLiveView(LiveView):
    def ui_theme(self) -> str:
        return "paper"

    def ui_mode(self) -> UiMode:
        return "auto"

    def ui_skin(self) -> str:
        return "editorial"

    def render_document(self, live_root: str, client_script: str) -> str:
        theme = _name("theme", self.ui_theme())
        mode = self.ui_mode()
        if mode not in _MODES:
            choices = ", ".join(sorted(_MODES))
            raise ValueError(f"LiveView UI mode must be one of: {choices}")
        skin = _name("skin", self.ui_skin())
        document = super().render_document(live_root, client_script)
        document = document.replace(
            "<html>",
            f'<html data-tori-ui-theme="{theme}" data-tori-ui-mode="{mode}" '
            f'data-tori-ui-skin="{skin}">',
            1,
        )
        document = document.replace(
            "</head>",
            f"{stylesheet_link().value}{script_tag().value}</head>",
            1,
        )
        return document.replace("<body>", '<body class="tori-ui-document">', 1)


def _name(kind: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"LiveView UI {kind} must be a string")
    if _NAME.fullmatch(value) is None:
        raise ValueError(f"LiveView UI {kind} must match [a-z][a-z0-9-]{{0,63}}")
    return value


__all__ = [
    "SCRIPT_PATH",
    "STYLESHEET_PATH",
    "LiveViewUiModule",
    "UiLiveView",
    "script_tag",
    "stylesheet_link",
]

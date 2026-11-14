from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from importlib.resources import files
from typing import Literal

from tori_py import DeferredModule, HttpResponse, ModuleSpec, controller, get
from tori_py_liveview import LiveView, SafeHtml, raw

from tori_py_liveview_ui.theming import (
    _ASSET_PREFIX,
    _BUNDLED_SKINS,
    _BUNDLED_THEMES,
    Skin,
    Theme,
    _bundled_css,
    _stylesheet,
)

_STATIC = files("tori_py_liveview_ui").joinpath("static")
# The stylesheet is the generated token rules of the bundled definitions
# followed by the component rules, with one line ending on every platform.
_STYLESHEET = _bundled_css().encode("utf-8") + (
    _STATIC.joinpath("tori_liveview_ui.css").read_bytes().replace(b"\r\n", b"\n")
)
_STYLESHEET_DIGEST = hashlib.sha256(_STYLESHEET).hexdigest()
STYLESHEET_PATH = f"{_ASSET_PREFIX}{_STYLESHEET_DIGEST[:12]}.css"
_SCRIPT = _STATIC.joinpath("tori_liveview_ui.js").read_bytes()
_SCRIPT_DIGEST = hashlib.sha256(_SCRIPT).hexdigest()
SCRIPT_PATH = f"{_ASSET_PREFIX}{_SCRIPT_DIGEST[:12]}.js"
type UiMode = Literal["auto", "light", "dark"]
_MODES = frozenset({"auto", "light", "dark"})
_NAME = re.compile(r"[a-z][a-z0-9-]{0,63}")
_BUNDLED: frozenset[Theme | Skin] = frozenset((*_BUNDLED_THEMES, *_BUNDLED_SKINS))


def _headers(content_type: str, digest: str) -> dict[str, str]:
    return {
        "cache-control": "public, max-age=31536000, immutable",
        "content-type": content_type,
        "etag": f'"{digest}"',
    }


_STYLESHEET_HEADERS = _headers("text/css; charset=utf-8", _STYLESHEET_DIGEST)
_SCRIPT_HEADERS = _headers("text/javascript; charset=utf-8", _SCRIPT_DIGEST)


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


def _definition_controller(definitions: tuple[Theme | Skin, ...]) -> type[object]:
    """Build the controller that serves one stylesheet per definition."""

    def endpoint(body: bytes):
        headers = _headers("text/css; charset=utf-8", hashlib.sha256(body).hexdigest())

        async def serve(self) -> HttpResponse:
            return HttpResponse(body, headers=headers)

        return serve

    routes: dict[str, object] = {}
    for index, definition in enumerate(definitions):
        path, body = _stylesheet(definition)
        routes[f"definition_{index}"] = get(path)(endpoint(body))
    return controller()(type("_DefinitionAssetController", (), routes))


def _registered(
    kind: str,
    definitions: object,
    expected: type[Theme] | type[Skin],
    bundled: tuple[Theme, ...] | tuple[Skin, ...],
) -> list[Theme | Skin]:
    if isinstance(definitions, str) or not isinstance(definitions, Iterable):
        raise TypeError(f"LiveView UI {kind}s must be {expected.__name__} objects")
    reserved = {definition.name for definition in bundled}
    registered: dict[str, Theme | Skin] = {}
    for definition in definitions:
        if not isinstance(definition, expected):
            raise TypeError(f"LiveView UI {kind}s must be {expected.__name__} objects")
        if definition in bundled:
            # A bundled definition is already in the package stylesheet.
            continue
        if definition.name in reserved:
            raise ValueError(
                f'LiveView UI {kind} name "{definition.name}" belongs to a bundled '
                f"{kind}"
            )
        if definition.name in registered:
            raise ValueError(
                f'LiveView UI {kind} "{definition.name}" is registered more than once'
            )
        registered[definition.name] = definition
    return list(registered.values())


class LiveViewUiModule:
    @classmethod
    def for_root(
        cls,
        *,
        key: str = "default",
        themes: Iterable[Theme] = (),
        skins: Iterable[Skin] = (),
    ) -> DeferredModule:
        """Serve the package assets and the stylesheets of application definitions.

        Every theme and skin a page returns from ``ui_theme()``, ``ui_skin()``,
        or ``ui_extra_definitions()`` must be listed here, unless it is bundled.
        """
        if not isinstance(key, str):
            raise TypeError("LiveView UI key must be a string")
        if not key:
            raise ValueError("LiveView UI key cannot be empty")
        definitions = (
            *_registered("theme", themes, Theme, _BUNDLED_THEMES),
            *_registered("skin", skins, Skin, _BUNDLED_SKINS),
        )

        def materialize() -> ModuleSpec:
            if not definitions:
                return ModuleSpec(controllers=(_AssetController,))
            return ModuleSpec(
                controllers=(_AssetController, _definition_controller(definitions))
            )

        return DeferredModule(cls, key, materialize)


def stylesheet_link(*definitions: Theme | Skin) -> SafeHtml:
    """Return the link to the package stylesheet and to application definitions.

    Each given theme or skin that is not bundled adds a link to its own
    stylesheet after the package one. ``LiveViewUiModule.for_root()`` must
    register those definitions, or the links answer 404.
    """
    links = [f'<link rel="stylesheet" href="{STYLESHEET_PATH}">']
    for definition in definitions:
        if not isinstance(definition, Theme | Skin):
            raise TypeError("LiveView UI stylesheet definitions must be Theme or Skin")
        if definition in _BUNDLED:
            continue
        link = f'<link rel="stylesheet" href="{_stylesheet(definition)[0]}">'
        if link not in links:
            links.append(link)
    return raw("".join(links))


def script_tag() -> SafeHtml:
    """Return the tag that loads the hooks before the LiveView client runs.

    The script registers its hooks once the document is parsed, so it belongs
    in ``<head>`` without ``defer`` or ``async``.
    """
    return raw(f'<script src="{SCRIPT_PATH}"></script>')


class UiLiveView(LiveView):
    def ui_theme(self) -> Theme | str:
        """Return the theme: a ``Theme``, or the name of one styled in CSS."""
        return Theme.PAPER

    def ui_mode(self) -> UiMode:
        """Return which palette of the theme applies."""
        return "auto"

    def ui_skin(self) -> Skin | str:
        """Return the skin: a ``Skin``, or the name of one styled in CSS."""
        return Skin.EDITORIAL

    def ui_extra_definitions(self) -> Iterable[Theme | Skin]:
        """Return further definitions the page uses, for example in ``themed``."""
        return ()

    def render_document(self, live_root: str, client_script: str) -> str:
        theme = self.ui_theme()
        mode = self.ui_mode()
        if mode not in _MODES:
            choices = ", ".join(sorted(_MODES))
            raise ValueError(f"LiveView UI mode must be one of: {choices}")
        skin = self.ui_skin()
        theme_name = _name("theme", theme, Theme)
        skin_name = _name("skin", skin, Skin)
        # A name stands for a definition styled in CSS and has no stylesheet.
        definitions = [
            *(chosen for chosen in (theme, skin) if not isinstance(chosen, str)),
            *self.ui_extra_definitions(),
        ]
        document = super().render_document(live_root, client_script)
        document = document.replace(
            "<html>",
            f'<html data-tori-ui-theme="{theme_name}" data-tori-ui-mode="{mode}" '
            f'data-tori-ui-skin="{skin_name}">',
            1,
        )
        document = document.replace(
            "</head>",
            f"{stylesheet_link(*definitions).value}{script_tag().value}</head>",
            1,
        )
        return document.replace("<body>", '<body class="tori-ui-document">', 1)


def _name(kind: str, value: object, definition: type[Theme] | type[Skin]) -> str:
    if isinstance(value, definition):
        return value.name
    if not isinstance(value, str):
        raise TypeError(
            f"LiveView UI {kind} must be a {definition.__name__} or a string"
        )
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

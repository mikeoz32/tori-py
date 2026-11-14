"""Shared chrome for the gallery pages."""

from __future__ import annotations

from string.templatelib import Template
from typing import ClassVar, Literal

from tori_py_liveview import MountContext, fragment
from tori_py_liveview_ui import UiLiveView, badge, stack

type Theme = Literal["auto", "light", "dark"]

THEMES: tuple[Theme, ...] = ("auto", "light", "dark")
SKINS = ("editorial", "minimal", "rounded")

# The gallery's pages in navigation order: path and label.
SECTIONS: list[tuple[str, str]] = [("/", "Overview")]


class GalleryPage(UiLiveView):
    """A gallery page whose theme and skin come from the query string."""

    heading: ClassVar[str]

    def __init__(self) -> None:
        self.theme: Theme = "auto"
        self.skin = "editorial"
        self.path = "/"

    async def mount(self, context: MountContext) -> None:
        theme = context.query_params.get("theme", "auto")
        skin = context.query_params.get("skin", "editorial")
        self.theme = theme if theme in THEMES else "auto"
        self.skin = skin if skin in SKINS else "editorial"

    def ui_theme(self) -> Theme:
        return self.theme

    def ui_skin(self) -> str:
        return self.skin

    def title(self) -> str | None:
        return f"{self.heading} - Tori UI gallery"

    def render_document(self, live_root: str, client_script: str) -> str:
        # An empty icon keeps browsers from requesting /favicon.ico.
        document = super().render_document(live_root, client_script)
        return document.replace("</head>", '<link rel="icon" href="data:,"></head>', 1)

    def href(
        self, path: str, *, theme: str | None = None, skin: str | None = None
    ) -> str:
        return f"{path}?theme={theme or self.theme}&skin={skin or self.skin}"

    def page(self, content: object) -> Template:
        sections = fragment(
            t'<a href="{self.href(path)}">{label}</a> ' for path, label in SECTIONS
        )
        themes = fragment(
            t'<a href="{self.href(self.path, theme=theme)}">{theme}</a> '
            for theme in THEMES
        )
        skins = fragment(
            t'<a href="{self.href(self.path, skin=skin)}">{skin}</a> ' for skin in SKINS
        )
        chrome = stack(
            [
                t'<nav aria-label="Gallery">{sections}</nav>',
                t"<p>Theme: {themes} {badge(self.theme)}</p>",
                t"<p>Skin: {skins} {badge(self.skin)}</p>",
            ],
            gap="xs",
        )
        return t"<main>{chrome}<h1>{self.heading}</h1>{content}</main>"

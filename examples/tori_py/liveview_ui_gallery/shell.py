"""Shared chrome for the gallery pages."""

from __future__ import annotations

from string.templatelib import Template
from typing import ClassVar, Literal

from tori_py_liveview import MountContext
from tori_py_liveview_ui import (
    Skin,
    Theme,
    UiLiveView,
    app_shell,
    button_group,
    card,
    connection_status,
    container,
    flash_group,
    link_button,
    mode_toggle,
    nav,
    nav_item,
    page_header,
    row,
    skip_link,
    spacer,
    stack,
)

from examples.tori_py.liveview_ui_gallery.looks import SKINS, THEMES

type Mode = Literal["auto", "light", "dark"]

MODES: tuple[Mode, ...] = ("auto", "light", "dark")
# The header offers the bundled skins; the Themes page offers every look.
_HEADER_SKINS = (Skin.EDITORIAL, Skin.MINIMAL, Skin.ROUNDED)

# The gallery's pages in navigation order: path and label.
SECTIONS: list[tuple[str, str]] = [
    ("/", "Overview"),
    ("/actions", "Actions"),
    ("/layout", "Layout"),
    ("/content", "Content"),
    ("/display", "Display"),
    ("/feedback", "Feedback"),
    ("/disclosure", "Disclosure"),
    ("/forms", "Forms"),
    ("/navigation", "Navigation"),
    ("/overlays", "Overlays"),
    ("/ai", "AI"),
    ("/chat", "Chat"),
    ("/themes", "Themes"),
]

# An application hook, defined the documented way: the object is replaced
# after the UI script has loaded, and the UI hooks still register.
_HOOKS = """<script>
globalThis.ToriLiveHooks = {
  GalleryClock: {
    mounted() {
      this.el.textContent = new Date().toLocaleTimeString();
    },
  },
};
</script>"""


def demo(title: str, content: object) -> Template:
    """Frame one component's examples."""
    return card(content, title=title)


class GalleryPage(UiLiveView):
    """A gallery page whose theme, mode, and skin come from the query string."""

    heading: ClassVar[str]
    summary: ClassVar[str]
    path: ClassVar[str]

    def __init__(self) -> None:
        self.theme: Theme = Theme.PAPER
        self.mode: Mode = "auto"
        self.skin: Skin = Skin.EDITORIAL

    async def mount(self, context: MountContext) -> None:
        params = context.query_params
        mode = params.get("mode", "auto")
        self.theme = THEMES.get(params.get("theme", ""), Theme.PAPER)
        self.mode = mode if mode in MODES else "auto"
        self.skin = SKINS.get(params.get("skin", ""), Skin.EDITORIAL)

    def ui_theme(self) -> Theme:
        return self.theme

    def ui_mode(self) -> Mode:
        return self.mode

    def ui_skin(self) -> Skin:
        return self.skin

    def title(self) -> str | None:
        return f"{self.heading} - Tori UI gallery"

    def render_document(self, live_root: str, client_script: str) -> str:
        document = super().render_document(_HOOKS + live_root, client_script)
        # An empty icon keeps browsers from requesting /favicon.ico.
        return document.replace("</head>", '<link rel="icon" href="data:,"></head>', 1)

    def href(
        self, path: str, *, theme: Theme | None = None, skin: Skin | None = None
    ) -> str:
        theme = theme or self.theme
        skin = skin or self.skin
        return f"{path}?theme={theme.name}&mode={self.mode}&skin={skin.name}"

    def page(self, content: object) -> Template:
        """Put a page's content under its header, in a scrolling column."""
        return self.frame(
            container(
                stack(
                    [
                        page_header(
                            self.heading, eyebrow="Gallery", description=self.summary
                        ),
                        content,
                    ],
                    gap="lg",
                )
            )
        )

    def frame(self, body: object) -> Template:
        """Put a body in the gallery's application shell."""
        pages = nav(
            (
                nav_item(
                    label,
                    href=self.href(path),
                    live="navigate",
                    current=path == self.path,
                )
                for path, label in SECTIONS
            ),
            label="Components",
        )
        # The skin is part of the document, so choosing one reloads the page.
        skins = button_group(
            (
                link_button(
                    skin.name,
                    href=self.href(self.path, skin=skin),
                    variant="primary" if skin == self.skin else "secondary",
                    size="sm",
                )
                for skin in _HEADER_SKINS
            ),
            label="Skin",
        )
        header = row(
            [
                t"<strong>Tori UI</strong>",
                spacer(),
                skins,
                mode_toggle(id="gallery-mode"),
            ],
            gap="sm",
            wrap=False,
        )
        notices = t"{flash_group(self.flash, id='gallery-flash')}{connection_status()}"
        shell = app_shell(
            t"{body}{notices}",
            id="gallery",
            header=header,
            sidebar=pages,
            sidebar_label="Gallery pages",
        )
        return t"{skip_link(href='#gallery-main')}{shell}"

"""Gallery page for the helpers that move the visitor around."""

from __future__ import annotations

from string.templatelib import Template

from tori_py_liveview import UnknownEventError, fragment, live_view
from tori_py_liveview_ui import (
    badge,
    breadcrumbs,
    button,
    grid,
    nav,
    nav_item,
    navbar,
    pagination,
    row,
    stack,
    steps,
    tab_links,
    text,
)

from examples.tori_py.liveview_ui_gallery.shell import GalleryPage, demo

_STAGES = ["Cart", ("Payment", "Card or invoice"), "Review", "Done"]


@live_view("/navigation")
class NavigationLive(GalleryPage):
    heading = "Navigation"
    summary = "Bars, link lists, breadcrumbs, pagination, steps, and tab links."
    path = "/navigation"

    def __init__(self) -> None:
        super().__init__()
        self.result_page = 1
        self.stage = 2

    async def handle_event(self, event: str, value: object) -> None:
        match event, value:
            case "page", {"page": str(number)} if number.isdigit():
                self.result_page = min(max(int(number), 1), 12)
            case "advance", _:
                self.stage = min(self.stage + 1, len(_STAGES) + 1)
            case "back", _:
                self.stage = max(self.stage - 1, 1)
            case _:
                raise UnknownEventError(event)

    def render(self) -> Template:
        bar = navbar(
            brand="Acme",
            items=fragment(
                [
                    nav_item("Products", href=self.href("/navigation"), current=True),
                    nav_item("Pricing", href=self.href("/navigation")),
                    nav_item("Docs", href="https://example.com", external=True),
                ]
            ),
            actions=button("Sign in", size="sm", variant="secondary"),
            label="Acme",
        )
        sections = nav(
            [
                nav_item(
                    "Inbox", href=self.href("/navigation"), icon="mail", badge=badge(3)
                ),
                nav_item(
                    "Starred", href=self.href("/navigation"), icon="star", current=True
                ),
                nav_item("Archive", href=self.href("/navigation"), icon="folder"),
            ],
            label="Mailboxes",
        )
        trail = breadcrumbs(
            [
                ("Gallery", self.href("/")),
                ("Navigation", self.href("/navigation")),
                ("Breadcrumbs", None),
            ],
            live="navigate",
        )
        pages = stack(
            [
                pagination(page=self.result_page, pages=12, event="page"),
                text(
                    t'Showing page <output id="result-page">{self.result_page}</output>'
                ),
                pagination(page=2, pages=3, href="/navigation?page={page}"),
            ]
        )
        progress = stack(
            [
                steps(_STAGES, current=self.stage),
                row(
                    [
                        button("Back", size="sm", variant="ghost", event="back"),
                        button("Continue", size="sm", event="advance"),
                    ],
                    gap="sm",
                ),
            ]
        )
        siblings = tab_links(
            [
                ("Navigation", self.href("/navigation")),
                ("Layout", self.href("/layout")),
                ("Content", self.href("/content")),
            ],
            current=self.href("/navigation"),
            label="Related pages",
            live="navigate",
        )
        return self.page(
            grid(
                [
                    demo("Navbar", bar),
                    demo("Nav", sections),
                    demo("Breadcrumbs", trail),
                    demo("Pagination", pages),
                    demo("Steps", progress),
                    demo("Tab links", siblings),
                ],
                columns="2",
                gap="lg",
            )
        )

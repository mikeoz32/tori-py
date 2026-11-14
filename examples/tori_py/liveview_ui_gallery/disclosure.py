"""Gallery page for the helpers that show and hide content in place."""

from __future__ import annotations

from string.templatelib import Template

from tori_py_liveview import UnknownEventError, live_view
from tori_py_liveview_ui import (
    accordion,
    button,
    collapsible,
    grid,
    row,
    stack,
    tabs,
    text,
)

from examples.tori_py.liveview_ui_gallery.shell import GalleryPage, demo

_REPORTS = {
    "daily": "Daily: 42 orders.",
    "weekly": "Weekly: 310 orders.",
    "monthly": "Monthly: 1,280 orders.",
}


@live_view("/disclosure")
class DisclosureLive(GalleryPage):
    heading = "Disclosure"
    summary = "Sections that open in place and tabs that switch panels."
    path = "/disclosure"

    def __init__(self) -> None:
        super().__init__()
        self.report = "daily"
        self.renders = 0

    async def handle_event(self, event: str, value: object) -> None:
        match event, value:
            case "report", {"tab": str(key)} if key in _REPORTS:
                self.report = key
            case "render", _:
                self.renders += 1
            case _:
                raise UnknownEventError(event)

    def render(self) -> Template:
        single = collapsible(
            "Shipping details",
            text("Orders leave the warehouse within two days."),
            id="shipping",
        )
        faq = accordion(
            [
                collapsible(
                    "How do I pay?", text("By card or invoice."), group="faq", id="pay"
                ),
                collapsible(
                    "Can I return an item?",
                    text("Within 30 days."),
                    group="faq",
                    id="return",
                ),
                collapsible(
                    "Where is my order?",
                    text("Track it from your account."),
                    group="faq",
                    id="track",
                    open=True,
                ),
            ]
        )
        client_tabs = tabs(
            [
                ("profile", "Profile", text("Name, picture, and biography.")),
                ("security", "Security", text("Password and sessions.")),
                ("billing", "Billing", text("Plan and invoices.")),
            ],
            id="settings",
            label="Settings",
        )
        page_tabs = tabs(
            [
                (key, key.title(), text(report) if key == self.report else None)
                for key, report in _REPORTS.items()
            ],
            id="reports",
            label="Reports",
            active=self.report,
            event="report",
        )
        rerender = row(
            [
                button("Render again", size="sm", variant="secondary", event="render"),
                text(t'Renders: <output id="renders">{self.renders}</output>'),
            ]
        )
        return self.page(
            stack(
                [
                    rerender,
                    grid(
                        [
                            demo("Collapsible", single),
                            demo("Accordion", faq),
                            demo("Tabs the browser switches", client_tabs),
                            demo("Tabs the page switches", page_tabs),
                        ],
                        columns="2",
                        gap="lg",
                    ),
                ]
            )
        )

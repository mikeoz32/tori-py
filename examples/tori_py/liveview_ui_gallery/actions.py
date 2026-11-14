"""Gallery page for buttons and other controls that start an action."""

from __future__ import annotations

from string.templatelib import Template

from tori_py_liveview import UnknownEventError, live_view
from tori_py_liveview_ui import (
    button,
    button_group,
    code,
    copy_button,
    grid,
    icon_button,
    link_button,
    row,
    stack,
    text,
    theme_toggle,
)

from examples.tori_py.liveview_ui_gallery.shell import GalleryPage, demo


@live_view("/actions")
class ActionsLive(GalleryPage):
    heading = "Actions"
    summary = "Buttons, links that look like buttons, and browser-side actions."
    path = "/actions"

    def __init__(self) -> None:
        super().__init__()
        self.total = 0
        self.deleted = 0
        self.favorite = False

    async def handle_event(self, event: str, value: object) -> None:
        match event, value:
            case "add", {"amount": str(amount)}:
                self.total += int(amount)
            case "delete", _:
                self.deleted += 1
            case "favorite", _:
                self.favorite = not self.favorite
            case _:
                raise UnknownEventError(event)

    def render(self) -> Template:
        sizes = row(
            [
                button("Small", size="sm"),
                button("Medium"),
                button("Large", size="lg"),
            ],
            gap="sm",
        )
        icons = row(
            [
                button("New item", icon="plus"),
                button("Continue", variant="secondary", icon_end="arrow-right"),
                button("Saving", loading=True),
                button("Wide", variant="ghost", full_width=True),
            ],
            gap="sm",
        )
        values = stack(
            [
                row(
                    [
                        button("Add 1", event="add", values={"amount": 1}),
                        button(
                            "Add 10",
                            variant="secondary",
                            event="add",
                            values={"amount": 10},
                        ),
                    ],
                    gap="sm",
                ),
                text(t'Total: <output id="total">{self.total}</output>'),
            ]
        )
        confirm = stack(
            [
                button(
                    "Delete",
                    variant="danger",
                    icon="trash",
                    event="delete",
                    confirm="Delete the record?",
                ),
                text(t'Deleted: <output id="deleted">{self.deleted}</output>'),
            ],
            align="start",
        )
        icon_buttons = row(
            [
                icon_button("edit", label="Edit"),
                icon_button("settings", label="Settings", variant="secondary"),
                icon_button("plus", label="Add", variant="primary"),
                icon_button("trash", label="Delete", variant="danger"),
                icon_button(
                    "star",
                    label="Favorite",
                    pressed=self.favorite,
                    event="favorite",
                ),
                icon_button("x", label="Close", size="sm"),
                icon_button("menu", label="Menu", size="lg", disabled=True),
            ],
            gap="sm",
        )
        links = row(
            [
                link_button("Layout page", href=self.href("/layout"), live="navigate"),
                link_button(
                    "Phoenix LiveView",
                    href="https://hexdocs.pm/phoenix_live_view",
                    variant="secondary",
                    external=True,
                    icon_end="external-link",
                ),
            ],
            gap="sm",
        )
        groups = stack(
            [
                button_group(
                    [
                        button("Day", variant="secondary"),
                        button("Week", variant="secondary"),
                        button("Month", variant="secondary"),
                    ],
                    label="Range",
                ),
                button_group(
                    [button("Cancel", variant="ghost"), button("Save")],
                    label="Form actions",
                    attached=False,
                ),
            ],
            align="start",
        )
        copy = stack(
            [
                text(code(t'<span id="token">tori-ui-0042</span>')),
                copy_button(to="#token", label="Copy token"),
            ],
            align="start",
        )
        theme = stack(
            [
                theme_toggle(id="actions-theme"),
                text(
                    "The browser stores the choice and applies it before paint.",
                    size="sm",
                    muted=True,
                ),
            ],
            align="start",
        )
        return self.page(
            grid(
                [
                    demo("Sizes", sizes),
                    demo("Icons, loading, full width", icons),
                    demo("Event values", values),
                    demo("Confirm", confirm),
                    demo("Icon buttons", icon_buttons),
                    demo("Link buttons", links),
                    demo("Button groups", groups),
                    demo("Copy button", copy),
                    demo("Theme toggle", theme),
                ],
                columns="2",
                gap="lg",
            )
        )

"""Gallery page for content that opens over the page."""

from __future__ import annotations

from string.templatelib import Template

from tori_py_liveview import UnknownEventError, live_view
from tori_py_liveview_ui import (
    button,
    close_overlay,
    confirm_dialog,
    divider,
    drawer,
    dropdown,
    grid,
    input,
    menu_item,
    modal,
    open_overlay,
    popover,
    row,
    stack,
    text,
)

from examples.tori_py.liveview_ui_gallery.shell import GalleryPage, demo


@live_view("/overlays")
class OverlaysLive(GalleryPage):
    heading = "Overlays"
    summary = "Modals, drawers, confirmations, menus, and popovers."
    path = "/overlays"

    def __init__(self) -> None:
        super().__init__()
        self.editing = False
        self.deleted = 0
        self.last_action = "none"

    async def handle_event(self, event: str, value: object) -> None:
        match event, value:
            case "edit", _:
                self.editing = True
            case "close_edit", _:
                self.editing = False
            case "delete", _:
                self.deleted += 1
            case "act", {"name": str(name)}:
                self.last_action = name
            case _:
                raise UnknownEventError(event)

    def render(self) -> Template:
        browser_modal = stack(
            [
                row([button("Open settings", event=open_overlay("settings"))]),
                modal(
                    stack(
                        [
                            text("The browser opens and closes this dialog."),
                            input("Display name", id="display-name", name="name"),
                        ]
                    ),
                    id="settings",
                    title="Settings",
                    description="Nothing here reaches the page.",
                    footer=button("Done", event=close_overlay("settings")),
                ),
            ]
        )
        editing = "yes" if self.editing else "no"
        page_modal = stack(
            [
                row([button("Edit profile", variant="secondary", event="edit")]),
                text(t'Editing: <output id="editing">{editing}</output>'),
                modal(
                    text("The page decides whether this dialog is open."),
                    id="edit",
                    title="Edit profile",
                    open=self.editing,
                    close_event="close_edit",
                    footer=button("Save", event="close_edit"),
                ),
            ]
        )
        side = stack(
            [
                row(
                    [
                        button(
                            "Open filters",
                            variant="secondary",
                            event=open_overlay("filters"),
                        )
                    ]
                ),
                drawer(
                    text("Filters sit in a panel at the side."),
                    id="filters",
                    title="Filters",
                    footer=button("Apply", event=close_overlay("filters")),
                ),
            ]
        )
        confirmation = stack(
            [
                row(
                    [
                        button(
                            "Delete project",
                            variant="danger",
                            event=open_overlay("confirm-delete"),
                        )
                    ]
                ),
                text(t'Deleted: <output id="deleted-projects">{self.deleted}</output>'),
                confirm_dialog(
                    "The project and its history are removed for everyone.",
                    id="confirm-delete",
                    title="Delete the project?",
                    confirm_event="delete",
                    confirm_label="Delete",
                    tone="danger",
                ),
            ]
        )
        menu = stack(
            [
                dropdown(
                    "Actions",
                    [
                        menu_item(
                            "Rename",
                            event="act",
                            values={"name": "rename"},
                            icon="edit",
                        ),
                        menu_item(
                            "Duplicate",
                            event="act",
                            values={"name": "duplicate"},
                            icon="copy",
                        ),
                        divider(),
                        menu_item(
                            "Delete",
                            event="act",
                            values={"name": "delete"},
                            icon="trash",
                            tone="danger",
                        ),
                    ],
                    id="actions",
                ),
                text(
                    t'Last action: <output id="last-action">{self.last_action}</output>'
                ),
            ],
            align="start",
        )
        details = popover(
            "Shortcuts",
            text("Press ? anywhere to see every shortcut.", size="sm"),
            id="shortcuts",
            panel_label="Keyboard shortcuts",
            icon="help-circle",
        )
        return self.page(
            grid(
                [
                    demo("Modal the browser opens", browser_modal),
                    demo("Modal the page opens", page_modal),
                    demo("Drawer", side),
                    demo("Confirm dialog", confirmation),
                    demo("Dropdown", menu),
                    demo("Popover", stack([details], align="start")),
                ],
                columns="2",
                gap="lg",
            )
        )

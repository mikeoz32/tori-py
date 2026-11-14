"""The gallery's first page: the foundation helpers."""

from __future__ import annotations

from string.templatelib import Template

from tori_py_liveview import UnknownEventError, live_view
from tori_py_liveview_ui import (
    alert,
    badge,
    button,
    card,
    checkbox,
    form,
    grid,
    input,
    select,
    stack,
    textarea,
)

from examples.tori_py.liveview_ui_gallery.shell import GalleryPage


@live_view("/")
class OverviewLive(GalleryPage):
    heading = "Overview"

    def __init__(self) -> None:
        super().__init__()
        self.path = "/"
        self.clicks = 0

    async def handle_event(self, event: str, value: object) -> None:
        if event != "click":
            raise UnknownEventError(event)
        self.clicks += 1

    def render(self) -> Template:
        buttons = stack(
            [
                button("Primary", event="click"),
                button("Secondary", variant="secondary", event="click"),
                button("Ghost", variant="ghost", event="click"),
                button("Danger", variant="danger", event="click"),
                button("Disabled", disabled=True),
                t'<output id="clicks">{self.clicks}</output>',
            ],
            gap="sm",
            align="start",
        )
        badges = stack(
            [
                badge("Neutral"),
                badge("Info", tone="info"),
                badge("Success", tone="success"),
                badge("Warning", tone="warning"),
                badge("Danger", tone="danger"),
            ],
            gap="xs",
            align="start",
        )
        alerts = stack(
            [
                alert("The deployment finished.", title="Deployed", tone="success"),
                alert("The disk is almost full.", title="Storage", tone="warning"),
                alert("The request failed.", tone="danger"),
            ]
        )
        fields = form(
            stack(
                [
                    input("Name", id="name", name="profile[name]", required=True),
                    select(
                        "Role",
                        [("admin", "Administrator"), ("member", "Member")],
                        id="role",
                        name="profile[role]",
                        prompt="Choose a role",
                    ),
                    textarea("About", id="about", name="profile[about]", rows=3),
                    checkbox("Subscribe", id="subscribe", name="profile[subscribe]"),
                    button("Save", button_type="submit"),
                ]
            ),
            id="profile-form",
        )
        return self.page(
            grid(
                [
                    card(buttons, eyebrow="Actions", title="Buttons"),
                    card(badges, eyebrow="Display", title="Badges"),
                    card(alerts, eyebrow="Feedback", title="Alerts"),
                    card(fields, eyebrow="Forms", title="Form controls"),
                ],
                columns="2",
                gap="lg",
            )
        )

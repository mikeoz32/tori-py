"""Gallery page for status, progress, and notifications."""

from __future__ import annotations

from string.templatelib import Template

from tori_py_liveview import JS, UnknownEventError, live_view
from tori_py_liveview_ui import (
    alert,
    banner,
    busy,
    button,
    grid,
    item_list,
    row,
    skeleton,
    spinner,
    stack,
    text,
    toast,
    toast_region,
)

from examples.tori_py.liveview_ui_gallery.shell import GalleryPage, demo


@live_view("/feedback")
class FeedbackLive(GalleryPage):
    heading = "Feedback"
    summary = "Alerts, banners, loading states, toasts, and flash messages."
    path = "/feedback"

    def __init__(self) -> None:
        super().__init__()
        self.notice = True
        self.loading = False
        self.toasts: dict[int, str] = {}
        self.sent = 0

    async def handle_event(self, event: str, value: object) -> None:
        match event, value:
            case "close_notice", _:
                self.notice = False
            case "toggle_loading", _:
                self.loading = not self.loading
            case "notify", _:
                self.sent += 1
                self.toasts[self.sent] = f"Message {self.sent} delivered."
            case "dismiss_toast", {"id": int(toast_id)}:
                self.toasts.pop(toast_id, None)
            case "flash", {"kind": str(kind)} if kind in ("info", "error"):
                self.put_flash(kind, f"A flash of kind {kind}.")
            case _:
                raise UnknownEventError(event)

    def render(self) -> Template:
        alerts = stack(
            [
                alert(
                    "The browser hides this alert; the page is not told.",
                    title="Dismissible",
                    tone="info",
                    dismissible=True,
                ),
                alert(
                    "The page removes this alert when you dismiss it.",
                    title="Page-owned",
                    tone="warning",
                    dismiss_event="close_notice",
                    actions=button("Details", size="sm", variant="secondary"),
                )
                if self.notice
                else text("The page-owned alert is gone.", muted=True),
            ]
        )
        notices = stack(
            [
                banner("Maintenance starts at noon.", dismissible=True),
                banner(
                    "Your trial ends in 3 days.",
                    tone="warning",
                    actions=button("Upgrade", size="sm"),
                ),
            ]
        )
        loaders = stack(
            [
                row(
                    [spinner(size="sm"), spinner(), spinner(size="lg")],
                    gap="lg",
                ),
                skeleton(lines=3),
                row([skeleton(shape="circle"), skeleton(shape="block")], gap="md"),
            ]
        )
        region = stack(
            [
                busy(
                    item_list(["Orders", "Invoices", "Customers"]),
                    busy=self.loading,
                    label="Loading reports",
                ),
                row([button("Toggle loading", size="sm", event="toggle_loading")]),
            ]
        )
        notifications = stack(
            [
                row(
                    [
                        button("Notify", icon="bell", event="notify"),
                        button(
                            "Flash info",
                            variant="secondary",
                            event="flash",
                            values={"kind": "info"},
                        ),
                        button(
                            "Flash error",
                            variant="secondary",
                            event="flash",
                            values={"kind": "error"},
                        ),
                    ],
                    gap="sm",
                ),
                text(
                    t'Open toasts: <output id="open-toasts">{len(self.toasts)}</output>'
                ),
            ]
        )
        toasts = toast_region(
            toast(
                message,
                id=f"toast-{toast_id}",
                title="Sent",
                tone="success",
                duration=1500,
                dismiss_event=JS().push("dismiss_toast", value={"id": toast_id}),
            )
            for toast_id, message in self.toasts.items()
        )
        return self.page(
            stack(
                [
                    grid(
                        [
                            demo("Alerts", alerts),
                            demo("Banners", notices),
                            demo("Spinner and skeleton", loaders),
                            demo("Busy region", region),
                            demo("Toasts and flash", notifications),
                        ],
                        columns="2",
                        gap="lg",
                    ),
                    toasts,
                ]
            )
        )

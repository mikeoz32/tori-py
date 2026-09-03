"""LiveView shell for the Lit workplace application."""

from __future__ import annotations

from string.templatelib import Template

from tori_py_liveview import LiveView, MountContext, live_view


@live_view("/live/workplace")
class WorkplaceLive(LiveView):
    """Keep server-owned shell state outside the Lit-owned application subtree."""

    def __init__(self) -> None:
        self.connected = False
        self.bridge_checks = 0

    async def mount(self, context: MountContext) -> None:
        self.connected = context.connected

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event != "check_bridge":
            await super().handle_event(event, None)
            return
        self.bridge_checks += 1

    def render(self) -> Template:
        state = "connected" if self.connected else "disconnected"
        status = "LiveView connected" if self.connected else "LiveView connecting"
        return (
            t'<aside class="liveview-bridge" data-live-state="{state}" '
            t'aria-label="Frontend runtime"><span class="liveview-bridge-label">'
            t'ToriPy LiveView</span><output role="status">{status}</output>'
            t'<button type="button" phx-click="check_bridge">Check LiveView bridge'
            t'</button><output id="liveview-bridge-checks">'
            t"Patch {self.bridge_checks}</output>"
            t'<span class="liveview-bridge-detail">Lit web component</span></aside>'
            t'<workplace-app id="workplace-lit-app" phx-update="ignore" '
            t'style="display:block"></workplace-app>'
        )

    def title(self) -> str:
        return "Tori Space - workplace atlas"

    def render_document(self, live_root: str, client_script: str) -> str:
        return (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="color-scheme" content="light">'
            f"<title>{self.title()}</title>"
            '<link rel="stylesheet" href="/web/styles.css">'
            '<link rel="stylesheet" href="/web/live-shell.css">'
            f"</head><body>{live_root}{client_script}"
            '<script type="module" src="/web/app.js"></script></body></html>'
        )


__all__ = ["WorkplaceLive"]

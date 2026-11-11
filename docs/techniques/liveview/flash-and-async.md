# Flash and Async Work

Flash messages tell the user what just happened and follow them across
navigation. Async work runs slow operations, such as loading data or building a
report, concurrently with the page and delivers the result as a normal update.

## Flash

```python
from string.templatelib import Template

from tori_py_liveview import LiveView, UnknownEventError, live_view


@live_view("/settings")
class SettingsLive(LiveView):
    async def handle_event(self, event: str, value: object) -> None:
        if event != "save":
            raise UnknownEventError(event)
        self.put_flash("info", "Settings saved")

    def render(self) -> Template:
        info = self.flash.get("info", "")
        return (
            t'<p id="flash-info" role="alert" phx-click="lv:clear-flash" '
            t'phx-value-key="info">{info}</p>'
            t'<button phx-click="save">Save</button>'
        )
```

| API | Meaning |
| --- | --- |
| `put_flash(kind, message)` | Set the message for `kind`, such as `"info"` or `"error"` |
| `clear_flash(kind=None)` | Remove one kind, or all flash |
| `flash` | Read-only mapping of the current messages |

The built-in `lv:clear-flash` event clears the kind in its `key` value, or all
flash without one; the framework handles it without calling `handle_event()`.
Components forward `put_flash()` and `clear_flash()` to their page, which
renders the flash.

Flash follows the user:

- `push_navigate()` carries the flash set since the last render to the next
  page as a signed token that expires after 60 seconds.
- `redirect()` carries it through the official `__phoenix_flash__` cookie, which
  the next HTTP render reads and deletes.
- A page that navigates while it mounts passes on its whole flash, including
  flash it received, so a message survives a page that moves on at once.
- Flash never follows a redirect to another host.
- The HTTP render's flash shows again only on the document's first connected
  mount, not after reconnects or live navigation.

## Async Work

```python
import asyncio

from tori_py_liveview import AsyncResult, MountContext


@live_view("/dashboard")
class DashboardLive(LiveView):
    def __init__(self) -> None:
        self.org: AsyncResult[object] = AsyncResult()
        self.report = "idle"

    async def mount(self, context: MountContext) -> None:
        self.assign_async("org", self.load_org)

    async def load_org(self) -> object:
        await asyncio.sleep(0)
        return "Acme"

    async def handle_event(self, event: str, value: object) -> None:
        if event != "report":
            raise UnknownEventError(event)
        self.report = "running"
        self.start_async("report", self.build_report)

    async def build_report(self) -> object:
        await asyncio.sleep(0)
        return 42

    async def handle_async(self, name: str, result: AsyncResult[object]) -> None:
        if name != "report":
            await super().handle_async(name, result)
            return
        self.report = f"rows: {result.result}" if result.ok else "failed"

    def render(self) -> Template:
        org = "loading" if self.org.loading else str(self.org.result)
        return (
            t"<p>{org}</p><p>{self.report}</p>"
            t'<button phx-click="report">Report</button>'
        )
```

| API | Meaning |
| --- | --- |
| `start_async(name, function)` | Await `function()` concurrently, then call `handle_async(name, result)` |
| `assign_async(name, function, *, reset=False)` | Track the work in the `AsyncResult` attribute called `name` |
| `cancel_async(name)` | Cancel the work; returns whether there was work to cancel |
| `handle_async(name, result)` | Receives each `start_async()` outcome; raises `UnknownAsyncError` by default |

`AsyncResult` mirrors Phoenix's: `loading` is true while work runs, `ok` and
`result` hold the latest success, and `failed` holds the latest exception.
`assign_async()` sets `loading` at once and keeps the previous `result` while it
reloads; `reset=True` clears it. The attribute name must be a public identifier
that does not shadow a method, property, or class attribute.

Work runs only on the connected page. In the HTTP render, `start_async()` does
nothing and `assign_async()` only marks its attribute as loading. The function
runs as its own task, but its result is delivered on the connection task one
message at a time, like events and `handle_info()`, so `handle_async()` may
change page state. Starting work under a name that is already running cancels
the old work and drops its result. A cancelled task reports
`asyncio.CancelledError` in `failed`.

When a page or component goes away, its work is cancelled. The page waits up to
`LiveViewOptions.async_cancel_timeout_seconds` for work that ignores
cancellation, then stops waiting and logs a warning. Blocking calls inside the
work would stall the whole event loop, so run them with `asyncio.to_thread()`.

Components run their own work with the same methods. Results go to the
component's `handle_async()` or attribute, and the component's work is
cancelled when it is destroyed, before its `disconnect()` runs.

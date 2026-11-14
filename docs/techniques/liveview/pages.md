# Pages and Lifecycle

A LiveView page is a `LiveView` subclass declared with `@live_view(path)` and
listed in `LiveViewModule.for_root(pages=[...])`. There is no package scan: a
decorated class that is not listed is not served.

## Declare a Page

```python
from string.templatelib import Template

from tori_py_liveview import (
    LiveView,
    MountContext,
    UnknownEventError,
    fragment,
    live_view,
)


class TaskStore:
    def __init__(self) -> None:
        self.titles: list[str] = []


@live_view("/tasks")
class TasksLive(LiveView):
    def __init__(self, store: TaskStore) -> None:
        self.store = store
        self.titles: list[str] = []

    async def mount(self, context: MountContext) -> None:
        self.titles = list(self.store.titles)

    async def handle_event(self, event: str, value: object) -> None:
        if event != "add" or not isinstance(value, dict):
            raise UnknownEventError(event)
        title = str(value.get("title", "")).strip()
        if title:
            self.store.titles.append(title)
            self.titles.append(title)

    def render(self) -> Template:
        items = fragment(t"<li>{title}</li>" for title in self.titles)
        return (
            t'<form phx-submit="add"><input name="title">'
            t"<button>Add</button></form><ul>{items}</ul>"
        )
```

Register `TaskStore` as a singleton provider in a module the LiveView module
imports, and pass that module through `LiveViewModule.for_root(imports=[...])`.

Only `render()` is required. Wrap collections with `fragment()`: a plain list
interpolated into a template renders as escaped text, not as markup.
[Templates and Rendering](templates.md) covers the composition helpers.

## Pages Are Request-Scoped Providers

The module registers every page as `ClassProvider(page, scope=Scope.REQUEST)`.
Constructor parameters resolve exactly like other providers, so pages can depend
on singletons, request-scoped services, and imported exports.

| Phase | Scope that resolves the page |
| --- | --- |
| HTTP render | The HTTP request scope |
| Connected page | A new work scope opened for that page join and closed after `disconnect()` |

Each live navigation and each reconnect opens a new work scope and a new page
instance. Request-scoped dependencies are therefore per page join, not per
WebSocket connection and not per event.

## Lifecycle

| Step | HTTP render | Connected page |
| --- | --- | --- |
| 1 | Session `on_mount` hooks | Session `on_mount` hooks |
| 2 | `mount(context)` with `connected=False` | `mount(context)` with `connected=True` |
| 3 | `handle_params(params, uri)` | `handle_params(params, uri)` |
| 4 | `render()` and `render_document()` | `render()`; full tree in the join reply, then only changes |
| 5 | Components disconnected, stream operations cleared | Events, patches, and info messages, one at a time |
| 6 | — | `disconnect()` once when the page ends |

Mount hooks and `handle_params` are covered in
[Routing and Navigation](navigation.md).

Use `connected` to keep expensive or long-lived work out of the HTTP render:

```python
async def mount(self, context: MountContext) -> None:
    self.titles = await self.store.recent(limit=20)
    if context.connected:
        self.feed.subscribe(self)
```

### Callbacks

| Method | Called | Default |
| --- | --- | --- |
| `async mount(context)` | Once per page instance | No-op |
| `async handle_params(params, uri)` | After every `mount()` and on every patch | No-op |
| `async handle_event(event, value)` | For each untargeted `phx-*` event | Raises `UnknownEventError` |
| `async handle_info(name, value)` | For each accepted `send_info()` message | Raises `UnknownInfoError` |
| `async handle_async(name, result)` | When work from `start_async()` finishes; see [Flash and Async Work](flash-and-async.md) | Raises `UnknownAsyncError` |
| `render()` | After mount and after every state-changing callback | Required |
| `title()` | With every render | `None`, an empty title |
| `render_document(live_root, client_script)` | HTTP render only | Minimal HTML5 document |
| `async disconnect()` | Once when a connected page ends | No-op |
| `live_action` property | Any time | The matched route `action`, or `None` |

### MountContext

| Field | HTTP render | Connected page |
| --- | --- | --- |
| `request` | Starlette `Request` | Starlette `WebSocket` |
| `params` | Path parameters as a read-only mapping of strings | Same values, from the signed token |
| `resource` | Path plus raw query string | Same, from the token or navigation URL |
| `connected` | `False` | `True` |
| `query_params` | Parsed query of `resource` | Parsed query of `resource` |
| `connect_params` | `None` | The join params the browser sent, read-only |

Both request types are Starlette `HTTPConnection` objects, so headers, cookies,
and the client address read the same way in both phases.

### Connect Params

`connect_params` mirrors Phoenix `get_connect_params`. Add your own params by
setting `globalThis.ToriLiveParams` to an object, or to a function of the root
element, before the client script runs; `render_document()` is a good place:

<!-- docs-test: skip -->

```python
def render_document(self, live_root: str, client_script: str) -> str:
    params = (
        "<script>globalThis.ToriLiveParams = "
        "{timezone: Intl.DateTimeFormat().resolvedOptions().timeZone};</script>"
    )
    return super().render_document(params + live_root, client_script)
```

The official client also sends `_mounts` (how many times this page has mounted),
`_live_referer` after live navigation, and `_track_static` with the URLs of
`phx-track-static` elements. `context.tracked_static` lists those URLs, and
`context.static_changed(current_urls)` reports whether they differ from the
application's current ones, for example to show a reload notice after a deploy.
Connect params come from the browser, so treat them as untrusted. Your own
params also appear in the WebSocket URL, so never put secrets in them.

## Events and Values

Bind events with Phoenix attributes such as `phx-click`, `phx-submit`,
`phx-change`, `phx-blur`, `phx-focus`, `phx-keydown`, and `phx-window-keyup`.
The binding value is the event name passed to `handle_event()`.

| Binding | `value` received |
| --- | --- |
| `phx-click` and other element events | A dict of the element's `phx-value-*` attributes, keyed without the prefix |
| `phx-keydown`, `phx-keyup` | Includes `key` and the `phx-value-*` attributes |
| `phx-blur`, `phx-focus` on a control | Normally `{"value": "..."}` |
| `phx-change`, `phx-submit` | The form decoded into nested dicts and lists |
| `JS().push(event, value=...)` | The pushed mapping merged with `phx-value-*` |

Form values use Phoenix bracket notation. `user[name]=Ada&tags[]=a&tags[]=b`
becomes:

```python
{"user": {"name": "Ada"}, "tags": ["a", "b"]}
```

All leaves are strings, and unchecked checkboxes are absent. For `phx-change`,
the field that changed arrives as a token list under `_target`, for example
`["user", "name"]`. Coerce and validate values in the page; the framework does
not convert form data to domain types.

```python
async def handle_event(self, event: str, value: object) -> None:
    match event, value:
        case "delete", {"id": str(task_id)}:
            await self.store.delete(task_id)
        case "save", {"task": {"title": str(title)}}:
            await self.save(title.strip())
        case _:
            raise UnknownEventError(event)
```

Treat every value as untrusted input. Events arrive from the browser, and a
client can send any event name or value it likes over an accepted connection.

### Failures

| Failure | Result |
| --- | --- |
| `handle_event` raises `UnknownEventError` | The event is acknowledged without a render; navigation and stream operations queued during that call are discarded |
| A targeted event names a component that no longer exists | Same as an unknown event |
| Any other exception in a connected callback or render | Logged, the socket closes with `1011`, the page is disconnected, and the client reconnects with a fresh page |
| `handle_info` raises, including the default `UnknownInfoError` | Same as any other exception: close with `1011` |
| An exception during the HTTP render | Propagates through the normal HTTP pipeline, filters, and problem responses |
| A 4xx `HttpException` from a connected `mount()`, `handle_params()`, mount hook, or the first render | The browser reloads the page once, and that HTTP request answers with the same status |

State changed before an exception stays on the page object. Validate first and
mutate last, or raise `UnknownEventError` before touching state.

## Titles and the Document

Return a string from `title()` to set `document.title`, or `None` for an empty
title. It is read on every render and sent to the browser when it changes, so it
can follow page state:

```python
def title(self) -> str | None:
    return f"Tasks ({len(self.titles)})"
```

`render_document(live_root, client_script)` builds the outer document for the
HTTP render only. The default writes a UTF-8 HTML5 document with a viewport
meta tag, the escaped title, `live_root`, and `client_script`. Override it to add
stylesheets, a language attribute, or layout around the live root:

```python
def render_document(self, live_root: str, client_script: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<link rel="stylesheet" href="/assets/app.css">'
        f"<title>Tasks</title></head><body>{live_root}{client_script}</body></html>"
    )
```

Both arguments are framework-generated trusted markup; include each one
unchanged. Everything else you write in the returned string is trusted application
HTML, so escape any data you add yourself. Content outside `live_root` is not
updated by connected renders. [LiveView UI](../liveview-ui/index.md) provides a
`UiLiveView` base that does this for its stylesheet.

## Server-Initiated Updates

Events, info messages, renders, and outbound writes for one page run one at a
time on the connection task. Background tasks and other services must not change
page state directly. They call `send_info()` and the page changes state in
`handle_info()`:

```python
import asyncio


class ClockLive(LiveView):
    def __init__(self) -> None:
        self.ticks = 0
        self.timer: asyncio.Task[None] | None = None

    async def mount(self, context: MountContext) -> None:
        if context.connected:
            self.timer = asyncio.create_task(self._tick())

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(1)
            self.send_info("tick")

    async def handle_info(self, name: str, value: object) -> None:
        if name != "tick":
            await super().handle_info(name, value)
            return
        self.ticks += 1

    async def disconnect(self) -> None:
        if self.timer is not None:
            self.timer.cancel()
            await asyncio.gather(self.timer, return_exceptions=True)

    def render(self) -> Template:
        return t"<output>{self.ticks}</output>"
```

`send_info(name, value=None)` returns `False` and drops the message before the
page is connected, after it disconnects, or when its queue already holds 32
messages. Each accepted message runs `handle_info()` and pushes a diff. Call it
from the application's event loop, not from another thread.

Because messages can be dropped, treat them as wake-up signals and reload the
source of truth when one arrives. A singleton service can fan out to every
connected page:

```python
class TaskFeed:
    def __init__(self) -> None:
        self._pages: set[LiveView] = set()

    def subscribe(self, page: LiveView) -> None:
        self._pages.add(page)

    def unsubscribe(self, page: LiveView) -> None:
        self._pages.discard(page)

    def changed(self) -> None:
        for page in tuple(self._pages):
            page.send_info("tasks_changed")
```

Subscribe from a connected `mount()` and unsubscribe in `disconnect()`.
`disconnect()` runs once for every connected page, including after failures and
live navigation. Stop and await every task the page started there. Server pushes
do not reset the browser's idle deadline; the Phoenix client's heartbeats do.

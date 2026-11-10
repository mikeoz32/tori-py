# tori-py-liveview

`tori-py-liveview` adds server-rendered interactive pages to ToriPy. A normal
HTTP route renders the initial document. The included official Phoenix and
Phoenix LiveView browser clients then join a ToriPy WebSocket gateway, forward
`phx-*` DOM events, and apply Phoenix render-tree diffs.

```text
uv add tori-py-liveview
```

## Quick start

```python
from string.templatelib import Template

from tori_py import module
from tori_py_liveview import (
    LiveComponent,
    LiveView,
    LiveViewModule,
    LiveViewOptions,
    MountContext,
    UnknownEventError,
    live_view,
)


@live_view("/counter")
class CounterLive(LiveView):
    def __init__(self) -> None:
        self.count = 0

    async def mount(self, context: MountContext) -> None:
        self.count = int(context.query_params.get("start", "0"))

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event != "increment":
            raise UnknownEventError(event)
        self.count += 1

    def render(self) -> Template:
        return (
            t'<section><button phx-click="increment">+</button>'
            t"<output>{self.count}</output></section>"
        )


liveview_module = LiveViewModule.for_root(
    LiveViewOptions(secret="replace-with-at-least-32-secret-bytes"),
    pages=[CounterLive],
)


@module(imports=[liveview_module])
class AppModule:
    pass
```

Pages are explicit request-scoped providers, so constructor injection works as
it does for other ToriPy providers. The disconnected HTTP mount and connected
WebSocket mount use separate provider instances. `MountContext.connected`
distinguishes them.

## Routing and navigation

```python
from tori_py_liveview import LiveSession


@live_view("/articles", action="index", session="team")
@live_view("/articles/new", action="new", session="team")
class ArticlesLive(LiveView):
    async def handle_params(self, params: dict[str, str], uri: str) -> None:
        del uri
        self.page = int(params.get("page", "1"))

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event == "next":
            self.push_patch(f"/articles?page={self.page + 1}")
        elif event == "new":
            self.push_navigate("/articles/new")
        else:
            raise UnknownEventError(event)


liveview_module = LiveViewModule.for_root(
    LiveViewOptions(secret="replace-with-at-least-32-secret-bytes"),
    pages=[ArticlesLive],
    sessions=[LiveSession("team", on_mount=(require_team,))],
)
```

One page class may serve several paths with different `action` values, exposed
as `live_action`. `handle_params` runs after every `mount` and on every patch
with merged path/query params. Client links use the official attributes
(`data-phx-link="patch"` / `"redirect"`); the server resolves them against the
same Starlette patterns. `push_navigate` works within one `LiveSession` and
falls back to a full reload across sessions. `redirect(to)` accepts a path or
an http(s) URL and is safe for untrusted values such as `?next=`: it cleans the
target the way browsers read it and rejects other schemes or hosts other than
the request host and `redirect_hosts`. Put authorization in `on_mount`,
`mount`, and `handle_params`: live navigate rejoins over the socket and never
passes the HTTP pipeline again. The LiveView integration requires the
Starlette adapter.

Ordinary Template interpolations and values passed to `rendered()` are HTML
escaped. Template statics, explicit `rendered()` statics, direct `str` render
returns, and values wrapped by `raw()` are trusted application HTML. Override
`render_document(live_root, client_script)` to supply a complete document while
retaining both framework arguments.

## Template authoring

`html(t"...")` converts a Python 3.14 template string to `Rendered`.
`fragment()` composes a finite iterable once, `classes()` builds conditional
class names as ordinary escaped text, and `attrs()` generates validated escaped
attributes. Pages and components may return Templates directly, and stream
items accept them as well.

Nested Templates, `Rendered` values, components, and streams remain nested
Phoenix render-tree values. Interpolate those structural values without `!s`,
`!r`, `!a`, or a format specification. Ordinary interpolation is supported only
in HTML text and quoted attribute values; dynamic tag or attribute names, CSS,
and JavaScript are outside the safe authoring contract.

## JS commands

The Phoenix client runs a `phx-*` binding value that starts with `[` as JS
commands. Build them with `JS`, the counterpart of `Phoenix.LiveView.JS`:

```python
from string.templatelib import Template

from tori_py_liveview import JS, LiveView, fragment


class ItemsLive(LiveView):
    def render(self) -> Template:
        menu = JS().toggle(
            to="#items", transition_in=("ease-out", "opacity-0", "opacity-100")
        )
        rows = fragment(self.row(item) for item in self.items)
        return t'<button phx-click="{menu}">Items</button><ul id="items">{rows}</ul>'

    def row(self, item: Item) -> Template:
        delete = JS().push("delete", value={"id": item.id}).hide(to=f"#item-{item.id}")
        button = t'<button phx-click="{delete}">Delete</button>'
        return t'<li id="item-{item.id}">{item.name} {button}</li>'
```

`JS()` starts an immutable chain; every method returns a new chain. The builder
covers the commands of the pinned client: `push`, `navigate`, `patch`,
`dispatch`, `show`, `hide`, `toggle`, `add_class`, `remove_class`,
`toggle_class`, `transition`, `set_attribute`, `remove_attribute`,
`toggle_attribute`, `ignore_attributes`, `focus`, `focus_first`, `push_focus`,
`pop_focus`, and `exec`. `to` is a selector or a `("closest", selector)` /
`("inner", selector)` pair, and a transition is a class string or a
`(classes, start, end)` triple. Arguments are JSON encoded and validated when a
command is added: `navigate` and `patch` take root-relative paths, attribute
commands follow the `attrs()` rules, and `exec` runs only `phx-*` bindings.
Pass a chain through Template interpolation, `attrs()`, or `rendered()`; LiveView
UI event options accept it too.

Other dynamic values cannot start a command value or appear inside one, so data
used as an event name is never run as commands. `phx-value-*`, `phx-target`,
`phx-key`, and `phx-disable-with` are exempt because the client never runs
them. Commands written in Template statics or `raw()` remain trusted
application code.

## Stateful components

Subclass `LiveComponent` for independently stateful pieces sharing one page
connection. A component identity is its concrete type plus the stable string ID
passed to `live_component`. `mount()` runs once for an identity, `update()` runs
before every render, and targeted events run on the component:

```python
from string.templatelib import Template


class CounterComponent(LiveComponent):
    def __init__(self) -> None:
        self.count = 0
        self.label = ""

    def update(self, assigns: object) -> None:
        assert isinstance(assigns, dict)
        self.label = str(assigns["label"])

    async def handle_event(self, event: str, value: object) -> None:
        if event != "increment":
            raise UnknownEventError(event)
        self.count += 1

    def render(self) -> Template:
        return (
            t'<button phx-target="{self.myself}" phx-click="increment">'
            t"{self.label}: {self.count}</button>"
        )


class DashboardLive(LiveView):
    def render(self) -> Template:
        counter = self.live_component(
            CounterComponent,
            "primary",
            {"label": "Primary"},
        )
        return t"<main>{counter}</main>"
```

`phx-target` is placed on the event element and carries `myself`. The target is
connection-local; do not persist or construct it. An omitted identity remains
revivable until the browser completes Phoenix's component-destruction handshake.
After final confirmation it is disconnected and forgotten; rendering it later
creates fresh state and a new target. Override the async `disconnect()` hook to
stop component-owned resources. Nested components are not supported. Component
output must contain exactly one root element and use explicit balanced end tags
rather than optional-end-tag HTML.

## Streams

Use streams for collections whose children should be owned by the browser rather
than retained and rerendered as page state. Queue the canonical collection on
each mount and expose it to the initial HTTP render with `stream_contents()`:

```python
class ActivityLive(LiveView):
    async def mount(self, context: MountContext) -> None:
        label = "Started"
        self.stream_reset("activities")
        self.stream_insert(
            "activities",
            "activity-1",
            t'<li id="activity-1">{label}</li>',
        )

    def render(self) -> Template:
        activities = self.stream_contents("activities")
        return t'<ul id="activities" phx-update="stream">{activities}</ul>'
```

`stream_insert()` appends by default, prepends with `at=0`, and updates an
existing item in place. A positive limit retains the first N children and a
negative limit retains the last N. `stream_delete()` removes one direct child;
`stream_reset()` removes all children. Each inserted item must have exactly one
explicitly balanced root element whose DOM `id` matches the item ID passed to
`stream_insert()`. Passing `str` as an item marks that whole string as trusted
application HTML, just like returning `str` from `render()`; use a Template or
`Rendered` dynamics for untrusted values so they are escaped.

Do not render ordinary dynamic children into a `phx-update="stream"` container.
Phoenix morphing preserves its children, and only the stream tuple may mutate
them. Operations are delivered once, rejected event queues are discarded, and
reconnect mount should reset and rebuild canonical state.

## Server-initiated updates

Timers and subscriptions must not mutate page state from their own tasks. Use
`send_info()` to enqueue a connection-local message, then update state from the
serialized `handle_info()` callback:

```python
import asyncio


async def mount(self, context: MountContext) -> None:
    if context.connected:
        self.timer = asyncio.create_task(self._tick_later())

async def _tick_later(self) -> None:
    await asyncio.sleep(1)
    _ = self.send_info("tick")

async def handle_info(self, name: str, value: object) -> None:
    if name != "tick":
        await super().handle_info(name, value)
        return
    self.count += 1
```

`send_info()` returns `False` before connection, after disconnect, or when the
bounded 32-message queue is full. Events, info callbacks, renders, and outbound
writes run serially on the connection task. Stop and await page-owned background
tasks from `disconnect()`; reconnect mounts a fresh page and queue. Server
updates do not extend the browser's inbound idle deadline.

## Configuration

`LiveViewOptions` controls the root-relative socket and client paths, explicit
allowed origins, inbound message limit, mount-token lifetime, join deadline,
and idle deadline. The default origin policy accepts only the HTTP origin
corresponding to the WebSocket `Host`; deployments behind a host-rewriting
proxy should set `allowed_origins` explicitly. `redirect_hosts` lists the bare
host names, such as an identity provider, that `redirect()` may leave the site
for; it is empty by default.

Mount tokens are signed, expiring HMAC values. They prevent page/resource
tampering but are not encrypted and do not replace authentication or
authorization. Use TLS and a strong deployment secret shared by all replicas.

## Compatibility

The package vendors unchanged official global builds of `phoenix@1.8.13` and
`phoenix_live_view@1.2.11`. Sources and checksums are recorded in
`static/phoenix_assets.lock.json`; `scripts/sync_phoenix_assets.py` verifies all
downloads before replacing either vendored file.

This release implements Phoenix Channels joins and replies, Phoenix render
trees, stateful component CIDs, targeted events, heartbeats,
reconnect-compatible joins, title updates, browser-owned bounded streams, and
serialized connection-local server updates through `send_info`/`handle_info`.
The configured socket path is the Phoenix endpoint base; the browser connects to
its `/websocket?vsn=2.0.0` transport route. Nested components, uploads,
navigation, and application hook/reply APIs are reserved for later releases.

See the runnable example in `examples/tori_py/liveview` and the normative
architecture in `TORI_PY_LIVEVIEW_ARCHITECTURE.md`.

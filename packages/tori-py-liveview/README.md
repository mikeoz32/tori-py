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

After the join, each update sends the browser only what changed. A template's
literal text, its statics, stays with the client, so a click that changes one
interpolated value sends that value alone. A component whose output did not
change is left out, and its DOM is left untouched. Statics are compared by
value, so a page or component that returns a plain `str`, such as an f-string,
has new statics whenever its text changes and is sent whole each time. Prefer
`t"..."` templates for anything that updates. A `fragment()` list whose length
changes is also sent whole.

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

`send_update(component_type, component_id, assigns)` passes assigns to a
rendered component from a page or component handler or from `handle_info()`,
without the parent having to track them:

```python
async def handle_info(self, name: str, value: object) -> None:
    if name == "progress":
        self.send_update(ProgressComponent, "upload", {"percent": value})
```

Queued updates call `update(assigns)` in order before the next render, only for
components the previous render produced; other identities are ignored. The
assigns the parent passes to `live_component()` during that render are applied
afterwards, so keep component state that `send_update()` sets separate from the
fields the parent overwrites.

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

## Hooks, pushed events, and replies

The client bootstrap passes `globalThis.ToriLiveHooks` to the official
`LiveSocket` as its `hooks` object. Register hooks on it from a script that runs
before the deferred client script, for example by prepending it in
`render_document`:

```python
_HOOKS = '<script defer src="/assets/hooks.js"></script>'


class ChatLive(LiveView):
    def render_document(self, live_root: str, client_script: str) -> str:
        return super().render_document(live_root, _HOOKS + client_script)

    def render(self) -> Template:
        return t'<div id="messages" phx-hook="ScrollToEnd">{self.messages}</div>'
```

```js
// /assets/hooks.js, served by the application
globalThis.ToriLiveHooks ??= {};
ToriLiveHooks.ScrollToEnd = {
  mounted() {
    this.handleEvent("scroll-to-end", () => this.el.scrollTo(0, this.el.scrollHeight));
  },
  updated() { this.el.scrollTo(0, this.el.scrollHeight); },
};
```

Hooked elements need a unique DOM `id`. `this.pushEvent(event, value, reply)` in
a hook reaches `handle_event` like any other browser event. A handler that
returns a mapping replies to it; `None` sends no reply:

```python
async def handle_event(self, event: str, value: object) -> Mapping[str, object] | None:
    if event == "load-more":
        self.page += 1
        self.push_event("scroll-to-end")
        return {"page": self.page}
    raise UnknownEventError(event)
```

`push_event(event, payload=None, dispatch="after")` sends a `phx:<event>` window
event, which hooks receive through `handleEvent`, with the next render: the
join, an event reply, or a `handle_info` update. `dispatch="before"` dispatches
it before the client applies that render. Payloads and replies are mappings with
string keys that must encode as JSON objects; they are copied when queued.
Pushed events are dropped when the handler raises `UnknownEventError` or
navigates away with `push_navigate()` or `redirect()`, during the disconnected
HTTP render, and on disconnect. An invalid reply closes the connection like any
other handler failure.

Components have the same `push_event()` and reply behaviour. Hook scripts are
trusted application code; ToriPy serves no hook runtime of its own.

## Flash

`put_flash(kind, message)` sets a flash message, `clear_flash(kind=None)`
removes one kind or all, and `self.flash` is the read-only mapping to render.
The official `lv:clear-flash` event clears the kind named by its `key` value:

```python
async def handle_event(self, event: str, value: object) -> None:
    if event == "save":
        await self.repository.save(self.draft)
        self.put_flash("info", "Saved")
        self.push_navigate("/drafts")


def render(self) -> Template:
    info = self.flash.get("info", "")
    return t"""
      <p id="flash" phx-click="lv:clear-flash" phx-value-key="info">{info}</p>
      ...
    """
```

Flash put in a handler follows `push_navigate()` as a signed token and
`redirect()` through the Phoenix `__phoenix_flash__` cookie, which the next HTTP
render reads and deletes. A page that navigates while mounting, such as `/`
redirecting to `/dashboard`, passes on all of its flash, including flash it
received, unless it clears it. Flash does not follow a `redirect()` to another
host. Flash tokens expire after 60 seconds. The disconnected
render's flash also appears on the first connected render, but not again after a
reconnect. Components forward `put_flash()` and `clear_flash()` to their page.

## Async work

`start_async(name, function)` awaits `function()` concurrently and passes the
outcome to `handle_async`, which runs serially with events and re-renders:

```python
async def handle_event(self, event: str, value: object) -> None:
    if event == "ask":
        self.answer = "thinking"
        self.start_async("answer", lambda: self.llm.complete(self.prompt))


async def handle_async(self, name: str, result: AsyncResult[object]) -> None:
    if name == "answer":
        self.answer = str(result.result) if result.ok else "failed"
```

`assign_async(name, function, reset=False)` keeps an `AsyncResult` in the
attribute `name` instead: it is `loading` until the work finishes and then `ok`
with `result`, or `failed` with the exception. A reload keeps the previous
result while loading unless `reset=True`. The name cannot be a method,
property, or class variable such as `title` or `flash`. The disconnected render
shows the loading state without starting work:

```python
async def mount(self, context: MountContext) -> None:
    self.org: AsyncResult[Organization] = AsyncResult()
    self.assign_async("org", lambda: self.organizations.get(self.org_id))
```

Restarting a running name cancels the previous task. `cancel_async(name)`
cancels work and delivers `asyncio.CancelledError` as its failure. Disconnect
and live navigation cancel all work, and component work is cancelled before
the component's `disconnect()` when it is removed. Cancelled work gets up to
`LiveViewOptions.async_cancel_timeout_seconds` (5 seconds by default) to stop;
work that ignores cancellation longer is logged and left behind. Work runs on
the event loop, so wrap blocking calls in `asyncio.to_thread`.

## Connect params

`MountContext.connect_params` holds the join params the browser sent to a
connected mount, mirroring Phoenix `get_connect_params`, and is `None` for the
disconnected render. Applications add their own params through
`globalThis.ToriLiveParams`, set before the client script runs:

```python
_PARAMS = (
    "<script>globalThis.ToriLiveParams = "
    "{timezone: Intl.DateTimeFormat().resolvedOptions().timeZone};</script>"
)
```

The official client also sends `_mounts`, `_live_referer` after live navigation,
and `_track_static` with the URLs of `phx-track-static` elements.
`context.static_changed(current_urls)` reports whether those assets differ from
the application's current ones, for example to show a reload notice after a
deploy. Connect params come from the browser, so treat them as untrusted. Your
own params also appear in the WebSocket URL, so never put secrets in them; the
LiveView join fields above are kept out of that URL.

A connected `mount`, `handle_params`, on-mount hook, or first `render` that
raises a 4xx `HttpException` makes the browser reload the page once. The reload carries a
signed token in the official `__phoenix_reload_status__` cookie, so the HTTP
render answers with that status even if only the connected mount fails, for
example when data loads only once connected.

## Configuration

`LiveViewOptions` controls the root-relative socket and client paths, explicit
allowed origins, inbound message limit, mount-token lifetime, join deadline,
idle deadline, and the deadline for cancelled async work. The default origin
policy accepts only the HTTP origin
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
reconnect-compatible joins, title updates, browser-owned bounded streams,
serialized connection-local server updates through `send_info`/`handle_info`,
live navigation, client hooks, pushed events, event replies, `send_update`,
flash, async work, connect params, `reload` join errors, and changed-only
render diffs with shared component statics. The configured
socket path is the Phoenix endpoint base; the browser connects to its
`/websocket?vsn=2.0.0` transport route. Nested components, child LiveViews, and
uploads are reserved for later releases.

See the runnable example in `examples/tori_py/liveview` and the normative
architecture in `TORI_PY_LIVEVIEW_ARCHITECTURE.md`.

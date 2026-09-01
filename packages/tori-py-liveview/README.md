# tori-py-liveview

`tori-py-liveview` adds server-rendered interactive pages to ToriPy. A normal
HTTP route renders the initial document. The included Opal browser client then
joins a ToriPy WebSocket gateway, forwards declared DOM events, and applies
protocol-v2 structural diffs.

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
        return t"""
            <button data-opal-click="increment">+</button>
            <output>{self.count}</output>
        """


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

`render()` accepts Python 3.14 template strings and automatically converts them
to structural `Rendered` values. Interpolated values are HTML escaped, while
nested `Template`, `Rendered`, `raw()`, and `stream_contents()` values are trusted
application markup. Conversions such as `!r` and format specifications are
applied before escaping.

Use interpolations for text and quoted attribute values, not tag names,
attribute names, unquoted attributes, JavaScript, or CSS. A manually constructed
`Template("...")` contains trusted static markup; do not construct one from
untrusted input. `html(t"...")` explicitly converts a template when a helper
needs a `Rendered` value. The lower-level `rendered(statics, *values)` API remains
available for generated code and escapes each dynamic value using the same
rules.

Override `render_document(live_root, client_script)` to supply a complete
document while retaining both framework arguments.

## Template collections

Use `fragment()` to compose a finite iterable of templates or other render
values. The iterable is consumed once, ordinary values are escaped, and nested
`Template`, `Rendered`, and `SafeHtml` values retain their trusted composition
semantics:

```python
from tori_py_liveview import fragment


def user_card(name: str) -> Template:
    return t'<article class="user-card">{name}</article>'


class UsersLive(LiveView):
    def render(self) -> Template:
        cards = fragment(user_card(user.name) for user in self.users)

        return t"""
            <main>
                <h1>Users</h1>
                <section class="user-grid">{cards}</section>
            </main>
        """
```

An empty iterable produces empty markup. When two fragments contain the same
number of items, changes are reported as positional dynamics. Use streams
instead when the browser should own insertion, deletion, ordering, or retention
of a changing collection.

## Conditional classes

Use `classes()` to normalize unconditional class names and append classes whose
keyword flags are enabled:

```python
from tori_py_liveview import classes


def render(self) -> Template:
    button_class = classes(
        "button button-primary",
        active=self.active,
        disabled=self.disabled,
        **{"is-loading": self.loading},
    )

    return t'<button class="{button_class}">Save</button>'
```

Positional names must be strings, conditional flags must be booleans, false
conditions are omitted, and whitespace is normalized. `classes()` returns an
ordinary string rather than trusted markup; interpolate it only into a quoted
attribute so the template processor still escapes untrusted class names.

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
        return t"""
            <button data-opal-target="{self.myself}" data-opal-click="increment">
                {self.label}: {self.count}
            </button>
        """


class DashboardLive(LiveView):
    def render(self) -> Template:
        counter = self.live_component(
            CounterComponent,
            "primary",
            {"label": "Primary"},
        )
        return t"<main>{counter}</main>"
```

`data-opal-target` may be on the event element or an ancestor inside the
component. The target is connection-local and must come from `myself`; do not
persist or construct it. Omitting an identity disconnects and forgets that
component. Rendering it again creates fresh state and a new target. Override
the async `disconnect()` hook to stop component-owned resources. Nested
components are not supported.

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
        return t'<ul id="activities" data-opal-stream>{activities}</ul>'
```

`stream_insert()` appends by default, prepends with `at=0`, and updates an
existing item in place. A positive limit retains the first N children and a
negative limit retains the last N. `stream_delete()` removes one direct child;
`stream_reset()` removes all children. Each inserted item must have exactly one
root element whose DOM `id` matches the item ID passed to `stream_insert()`.
Passing `str` as an item marks that whole string as trusted application HTML,
just like returning `str` from `render()`; prefer a `Template` or `Rendered`
value when an item contains untrusted values so they are escaped.

Do not render ordinary dynamic children into a `data-opal-stream` container.
Normal structural morphing preserves its children, and only the ordered stream
batch may mutate them. Operations are delivered once, rejected event queues are
discarded, and reconnect mount should reset and rebuild canonical state.

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
    self.send_info("tick")

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
proxy should set `allowed_origins` explicitly.

Mount tokens are signed, expiring HMAC values. They prevent page/resource
tampering but are not encrypted and do not replace authentication or
authorization. Use TLS and a strong deployment secret shared by all replicas.

## Compatibility

The package vendors the unchanged Opal protocol-v2 browser client from commit
`48dc24f31fb64ddd602175a8fcba13fd84f3c72a`. Its source and checksum are recorded
in `static/opal_live_view.lock.json`; `scripts/sync_opal_client.py` verifies the
checksum before replacing the vendored file.

This release implements page snapshots, structural diffs, stateful components,
targeted events, event correlation, stale-version resynchronization, heartbeats,
reconnect-compatible joins, title updates, and browser-owned bounded streams.
It also serializes server-initiated `send_info` updates through ordinary render
messages. Nested components, uploads, navigation, and server hook/reply APIs are
reserved for later releases; their existing browser protocol must not be
reinterpreted.

See the runnable example in `examples/tori_py/liveview` and the normative
architecture in `TORI_PY_LIVEVIEW_ARCHITECTURE.md`.

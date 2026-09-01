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
from tori_py import module
from tori_py_liveview import (
    LiveComponent,
    LiveView,
    LiveViewModule,
    LiveViewOptions,
    MountContext,
    Rendered,
    UnknownEventError,
    live_view,
    rendered,
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

    def render(self) -> Rendered:
        return rendered(
            ('<button data-opal-click="increment">+</button><output>', "</output>"),
            self.count,
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

Dynamic values passed to `rendered()` are HTML escaped. Static fragments and
values wrapped by `raw()` are trusted application HTML. Override
`render_document(live_root, client_script)` to supply a complete document while
retaining both framework arguments.

## Stateful components

Subclass `LiveComponent` for independently stateful pieces sharing one page
connection. A component identity is its concrete type plus the stable string ID
passed to `live_component`. `mount()` runs once for an identity, `update()` runs
before every render, and targeted events run on the component:

```python
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

    def render(self) -> Rendered:
        return rendered(
            ('<button data-opal-target="',
             '" data-opal-click="increment">', ': ', '</button>'),
            self.myself,
            self.label,
            self.count,
        )


class DashboardLive(LiveView):
    def render(self) -> Rendered:
        counter = self.live_component(
            CounterComponent,
            "primary",
            {"label": "Primary"},
        )
        return rendered(("<main>", "</main>"), counter)
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
        self.stream_reset("activities")
        self.stream_insert(
            "activities",
            "activity-1",
            rendered(('<li id="activity-1">', "</li>"), "Started"),
        )

    def render(self) -> Rendered:
        activities = self.stream_contents("activities")
        return rendered(
            ('<ul id="activities" data-opal-stream>', "</ul>"),
            activities,
        )
```

`stream_insert()` appends by default, prepends with `at=0`, and updates an
existing item in place. A positive limit retains the first N children and a
negative limit retains the last N. `stream_delete()` removes one direct child;
`stream_reset()` removes all children. Each inserted item must have exactly one
root element whose DOM `id` matches the item ID passed to `stream_insert()`.
Passing `str` as an item marks that whole string as trusted application HTML,
just like returning `str` from `render()`; use `Rendered` dynamics for untrusted
values so they are escaped.

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

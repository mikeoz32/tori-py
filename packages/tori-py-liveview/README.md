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
            ('<button phx-target="',
             '" phx-click="increment">', ': ', '</button>'),
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
        self.stream_reset("activities")
        self.stream_insert(
            "activities",
            "activity-1",
            rendered(('<li id="activity-1">', "</li>"), "Started"),
        )

    def render(self) -> Rendered:
        activities = self.stream_contents("activities")
        return rendered(
            ('<ul id="activities" phx-update="stream">', "</ul>"),
            activities,
        )
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

The package vendors unchanged official global builds of `phoenix@1.8.13` and
`phoenix_live_view@1.2.11`. Sources and checksums are recorded in
`static/phoenix_assets.lock.json`; `scripts/sync_phoenix_assets.py` verifies all
downloads before replacing either vendored file.

This release implements Phoenix Channels joins and replies, Phoenix render
trees, stateful component CIDs, targeted events, heartbeats,
reconnect-compatible joins, title updates, and browser-owned bounded streams.
The configured socket path is the Phoenix endpoint base; the browser connects to
its `/websocket?vsn=2.0.0` transport route. Nested components, uploads,
navigation, hooks, and `send_info` are reserved for later releases.

See the runnable example in `examples/tori_py/liveview` and the normative
architecture in `TORI_PY_LIVEVIEW_ARCHITECTURE.md`.

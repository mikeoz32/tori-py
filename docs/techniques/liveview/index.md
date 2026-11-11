# LiveView

`tori-py-liveview` adds server-rendered interactive pages to a ToriPy
application. Page state lives in a Python object on the server. The browser runs
the unchanged official Phoenix and Phoenix LiveView JavaScript clients, which
send DOM events over a WebSocket and apply the HTML diffs the server returns.
You write no client JavaScript for ordinary interaction.

```text
uv add tori-py-liveview
```

Add [LiveView UI](../liveview-ui/index.md) when you also want styled, stateless
form and layout helpers:

```text
uv add tori-py-liveview tori-py-liveview-ui
```

## How a Page Works

```text
browser                                   server
  GET /counter  ───────────────────────▶  page provider (request scope)
                                          mount(connected=False), render
  ◀── full HTML + signed mount token ───  Cache-Control: no-store
  GET /_tori/live.js (Phoenix clients)
  WS  /_tori/live/websocket  ──────────▶  Origin check
  phx_join(token)  ────────────────────▶  new page instance (work scope)
                                          mount(connected=True), render
  ◀── full render tree  ────────────────
  phx-click="increment"  ──────────────▶  handle_event, render
  ◀── render tree; client patches DOM ──
```

1. A normal HTTP `GET` resolves the page, mounts it disconnected, and returns a
   complete HTML document. Search engines, slow clients, and users without
   JavaScript see real content.
2. The document embeds a signed mount token and loads the bundled Phoenix
   clients from `/_tori/live.js`.
3. The client opens a WebSocket and joins with the token. The server mounts a
   new connected page instance and sends the full render tree.
4. Each `phx-*` event runs one page callback. The server renders again and
   replies with the Phoenix render tree; the client patches only the DOM nodes
   that changed.

The HTTP page and the connected page are separate provider instances.
`MountContext.connected` tells `mount()` which one it is serving.

## Quick Start

```python
from string.templatelib import Template

from tori_py import NestApplication, module
from tori_py.starlette import StarletteAdapter, asgi
from tori_py_liveview import (
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
            t'<main><button phx-click="increment">+</button>'
            t"<output>{self.count}</output></main>"
        )


liveview_module = LiveViewModule.for_root(
    LiveViewOptions(secret="replace-with-at-least-32-secret-bytes"),
    pages=[CounterLive],
)


@module(imports=[liveview_module])
class AppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule, adapter=StarletteAdapter())


application = asgi(create_application)
```

Run it and open `http://127.0.0.1:8000/counter?start=5`:

```text
uv run tori-py run app:create_application
```

`render()` returns a Python 3.14 template string. Interpolated values are HTML
escaped. See [Templates and Rendering](templates.md).

The secret signs mount tokens. Read it from configuration in real deployments;
see [Configuration and Security](configuration-and-security.md).

## What the Module Registers

`LiveViewModule.for_root()` returns a keyed `DeferredModule`. It registers:

| Item | Default | Purpose |
| --- | --- | --- |
| One `GET` controller route per `@live_view` path | your paths | Disconnected HTML render |
| Each page class as a request-scoped `ClassProvider` | — | Constructor injection for pages |
| Client script route | `/_tori/live.js` | Pinned Phoenix 1.8.13 and Phoenix LiveView 1.2.11 clients plus a small bootstrap |
| WebSocket gateway | `/_tori/live/websocket` | Phoenix Channels V2 endpoint |
| `LiveViewOptions` value provider | — | The options the module was created with |

Pass `imports=` to `for_root()` when pages depend on providers exported by other
modules. Page paths must be unique and must not collide with the socket or
client paths.

LiveView requires the `StarletteAdapter`. The native `tori_py.asgi` adapter is
HTTP only and serves no WebSocket scopes.

## Guide Map

| Topic | Read |
| --- | --- |
| Page callbacks, events, form values, server-initiated updates | [Pages and Lifecycle](pages.md) |
| Template strings, escaping, `attrs()`, `classes()`, `fragment()` | [Templates and Rendering](templates.md) |
| Client-side commands such as show, hide, and transitions | [JS Commands](js-commands.md) |
| Independently stateful parts of a page | [Stateful Components](components.md) |
| Large or append-only collections owned by the browser | [Streams](streams.md) |
| Several routes per page, patches, live navigation, mount hooks | [Routing and Navigation](navigation.md) |
| Options, origins, tokens, limits, authorization | [Configuration and Security](configuration-and-security.md) |
| Unit, HTTP, and browser tests | [Testing LiveView](testing.md) |
| Styled forms, layout, themes, and skins | [LiveView UI](../liveview-ui/index.md) |

To build a page step by step, follow the
[Live Task Board tutorial](../../tutorials/live-task-board.md). A runnable
showcase with a browser end-to-end test lives in
[`examples/tori_py/liveview`](https://github.com/mikeoz32/tori-py/tree/main/examples/tori_py/liveview).

## Current Scope

The package implements Phoenix Channels joins and replies, render-tree diffs,
stateful components with targeted events, browser-owned streams, title updates,
heartbeats, reconnect joins, route-aware patches and live navigation, mount
hooks, the `JS` command builder, and serialized server-initiated updates.

Not implemented: nested components, file uploads, and application hook/reply
APIs (`phx-hook` with `pushEvent` replies or server `push_event`). The server
keeps no page after a disconnect and does not migrate sessions between replicas;
a reconnect always mounts a fresh page.

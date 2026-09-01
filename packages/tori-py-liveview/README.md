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
`e492477d62bbe578eb6a7b132db60e5b845ceb35`. Its source and checksum are recorded
in `static/opal_live_view.lock.json`; `scripts/sync_opal_client.py` verifies the
checksum before replacing the vendored file.

This release implements page snapshots, structural diffs, event correlation,
stale-version resynchronization, heartbeats, reconnect-compatible joins, and
title updates. Server-side components, streams, uploads, and `send_info` are
reserved for later releases. Their existing browser protocol must not be
reinterpreted by page-only implementations.

See the runnable example in `examples/tori_py/liveview` and the normative
architecture in `TORI_PY_LIVEVIEW_ARCHITECTURE.md`.

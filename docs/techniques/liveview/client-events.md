# Hooks and Server Events

Phoenix hooks run your JavaScript when an element is added, updated, or removed.
A hook can push events to the page and receive a reply, and the page can push
events to the browser. Pages and components can also update other components
without passing new assigns through a render.

## Register Hooks

The client bootstrap passes `globalThis.ToriLiveHooks` to the official
`LiveSocket` as its `hooks` option. Define that object before the client script
runs, for example from `render_document()`, and attach a hook to an element with
`phx-hook` and a stable `id`:

```python
from collections.abc import Mapping
from string.templatelib import Template

from tori_py_liveview import LiveView, UnknownEventError, live_view

_HOOKS = """<script>
globalThis.ToriLiveHooks = {
  Clock: {
    mounted() {
      this.pushEvent("ping", {sent: Date.now()}, (reply) => {
        this.el.dataset.latency = String(Date.now() - reply.sent);
      });
      this.handleEvent("tick", ({at}) => { this.el.textContent = at; });
    },
  },
};
</script>"""


@live_view("/clock")
class ClockLive(LiveView):
    async def handle_event(
        self, event: str, value: object
    ) -> Mapping[str, object] | None:
        match event, value:
            case "ping", {"sent": int(sent)}:
                self.push_event("tick", {"at": "12:00"})
                return {"sent": sent}
            case _:
                raise UnknownEventError(event)

    def render(self) -> Template:
        return t'<time id="clock" phx-hook="Clock"></time>'

    def render_document(self, live_root: str, client_script: str) -> str:
        return super().render_document(_HOOKS + live_root, client_script)
```

The hook object is application JavaScript: the server never writes into it, and
it must not include data from users or storage.

## Events from Hooks and Replies

`this.pushEvent(event, payload, callback)` in a hook reaches `handle_event()`
like any `phx-*` binding, so validate its value the same way. When
`handle_event()` returns a mapping, it becomes the reply: the client calls the
hook's callback with it after applying the render. A reply must be a JSON
object. Returning `None`, the default, sends no reply. Component handlers may
return a reply too.

`this.pushEventTo(selector, event, payload)` targets a component when the
selector matches an element inside it, as `phx-target` does.

## Push Events to the Browser

`push_event(event, payload=None, *, dispatch="after")` queues an event that
travels with the next render. The client delivers it to hooks that called
`this.handleEvent(event, ...)` and dispatches it on `window` as `phx:<event>`:

```javascript
window.addEventListener("phx:tick", (event) => console.log(event.detail.at));
```

The payload must be a JSON object; mappings with string keys, lists, strings,
numbers, booleans, and `None` are accepted. `dispatch="before"` dispatches the
event before the client applies the render's DOM changes instead of after.

Pushed events are discarded when the handler raises `UnknownEventError` or
navigates away, and the HTTP render sends none. Components forward
`push_event()` to their page.

## Update Components

`send_update(component_type, component_id, assigns)` passes assigns to a
component from a page or component handler, or from `handle_info()`, without
the page tracking them:

<!-- docs-test: skip -->

```python
async def handle_info(self, name: str, value: object) -> None:
    if name == "progress":
        self.send_update(ProgressComponent, "upload", {"percent": value})
```

Queued updates call the component's `update(assigns)` in order before the next
render, only for components the previous render produced; other identities are
ignored. The page's `live_component()` call in that render then calls
`update()` again with the page's own assigns. Keep values that only
`send_update()` changes under keys the page does not pass, and leave them
unchanged when `update()` receives assigns without them.

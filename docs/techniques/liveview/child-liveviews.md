# Child LiveViews

A child LiveView is a page rendered inside another page. It has its own state,
events, `send_info()` queue, async work, and renders, so it can update without
its parent and the parent can update without it. Use one for a self-contained
area such as a cart, a chat panel, or a notification list. For a widget that
only needs its own state and events, a [component](components.md) is lighter.

## Render a Child

```python
from string.templatelib import Template

from tori_py_liveview import (
    LiveView,
    LiveViewModule,
    LiveViewOptions,
    MountContext,
    UnknownEventError,
    live_view,
)


class CartLive(LiveView):
    def __init__(self) -> None:
        self.store = ""
        self.items = 0

    async def mount(self, context: MountContext) -> None:
        self.store = context.params["store"]

    async def handle_event(self, event: str, value: object) -> None:
        if event != "add":
            raise UnknownEventError(event)
        self.items += 1

    def render(self) -> Template:
        return (
            t"<aside>{self.items} items from {self.store}"
            t'<button phx-click="add">Add</button></aside>'
        )


@live_view("/shop")
class ShopLive(LiveView):
    def render(self) -> Template:
        cart = self.live_render(CartLive, "cart", {"store": "kyiv"})
        return t"<main><h1>Shop</h1>{cart}</main>"


liveview_module = LiveViewModule.for_root(
    LiveViewOptions(secret="change-me-in-production-" + "x" * 16),
    pages=[ShopLive],
    embedded=[CartLive],
)
```

`live_render(page_type, view_id, params=None)` may only run while the page
renders. The child must be registered with the module: list pages that are only
ever rendered as children under `embedded=`, where they get no path and must not
declare `@live_view`, or list a routed page under `pages=` as usual.

| Argument | Meaning |
| --- | --- |
| `page_type` | The child page class |
| `view_id` | The container's DOM id; 1 to 128 letters, digits, `_`, or `-`, unique on the page |
| `params` | A mapping of strings the child receives as `context.params` |

## How a Child Runs

The HTTP render mounts each child with `connected=False`, renders it, and
places its HTML in the container, so the first response shows the whole page.
Children may render their own children, up to eight levels deep.

Once the page connects, the browser joins each child on its own channel over the
same WebSocket. The server accepts a child only with the signed token that the
current join of its parent rendered for that id, so tokens from the HTTP render,
another page, or an earlier connection are refused; the browser always joins
with the latest ones, also after a reconnect. The child then mounts with
`connected=True` in its own work scope, which stays the active scope for all of
the child's callbacks: request-scoped dependencies and scoped method
interceptors of the page and of each child see their own view's scope. The
views of a page still handle one message at a time.
`phx-*` events inside the child's container go to the child, and a parent
update leaves the child's container and contents alone.

Removing the child from the parent's render makes the browser leave it, which
disconnects the child. When a parent ends, its children end first, also when
the connection is cancelled or the application shuts down, and each of them
ends even when another one's cleanup fails.

## Rules

- A child's `context.params` are the strings from `live_render()`, and
  `context.resource` is the resource the page mounted with.
- Children do not run the session's `on_mount` hooks or `handle_params()`, as in
  Phoenix. A child authorizes in its own `mount()`.
- Only the page can `push_patch()`; a child that calls it raises
  `LiveViewError`. A child's `push_navigate()` navigates the whole page, and its
  `redirect()` loads another document.
- A child navigating during the HTTP render raises `LiveViewError`; navigate
  only once connected.
- A child's `title()` replaces the page title only when it returns a string.
- An exception in a child closes the WebSocket with `1011`, like an exception
  in the page, and the browser reconnects every view.
- Sticky children that survive live navigation, container tag and attribute
  options, and rendering a child from a component are not supported.

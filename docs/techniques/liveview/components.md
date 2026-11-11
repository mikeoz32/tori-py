# Stateful Components

A `LiveComponent` is a piece of a page with its own state and event handlers. It
shares the page's WebSocket connection and is rendered by the page. Use one when
several independent copies of the same widget need separate state, such as one
editor per row or a counter per panel.

For stateless markup, write a plain function that returns a template, or use the
[LiveView UI](../liveview-ui/index.md) helpers. Components are only worth their
lifecycle when they own state.

## Define and Render a Component

```python
from string.templatelib import Template

from tori_py_liveview import (
    LiveComponent,
    LiveView,
    UnknownEventError,
    fragment,
    live_view,
)


class RatingComponent(LiveComponent):
    def __init__(self) -> None:
        self.label = ""
        self.stars = 0

    def update(self, assigns: object) -> None:
        if not isinstance(assigns, dict) or not isinstance(assigns.get("label"), str):
            raise TypeError("RatingComponent requires a string label")
        self.label = assigns["label"]

    async def handle_event(self, event: str, value: object) -> None:
        match event, value:
            case "rate", {"stars": str(stars)} if stars in {"1", "2", "3"}:
                self.stars = int(stars)
            case _:
                raise UnknownEventError(event)

    def render(self) -> Template:
        buttons = fragment(
            t'<button phx-click="rate" phx-target="{self.myself}" '
            t'phx-value-stars="{n}">{n}</button>'
            for n in (1, 2, 3)
        )
        return (
            t'<section id="rating-{self.id}"><h3>{self.label}</h3>'
            t"{buttons}<output>{self.stars}</output></section>"
        )


@live_view("/review")
class ReviewLive(LiveView):
    def render(self) -> Template:
        food = self.live_component(RatingComponent, "food", {"label": "Food"})
        service = self.live_component(RatingComponent, "service", {"label": "Service"})
        return t"<main>{food}{service}</main>"
```

Each `live_component(component_type, component_id, assigns)` call inside
`render()` returns a component reference to interpolate. `phx-target` with
`self.myself` sends an event to that component instead of the page.

## Identity and Lifecycle

A component's identity is its concrete class plus the string ID passed to
`live_component()`. The page keeps one instance per identity for as long as the
identity keeps being rendered.

| Callback | When |
| --- | --- |
| `__init__()` | When a new identity is first rendered; takes no arguments |
| `mount()` | Once, right after the instance is attached |
| `update(assigns)` | Before every render of the component, with the assigns passed by the page |
| `render()` | Every time the page renders it |
| `async handle_event(event, value)` | For events whose `phx-target` is `self.myself` |
| `async disconnect()` | Once, when the component is destroyed or the page ends |

`mount()`, `update()`, and `render()` are synchronous. Do I/O in the page or in
`handle_event()`, and pass the results down as assigns.

| Property | Meaning |
| --- | --- |
| `id` | The string ID given by the page |
| `myself` | The connection-local numeric component ID, used as `phx-target` |
| `connected` | Whether the owning page is the connected instance |

Components are not resolved from the DI container. Constructor injection does
not apply; pass dependencies through assigns or a `factory`:

```python
editor = self.live_component(
    EditorComponent,
    f"task-{task.id}",
    {"task": task},
    factory=lambda: EditorComponent(self.tasks),
)
```

`factory` runs only when the identity is new, and it must return exactly the
declared class.

## Removal

When a render no longer includes an identity, the component is not destroyed
immediately. The official client first confirms that the component's DOM is gone
and then asks the server to destroy it. Until that handshake completes, rendering
the same identity again revives the same instance and state. After it completes,
the server calls `disconnect()` and forgets the instance; rendering that identity
later creates fresh state and a new `myself`.

Override `disconnect()` to release component-owned resources. Exceptions from it
are logged and do not affect other components.

## Rules

- Call `live_component()` only while the page is rendering. Calling it elsewhere
  raises `LiveViewError`.
- Render each identity at most once per page render.
- A component's output must have exactly one root element with explicit,
  balanced end tags. Optional end tags, such as an unclosed `<li>` or `<p>`, are
  rejected.
- Treat `myself` as connection-local. Never store it or construct one; render it
  from the component.
- Nested components are not supported: a component cannot render another
  component.
- Component events are as untrusted as page events. Validate values and
  authorize actions in `handle_event()`.

The HTTP render also creates, mounts, and renders components, then disconnects
them after the document is built. The connected page creates its own instances.

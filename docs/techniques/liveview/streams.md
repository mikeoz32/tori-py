# Streams

A stream lets the browser own a collection's rendered children. The page sends
insert, delete, and reset operations; the client applies them to a container and
keeps the existing DOM. The server does not keep the items, so memory stays flat
for feeds, logs, chat histories, and long tables.

Use ordinary page state for small collections you re-render as a whole. Use a
stream when the collection is large, grows without bound, or should not be held
in every connected page.

## A Stream Page

```python
from string.templatelib import Template

from tori_py_liveview import LiveView, MountContext, UnknownEventError, live_view


@live_view("/activity")
class ActivityLive(LiveView):
    def __init__(self) -> None:
        self.next_id = 1

    async def mount(self, context: MountContext) -> None:
        self.stream_reset("activity")
        for text in ("Signed in", "Opened settings"):
            self.add(text)

    def add(self, text: str, *, at: int = -1) -> None:
        item_id = f"activity-{self.next_id}"
        self.next_id += 1
        self.stream_insert(
            "activity",
            item_id,
            t'<li id="{item_id}">{text} '
            t'<button phx-click="remove" phx-value-id="{item_id}">×</button></li>',
            at=at,
            limit=-50,
        )

    async def handle_event(self, event: str, value: object) -> None:
        match event, value:
            case "ping", _:
                self.add("Ping", at=0)
            case "remove", {"id": str(item_id)}:
                self.stream_delete("activity", item_id)
            case _:
                raise UnknownEventError(event)

    def render(self) -> Template:
        items = self.stream_contents("activity")
        return (
            t'<button phx-click="ping">Ping</button>'
            t'<ul id="activity" phx-update="stream">{items}</ul>'
        )
```

## Operations

| Method | Effect |
| --- | --- |
| `stream_insert(container_id, item_id, item, *, at=-1, limit=None)` | Append, insert at an index, or replace an existing item in place |
| `stream_delete(container_id, item_id)` | Remove one direct child |
| `stream_reset(container_id)` | Remove all children |
| `stream_contents(container_id)` | The value to interpolate inside the container |

`at=-1` appends and `at=0` prepends; any other non-negative index inserts there.
Inserting an ID that already exists updates that child where it is.

`limit` bounds the container after the insert. A positive limit keeps the first
N children; a negative limit keeps the last N. Typical pairs are `at=0,
limit=50` for newest-first feeds and `at=-1, limit=-50` for logs.

Operations queue on the page and are sent with the next render, then cleared. A
render that includes no new operations leaves the browser's children untouched.

## Item Rules

- `item` is a `Template`, a `Rendered` value, or a `str`. A `str` is trusted
  HTML, so use a template for any data.
- Each item has exactly one root element with explicit, balanced end tags.
- The root element's `id` must equal `item_id`, and DOM IDs must be unique in
  the page.
- Container and item IDs are non-empty strings without whitespace or control
  characters.

Invalid items raise `ValueError` or `TypeError` when inserted.

## Container Rules

Render the container with `phx-update="stream"` and the container's DOM `id`
equal to `container_id`. Interpolate only `stream_contents()` inside it:

```python
items = self.stream_contents("activity")
return t'<ul id="activity" phx-update="stream">{items}</ul>'
```

Phoenix preserves a stream container's children across patches, so any other
dynamic children you render there would not update. Put headers, empty states,
and controls outside the container.

## HTTP Render and Reconnects

The HTTP render applies the queued operations in order and renders the
resulting items as plain HTML, so the first response already shows the list.
The connected page sends them as stream operations.

A reconnect or live navigation mounts a fresh page with no stream history. The
browser's old children are not kept in sync automatically. Call
`stream_reset()` in `mount()` and insert the canonical items again, as in the
example above, so every mount rebuilds the same list.

Operations queued during an event that raises `UnknownEventError` are discarded.
The server does not retry delivery: once a render with stream operations has
been sent, they are gone from the page.

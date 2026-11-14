# Feedback

Feedback helpers tell the visitor what happened and what is still happening.

| Helper | Use it for |
| --- | --- |
| `alert` | A message in the flow of the page |
| `banner` | A notice that concerns the whole page |
| `toast`, `toast_region` | A short message that floats above the page |
| `flash_group` | The page's [flash](../liveview/flash-and-async.md#flash) as toasts |
| `spinner`, `skeleton`, `busy` | Work in progress |
| `connection_status` | A lost connection to the server |

## Alerts and Banners

`alert(content, *, title, tone, actions, dismissible, dismiss_event, ...)`
renders a `<section>` with `role="status"`, or `role="alert"` for the `danger`
tone. `banner(content, *, tone, actions, dismissible, dismiss_event, ...)` is a
flat strip for the top of a page or a region.

Both can be dismissed in two ways:

```python
from tori_py_liveview_ui import alert

# The browser hides it. The page is not told, and the alert returns on the
# next full page load.
alert("Saved as a draft.", tone="info", dismissible=True)

# The button pushes an event, and the page stops rendering the alert.
alert("Your trial ends soon.", tone="warning", dismiss_event="hide_trial_notice")
```

Use `dismiss_event` when the dismissal should last, and `dismissible` when it is
only in the way right now.

## Toasts

A toast region is fixed to a corner of the viewport, and toasts stack in it.
Render one region per page and keep the toasts in page state:

```python
from string.templatelib import Template

from tori_py_liveview import JS, LiveView, UnknownEventError
from tori_py_liveview_ui import button, toast, toast_region


class InboxLive(LiveView):
    def __init__(self) -> None:
        self.toasts: dict[int, str] = {}
        self.sent = 0

    async def handle_event(self, event: str, value: object) -> None:
        match event, value:
            case "send", _:
                self.sent += 1
                self.toasts[self.sent] = f"Message {self.sent} sent."
            case "dismiss_toast", {"id": int(toast_id)}:
                self.toasts.pop(toast_id, None)
            case _:
                raise UnknownEventError(event)

    def render(self) -> Template:
        toasts = toast_region(
            toast(
                message,
                id=f"toast-{toast_id}",
                tone="success",
                dismiss_event=JS().push("dismiss_toast", value={"id": toast_id}),
            )
            for toast_id, message in self.toasts.items()
        )
        return t"{button('Send', event='send')}{toasts}"
```

`toast(content, *, id, title, tone, duration, dismiss_event, ...)`:

- `id` is required and must be unique on the page.
- The toast closes itself after `duration` milliseconds, 5000 by default. The
  countdown pauses while the visitor points at the toast or focuses inside it.
  `duration=None` keeps it until dismissed; use that for errors.
- Closing presses the toast's own dismiss button. Without `dismiss_event` the
  browser hides the toast; the page will render it again unless it stops. With
  `dismiss_event` the page removes it, as above. A `JS().push(...)` chain
  carries the toast's ID to the handler.

`toast_region(children, *, id, placement, label)` takes a `placement` of
`top-start`, `top-end`, `bottom-start`, or `bottom-end`.

## Flash

`flash_group(flash, *, id, placement, label, duration)` renders the page's flash
messages as toasts:

<!-- docs-test: skip -->

```python
def render(self) -> Template:
    return t"<main>...</main>{flash_group(self.flash)}"
```

It shows the `info`, `success`, `warning`, and `error` kinds. `info` and
`success` close themselves after `duration`; `warning` and `error` stay until
dismissed. Closing a toast clears its kind through LiveView's built-in
`lv:clear-flash` event, so the message does not return on the next render.

## Loading

| Helper | Output |
| --- | --- |
| `spinner(*, label, size)` | A spinner that announces `label` to screen readers |
| `skeleton(*, shape, lines)` | A placeholder shaped like the content to come |
| `busy(content, *, busy, label)` | A region that dims and shows a spinner while `busy` |

```python
from tori_py_liveview_ui import busy, skeleton, table

rows: list[list[object]] | None = None  # None while the query runs

report = busy(
    skeleton(lines=4) if rows is None else table(["Name", "Total"], rows),
    busy=rows is None,
    label="Loading the report",
)
```

A skeleton's `shape` is `text` (with 1 to 20 `lines`), `block`, or `circle`.
Skeletons are hidden from assistive technology, so pair them with `busy()` or a
`spinner()` whose label says what is loading.

While `busy` is true the region is inert: its controls take no clicks and no
keyboard focus. For a single control, use
[`button(loading=True)`](actions.md#loading).

## Connection Status

`connection_status(*, message)` tells the visitor that the page has lost its
connection. Render it once, anywhere inside the page. It stays hidden while
LiveView is connected and appears at the top of the viewport while the client
reconnects, because the client marks the page's root element in that state.

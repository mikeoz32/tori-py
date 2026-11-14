# Actions

Action helpers render the controls a visitor presses: buttons, links that look
like buttons, and two controls that act in the browser alone.

```python
from string.templatelib import Template

from tori_py_liveview import LiveView, UnknownEventError
from tori_py_liveview_ui import button, icon_button, row


class CartLive(LiveView):
    def __init__(self) -> None:
        self.items: dict[str, int] = {"tea": 1, "mug": 2}

    async def handle_event(self, event: str, value: object) -> None:
        match event, value:
            case "add", {"sku": str(sku), "amount": str(amount)}:
                self.items[sku] = self.items.get(sku, 0) + int(amount)
            case "remove", {"sku": str(sku)}:
                self.items.pop(sku, None)
            case _:
                raise UnknownEventError(event)

    def line(self, sku: str, count: int) -> Template:
        add = button(
            "Add",
            size="sm",
            icon="plus",
            event="add",
            values={"sku": sku, "amount": 1},
        )
        remove = icon_button(
            "trash",
            label=f"Remove {sku}",
            variant="danger",
            event="remove",
            values={"sku": sku},
            confirm=f"Remove {sku} from the cart?",
        )
        return t'<li id="line-{sku}">{row([f"{sku}: {count}", add, remove])}</li>'
```

## Buttons

`button(label, *, variant, size, button_type, disabled, event, target, ...)`
renders a native `<button>`. `variant` is `primary`, `secondary`, `ghost`, or
`danger`; `size` is `sm`, `md`, or `lg`; `button_type` is `button`, `submit`, or
`reset`.

| Option | Effect |
| --- | --- |
| `event`, `target` | `phx-click` and `phx-target`; see [events](index.md#events) |
| `values` | Values the click sends with its event |
| `icon`, `icon_end` | A bundled [icon](content.md#icons) before or after the label |
| `loading` | Shows a spinner, disables the button, and sets `aria-busy` |
| `disable_with` | The label to show while the event or form submit is in flight |
| `confirm` | A question the visitor must accept before the click counts |
| `full_width` | Stretches the button to its container |

### Event Values

`values` becomes `phx-value-*` attributes, and the handler receives them as a
mapping with string values:

```python
button("Archive", event="archive", values={"id": "m1", "pinned": True})
# handle_event("archive", {"id": "m1", "pinned": "true"})
```

Keys must start with a lowercase letter and contain only lowercase letters,
digits, `-`, and `_`. Values are strings, numbers, or booleans. `values`
without an `event` raises `ValueError`.

### Loading

Three states cover different moments:

- `loading=True` is state your page owns, for work that outlasts one event, such
  as a job started with [`start_async()`](../liveview/flash-and-async.md).
- `disable_with="Saving..."` is handled by the Phoenix client for the time one
  event takes: it swaps the label and disables the button until the server
  answers.
- The client also marks the button with `phx-click-loading` during the round
  trip, and a submit button inside a submitting form dims. This needs no option.

### Confirm

`confirm` asks in the browser's own dialog before the click reaches LiveView.
When the visitor cancels, no event is sent and a submit button does not submit.
The text is escaped; it cannot carry markup.

## Icon Buttons

`icon_button(icon, *, label, variant, size, disabled, pressed, event, ...)`
renders a square button with only an icon. `label` is required: it is the
button's accessible name and its tooltip.

`pressed=True` or `pressed=False` makes it a toggle button that reports its
state through `aria-pressed`. Your page owns the state and passes it on every
render:

```python
icon_button("star", label="Favorite", pressed=True, event="toggle_favorite")
```

## Link Buttons

`link_button(label, *, href, variant, size, live, replace, external, ...)`
renders an `<a>` with a button's look. Use it for navigation and `button` for
actions. It takes the same `live`, `replace`, and `external` options as
[`link`](content.md#links), plus `icon`, `icon_end`, and `full_width`.

```python
from tori_py_liveview_ui import link_button

link_button("Open report", href="/reports/7", live="navigate", icon_end="arrow-right")
```

## Button Groups

`button_group(children, *, label, attached)` wraps related buttons in a group
named by `label`. By default the buttons join into one segmented control;
`attached=False` keeps them apart.

```python
from tori_py_liveview_ui import button_group

button_group(
    [button("Day", variant="secondary"), button("Week", variant="secondary")],
    label="Range",
)
```

## Copy Button

`copy_button(*, to, label, copied_label, variant, size)` copies an element's
text to the clipboard. It works in the browser alone: the page is not told.

`to` selects the element the way a [`JS` command](../liveview/js-commands.md)
target does:

```python
from tori_py_liveview_ui import copy_button

copy_button(to="#api-key")                      # a CSS selector
copy_button(to=("closest", ".invite"))          # an ancestor of the button
copy_button(to=("inner", ".tori-ui-code"))      # a descendant of the button
```

The text comes from the element's first descendant marked
`data-tori-ui-copy-source`, or from the element itself: a form control's value,
or the text as rendered. For two seconds the button shows `copied_label` and
announces it to screen readers.

Browsers allow clipboard access on HTTPS and on `localhost`. On plain HTTP from
another host the button falls back to the older copy command, which most
browsers still honor.

## Theme Toggle

`theme_toggle(*, id, label, auto_label, light_label, dark_label)` lets the
visitor choose the system, light, or dark theme. The browser stores the choice
and applies it to every `UiLiveView` document before it paints, so there is no
flash of the other theme and nothing for the page to handle. See
[Themes and Skins](theming.md#letting-the-visitor-choose).

`id` is required and must be unique on the page; several toggles on one page
stay in step.

# LiveView UI

`tori-py-liveview-ui` is a small presentation layer for
[LiveView](../liveview/index.md) pages: typed, stateless template helpers for
layout, display, and forms, plus one local stylesheet with color themes and
visual skins. It adds no JavaScript, no client runtime, no state model, and no
validation engine. Pages and components keep owning state and behavior.

```text
uv add tori-py-liveview tori-py-liveview-ui
```

## Setup

Import `LiveViewUiModule` next to the LiveView module and derive pages from
`UiLiveView`:

```python
from string.templatelib import Template

from tori_py import module
from tori_py_liveview import LiveViewModule, LiveViewOptions, live_view
from tori_py_liveview_ui import LiveViewUiModule, UiLiveView, button, card, stack


@live_view("/dashboard")
class DashboardLive(UiLiveView):
    def __init__(self) -> None:
        self.refreshes = 0

    async def handle_event(self, event: str, value: object) -> None:
        if event != "refresh":
            await super().handle_event(event, value)
            return
        self.refreshes += 1

    def render(self) -> Template:
        action = button("Refresh", event="refresh")
        panel = card(
            t"<p>Refreshed {self.refreshes} times.</p>",
            title="Dashboard",
            footer=action,
        )
        return t"<main>{stack([panel], gap='lg')}</main>"


liveview_module = LiveViewModule.for_root(
    LiveViewOptions(secret="replace-with-at-least-32-secret-bytes"),
    pages=[DashboardLive],
)


@module(imports=[liveview_module, LiveViewUiModule.for_root()])
class AppModule:
    pass
```

`LiveViewUiModule.for_root(key="default")` registers one route that serves the
bundled CSS at `STYLESHEET_PATH`, a content-addressed path such as
`/_tori/liveview-ui/<hash>.css` with immutable caching headers and an ETag.

`UiLiveView` is a `LiveView` whose `render_document()` adds the stylesheet link
and the `data-tori-ui-theme` and `data-tori-ui-skin` attributes to `<html>`.
Override `ui_theme()` and `ui_skin()` to choose them; see
[Themes and Skins](theming.md). A page with its own `render_document()` can call
`stylesheet_link()` and set the attributes itself.

## Helpers

Every helper returns a `Template`, so helpers nest inside each other and inside
your own templates. Content arguments follow LiveView's escaping rules: strings
are escaped, and templates and helper results stay markup.

### Layout and Display

| Helper | Output | Options |
| --- | --- | --- |
| `stack(children, *, gap, align)` | Vertical flow | `gap`: `xs`, `sm`, `md`, `lg`, `xl`; `align`: `start`, `center`, `end`, `stretch` |
| `grid(children, *, columns, gap)` | Responsive grid | `columns`: `"auto"`, `"1"`, `"2"`, `"3"`, `"4"` (strings) |
| `card(content, *, eyebrow, title, footer)` | `<article>` with optional header and footer | `title` renders as `<h2>` |
| `alert(content, *, title, tone)` | `<section>` with `role="status"`, or `role="alert"` for `danger` | `tone`: `neutral`, `info`, `success`, `warning`, `danger` |
| `badge(content, *, tone)` | Inline status label | Same tones as `alert` |
| `button(label, *, variant, size, button_type, disabled, event, target)` | `<button>` | `variant`: `primary`, `secondary`, `ghost`, `danger`; `size`: `sm`, `md`, `lg`; `button_type`: `button`, `submit`, `reset` |

### Forms

| Helper | Output |
| --- | --- |
| `form(content, *, id, change_event, submit_event, target)` | `<form method="post">` with optional `phx-change`, `phx-submit`, `phx-target` |
| `input(label, *, id, name, value, input_type, ...)` | Labeled `<input>` with help and error text |
| `textarea(label, *, id, name, value, rows, ...)` | Labeled `<textarea>` with 1 to 100 rows |
| `select(label, options, *, id, name, value, prompt, ...)` | Labeled `<select>` over `(value, label)` pairs |
| `checkbox(label, *, id, name, value, checked, ...)` | Labeled checkbox with an explicit submitted value |
| `field(label, control, *, control_id, help_text, error, required)` | Label and messages around your own control |
| `field_error(message, *, id)` | Error paragraph with `role="alert"` |

[Forms](forms.md) explains names, decoded values, validation, and accessibility.

## Events

`button(event=...)` binds `phx-click`. Form controls accept `change_event` and
`blur_event`, and `form()` accepts `change_event` and `submit_event`. Each event
option takes an event name or a [`JS`](../liveview/js-commands.md) chain:

```python
from tori_py_liveview import JS

close = JS().hide(to="#settings").pop_focus()
button("Close", variant="ghost", event=close)
```

`target` sends the event to a stateful component; pass the component's
`self.myself`. A `target` without any event raises `ValueError`.

```python
from string.templatelib import Template

from tori_py_liveview import LiveComponent


class TodoComponent(LiveComponent):
    def render(self) -> Template:
        done = button("Done", size="sm", event="done", target=self.myself)
        return t'<li id="todo-{self.id}">{self.title} {done}</li>'
```

## Contract

The helpers are deliberately closed:

- Visual options are closed sets. An unknown variant, size, tone, gap, or column
  count raises `ValueError` immediately.
- There are no `class=` or `**attrs` escape hatches. Style through the theme and
  skin tokens, or write your own template for markup the helpers do not cover.
- Helpers hold no state and emit no JavaScript. They only render native elements
  and standard Phoenix bindings.
- IDs must be non-empty and contain no whitespace; boolean options must be real
  `bool` values.

All CSS selectors use the `tori-ui-` prefix and the stylesheet has no global
reset, so the helpers can sit next to your own styles.

## Guide Map

| Topic | Read |
| --- | --- |
| Form controls, names, validation feedback, accessibility | [Forms](forms.md) |
| Light and dark themes, bundled skins, custom skins, CSS tokens | [Themes and Skins](theming.md) |
| Page lifecycle, events, and escaping | [LiveView](../liveview/index.md) |

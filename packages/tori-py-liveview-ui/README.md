# tori-py-liveview-ui

`tori-py-liveview-ui` is the optional styled foundation for Tori Py LiveView. It
provides six stateless, typed Python 3.14 template helpers and a locally bundled
stylesheet. It uses the existing LiveView/Opal rendering and event contracts; it
does not add a browser runtime or own state.

```text
uv add tori-py-liveview-ui
```

The distribution depends on `tori-py-framework` and `tori-py-liveview`. Install
only this package when the application already uses LiveView; `uv` resolves both
dependencies.

## Quick start

Import the UI stylesheet module with the normal LiveView module, then inherit
from `UiLiveView`:

```python
from string.templatelib import Template

from tori_py import module
from tori_py_liveview import LiveViewModule, LiveViewOptions, live_view
from tori_py_liveview_ui import (
    LiveViewUiModule,
    UiLiveView,
    alert,
    badge,
    button,
    card,
    stack,
)


@live_view("/status")
class StatusLive(UiLiveView):
    def render(self) -> Template:
        notice = alert("Changes are saved.", title="Ready", tone="success")
        actions = button("Refresh", variant="secondary", event="refresh")
        return stack(
            [
                card(notice, eyebrow="Account", title="Status", footer=actions),
                badge("Online", tone="success"),
            ],
            gap="lg",
        )


liveview_module = LiveViewModule.for_root(
    LiveViewOptions(secret="replace-with-at-least-32-secret-bytes"),
    pages=[StatusLive],
)


@module(imports=[liveview_module, LiveViewUiModule.for_root()])
class AppModule:
    pass
```

`UiLiveView` inserts the stylesheet into the standard LiveView document and sets
`data-tori-ui-theme="auto"` on `<html>`. Override `ui_theme()` to return
`"light"` or `"dark"`. For a custom `render_document()`, put
`stylesheet_link()` in the document head yourself. `LiveViewUiModule.for_root()`
serves the stylesheet at `STYLESHEET_PATH`, a SHA-256 content-addressed path with
an immutable one-year cache policy.

## Components

Every helper returns a `Template`, so text interpolation stays HTML escaped and
nested LiveView templates compose normally. Do not use interpolation for tag
names, attribute names, unquoted attributes, CSS, or JavaScript. Passing
`Template`, `Rendered`, or `SafeHtml` content is the same explicit trusted
composition boundary as in LiveView; do not mark untrusted input as raw markup.
LiveView's `attrs()` helper also rejects executable URL schemes, event-handler
names, inline styles, and `srcdoc`; it remains an encoding helper rather than a
general content-sanitization API.

| Helper | Options |
| --- | --- |
| `button(label, ...)` | `variant`: `primary`, `secondary`, `ghost`, `danger`; `size`: `sm`, `md`, `lg`; `button_type`: `button`, `submit`, `reset`; `disabled`; optional `event` and `target` |
| `badge(content, ...)` | `tone`: `neutral`, `info`, `success`, `warning`, `danger` |
| `alert(content, ...)` | optional string `title`; `tone`: `neutral`, `info`, `success`, `warning`, `danger` |
| `card(content, ...)` | optional string `eyebrow`, optional string `title`, optional `footer` |
| `stack(children, ...)` | `gap`: `xs`, `sm`, `md`, `lg`, `xl`; `align`: `start`, `center`, `end`, `stretch` |
| `grid(children, ...)` | `columns`: `auto`, `1`, `2`, `3`, `4`; `gap`: `xs`, `sm`, `md`, `lg`, `xl` |

`stack` and `grid` consume a finite iterable once. Unknown visual values fail
early. The API intentionally has no arbitrary `attrs` or `class` parameter:
callers cannot inject arbitrary attributes or classes through these helpers.

`button(event="save")` emits `data-opal-click="save"`. For a stateful
`LiveComponent`, pass its positive connection-local `myself` target as
`target`; `target` requires an event. The helper only emits existing Opal
attributes—it does not create JavaScript behavior or route events itself.

## Styling and accessibility

The local CSS uses only `tori-ui-` selectors and has no global element reset.
Its public `--tori-ui-*` custom properties cover colors, shadows, and system font
stacks, so application CSS can override the design tokens. No CDN, Node tooling,
external fonts, remote assets, or runtime JavaScript are required.

The stylesheet supports auto/light/dark color themes, responsive grid collapse,
visible keyboard focus, disabled button affordance, and reduced-motion button
transitions. `alert` uses a semantic status role (or an alert role for danger),
and `card` and button markup use native semantic elements.

## Scope

This is a deliberately small foundation, not a full component framework. It does
not include forms, validation UI, modals, navigation, menus, uploads, Tailwind or
Bootstrap integration, JavaScript widgets, a global reset, arbitrary
attribute/class injection, or page/component state ownership.

See the normative [architecture](../../../TORI_PY_LIVEVIEW_UI_ARCHITECTURE.md)
and [implementation plan](../../../TORI_PY_LIVEVIEW_UI_IMPLEMENTATION_PLAN.md).

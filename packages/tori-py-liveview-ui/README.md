# ToriPy LiveView UI

`tori-py-liveview-ui` is a separately installable presentation foundation for
`tori-py-liveview`. It provides six stateless typed template helpers, a local
content-addressed stylesheet, and an optional `UiLiveView` document base. It
does not add another browser client, protocol, state model, or JavaScript
runtime.

```bash
uv add tori-py-liveview-ui
```

## Setup

Register the UI module beside the normal LiveView module:

```python
from tori_py import module
from tori_py_liveview import LiveViewModule
from tori_py_liveview_ui import LiveViewUiModule

liveview_module = LiveViewModule.for_root(...)


@module(imports=[liveview_module, LiveViewUiModule.for_root()])
class ApplicationModule:
    pass
```

`LiveViewUiModule` serves the exact bundled CSS bytes at the immutable
content-addressed `STYLESHEET_PATH`. `UiLiveView` inserts the corresponding
stylesheet link and sets `data-tori-ui-theme="auto"` by default:

```python
from string.templatelib import Template

from tori_py_liveview_ui import UiLiveView, button, card, stack


class DashboardLive(UiLiveView):
    def render(self) -> Template:
        action = button("Refresh", event="refresh")
        panel = card("Latest server state", title="Dashboard", footer=action)
        return stack([panel], gap="lg")
```

Override `ui_theme()` with `"light"` or `"dark"` for a fixed theme. A custom
`LiveView.render_document()` can use `stylesheet_link()` directly instead.

## Components

- `button`: primary, secondary, ghost, and danger variants; small, medium, and
  large sizes; optional Phoenix `phx-click` event and component `phx-target`.
- `badge`: neutral, info, success, warning, and danger tones.
- `alert`: accessible status or danger alert with an optional title.
- `card`: optional eyebrow, heading, and footer regions.
- `stack`: vertical layout with closed gap and alignment options.
- `grid`: responsive auto-fit or one-to-four-column layout.

All helpers return Python 3.14 template strings. Ordinary content remains
escaped by `tori-py-liveview`; nested templates and trusted rendered values
compose explicitly. Unsupported visual options fail immediately, and the
helpers do not accept arbitrary class names or attribute dictionaries.

## Styling Contract

Selectors use the `tori-ui-` prefix. Public `--tori-ui-*` custom properties
cover surfaces, text, lines, accent/tone colors, shadows, and font stacks and
may be overridden by application CSS. The stylesheet includes explicit and
system-driven light/dark themes, responsive grids, visible keyboard focus,
disabled behavior, and reduced-motion support.

There is no CDN, Node dependency, external font, global reset, runtime
JavaScript, form system, or widget-owned behavior in this package.

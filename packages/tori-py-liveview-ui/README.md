# ToriPy LiveView UI

`tori-py-liveview-ui` is a separately installable presentation foundation for
`tori-py-liveview`. It provides stateless typed display, layout, and form
template helpers, a local content-addressed stylesheet, and an optional
`UiLiveView` document base with independent color themes and visual skins. It
does not add another browser client, protocol, validation engine, state model,
or JavaScript runtime.

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
stylesheet link and sets `data-tori-ui-theme="auto"` plus
`data-tori-ui-skin="editorial"` by default:

```python
from string.templatelib import Template

from tori_py_liveview_ui import UiLiveView, button, card, stack


class DashboardLive(UiLiveView):
    def render(self) -> Template:
        action = button("Refresh", event="refresh")
        panel = card("Latest server state", title="Dashboard", footer=action)
        return stack([panel], gap="lg")

    def ui_skin(self) -> str:
        return "minimal"
```

Override `ui_theme()` with `"light"` or `"dark"` for a fixed theme. A custom
`LiveView.render_document()` can use `stylesheet_link()` and set the theme and
skin data attributes directly instead.

## Components

Display and layout:

- `button`: primary, secondary, ghost, and danger variants; small, medium, and
  large sizes; optional Phoenix `phx-click` event and component `phx-target`.
- `badge`: neutral, info, success, warning, and danger tones.
- `alert`: accessible status or danger alert with an optional title.
- `card`: optional eyebrow, heading, and footer regions.
- `stack`: vertical layout with closed gap and alignment options.
- `grid`: responsive auto-fit or one-to-four-column layout.

Forms and validation presentation:

- `form`: native POST form with optional Phoenix `phx-change`, `phx-submit`, and
  component `phx-target` bindings.
- `input`: labeled text-like control with a closed set of safe input types.
- `textarea`: labeled multiline control with one to 100 rows.
- `select`: labeled single-value select over explicit `(value, label)` options.
- `checkbox`: labeled native checkbox with an explicit submitted value.
- `field`: labeled wrapper for application-owned custom controls.
- `field_error`: live validation feedback with `role="alert"`.

All helpers return Python 3.14 template strings. Ordinary content remains
escaped by `tori-py-liveview`; nested templates and trusted rendered content
compose explicitly. Form attribute and textarea values remain documented
scalars rather than render-tree extension points. Unsupported visual options
fail immediately, and the helpers do not accept arbitrary class names or
attribute dictionaries.

## Forms

Form controls include native labels and can render help and validation error
text. Generated IDs connect those messages through `aria-describedby`; errors
also set `aria-invalid="true"` on the control.

```python
from tori_py_liveview_ui import button, form, input, stack

email = input(
    "Email",
    id="profile-email",
    name="profile[email]",
    value=self.email,
    input_type="email",
    autocomplete="email",
    help_text="Used for account notices.",
    error=self.email_error,
    required=True,
)
profile_form = form(
    stack(
        [email, button("Save", button_type="submit")],
        gap="sm",
        align="start",
    ),
    id="profile-form",
    change_event="validate",
    submit_event="save",
)
```

`name` is emitted unchanged, including LiveView bracket notation such as
`profile[email]` and `tags[]`. Form change and submit handlers receive a decoded
name-shaped mapping whose leaves are strings; unchecked checkboxes are absent.
A `phx-blur` handler instead receives the control event mapping, normally
`{"value": "..."}`. Pages and components own coercion, domain validation,
current values, and error state.

Control-level `change_event` is valid only when the control is inside a form, as
required by the official Phoenix client. A submit button inside a `phx-submit`
form normally has no click event, avoiding duplicate application events. Forms
use native `method="post"` so a disconnected submission does not expose values
in the URL; applications that require non-JavaScript fallback must provide and
link to their own HTTP POST endpoint.

`field()` supports custom controls. The caller must give the control the same ID
as `control_id`, connect optional `<control-id>-help` and
`<control-id>-error` descriptions, and apply native `required` and
`aria-invalid` state itself.

## Skins

Color theme and visual skin are separate:

- `ui_theme()` selects `auto`, `light`, or `dark` palette values.
- `ui_skin()` selects geometry, density, typography, and shadows.

Bundled skins are `editorial` (default), `minimal`, and `rounded`. Skin selection
is part of the initial outer document and does not change through normal
connected LiveView diffs.

Application-owned skin names match `[a-z][a-z0-9-]{0,63}` and override public
tokens in application CSS loaded after the package stylesheet:

```python
class BrandLive(UiLiveView):
    def ui_skin(self) -> str:
        return "acme"
```

```css
[data-tori-ui-skin="acme"] {
  --tori-ui-space-md: 1.125rem;
  --tori-ui-radius-control: 0.5rem;
  --tori-ui-radius-surface: 0.75rem;
  --tori-ui-control-height-md: 2.75rem;
  --tori-ui-field-control-height: 2.75rem;
  --tori-ui-field-control-radius: 0.5rem;
  --tori-ui-border-width: 2px;
  --tori-ui-font-body: Inter, system-ui, sans-serif;
  --tori-ui-shadow-x: 0;
  --tori-ui-shadow-y: 8px;
  --tori-ui-shadow-blur: 24px;
  --tori-ui-shadow-spread: -16px;
}
```

Missing custom values inherit the root editorial defaults. Application CSS is
not concatenated into the immutable package asset and does not alter its URL or
ETag.

## Styling Contract

Selectors use the `tori-ui-` prefix. Public `--tori-ui-*` custom properties
cover surfaces, text, lines, accent/tone colors, spacing, radii, control heights,
borders, typography, shadows, focus geometry, and density. The stylesheet
includes explicit and system-driven light/dark themes, three bundled skins,
responsive grids, visible keyboard focus, disabled behavior, and reduced-motion
support.

There is no CDN, Node dependency, external font, global reset, runtime
JavaScript, validation/coercion engine, or widget-owned behavior in this
package. A future Tailwind integration belongs in a separately distributed
precompiled skin adapter, not in the core runtime dependency graph.

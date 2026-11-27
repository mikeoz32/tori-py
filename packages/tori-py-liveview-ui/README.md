# ToriPy LiveView UI

`tori-py-liveview-ui` is a separately installable component library for
`tori-py-liveview`. It provides stateless typed template helpers grouped in
families, a local content-addressed stylesheet, a local content-addressed script
of Phoenix hooks, and an optional `UiLiveView` document base with independent
color themes and visual skins. It does not add another browser client, protocol,
validation engine, or state model.

Python argument types, tuple shapes, and closed `Literal` options are enforced
by static type checking. Helpers trust those annotations and do not promise
runtime type errors for untyped calls. Validate external data before passing it
to a helper. Runtime checks retain semantic constraints such as required names,
numeric ranges, safe IDs/selectors, and argument relationships; rendering keeps
its escaping and URL scheme protections.

```bash
uv add tori-py-liveview-ui
```

The optional `markdown` extra adds the `markdown()` helper on `markdown-it-py`,
and the optional `highlight` extra colors its code blocks with Pygments:

```bash
uv add "tori-py-liveview-ui[markdown,highlight]"
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

`LiveViewUiModule` serves the exact bundled CSS and JavaScript bytes at the
immutable content-addressed `STYLESHEET_PATH` and `SCRIPT_PATH`. `UiLiveView`
inserts the corresponding stylesheet link and script tag, puts the
`tori-ui-document` surface class on `<body>`, and sets
`data-tori-ui-theme="paper"`, `data-tori-ui-mode="auto"`, and
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

Override `ui_mode()` with `"light"` or `"dark"` for a fixed color mode. A custom
`LiveView.render_document()` can use `stylesheet_link()` and `script_tag()` and
set the theme, mode, and skin data attributes directly instead.

The script defines `ToriUi`-prefixed Phoenix hooks for the few behaviors that
native elements and LiveView `JS` commands cannot express, and adds them to
`globalThis.ToriLiveHooks` beside the application's own hooks. It loads no
remote code and holds no application state.

## Components

The helpers are grouped in families:

- Layout: `app_shell`, `card`, `center`, `container`, `divider`, `grid`,
  `page_header`, `row`, `scroll_area`, `section`, `spacer`, `split`, `stack`,
  and `toolbar`.
- Content: `blockquote`, `code`, `code_block`, `description_list`, `heading`,
  `image`, `item_list`, `kbd`, `link`, `prose`, `text`, and `icon` with a closed
  set of bundled inline SVG icons.
- Actions: `button`, `button_group`, `copy_button`, `icon_button`,
  `link_button`, and `mode_toggle`.
- Display: `avatar`, `avatar_group`, `badge`, `empty_state`, `list_group`,
  `list_item`, `meter`, `progress`, `sparkline`, `stat`, `status_dot`, `table`,
  `table_row`, `tag`, `timeline`, `timeline_item`, and `tooltip`.
- Feedback: `alert`, `banner`, `busy`, `connection_status`, `flash_group`,
  `skeleton`, `spinner`, `toast`, and `toast_region`.
- Disclosure: `accordion`, `collapsible`, and `tabs`.
- Navigation: `navbar`, `nav`, `nav_item`, `breadcrumbs`, `pagination`, `steps`,
  `tab_links`, and `skip_link`.
- Overlays: `modal`, `drawer`, `confirm_dialog`, `dropdown`, `menu_item`,
  `popover`, and the `open_overlay` and `close_overlay` commands.
- Chat and AI: `chat`, `chat_log`, `chat_message`, `message_actions`,
  `composer`, `suggestions`, `chat_empty`, `typing_indicator`,
  `conversation_list`, `response_branch`, `reasoning`, `tool_call`,
  `agent_steps`, `agent_step`, `sources`, `citation`, `attachment`,
  `token_usage`, `artifact_panel`, and `markdown`.
- Forms: `form`, `fieldset`, `form_actions`, `field`, `field_error`, `input`,
  `textarea`, `select`, `multi_select`, `combobox`, `search`, `slider`,
  `checkbox`, `checkbox_group`, `radio_group`, `segmented`, `switch`, and
  `hidden`.

The gallery in `examples/tori_py/liveview_ui_gallery` shows every helper in each
theme and skin.

Foundation helpers:

- `button`: primary, secondary, ghost, and danger variants; small, medium, and
  large sizes; optional Phoenix `phx-click` event and component `phx-target`;
  icons, event values, loading state, and a native confirmation.
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

## Themes, Modes, and Skins

Color theme, color mode, and visual skin are separate:

- `ui_theme()` selects a `Theme`: one palette for light and one for dark.
- `ui_mode()` selects the `auto`, `light`, or `dark` palette.
- `ui_skin()` selects a `Skin`: geometry, density, typography, and shadows.

Themes and skins are typed definitions, and the package generates their CSS.
`Theme.from_seeds()` derives a theme from one or two colors, `Skin.derive()`
changes some tokens of a bundled skin, every value is validated, and a theme
is checked for WCAG AA contrast when it is built:

```python
from tori_py_liveview_ui import LiveViewUiModule, Skin, Theme

ACME = Theme.from_seeds("acme", accent="#7c3aed", neutral="#6b7280")
COMPACT = Skin.MINIMAL.derive("compact", radius_control="0.5rem")
ui_module = LiveViewUiModule.for_root(themes=[ACME], skins=[COMPACT])
```

A page returns `ACME` from `ui_theme()` and `COMPACT` from `ui_skin()`. The
bundled themes are `Theme.PAPER` (default), `Theme.SLATE`, and `Theme.CONTRAST`.

Bundled skins are `Skin.EDITORIAL` (default), `Skin.MINIMAL`, and `Skin.ROUNDED`.
The theme and the skin are part of the initial outer document and do not change
through normal connected LiveView diffs; the visitor switches the mode in the
browser with `mode_toggle()`.

A page may instead return a name that matches `[a-z][a-z0-9-]{0,63}` and define
the tokens in application CSS loaded after the package stylesheet:

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

See the [LiveView UI guide](https://mikeoz32.github.io/tori-py/techniques/liveview-ui/)
for forms, themes, skins, and the full token reference.

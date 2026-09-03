# ToriPy LiveView UI Architecture

## 1. Purpose

`tori-py-liveview-ui` is an optional, separately installable presentation
foundation for `tori-py-liveview`. It provides a small set of stateless Python
3.14 template helpers and one locally bundled, themeable and skinnable
stylesheet. It does not introduce a second LiveView runtime, browser protocol,
client script, or state model.

```text
tori-py-liveview-ui -> tori-py-framework, tori-py-liveview
tori-py-framework    -X-> tori-py-liveview-ui
tori-py-liveview     -X-> tori-py-liveview-ui
```

Applications explicitly import `LiveViewUiModule.for_root()` alongside their
`LiveViewModule`. The UI module materializes one ordinary ToriPy controller for
the stylesheet; it creates no providers and performs no discovery, package scan,
or global registration.

## 2. Public Surface

The public facade is `tori_py_liveview_ui`:

- `button`, `badge`, `alert`, `card`, `stack`, `grid`, `form`, `field`,
  `field_error`, `input`, `textarea`, `select`, and `checkbox` return
  `string.templatelib.Template` values;
- `LiveViewUiModule.for_root(key="default")` exposes the stylesheet route;
- `STYLESHEET_PATH` is that route's content-addressed path;
- `stylesheet_link()` returns the trusted `<link>` markup for a custom document;
- `UiLiveView` is a `LiveView` base class that installs the stylesheet link and
  independent document theme and skin attributes.

The functions are stateless render helpers, not `LiveComponent` instances. They
never mount, receive events, retain assigns, or own page or component state.

## 3. Component Contract

The foundation intentionally exposes a closed visual vocabulary:

| Helper | Closed values | Other documented inputs |
| --- | --- | --- |
| `button` | variants: `primary`, `secondary`, `ghost`, `danger`; sizes: `sm`, `md`, `lg`; types: `button`, `submit`, `reset` | `label`, `disabled`, optional non-empty `event`, and optional positive safe-integer `target` |
| `badge` | tones: `neutral`, `info`, `success`, `warning`, `danger` | `content` |
| `alert` | tones: `neutral`, `info`, `success`, `warning`, `danger` | `content`, optional string `title` |
| `card` | - | `content`, optional string `eyebrow` and `title`, optional `footer` |
| `stack` | gaps: `xs`, `sm`, `md`, `lg`, `xl`; alignment: `start`, `center`, `end`, `stretch` | finite `children` iterable |
| `grid` | columns: `auto`, `1`, `2`, `3`, `4`; gaps: `xs`, `sm`, `md`, `lg`, `xl` | finite `children` iterable |
| `form` | method: `post` | `content`, required whitespace-free `id`, optional non-empty change/submit events, optional positive safe-integer `target` |
| `field` | - | non-empty string `label`, `control`, whitespace-free `control_id`, optional non-empty string help/error, required presentation |
| `field_error` | - | non-empty string `message` and whitespace-free `id` |
| `input` | types: `date`, `datetime-local`, `email`, `month`, `number`, `password`, `search`, `tel`, `text`, `time`, `url`, `week` | label, id, name, scalar string/number value, placeholder, autocomplete, help/error, required/disabled state, change/blur events, target |
| `textarea` | rows: 1 through 100 | label, id, name, string value, placeholder, help/error, required/disabled state, change/blur events, target |
| `select` | - | label, finite `(string value, label)` options, selected value, prompt, help/error, required/disabled state, change/blur events, target |
| `checkbox` | - | label, id, name, string value, checked/required/disabled state, help/error, change/blur events, target |

Invalid closed values fail immediately. The helpers intentionally offer no
arbitrary attribute dictionary, `class` parameter, selector escape hatch, or
automatic class injection. Applications can wrap a helper in their own template
where they need a separately owned extension point.

`button(event=..., target=...)` emits `phx-click` and `phx-target`. `target`
requires `event` and is a positive JavaScript-safe integer. A page button normally
omits `target`; a stateful LiveView component passes its connection-local
`myself` value. The helper preserves Phoenix's existing click and
component-target semantics and does not add JavaScript behavior.

`form` emits `method="post"`, maps change and submit events to `phx-change` and
`phx-submit`, and can route both to one component through `phx-target`. The POST
default prevents native fallback from putting form values in a URL; the LiveView
route does not thereby become an HTTP form handler, so an application that needs
non-JavaScript submission owns a separate POST endpoint. `input`, `textarea`,
`select`, and `checkbox` may map change and blur events to `phx-change` and
`phx-blur`; control-level `phx-change` requires the control to be inside a form,
as required by the official client. Their optional target requires at least one
event. A submit button inside a `phx-submit` form normally omits its own click
event so one user action does not intentionally dispatch two application events.

Each concrete form control renders a complete field with a native label. Help
and error content receive deterministic `<control-id>-help` and
`<control-id>-error` IDs and are referenced by `aria-describedby`; an error also
sets `aria-invalid="true"` and renders through `field_error` with
`role="alert"`. Native `required`, `disabled`, `checked`, and `selected`
attributes retain browser semantics. The lower-level `field` helper supports a
custom control, but that control's author remains responsible for matching its
ID and ARIA references to the generated help and error IDs and for applying
native `required` and `aria-invalid` state to that control.

Form names are passed through unchanged, so applications may use LiveView's
documented bracket notation for nested mappings and `[]` lists. Phoenix
`phx-change` and `phx-submit` handlers receive the decoded name-shaped mapping
whose leaves are strings; absent unchecked checkboxes remain absent. A
`phx-blur` handler instead receives the official control event value mapping,
normally `{"value": "..."}`. The UI package performs no coercion, domain
validation, changeset modeling, or state management. Pages and components
supply current values and error messages on every render.

`alert` uses `role="alert"` for the `danger` tone and `role="status"` otherwise.
Its optional title is an `h2`; `card` uses an `article`, optional header and
footer, and an `h2` title. `button` is a native button with a closed HTML `type`,
disabled state, and visible focus styling.

## 4. Rendering and Safety

Every helper returns a Python 3.14 template string. Its content interpolations
remain subject to `tori-py-liveview` escaping. Nested `Template`, `Rendered`,
component, stream, and explicitly trusted `SafeHtml` content composes according
to LiveView's Phoenix render-tree contract. Form attribute values are restricted
to their documented scalar types, and textarea values are strings; render trees
are not accepted as control values. `stack` and `grid` use `fragment()` and
consume their finite child iterable once.

The package uses LiveView's `attrs()` helper for generated element attributes and
`classes()` for its fixed class list. `attrs()` omits absent optional values and
renders booleans safely. The public helper rejects event-handler, style, and
`srcdoc` names and executable `data:`, `javascript:`, and `vbscript:` schemes in
URL-bearing attributes. It is not exposed by UI components as an arbitrary
caller-controlled injection point. Template interpolations are not safe in tag
names, attribute names, unquoted attributes, CSS, or JavaScript. `raw()` and
manually constructed template statics remain explicit application trust
boundaries and must not receive untrusted input.

## 5. Stylesheet and Documents

The wheel contains `tori_liveview_ui.css`. At import time the package computes
its SHA-256 digest and publishes it at:

```text
/_tori/liveview-ui/<first-12-hex-digest>.css
```

`STYLESHEET_PATH` is the exact path for the bundled bytes. The controller returns
those bytes with `text/css; charset=utf-8`, an ETag containing the full digest,
and `Cache-Control: public, max-age=31536000, immutable`. Changing the CSS
changes the path, so long-lived browser and intermediary caching is safe.

`UiLiveView.render_document()` adds independent `data-tori-ui-theme` and
`data-tori-ui-skin` attributes to `<html>` and inserts `stylesheet_link()` into
`<head>` while retaining the normal LiveView document, root, and official
Phoenix browser client. `ui_theme()` defaults to `"auto"` and may return only
`"auto"`, `"light"`, or `"dark"`; any other value fails rendering.
`ui_skin()` defaults to `"editorial"`. It accepts lowercase CSS identifiers
starting with a letter, followed by at most 63 lowercase letters, digits, or
hyphens. This admits the bundled `editorial`, `minimal`, and `rounded` skins and
application-owned names such as `brand-2026` without permitting document
attribute injection.

Theme selects only color mode and palette. Skin independently selects spacing,
shape, density, typography, shadow geometry, focus geometry, and component
layout. Both are selected during initial document rendering; the outer `<html>`
element is outside the normal LiveView diff root, so changing either from
connected page state is not a supported dynamic operation. A custom
`LiveView.render_document()` can call `stylesheet_link()` and set the two data
attributes itself instead.

All component selectors use the `tori-ui-` prefix. The stylesheet has no global
element reset; its box-sizing rule is limited to component trees. Root defaults
provide the light theme and editorial skin for custom documents that include
only the stylesheet.

Public theme tokens cover paper, panel surfaces, ink, muted text, lines, accent,
tone colors, and shadow color. Public skin tokens include:

- `--tori-ui-space-{xs,sm,md,lg,xl}`;
- `--tori-ui-radius-{control,surface,pill}`;
- `--tori-ui-control-height-{sm,md,lg}` and
  `--tori-ui-field-control-height`;
- general control padding, button size padding, alert/card region padding,
  form/field gaps, field-control radius/padding, border width, and accent border
  width;
- display, body, and code font stacks plus control/label weight, tracking, and
  text transform;
- shadow x/y/blur/spread and the composed shadow;
- button/field focus offsets, disabled opacities, grid minimum, checkbox
  size/gap, and hover translation.

Applications create a skin by returning its validated name from `ui_skin()` and
defining the corresponding `[data-tori-ui-skin="..."]` token overrides in an
application stylesheet loaded after `stylesheet_link()`. They may also override
tokens for a bundled skin. Application CSS remains separate from the immutable
package bytes and therefore does not change `STYLESHEET_PATH` or its ETag. Font
stacks use locally available system fonts only: the package downloads no fonts
or other assets, contains no `@import` or asset URL, and includes no runtime
JavaScript.

The stylesheet supports explicit light/dark themes and automatic system-color
selection, responsive grid collapse at narrow widths, `:focus-visible` for
buttons and form controls, disabled and invalid form affordances, and
`prefers-reduced-motion` transition removal.

## 6. Non-Goals

This package does not provide:

- domain validation, value coercion, form models, radio groups, multiple
  selects, file controls, uploads, modal, navigation, or menu APIs;
- JavaScript widgets or widget-owned behavior;
- Tailwind, Bootstrap, Node tooling, a CDN, external fonts, or runtime JS in the
  core package; a separately distributed precompiled skin adapter may be added
  without changing this dependency boundary;
- a global CSS reset or arbitrary caller-supplied attributes/classes;
- dynamic connected-state theme or skin switching;
- LiveComponent state, page state, event dispatch ownership, or a replacement
  for Phoenix Channels and render-tree semantics.

Future component families must establish their own public contracts rather than
expanding this slice by undocumented attributes or implicit state.

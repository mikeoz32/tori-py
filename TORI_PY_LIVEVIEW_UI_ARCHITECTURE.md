# ToriPy LiveView UI Architecture

## 1. Purpose

`tori-py-liveview-ui` is an optional, separately installable component library
for `tori-py-liveview`. It provides stateless Python 3.14 template helpers
grouped in families, one locally bundled, themeable and skinnable stylesheet,
and one locally bundled script of Phoenix hooks. It does not introduce a second
LiveView runtime, browser protocol, or state model.

```text
tori-py-liveview-ui -> tori-py-framework, tori-py-liveview
tori-py-framework    -X-> tori-py-liveview-ui
tori-py-liveview     -X-> tori-py-liveview-ui
```

Applications explicitly import `LiveViewUiModule.for_root()` alongside their
`LiveViewModule`. The UI module materializes one ordinary ToriPy controller for
the stylesheet and the script; it creates no providers and performs no
discovery, package scan, or global registration.

## 2. Public Surface

The public facade is the flat `tori_py_liveview_ui` namespace:

- helper functions that return `string.templatelib.Template` values, listed by
  family in section 4;
- `LiveViewUiModule.for_root(key="default")` exposes the asset routes;
- `STYLESHEET_PATH` and `SCRIPT_PATH` are those routes' content-addressed paths;
- `stylesheet_link()` and `script_tag()` return the trusted `<link>` and
  `<script>` markup for a custom document;
- `UiLiveView` is a `LiveView` base class that installs both tags and
  independent document theme and skin attributes.

The implementation modules behind the facade are private. Applications import
names from `tori_py_liveview_ui` only.

## 3. Helper Rules

Every helper follows the same contract:

- It is a stateless render function, not a `LiveComponent`. It never mounts,
  receives events, retains assigns, or owns page or component state. Pages and
  components supply current values on every render.
- Its visual vocabulary is closed. Variants, sizes, tones, gaps, alignments,
  and similar options accept only their documented values, and invalid values
  fail immediately rather than becoming CSS class or attribute injection.
- It offers no arbitrary attribute dictionary, `class` parameter, selector
  escape hatch, or automatic class injection. Applications can wrap a helper in
  their own template where they need a separately owned extension point.
- An event parameter accepts a non-empty event name or a LiveView `JS` command
  chain and maps to the documented `phx-*` binding. An optional `target` is a
  positive JavaScript-safe integer, normally a component's connection-local
  `myself`, maps to `phx-target`, and requires at least one event.
- DOM ID parameters are non-empty strings without whitespace. A helper that
  needs an ID for a label, an ARIA reference, or a hook requires it explicitly
  and never generates a random one.
- Content parameters accept any value LiveView can interpolate. Strings are
  escaped; `Template`, `Rendered`, component, stream, and explicitly trusted
  `SafeHtml` content composes according to LiveView's Phoenix render-tree
  contract. Finite iterables of children are consumed once through
  `fragment()`.

## 4. Families

### 4.1 Actions

| Helper | Closed values | Other documented inputs |
| --- | --- | --- |
| `button` | variants: `primary`, `secondary`, `ghost`, `danger`; sizes: `sm`, `md`, `lg`; types: `button`, `submit`, `reset` | `label`, `disabled`, optional `event`, and optional `target` |

`button(event=..., target=...)` emits `phx-click` and `phx-target`. A page
button normally omits `target`; a stateful LiveView component passes its
`myself` value. `button` is a native button with a closed HTML `type`, disabled
state, and visible focus styling. A submit button inside a `phx-submit` form
normally omits its own click event so one user action does not intentionally
dispatch two application events.

### 4.2 Layout

| Helper | Closed values | Other documented inputs |
| --- | --- | --- |
| `card` | - | `content`, optional string `eyebrow` and `title`, optional `footer` |
| `stack` | gaps: `xs`, `sm`, `md`, `lg`, `xl`; alignment: `start`, `center`, `end`, `stretch` | finite `children` iterable |
| `grid` | columns: `auto`, `1`, `2`, `3`, `4`; gaps: `xs`, `sm`, `md`, `lg`, `xl` | finite `children` iterable |

`card` uses an `article`, optional header and footer, and an `h2` title.

### 4.3 Display

| Helper | Closed values | Other documented inputs |
| --- | --- | --- |
| `badge` | tones: `neutral`, `info`, `success`, `warning`, `danger` | `content` |

### 4.4 Feedback

| Helper | Closed values | Other documented inputs |
| --- | --- | --- |
| `alert` | tones: `neutral`, `info`, `success`, `warning`, `danger` | `content`, optional string `title` |

`alert` uses `role="alert"` for the `danger` tone and `role="status"` otherwise.
Its optional title is an `h2`.

### 4.5 Forms

| Helper | Closed values | Other documented inputs |
| --- | --- | --- |
| `form` | method: `post` | `content`, required `id`, optional change/submit events, optional `target` |
| `field` | - | non-empty string `label`, `control`, `control_id`, optional non-empty string help/error, required presentation |
| `field_error` | - | non-empty string `message` and `id` |
| `input` | types: `date`, `datetime-local`, `email`, `month`, `number`, `password`, `search`, `tel`, `text`, `time`, `url`, `week` | label, id, name, scalar string/number value, placeholder, autocomplete, help/error, required/disabled state, change/blur events, target |
| `textarea` | rows: 1 through 100 | label, id, name, string value, placeholder, help/error, required/disabled state, change/blur events, target |
| `select` | - | label, finite `(string value, label)` options, selected value, prompt, help/error, required/disabled state, change/blur events, target |
| `checkbox` | - | label, id, name, string value, checked/required/disabled state, help/error, change/blur events, target |

`form` emits `method="post"`, maps change and submit events to `phx-change` and
`phx-submit`, and can route both to one component through `phx-target`. The POST
default prevents native fallback from putting form values in a URL; the LiveView
route does not thereby become an HTTP form handler, so an application that needs
non-JavaScript submission owns a separate POST endpoint. `input`, `textarea`,
`select`, and `checkbox` may map change and blur events to `phx-change` and
`phx-blur`; control-level `phx-change` requires the control to be inside a form,
as required by the official client.

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
validation, changeset modeling, or state management.

## 5. Browser Behavior

Application state stays on the server, in pages and components. Presentation
state that only the browser needs, such as whether a menu is open, where a log
is scrolled, or which theme the visitor chose, stays in the browser. Helpers
reach for browser behavior in this order:

1. native elements and attributes, such as `<details>`, `<dialog>`, and
   `<progress>`;
2. LiveView `JS` commands in `phx-*` bindings, which the official client runs
   and keeps across patches;
3. a Phoenix hook from the bundled script, only where the first two cannot
   express the behavior.

The script is plain JavaScript without a build step. It defines hooks whose
names start with `ToriUi` and adds them to `globalThis.ToriLiveHooks`, the
object the LiveView client passes to the official `LiveSocket`. It registers
them when it loads and again when the document has been parsed, which browsers
do before they run the deferred LiveView client, so an application script that
replaces the object in between does not lose them. Hooks hold only state that
belongs to their element, such as a timer or a scroll position. They do not
store application data, open their own connections, load remote code, or
evaluate strings as code.

The script also applies a theme the visitor stored earlier to
`data-tori-ui-theme` on `<html>` before the body is parsed. Without a stored
choice the document keeps the theme the server rendered.

## 6. Rendering and Safety

Every helper returns a Python 3.14 template string. Its content interpolations
remain subject to `tori-py-liveview` escaping. Form attribute values are
restricted to their documented scalar types, and textarea values are strings;
render trees are not accepted as control values.

The package uses LiveView's `attrs()` helper for generated element attributes and
`classes()` for its fixed class list. `attrs()` omits absent optional values and
renders booleans safely. The public helper rejects event-handler, style, and
`srcdoc` names and executable `data:`, `javascript:`, and `vbscript:` schemes in
URL-bearing attributes. It is not exposed by UI components as an arbitrary
caller-controlled injection point. Template interpolations are not safe in tag
names, attribute names, unquoted attributes, CSS, or JavaScript. `raw()` and
manually constructed template statics remain explicit application trust
boundaries and must not receive untrusted input.

## 7. Assets and Documents

The wheel contains `tori_liveview_ui.css` and `tori_liveview_ui.js`. At import
time the package computes each file's SHA-256 digest and publishes the files at:

```text
/_tori/liveview-ui/<first-12-hex-digest>.css
/_tori/liveview-ui/<first-12-hex-digest>.js
```

`STYLESHEET_PATH` and `SCRIPT_PATH` are the exact paths for the bundled bytes.
The controller returns those bytes with `text/css; charset=utf-8` or
`text/javascript; charset=utf-8`, an ETag containing the full digest, and
`Cache-Control: public, max-age=31536000, immutable`. Changing a file changes
its path, so long-lived browser and intermediary caching is safe.

`UiLiveView.render_document()` adds independent `data-tori-ui-theme` and
`data-tori-ui-skin` attributes to `<html>`, inserts `stylesheet_link()` and
`script_tag()` into `<head>`, and puts the `tori-ui-document` class on `<body>`
while retaining the normal LiveView document, root, and official Phoenix browser
client. The body class gives the document the theme's paper background, ink
color, and body font and removes the body margin; it is an explicit class, not
an element selector. The script tag has no `defer` or `async`
attribute: it must run before the deferred client reads the hooks, and before
the first paint to apply a stored theme. `ui_theme()` defaults to `"auto"` and
may return only `"auto"`, `"light"`, or `"dark"`; any other value fails
rendering. `ui_skin()` defaults to `"editorial"`. It accepts lowercase CSS
identifiers starting with a letter, followed by at most 63 lowercase letters,
digits, or hyphens. This admits the bundled `editorial`, `minimal`, and
`rounded` skins and application-owned names such as `brand-2026` without
permitting document attribute injection.

Theme selects only color mode and palette. Skin independently selects spacing,
shape, density, typography, shadow geometry, focus geometry, and component
layout. Both are selected during initial document rendering; the outer `<html>`
element is outside the normal LiveView diff root, so the server does not change
either from connected page state. A custom `LiveView.render_document()` can call
`stylesheet_link()` and `script_tag()` and set the two data attributes itself
instead.

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
or other assets, and the stylesheet contains no `@import` or asset URL.

The stylesheet supports explicit light/dark themes and automatic system-color
selection, responsive grid collapse at narrow widths, `:focus-visible` for
buttons and form controls, disabled and invalid form affordances, and
`prefers-reduced-motion` transition removal.

## 8. Non-Goals

This package does not provide:

- domain validation, value coercion, form models, or changesets;
- a client runtime, a client-side state model, or widgets that own application
  state;
- file controls or upload integration until LiveView implements the Phoenix
  upload contract;
- Tailwind, Bootstrap, Node tooling, a CDN, external fonts, or remote script
  code; a separately distributed precompiled skin adapter may be added without
  changing this dependency boundary;
- a global CSS reset or arbitrary caller-supplied attributes/classes;
- required runtime dependencies beyond ToriPy and LiveView; optional features
  ship as extras;
- LiveComponent state, page state, event dispatch ownership, or a replacement
  for Phoenix Channels and render-tree semantics.

New component families establish their public contract in section 4 before
they ship, rather than expanding a helper by undocumented attributes or
implicit state.

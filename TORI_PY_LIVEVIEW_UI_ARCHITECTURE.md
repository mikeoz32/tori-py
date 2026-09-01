# ToriPy LiveView UI Architecture

## 1. Purpose

`tori-py-liveview-ui` is an optional, separately installable presentation
foundation for `tori-py-liveview`. It provides a small set of stateless Python
3.14 template helpers and one locally bundled stylesheet. It does not introduce
a second LiveView runtime, browser protocol, client script, or state model.

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

- `button`, `badge`, `alert`, `card`, `stack`, and `grid` return
  `string.templatelib.Template` values;
- `LiveViewUiModule.for_root(key="default")` exposes the stylesheet route;
- `STYLESHEET_PATH` is that route's content-addressed path;
- `stylesheet_link()` returns the trusted `<link>` markup for a custom document;
- `UiLiveView` is a `LiveView` base class that installs the stylesheet link and
  a document theme attribute.

The functions are stateless render helpers, not `LiveComponent` instances. They
never mount, receive events, retain assigns, or own page or component state.

## 3. Component Contract

The foundation intentionally exposes a closed visual vocabulary:

| Helper | Closed values | Other documented inputs |
| --- | --- | --- |
| `button` | variants: `primary`, `secondary`, `ghost`, `danger`; sizes: `sm`, `md`, `lg`; types: `button`, `submit`, `reset` | `label`, `disabled`, optional non-empty `event`, and optional positive `target` |
| `badge` | tones: `neutral`, `info`, `success`, `warning`, `danger` | `content` |
| `alert` | tones: `neutral`, `info`, `success`, `warning`, `danger` | `content`, optional string `title` |
| `card` | — | `content`, optional string `eyebrow` and `title`, optional `footer` |
| `stack` | gaps: `xs`, `sm`, `md`, `lg`, `xl`; alignment: `start`, `center`, `end`, `stretch` | finite `children` iterable |
| `grid` | columns: `auto`, `1`, `2`, `3`, `4`; gaps: `xs`, `sm`, `md`, `lg`, `xl` | finite `children` iterable |

Invalid closed values fail immediately. The helpers intentionally offer no
arbitrary attribute dictionary, `class` parameter, selector escape hatch, or
automatic class injection. This keeps the emitted markup, CSS contract, and
accessibility behavior auditable. Applications can wrap a helper in their own
template where they need a separately owned extension point.

`button(event=..., target=...)` emits `data-opal-click` and
`data-opal-target`. `target` requires `event` and is a positive integer. A page
button normally omits `target`; a stateful LiveView component passes its
connection-local `myself` value. The helper preserves Opal's existing click and
target semantics and does not add JavaScript behavior.

`alert` uses `role="alert"` for the `danger` tone and `role="status"` otherwise.
Its optional title is an `h2`; `card` uses an `article`, optional header and
footer, and an `h2` title. `button` is a native button with a closed HTML
`type`, disabled state, and visible focus styling.

## 4. Rendering and Safety

Every helper returns a Python 3.14 template string. Its ordinary interpolations
remain subject to `tori-py-liveview` escaping: text and quoted attribute values
are escaped; nested `Template`, `Rendered`, and explicitly trusted `SafeHtml`
values compose according to LiveView's rendering contract. `stack` and `grid`
use `fragment()` and consume their finite child iterable once.

The package uses LiveView's `attrs()` helper for generated button attributes and
`classes()` for its fixed class list. `attrs()` omits absent optional values and
renders booleans safely. The public helper rejects event-handler, style, and
`srcdoc` names and executable `data:`, `javascript:`, and `vbscript:` schemes in
URL-bearing attributes. It is not exposed by UI components as an arbitrary
caller-controlled attribute injection point. Template interpolations are not
safe in tag names, attribute names, unquoted attributes, CSS, or JavaScript.
`raw()` and manually constructed template statics remain explicit application
trust boundaries and must not receive untrusted input.

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

`UiLiveView.render_document()` adds `data-tori-ui-theme` to `<html>` and inserts
`stylesheet_link()` into `<head>` while retaining the normal LiveView document,
root, and browser client. `ui_theme()` defaults to `"auto"` and may return only
`"auto"`, `"light"`, or `"dark"`; any other value fails rendering. A custom
`LiveView.render_document()` can call `stylesheet_link()` itself instead.

All component selectors use the `tori-ui-` prefix. The stylesheet has no global
element reset; its box-sizing rule is limited to component trees. Public
`--tori-ui-*` custom properties define paper, panels, ink, muted/line colors,
accent and tone colors, shadow color/shadow, and display/body/code font stacks.
Applications may override those properties in their own CSS. Font stacks use
locally available system fonts only: the package downloads no fonts or other
assets, contains no `@import` or asset URL, and includes no runtime JavaScript.

The stylesheet supports explicit light/dark themes and automatic system-color
selection, responsive grid collapse at narrow widths, `:focus-visible` for the
button, disabled affordance, and `prefers-reduced-motion` transition removal.

## 6. Non-Goals

This foundation slice does not provide:

- a form system, validation UI, modal, navigation, or upload API;
- JavaScript widgets or widget-owned behavior;
- Tailwind, Bootstrap, Node tooling, a CDN, external fonts, or runtime JS;
- a global CSS reset or arbitrary caller-supplied attributes/classes;
- LiveComponent state, page state, event dispatch ownership, or a replacement
  for Opal protocol-v2 semantics.

Future component families must establish their own public contracts rather than
expanding this slice by undocumented attributes or implicit state.

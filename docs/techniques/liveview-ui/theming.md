# Themes, Modes, and Skins

The look of a LiveView UI document is three independent choices:

| Choice | Decides | Values |
| --- | --- | --- |
| Theme | Colors: one palette for light and one for dark | A `Theme` |
| Mode | Which of the theme's two palettes applies | `auto`, `light`, `dark` |
| Skin | Shape: spacing, radii, control sizes, typography, shadows, focus | A `Skin` |

Themes and skins are typed definitions. The package generates their CSS, so an
application describes a look in Python and writes no stylesheet for it. The
bundled themes and skins are made with the same API.

All three choices are attributes on the `<html>` element. Connected renders
patch the live root, not `<html>`, so what the server chooses takes effect with
a new document: the next full page load, or a live navigation to a page whose
look differs, which
[loads a new document](#navigating-between-looks). The visitor can still switch
the mode at any time with a [mode toggle](#letting-the-visitor-choose-the-mode),
which works in the browser.

## Choosing a Look

`UiLiveView` calls `ui_theme()`, `ui_mode()`, and `ui_skin()` while building the
HTTP document:

```python
from typing import Literal

from tori_py_liveview_ui import Skin, Theme, UiLiveView


class ReportsLive(UiLiveView):
    def ui_theme(self) -> Theme:
        return Theme.SLATE

    def ui_mode(self) -> Literal["auto", "light", "dark"]:
        return "dark"

    def ui_skin(self) -> Skin:
        return Skin.MINIMAL
```

| Method | Default | Returns |
| --- | --- | --- |
| `ui_theme()` | `Theme.PAPER` | A `Theme`, or the name of a theme you style in CSS |
| `ui_mode()` | `"auto"` | `"auto"`, `"light"`, or `"dark"` |
| `ui_skin()` | `Skin.EDITORIAL` | A `Skin`, or the name of a skin you style in CSS |

`auto` follows the visitor's `prefers-color-scheme` setting. Any other value
raises `TypeError` or `ValueError` during the HTTP render.

The methods run after `mount()` and `handle_params()`, so they can return a
per-visitor preference loaded during mount:

```python
from starlette.requests import HTTPConnection

from tori_py_liveview import MountContext


class SettingsLive(UiLiveView):
    async def mount(self, context: MountContext) -> None:
        dark = (
            isinstance(context.request, HTTPConnection)
            and context.request.cookies.get("mode") == "dark"
        )
        self.dark = dark

    def ui_mode(self) -> Literal["auto", "light", "dark"]:
        return "dark" if self.dark else "auto"
```

A WebSocket event cannot set a cookie. To change the preference, submit it to an
HTTP endpoint of your own that stores it and redirects back to the page.

## Letting the Visitor Choose the Mode

`mode_toggle()` renders three buttons for the system, light, and dark modes:

```python
from tori_py_liveview_ui import mode_toggle

toggle = mode_toggle(id="mode")
```

The choice never reaches your page:

- The bundled script sets `data-tori-ui-mode` on `<html>` at once and stores
  the choice in the browser's `localStorage` under `tori-ui-mode`.
- On every later `UiLiveView` document it applies the stored choice before the
  body is parsed, so the page does not flash in the other mode.
- A stored choice wins over `ui_mode()`. Without one, the document keeps the
  mode the server rendered.

Use `ui_mode()` alone when the application decides, and add the toggle when the
visitor should. A preference you need on the server, for example in an email,
belongs in your own storage. The theme and the skin are the application's
choice; there is no toggle for them.

## Bundled Themes and Skins

| Theme | Character |
| --- | --- |
| `Theme.PAPER` | Default. Warm paper surfaces and a red-orange accent |
| `Theme.SLATE` | Cool neutral surfaces and a blue accent |
| `Theme.CONTRAST` | Black and white surfaces and text at WCAG AAA contrast |

| Skin | Character |
| --- | --- |
| `Skin.EDITORIAL` | Default. Square surfaces, serif display type, uppercase controls and labels, hard offset shadow |
| `Skin.MINIMAL` | System fonts, slight radii, compact controls, no uppercase, subtle shadow |
| `Skin.ROUNDED` | Large radii, taller controls, soft diffuse shadow, no uppercase |

Every theme works with every mode and every skin. Bundled definitions are part
of the package stylesheet and need no registration.

## Defining a Theme

The quickest theme is derived from one or two colors:

```python
ACME = Theme.from_seeds("acme", accent="#7c3aed", neutral="#6b7280")
```

`accent` colors buttons, links, and the current item. `neutral` tints the
surfaces, the text, and the lines; leave it out for a faint tint of the accent.
Both palettes are derived in the OKLCH color space, and each derived color is
moved until it is readable on its surfaces. Pass `contrast="high"` for WCAG AAA
text contrast on black and white surfaces.

For full control, give both palettes. A `Palette` has fifteen colors, and
`derive()` copies one with some colors changed:

```python
OCEAN = Theme(
    "ocean",
    light=Theme.PAPER.light.derive(accent="#0b5cad", accent_ink="#ffffff"),
    dark=Theme.PAPER.dark.derive(accent="#7cc4ff", accent_ink="#0b1b2b"),
)
```

Colors are `#rgb`, `#rrggbb`, or `#rrggbbaa`. Only `shadow_color` and `scrim`
may be translucent.

### Contrast

A theme is checked when it is built. Body and muted text, the label of an
accent or danger button, and text set in a tone must reach WCAG AA (4.5:1) on
their surfaces, and the accent and the tones must reach 3:1 as graphics. A
theme that does not raises `ThemeContrastError`, which names each failing pair:

<!-- docs-test: raises ThemeContrastError -->

```python
Theme("faint", light=Theme.PAPER.light.derive(muted="#b5ada0"), dark=Theme.PAPER.dark)
```

Pass `allow_low_contrast=True` to build such a theme anyway. `Theme.report()`
returns every requirement as a `ContrastCheck` with the ratio the theme
reaches:

```python
closest = min(ACME.report(), key=lambda check: check.ratio / check.required)
summary = f"{closest.mode} {closest.foreground} on {closest.background}"
```

## Defining a Skin

A skin starts from a bundled one. `Skin.derive()` takes the new name and the
tokens to change:

```python
COMPACT = Skin.MINIMAL.derive(
    "compact",
    radius_control="0.5rem",
    control_height_md="2.1rem",
    font_body=("Inter", "system-ui", "sans-serif"),
)
```

Every value is validated against the kind of its token, so a typo fails when
the module is imported instead of producing a broken stylesheet:

| Kind | Tokens | Accepts |
| --- | --- | --- |
| Size | Spacing, radii, heights, gaps, widths, shadow blur | `0` or a number with `rem`, `em`, `px`, `%`, `ch`, `vw`, or `vh` |
| Offset | Shadow x, y, and spread, focus offsets, letter spacing, hover translation | A size that may be negative |
| Box | Button, alert, and card padding | One to four sizes |
| Font stack | `font_display`, `font_body`, `font_code` | A tuple of family names; generic families such as `serif` are written bare and the others quoted |
| Weight | `control_font_weight`, `label_font_weight` | An integer from 1 to 1000 |
| Case | `control_text_transform`, `label_text_transform` | `none`, `uppercase`, `lowercase`, or `capitalize` |
| Opacity | `disabled_opacity`, `field_disabled_opacity` | A number from 0 to 1 |

No token accepts free CSS, so a definition cannot add a rule or a URL to a
stylesheet. The package ships no fonts: a font stack names families the visitor
has, or ones you load in your own stylesheet.

## Registering Application Definitions

Pass your themes and skins to the module, and return them from a page:

```python
from tori_py import module
from tori_py_liveview_ui import LiveViewUiModule


@module(imports=[LiveViewUiModule.for_root(themes=[ACME], skins=[COMPACT])])
class AppModule:
    pass


class DashboardLive(UiLiveView):
    def ui_theme(self) -> Theme:
        return ACME

    def ui_skin(self) -> Skin:
        return COMPACT
```

The module serves each definition as its own stylesheet at a content-addressed
path, `stylesheet_path`, with the same immutable caching as the package
stylesheet, which stays unchanged. The document links the stylesheets of the
definitions the page returns, after the package stylesheet.

A definition a page returns must be registered. If it is not, its stylesheet
answers 404 and the page falls back to the default look. A name may be
registered once, and the names of the bundled definitions are reserved.

## A Look for Part of a Page

`themed()` gives part of a page its own theme, mode, or skin. What it leaves
out is inherited from the document:

```python
from tori_py_liveview_ui import card, themed

night = themed(card("Always dark", title="Night"), mode="dark")
preview = themed(card("Slate, rounded"), theme=Theme.SLATE, skin=Skin.ROUNDED)
```

The element is a surface: it has the paper background, ink color, and body font
of the look inside it. When it uses an application theme or skin that the page
does not already return, name that definition in `ui_extra_definitions()` so
that the document links its stylesheet:

```python
class PreviewLive(UiLiveView):
    def ui_extra_definitions(self) -> tuple[Theme | Skin, ...]:
        return (ACME, COMPACT)
```

## Navigating Between Looks

Live navigation keeps the document, so the theme, the mode, the skin, and the
stylesheets of application definitions stay as the first page set them.
`UiLiveView` therefore returns its look from
[`document_key()`](../liveview/navigation.md#documents-and-document-keys):

<!-- docs-test: skip -->

```python
page.document_key()  # "slate|dark|compact|/_tori/liveview-ui/skin-compact.1a2b3c4d5e6f.css"
```

When a live link, `push_navigate()`, or `JS().navigate()` reaches a page whose
key differs from the key of the page that rendered the document, the browser
loads that page in a new document that has its look. Between pages with the
same look the document is kept, and nothing reloads.

- The key is read after `mount()` and `handle_params()`, so `ui_theme()`,
  `ui_mode()`, `ui_skin()`, and `ui_extra_definitions()` may depend on what they
  set, for example a preference loaded in `mount()`.
- The mode is the one the server renders, not the one the visitor stored. A
  visitor who used the toggle does not make every navigation reload.
- A page needs the stylesheets of the application definitions it returns, so a
  page that returns more of them than the document links loads a new document
  too.
- A page that overrides `document_key()` and combines its own value with the
  look calls `super().document_key()`.

## Themes and Skins in Your Own CSS

`ui_theme()` and `ui_skin()` may return a name instead of a definition. The
name must match `[a-z][a-z0-9-]{0,63}`; it becomes the attribute value, and
your own stylesheet, loaded after the package one, defines the tokens:

```css
[data-tori-ui-skin="acme"] {
  --tori-ui-radius-control: 0.5rem;
  --tori-ui-border-width: 2px;
}

[data-tori-ui-theme="acme"] {
  --tori-ui-accent: light-dark(#7c3aed, #a78bfa);
}
```

Give each palette token a `light-dark()` pair so that it follows the mode.
Tokens you do not set keep the values of the default theme and skin. A name
gets no validation and no contrast check, so prefer a definition unless the
look already exists as CSS.

## Pages Without `UiLiveView`

A page with its own document can use the assets directly. Pass the application
definitions it uses to `stylesheet_link()`, add `script_tag()` to the head, set
the three attributes on `<html>`, and give `<body>` the `tori-ui-document` class
for the theme's page background and text color:

```python
from tori_py_liveview import LiveView
from tori_py_liveview_ui import script_tag, stylesheet_link


class PlainLive(LiveView):
    def render_document(self, live_root: str, client_script: str) -> str:
        return (
            f'<!doctype html><html data-tori-ui-theme="{ACME.name}" '
            f'data-tori-ui-mode="auto" data-tori-ui-skin="{COMPACT.name}">'
            '<head><meta charset="utf-8">'
            f"{stylesheet_link(ACME, COMPACT).value}{script_tag().value}</head>"
            f'<body class="tori-ui-document">{live_root}{client_script}</body>'
            "</html>"
        )
```

Keep `script_tag()` in the head and do not add `defer` or `async` to it. Leave
it out only if the page uses no helper that needs a hook, a copy button, a
confirmation, or the mode toggle.

`STYLESHEET_PATH` and `SCRIPT_PATH` are the content-addressed URLs of the
bundled files if you need them elsewhere, for example in a `Link` preload
header. `LiveViewUiModule` must still be imported so that the paths are served.

## Token Reference

All public custom properties start with `--tori-ui-`. A field of `Palette` or
`Skin` is the token of the same name with hyphens: `radius_control` is
`--tori-ui-radius-control`. `Palette.tokens()`, `Theme.tokens()`, and
`Skin.tokens()` return the names with their values.

| Group | Tokens |
| --- | --- |
| Palette (theme) | `paper`, `panel`, `panel-raised`, `ink`, `muted`, `line`, `line-strong`, `accent`, `accent-ink`, `danger`, `info`, `success`, `warning`, `shadow-color`, `scrim` |
| Spacing | `space-xs`, `space-sm`, `space-md`, `space-lg`, `space-xl`, `form-gap`, `field-gap`, `checkbox-gap`, `grid-min` |
| Radii | `radius-control`, `radius-surface`, `radius-pill`, `field-control-radius` |
| Controls | `control-height-sm`, `control-height-md`, `control-height-lg`, `field-control-height`, `control-padding-block`, `control-padding-inline`, `field-control-padding-block`, `field-control-padding-inline`, `button-padding-sm`, `button-padding-lg`, `checkbox-size` |
| Surfaces | `alert-padding`, `card-header-padding`, `card-body-padding`, `card-footer-padding` |
| Borders | `border-width`, `accent-border-width` |
| Typography | `font-display`, `font-body`, `font-code`, `control-font-weight`, `control-letter-spacing`, `control-text-transform`, `label-font-weight`, `label-letter-spacing`, `label-text-transform` |
| Shadows | `shadow-x`, `shadow-y`, `shadow-blur`, `shadow-spread` |
| Focus and states | `focus-width`, `focus-offset`, `field-focus-offset`, `disabled-opacity`, `field-disabled-opacity`, `hover-translate` |
| Composed | `shadow`, `radius-surface-inner` |
| Application shell | `sidebar-width`, `aside-width` |
| Stacking order | `layer-raised`, `layer-drawer`, `layer-overlay`, `layer-toast` |

The composed tokens are built from the others in every theme and skin rule:
`shadow` from the shadow tokens and the theme's `shadow-color`, and
`radius-surface-inner` from `radius-surface` and `border-width`. The
application shell and stacking order tokens are the same in every skin;
override them on `:root` in your own stylesheet.

## Browser Support

A theme sets each palette token to a `light-dark()` pair and the mode sets
`color-scheme`. This needs Chrome 123, Firefox 120, or Safari 17.5, or a later
version.

## Accessibility and Motion

The stylesheet gives every interactive helper a visible keyboard focus ring
sized by `focus_width` and `focus_offset`, dims disabled controls, and removes
button transitions when the visitor prefers reduced motion. A theme is checked
for contrast when it is built; keep the focus tokens large enough to see.

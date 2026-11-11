# Themes and Skins

LiveView UI separates two choices:

- the color theme: `auto`, `light`, or `dark` palette values;
- the visual skin: geometry, density, typography, borders, and shadows.

Both are attributes on the `<html>` element and are fixed for the lifetime of a
loaded document. Connected renders patch the live root, not `<html>`, so a new
theme or skin takes effect on the next full page load.

## Choosing a Theme and Skin

`UiLiveView` calls `ui_theme()` and `ui_skin()` while building the HTTP
document:

```python
from typing import Literal

from tori_py_liveview_ui import UiLiveView


class ReportsLive(UiLiveView):
    def ui_theme(self) -> Literal["auto", "light", "dark"]:
        return "dark"

    def ui_skin(self) -> str:
        return "minimal"
```

| Method | Default | Allowed values |
| --- | --- | --- |
| `ui_theme()` | `"auto"` | `"auto"`, `"light"`, `"dark"` |
| `ui_skin()` | `"editorial"` | Any name matching `[a-z][a-z0-9-]{0,63}` |

`auto` follows the visitor's `prefers-color-scheme` setting. Invalid values raise
`ValueError` during the HTTP render.

Both methods run after `mount()` and `handle_params()`, so they can return a
per-visitor preference loaded during mount:

```python
from starlette.requests import HTTPConnection

from tori_py_liveview import MountContext


class SettingsLive(UiLiveView):
    async def mount(self, context: MountContext) -> None:
        dark = (
            isinstance(context.request, HTTPConnection)
            and context.request.cookies.get("theme") == "dark"
        )
        self.dark = dark

    def ui_theme(self) -> Literal["auto", "light", "dark"]:
        return "dark" if self.dark else "auto"
```

A WebSocket event cannot set a cookie. To change the preference, submit it to an
HTTP endpoint of your own that stores it and redirects back to the page.

## Bundled Skins

| Skin | Character |
| --- | --- |
| `editorial` | Default. Square surfaces, serif display type, uppercase controls and labels, hard offset shadow |
| `minimal` | System fonts, slight radii, compact controls, no uppercase, subtle shadow |
| `rounded` | Large radii, taller controls, soft diffuse shadow, no uppercase |

Every skin works with every theme.

## Custom Skins

A custom skin is a name plus CSS. Return the name from `ui_skin()` and override
public tokens in a stylesheet loaded after the package stylesheet:

```python
class BrandLive(UiLiveView):
    def ui_skin(self) -> str:
        return "acme"
```

```css
[data-tori-ui-skin="acme"] {
  --tori-ui-radius-control: 0.5rem;
  --tori-ui-radius-surface: 0.75rem;
  --tori-ui-control-height-md: 2.75rem;
  --tori-ui-field-control-height: 2.75rem;
  --tori-ui-border-width: 2px;
  --tori-ui-font-body: system-ui, sans-serif;
  --tori-ui-control-text-transform: none;
  --tori-ui-label-text-transform: none;
  --tori-ui-shadow-x: 0;
  --tori-ui-shadow-y: 8px;
  --tori-ui-shadow-blur: 24px;
  --tori-ui-shadow-spread: -16px;
}
```

Tokens you do not override keep the `editorial` defaults. Your CSS is not merged
into the package asset, so the package stylesheet URL and ETag do not change.

Serve the application stylesheet yourself and link it after the package link.
`UiLiveView.render_document()` inserts the package link before `</head>`, so
insert yours in the same place afterwards:

```python
from importlib.resources import files

from tori_py import HttpResponse, controller, get
from tori_py_liveview_ui import UiLiveView

BRAND_CSS = files("my_app").joinpath("static", "brand.css").read_bytes()


@controller()
class BrandAssets:
    @get("/assets/brand.css")
    async def stylesheet(self) -> HttpResponse:
        return HttpResponse(
            BRAND_CSS,
            headers={"content-type": "text/css; charset=utf-8"},
        )


class BrandLive(UiLiveView):
    def ui_skin(self) -> str:
        return "acme"

    def render_document(self, live_root: str, client_script: str) -> str:
        document = super().render_document(live_root, client_script)
        link = '<link rel="stylesheet" href="/assets/brand.css">'
        return document.replace("</head>", f"{link}</head>", 1)
```

Register the controller in one of your modules. Put the custom page logic in a
shared base class when several pages use the same skin.

To restyle colors, override the palette tokens under the theme selectors instead
of the skin selector, for example `[data-tori-ui-theme="dark"]`.

## Pages Without `UiLiveView`

A page with its own document can use the stylesheet directly. Add
`stylesheet_link()` to the head and set both attributes on `<html>`:

```python
from tori_py_liveview import LiveView
from tori_py_liveview_ui import stylesheet_link


class PlainLive(LiveView):
    def render_document(self, live_root: str, client_script: str) -> str:
        return (
            '<!doctype html><html data-tori-ui-theme="auto" '
            'data-tori-ui-skin="editorial"><head><meta charset="utf-8">'
            f"{stylesheet_link().value}</head>"
            f"<body>{live_root}{client_script}</body></html>"
        )
```

`STYLESHEET_PATH` is the content-addressed URL of the bundled CSS if you need it
elsewhere, for example in a `Link` preload header. `LiveViewUiModule` must still
be imported so that the path is served.

## Token Reference

All public custom properties start with `--tori-ui-`.

| Group | Tokens |
| --- | --- |
| Palette (theme) | `paper`, `panel`, `panel-raised`, `ink`, `muted`, `line`, `line-strong`, `accent`, `accent-ink`, `danger`, `info`, `success`, `warning`, `shadow-color` |
| Spacing | `space-xs`, `space-sm`, `space-md`, `space-lg`, `space-xl`, `form-gap`, `field-gap`, `checkbox-gap`, `grid-min` |
| Radii | `radius-control`, `radius-surface`, `radius-surface-inner`, `radius-pill`, `field-control-radius` |
| Controls | `control-height-sm`, `control-height-md`, `control-height-lg`, `field-control-height`, `control-padding-block`, `control-padding-inline`, `field-control-padding-block`, `field-control-padding-inline`, `button-padding-sm`, `button-padding-lg`, `checkbox-size` |
| Surfaces | `alert-padding`, `card-header-padding`, `card-body-padding`, `card-footer-padding` |
| Borders | `border-width`, `accent-border-width` |
| Typography | `font-display`, `font-body`, `font-code`, `control-font-weight`, `control-letter-spacing`, `control-text-transform`, `label-font-weight`, `label-letter-spacing`, `label-text-transform` |
| Shadows | `shadow-x`, `shadow-y`, `shadow-blur`, `shadow-spread`, `shadow` |
| Focus and states | `focus-width`, `focus-offset`, `field-focus-offset`, `disabled-opacity`, `field-disabled-opacity`, `hover-translate` |

`shadow` is composed from the other shadow tokens, so override the parts.
`radius-surface-inner` is derived from `radius-surface` and `border-width`.

## Accessibility and Motion

The stylesheet gives every interactive helper a visible keyboard focus ring
sized by `focus-width` and `focus-offset`, dims disabled controls, and removes
button transitions when the visitor prefers reduced motion. Keep enough contrast
when you override palette tokens, and keep the focus tokens large enough to see.

The package ships no fonts. Font tokens list local and system families; load
web fonts in your own stylesheet if you want them.

from __future__ import annotations

import hashlib
import re
from importlib.resources import files
from typing import Any, cast

import httpx
import pytest
from tori_py import (
    DeferredModule,
    ModuleSpec,
    NestApplication,
    get_controller_metadata,
    get_route_metadata,
    module,
)
from tori_py.starlette import StarletteAdapter
from tori_py_liveview_ui import (
    STYLESHEET_PATH,
    LiveViewUiModule,
    UiLiveView,
    stylesheet_link,
)


def _contrast_ratio(first: str, second: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _light_theme_color(stylesheet: str, property_name: str) -> str:
    theme = re.search(r":root,.*?\{(?P<body>.*?)\}", stylesheet, re.DOTALL)
    assert theme is not None
    color = re.search(
        rf"--tori-ui-{re.escape(property_name)}:\s*(#[0-9a-fA-F]{{6}})",
        theme.group("body"),
    )
    assert color is not None
    return color.group(1)


def test_ui_module_materializes_one_controller_without_providers() -> None:
    dynamic = LiveViewUiModule.for_root(key="console")
    spec = cast(ModuleSpec, dynamic.factory())

    assert isinstance(dynamic, DeferredModule)
    assert dynamic.key == "console"
    assert spec.imports == ()
    assert spec.providers == ()
    assert spec.exports == ()
    controllers = tuple(spec.controllers)
    assert len(controllers) == 1
    controller_type = controllers[0]
    assert get_controller_metadata(controller_type) is not None
    route = get_route_metadata(cast(Any, controller_type).stylesheet)
    assert route is not None
    assert route.path == STYLESHEET_PATH
    assert route.method == "GET"


def test_ui_module_validates_its_instance_key() -> None:
    with pytest.raises(TypeError, match="key must be a string"):
        LiveViewUiModule.for_root(key=cast(str, 1))
    with pytest.raises(ValueError, match="key cannot be empty"):
        LiveViewUiModule.for_root(key="")


@pytest.mark.asyncio
async def test_stylesheet_controller_serves_the_exact_immutable_asset() -> None:
    dynamic = LiveViewUiModule.for_root()
    spec = cast(ModuleSpec, dynamic.factory())
    controller_type = tuple(spec.controllers)[0]
    response = await controller_type().stylesheet()
    expected = (
        files("tori_py_liveview_ui")
        .joinpath("static", "tori_liveview_ui.css")
        .read_bytes()
    )
    digest = hashlib.sha256(expected).hexdigest()

    assert response.status_code == 200
    assert response.content == expected
    assert response.headers == {
        "cache-control": "public, max-age=31536000, immutable",
        "content-type": "text/css; charset=utf-8",
        "etag": f'"{digest}"',
    }
    assert STYLESHEET_PATH == f"/_tori/liveview-ui/{digest[:12]}.css"


@pytest.mark.asyncio
async def test_stylesheet_route_serves_the_bundled_asset() -> None:
    @module(imports=[LiveViewUiModule.for_root()])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    transport = httpx.ASGITransport(app=application.get_adapter(StarletteAdapter).app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get(STYLESHEET_PATH)
    await application.shutdown()

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/css; charset=utf-8"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_stylesheet_link_is_local_and_uses_the_public_path() -> None:
    assert stylesheet_link().value == (
        f'<link rel="stylesheet" href="{STYLESHEET_PATH}">'
    )


def test_ui_liveview_injects_stylesheet_theme_and_skin_into_document() -> None:
    class Page(UiLiveView):
        def render(self) -> str:
            return "<p>Dashboard</p>"

        def title(self) -> str:
            return "Dashboard"

    document = Page().render_document(
        '<main data-phx-session="session"></main>',
        '<script defer src="/_tori/live/client.js"></script>',
    )

    assert document.startswith(
        '<!doctype html><html data-tori-ui-theme="auto" '
        'data-tori-ui-skin="editorial"><head>'
    )
    assert document.count(stylesheet_link().value) == 1
    assert stylesheet_link().value in document.split("</head>", 1)[0]
    assert '<title data-default="">Dashboard</title>' in document
    assert '<main data-phx-session="session"></main>' in document
    assert '<script defer src="/_tori/live/client.js"></script>' in document


def test_ui_liveview_supports_explicit_themes_and_rejects_unknown_values() -> None:
    class DarkPage(UiLiveView):
        def render(self) -> str:
            return ""

        def ui_theme(self):
            return "dark"

    assert 'data-tori-ui-theme="dark"' in DarkPage().render_document("", "")

    class InvalidPage(UiLiveView):
        def render(self) -> str:
            return ""

        def ui_theme(self):
            return "sepia"

    with pytest.raises(ValueError, match="theme must be one of"):
        InvalidPage().render_document("", "")


def test_ui_liveview_supports_bundled_and_application_owned_skins() -> None:
    class MinimalPage(UiLiveView):
        def render(self) -> str:
            return ""

        def ui_theme(self):
            return "dark"

        def ui_skin(self) -> str:
            return "minimal"

    class BrandPage(UiLiveView):
        def render(self) -> str:
            return ""

        def ui_skin(self) -> str:
            return "brand-2026"

    minimal_document = MinimalPage().render_document("", "")
    assert 'data-tori-ui-theme="dark"' in minimal_document
    assert 'data-tori-ui-skin="minimal"' in minimal_document
    assert 'data-tori-ui-skin="brand-2026"' in BrandPage().render_document("", "")


@pytest.mark.parametrize("skin", ["", "Rounded", "two words", "-leading", "a" * 65])
def test_ui_liveview_rejects_invalid_skin_names(skin: str) -> None:
    class InvalidPage(UiLiveView):
        def render(self) -> str:
            return ""

        def ui_skin(self) -> str:
            return skin

    with pytest.raises(
        ValueError,
        match=re.escape("skin must match [a-z][a-z0-9-]{0,63}"),
    ):
        InvalidPage().render_document("", "")


def test_ui_liveview_rejects_non_string_skin_names() -> None:
    class InvalidPage(UiLiveView):
        def render(self) -> str:
            return ""

        def ui_skin(self):
            return 1

    with pytest.raises(TypeError, match="skin must be a string"):
        InvalidPage().render_document("", "")


def test_stylesheet_contains_the_foundation_contract_without_remote_assets() -> None:
    stylesheet = (
        files("tori_py_liveview_ui")
        .joinpath("static", "tori_liveview_ui.css")
        .read_text(encoding="utf-8")
    )

    for selector in (
        ".tori-ui-button",
        ".tori-ui-badge",
        ".tori-ui-alert",
        ".tori-ui-card",
        ".tori-ui-stack",
        ".tori-ui-grid",
        ".tori-ui-form",
        ".tori-ui-field",
        ".tori-ui-input",
        ".tori-ui-textarea",
        ".tori-ui-select",
        ".tori-ui-checkbox",
        '[data-tori-ui-theme="dark"]',
        '[data-tori-ui-theme="auto"]',
        '[data-tori-ui-skin="editorial"]',
        '[data-tori-ui-skin="minimal"]',
        '[data-tori-ui-skin="rounded"]',
        ":focus-visible",
        "prefers-reduced-motion",
    ):
        assert selector in stylesheet
    assert "@import" not in stylesheet
    assert "url(" not in stylesheet


def test_stylesheet_exposes_the_public_skin_token_contract() -> None:
    stylesheet = (
        files("tori_py_liveview_ui")
        .joinpath("static", "tori_liveview_ui.css")
        .read_text(encoding="utf-8")
    )
    editorial = re.search(
        r':root,\s*\[data-tori-ui-skin="editorial"\]\s*\{(?P<body>.*?)\}',
        stylesheet,
        re.DOTALL,
    )
    assert editorial is not None

    for token in (
        "space-xs",
        "space-sm",
        "space-md",
        "space-lg",
        "space-xl",
        "radius-control",
        "radius-surface",
        "radius-surface-inner",
        "radius-pill",
        "control-height-sm",
        "control-height-md",
        "control-height-lg",
        "field-control-height",
        "control-padding-block",
        "control-padding-inline",
        "button-padding-sm",
        "button-padding-lg",
        "alert-padding",
        "card-header-padding",
        "card-body-padding",
        "card-footer-padding",
        "form-gap",
        "field-gap",
        "field-control-radius",
        "field-control-padding-block",
        "field-control-padding-inline",
        "border-width",
        "accent-border-width",
        "font-display",
        "font-body",
        "font-code",
        "control-font-weight",
        "control-letter-spacing",
        "control-text-transform",
        "label-font-weight",
        "label-letter-spacing",
        "label-text-transform",
        "shadow-x",
        "shadow-y",
        "shadow-blur",
        "shadow-spread",
        "shadow",
        "focus-width",
        "focus-offset",
        "field-focus-offset",
        "disabled-opacity",
        "field-disabled-opacity",
        "grid-min",
        "checkbox-size",
        "checkbox-gap",
        "hover-translate",
    ):
        assert f"--tori-ui-{token}:" in editorial.group("body")


def test_bundled_skins_define_distinct_geometry_and_typography() -> None:
    stylesheet = (
        files("tori_py_liveview_ui")
        .joinpath("static", "tori_liveview_ui.css")
        .read_text(encoding="utf-8")
    )

    editorial = re.search(
        r':root,\s*\[data-tori-ui-skin="editorial"\]\s*\{(?P<body>.*?)\}',
        stylesheet,
        re.DOTALL,
    )
    minimal = re.search(
        r'\[data-tori-ui-skin="minimal"\]\s*\{(?P<body>.*?)\}',
        stylesheet,
        re.DOTALL,
    )
    rounded = re.search(
        r'\[data-tori-ui-skin="rounded"\]\s*\{(?P<body>.*?)\}',
        stylesheet,
        re.DOTALL,
    )
    assert editorial is not None
    assert minimal is not None
    assert rounded is not None

    assert "--tori-ui-radius-control: 0.28rem" in editorial.group("body")
    assert "--tori-ui-control-text-transform: uppercase" in editorial.group("body")
    assert "--tori-ui-alert-padding: 1rem 1.1rem" in editorial.group("body")
    assert "--tori-ui-card-header-padding: 1.15rem 1.2rem 0.95rem" in editorial.group(
        "body"
    )
    assert "--tori-ui-form-gap: 1.15rem" in editorial.group("body")
    assert "--tori-ui-field-gap: 0.42rem" in editorial.group("body")
    assert "--tori-ui-field-control-radius: 0.22rem" in editorial.group("body")
    assert "--tori-ui-radius-control: 0.15rem" in minimal.group("body")
    assert "--tori-ui-shadow-x: 0" in minimal.group("body")
    assert "--tori-ui-font-display: ui-sans-serif" in minimal.group("body")
    assert "--tori-ui-radius-control: 0.75rem" in rounded.group("body")
    assert "--tori-ui-shadow-y: 12px" in rounded.group("body")
    assert "--tori-ui-font-display: ui-rounded" in rounded.group("body")


def test_stylesheet_preserves_invalid_native_checkbox_affordance() -> None:
    stylesheet = (
        files("tori_py_liveview_ui")
        .joinpath("static", "tori_liveview_ui.css")
        .read_text(encoding="utf-8")
    )

    assert ".tori-ui-field--invalid .tori-ui-checkbox__control" in stylesheet
    assert "box-shadow: 0 0 0 2px var(--tori-ui-danger)" in stylesheet


def test_light_primary_button_meets_wcag_aa_contrast() -> None:
    stylesheet = (
        files("tori_py_liveview_ui")
        .joinpath("static", "tori_liveview_ui.css")
        .read_text(encoding="utf-8")
    )

    accent = _light_theme_color(stylesheet, "accent")
    accent_ink = _light_theme_color(stylesheet, "accent-ink")

    assert _contrast_ratio(accent, accent_ink) >= 4.5


def test_light_form_placeholder_meets_wcag_aa_contrast() -> None:
    stylesheet = (
        files("tori_py_liveview_ui")
        .joinpath("static", "tori_liveview_ui.css")
        .read_text(encoding="utf-8")
    )

    muted = _light_theme_color(stylesheet, "muted")
    panel = _light_theme_color(stylesheet, "panel")

    assert _contrast_ratio(muted, panel) >= 4.5
    assert "opacity: 0.75" not in stylesheet
    assert "opacity: 1;" in stylesheet

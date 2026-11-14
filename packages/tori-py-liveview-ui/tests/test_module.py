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
    SCRIPT_PATH,
    STYLESHEET_PATH,
    LiveViewUiModule,
    Theme,
    UiLiveView,
    script_tag,
    stylesheet_link,
)
from tori_py_liveview_ui import module as ui_module


def _stylesheet() -> str:
    return ui_module._STYLESHEET.decode("utf-8")


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
    color = Theme.PAPER.light.tokens()[property_name]
    # The stylesheet carries the color of the bundled definition.
    assert f"--tori-ui-{property_name}: light-dark({color}," in stylesheet
    return color


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
    script_route = get_route_metadata(cast(Any, controller_type).script)
    assert script_route is not None
    assert script_route.path == SCRIPT_PATH
    assert script_route.method == "GET"


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
    component_rules = (
        files("tori_py_liveview_ui")
        .joinpath("static", "tori_liveview_ui.css")
        .read_bytes()
        .replace(b"\r\n", b"\n")
    )
    expected = ui_module._STYLESHEET
    digest = hashlib.sha256(expected).hexdigest()

    assert response.status_code == 200
    assert response.content == expected
    # The generated tokens of the bundled definitions come first, then the
    # component rules, with one line ending on every platform.
    assert expected.startswith(b"/* Tokens generated from the bundled theme")
    assert expected.endswith(component_rules)
    assert b"--tori-ui-" not in component_rules.split(b"*/", 1)[0]
    assert b"\r" not in expected
    assert response.headers == {
        "cache-control": "public, max-age=31536000, immutable",
        "content-type": "text/css; charset=utf-8",
        "etag": f'"{digest}"',
    }
    assert STYLESHEET_PATH == f"/_tori/liveview-ui/{digest[:12]}.css"


@pytest.mark.asyncio
async def test_script_controller_serves_the_exact_immutable_asset() -> None:
    dynamic = LiveViewUiModule.for_root()
    spec = cast(ModuleSpec, dynamic.factory())
    controller_type = tuple(spec.controllers)[0]
    response = await controller_type().script()
    expected = (
        files("tori_py_liveview_ui")
        .joinpath("static", "tori_liveview_ui.js")
        .read_bytes()
    )
    digest = hashlib.sha256(expected).hexdigest()

    assert response.status_code == 200
    assert response.content == expected
    assert response.headers == {
        "cache-control": "public, max-age=31536000, immutable",
        "content-type": "text/javascript; charset=utf-8",
        "etag": f'"{digest}"',
    }
    assert SCRIPT_PATH == f"/_tori/liveview-ui/{digest[:12]}.js"


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
        script = await client.get(SCRIPT_PATH)
    await application.shutdown()

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/css; charset=utf-8"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert script.status_code == 200
    assert script.headers["content-type"] == "text/javascript; charset=utf-8"
    assert script.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_stylesheet_link_is_local_and_uses_the_public_path() -> None:
    assert stylesheet_link().value == (
        f'<link rel="stylesheet" href="{STYLESHEET_PATH}">'
    )


def test_script_tag_is_local_blocking_and_uses_the_public_path() -> None:
    assert script_tag().value == f'<script src="{SCRIPT_PATH}"></script>'


def test_script_registers_hooks_without_remote_code_or_dynamic_evaluation() -> None:
    script = (
        files("tori_py_liveview_ui")
        .joinpath("static", "tori_liveview_ui.js")
        .read_text(encoding="utf-8")
    )

    assert "globalThis.ToriLiveHooks ??= {}" in script
    assert '"readystatechange"' in script
    for forbidden in (
        "http://",
        "https://",
        "import(",
        "eval(",
        "new Function",
        "innerHTML",
        "document.write",
        "fetch(",
        "XMLHttpRequest",
    ):
        assert forbidden not in script
    # Every hook the script defines carries the package prefix.
    for name in re.findall(r"^  hooks\.(\w+) = ", script, re.MULTILINE):
        assert name.startswith("ToriUi")


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
        '<!doctype html><html data-tori-ui-theme="paper" data-tori-ui-mode="auto" '
        'data-tori-ui-skin="editorial"><head>'
    )
    assert document.count(stylesheet_link().value) == 1
    assert stylesheet_link().value in document.split("</head>", 1)[0]
    assert document.count(script_tag().value) == 1
    # The hooks script runs before the deferred LiveView client in the body.
    assert script_tag().value in document.split("</head>", 1)[0]
    assert '<title data-default="">Dashboard</title>' in document
    assert document.count('<body class="tori-ui-document">') == 1
    assert '<main data-phx-session="session"></main>' in document
    assert '<script defer src="/_tori/live/client.js"></script>' in document


def test_ui_liveview_supports_explicit_modes_and_rejects_unknown_values() -> None:
    class DarkPage(UiLiveView):
        def render(self) -> str:
            return ""

        def ui_mode(self):
            return "dark"

    assert 'data-tori-ui-mode="dark"' in DarkPage().render_document("", "")

    class InvalidPage(UiLiveView):
        def render(self) -> str:
            return ""

        def ui_mode(self):
            return "sepia"

    with pytest.raises(ValueError, match="mode must be one of: auto, dark, light"):
        InvalidPage().render_document("", "")


def test_ui_liveview_names_the_theme_and_rejects_unsafe_names() -> None:
    class BrandPage(UiLiveView):
        def render(self) -> str:
            return ""

        def ui_theme(self) -> str:
            return "brand-2026"

    assert 'data-tori-ui-theme="brand-2026"' in BrandPage().render_document("", "")

    class UnsafePage(UiLiveView):
        def render(self) -> str:
            return ""

        def ui_theme(self) -> str:
            return 'x" onload="alert(1)'

    with pytest.raises(ValueError, match="theme must match"):
        UnsafePage().render_document("", "")


def test_ui_liveview_supports_bundled_and_application_owned_skins() -> None:
    class MinimalPage(UiLiveView):
        def render(self) -> str:
            return ""

        def ui_mode(self):
            return "dark"

        def ui_skin(self) -> str:
            return "minimal"

    class BrandPage(UiLiveView):
        def render(self) -> str:
            return ""

        def ui_skin(self) -> str:
            return "brand-2026"

    minimal_document = MinimalPage().render_document("", "")
    assert 'data-tori-ui-mode="dark"' in minimal_document
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

    with pytest.raises(TypeError, match="skin must be a Skin or a string"):
        InvalidPage().render_document("", "")


def test_stylesheet_contains_the_foundation_contract_without_remote_assets() -> None:
    stylesheet = _stylesheet()

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
        '[data-tori-ui-theme="paper"]',
        '[data-tori-ui-mode="light"]',
        '[data-tori-ui-mode="dark"]',
        '[data-tori-ui-mode="auto"]',
        '[data-tori-ui-skin="editorial"]',
        '[data-tori-ui-skin="minimal"]',
        '[data-tori-ui-skin="rounded"]',
        ".tori-ui-document",
        ":focus-visible",
        "prefers-reduced-motion",
    ):
        assert selector in stylesheet
    assert "@import" not in stylesheet
    assert "url(" not in stylesheet


def test_stylesheet_exposes_the_public_skin_token_contract() -> None:
    stylesheet = _stylesheet()
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
    stylesheet = _stylesheet()

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
    stylesheet = _stylesheet()

    assert ".tori-ui-field--invalid .tori-ui-checkbox__control" in stylesheet
    assert "box-shadow: 0 0 0 2px var(--tori-ui-danger)" in stylesheet


def test_light_primary_button_meets_wcag_aa_contrast() -> None:
    stylesheet = _stylesheet()

    accent = _light_theme_color(stylesheet, "accent")
    accent_ink = _light_theme_color(stylesheet, "accent-ink")

    assert _contrast_ratio(accent, accent_ink) >= 4.5


def test_light_form_placeholder_meets_wcag_aa_contrast() -> None:
    stylesheet = _stylesheet()

    muted = _light_theme_color(stylesheet, "muted")
    panel = _light_theme_color(stylesheet, "panel")

    assert _contrast_ratio(muted, panel) >= 4.5
    assert "opacity: 0.75" not in stylesheet
    assert "opacity: 1;" in stylesheet

from __future__ import annotations

import hashlib
import re
from importlib.resources import files
from typing import Any, cast

import httpx
import pytest
from tori_py import (
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


def test_ui_module_materializes_a_versioned_stylesheet_route() -> None:
    descriptor = LiveViewUiModule.for_root(key="design-system")
    spec = cast(ModuleSpec, descriptor.factory())

    assert descriptor.module is LiveViewUiModule
    assert descriptor.key == "design-system"
    assert len(tuple(spec.controllers)) == 1
    controller_type = tuple(spec.controllers)[0]
    assert get_controller_metadata(controller_type) is not None
    route = get_route_metadata(cast(Any, controller_type).stylesheet)
    assert route is not None
    assert route.path == STYLESHEET_PATH
    assert spec.providers == ()


@pytest.mark.asyncio
async def test_stylesheet_route_serves_the_bundled_immutable_asset() -> None:
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

    stylesheet = (
        files("tori_py_liveview_ui")
        .joinpath("static/tori_liveview_ui.css")
        .read_bytes()
    )
    digest = hashlib.sha256(stylesheet).hexdigest()
    assert response.status_code == 200
    assert response.content == stylesheet
    assert response.headers["content-type"] == "text/css; charset=utf-8"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["etag"] == f'"{digest}"'
    assert digest[:12] in STYLESHEET_PATH


def test_ui_liveview_adds_stylesheet_and_theme_to_the_default_document() -> None:
    class Page(UiLiveView):
        def render(self) -> str:
            return '<main class="tori-ui-stack">Ready</main>'

        def title(self) -> str:
            return '<Styled & "safe">'

        def ui_theme(self) -> str:
            return "dark"

    document = Page().render_document(
        "<main data-opal-live-root></main>",
        '<script type="module"></script>',
    )

    assert '<html data-tori-ui-theme="dark">' in document
    assert stylesheet_link().value in document
    assert "&lt;Styled &amp; &quot;safe&quot;&gt;" in document


def test_ui_liveview_rejects_an_unknown_theme() -> None:
    class Page(UiLiveView):
        def render(self) -> str:
            return ""

        def ui_theme(self) -> str:
            return "neon"

    with pytest.raises(ValueError, match="UI theme"):
        Page().render_document("", "")


def test_stylesheet_contains_the_foundation_contract_without_remote_assets() -> None:
    stylesheet = (
        files("tori_py_liveview_ui")
        .joinpath("static/tori_liveview_ui.css")
        .read_text(encoding="utf-8")
    )

    for selector in (
        ".tori-ui-button",
        ".tori-ui-badge",
        ".tori-ui-alert",
        ".tori-ui-card",
        ".tori-ui-stack",
        ".tori-ui-grid",
        '[data-tori-ui-theme="dark"]',
        '[data-tori-ui-theme="auto"]',
        ":focus-visible",
        "prefers-reduced-motion",
    ):
        assert selector in stylesheet
    assert "@import" not in stylesheet
    assert "url(" not in stylesheet


def test_light_primary_button_meets_wcag_aa_contrast() -> None:
    stylesheet = (
        files("tori_py_liveview_ui")
        .joinpath("static/tori_liveview_ui.css")
        .read_text(encoding="utf-8")
    )

    accent = _light_theme_color(stylesheet, "accent")
    accent_ink = _light_theme_color(stylesheet, "accent-ink")

    assert _contrast_ratio(accent, accent_ink) >= 4.5

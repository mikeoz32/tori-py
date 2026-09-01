from __future__ import annotations

import hashlib
from importlib.resources import files
from typing import Any, cast

import pytest
from tori_py import (
    DeferredModule,
    ModuleSpec,
    get_controller_metadata,
    get_route_metadata,
)
from tori_py_liveview_ui import (
    STYLESHEET_PATH,
    LiveViewUiModule,
    UiLiveView,
    stylesheet_link,
)


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
    metadata = get_controller_metadata(controller_type)
    assert metadata is not None
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
        .joinpath(
            "static",
            "tori_liveview_ui.css",
        )
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


def test_stylesheet_link_is_local_and_uses_the_public_path() -> None:
    assert stylesheet_link().value == (
        f'<link rel="stylesheet" href="{STYLESHEET_PATH}">'
    )


def test_ui_liveview_injects_the_stylesheet_and_theme_into_the_normal_document() -> (
    None
):
    class Page(UiLiveView):
        def render(self) -> str:
            return "<p>Dashboard</p>"

        def title(self) -> str:
            return "Dashboard"

    document = Page().render_document(
        '<main data-phx-session="session"></main>',
        '<script defer src="/_tori/live/client.js"></script>',
    )

    assert document.startswith('<!doctype html><html data-tori-ui-theme="auto"><head>')
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

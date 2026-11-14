"""Application themes and skins are registered, served, and linked."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from typing import cast

import httpx
import pytest
from tori_py import ModuleSpec, NestApplication, get_route_metadata, module
from tori_py.starlette import StarletteAdapter
from tori_py_liveview_ui import (
    SCRIPT_PATH,
    STYLESHEET_PATH,
    LiveViewUiModule,
    Skin,
    Theme,
    UiLiveView,
    script_tag,
    stylesheet_link,
)

ACME = Theme(
    "acme",
    light=Theme.PAPER.light.derive(accent="#0b5cad", accent_ink="#ffffff"),
    dark=Theme.PAPER.dark.derive(accent="#7cc4ff", accent_ink="#0b1b2b"),
)
COMPACT = Skin.MINIMAL.derive("compact", radius_control="0.5rem")


def _link(path: str) -> str:
    return f'<link rel="stylesheet" href="{path}">'


def test_a_definition_has_a_content_addressed_stylesheet_path() -> None:
    assert re.fullmatch(
        r"/_tori/liveview-ui/theme-acme\.[0-9a-f]{12}\.css", ACME.stylesheet_path
    )
    assert re.fullmatch(
        r"/_tori/liveview-ui/skin-compact\.[0-9a-f]{12}\.css", COMPACT.stylesheet_path
    )
    digest = hashlib.sha256(ACME.css().encode("utf-8")).hexdigest()
    assert ACME.stylesheet_path.endswith(f".{digest[:12]}.css")
    # Another value is another path, so the cache can be immutable.
    changed = COMPACT.derive("compact", radius_control="0.6rem")
    assert changed.stylesheet_path != COMPACT.stylesheet_path
    # Equal definitions share a path.
    again = Skin.MINIMAL.derive("compact", radius_control="0.5rem")
    assert again.stylesheet_path == COMPACT.stylesheet_path


def test_module_without_definitions_keeps_one_controller() -> None:
    spec = cast(ModuleSpec, LiveViewUiModule.for_root().factory())

    assert len(tuple(spec.controllers)) == 1


def test_module_serves_one_route_per_registered_definition() -> None:
    dynamic = LiveViewUiModule.for_root(themes=[ACME], skins=(COMPACT,))
    spec = cast(ModuleSpec, dynamic.factory())
    assets, definitions = tuple(spec.controllers)

    assert spec.providers == ()
    routes = [
        get_route_metadata(getattr(definitions, name))
        for name in ("definition_0", "definition_1")
    ]
    assert [route.path for route in routes if route is not None] == [
        ACME.stylesheet_path,
        COMPACT.stylesheet_path,
    ]
    assert all(route is not None and route.method == "GET" for route in routes)
    assert get_route_metadata(assets.stylesheet) is not None  # ty: ignore[unresolved-attribute]


def test_module_ignores_bundled_definitions() -> None:
    dynamic = LiveViewUiModule.for_root(themes=[Theme.PAPER], skins=[Skin.ROUNDED])

    assert len(tuple(cast(ModuleSpec, dynamic.factory()).controllers)) == 1


@pytest.mark.parametrize(
    ("themes", "skins", "error", "message"),
    [
        (["acme"], (), TypeError, "themes must be Theme objects"),
        ("acme", (), TypeError, "themes must be Theme objects"),
        ([COMPACT], (), TypeError, "themes must be Theme objects"),
        ((), [ACME], TypeError, "skins must be Skin objects"),
        ((), 7, TypeError, "skins must be Skin objects"),
        (
            [ACME, Theme("acme", light=Theme.PAPER.light, dark=Theme.PAPER.dark)],
            (),
            ValueError,
            'theme "acme" is registered more than once',
        ),
        (
            [Theme("paper", light=ACME.light, dark=ACME.dark)],
            (),
            ValueError,
            'theme name "paper" belongs to a bundled theme',
        ),
        (
            (),
            [Skin.MINIMAL.derive("rounded")],
            ValueError,
            'skin name "rounded" belongs to a bundled skin',
        ),
    ],
)
def test_module_rejects_invalid_registrations(
    themes: object, skins: object, error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        LiveViewUiModule.for_root(
            themes=cast(Iterable[Theme], themes), skins=cast(Iterable[Skin], skins)
        )


@pytest.mark.asyncio
async def test_registered_definitions_are_served_as_immutable_stylesheets() -> None:
    @module(imports=[LiveViewUiModule.for_root(themes=[ACME], skins=[COMPACT])])
    class Root:
        pass

    unregistered = Skin.ROUNDED.derive("loose", space_md="2rem")
    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    transport = httpx.ASGITransport(app=application.get_adapter(StarletteAdapter).app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        theme = await client.get(ACME.stylesheet_path)
        skin = await client.get(COMPACT.stylesheet_path)
        package = await client.get(STYLESHEET_PATH)
        missing = await client.get(unregistered.stylesheet_path)
    await application.shutdown()

    assert theme.status_code == 200
    assert theme.text == ACME.css()
    assert theme.headers["content-type"] == "text/css; charset=utf-8"
    assert theme.headers["cache-control"] == "public, max-age=31536000, immutable"
    digest = hashlib.sha256(ACME.css().encode("utf-8")).hexdigest()
    assert theme.headers["etag"] == f'"{digest}"'
    assert skin.status_code == 200
    assert skin.text == COMPACT.css()
    # Application definitions never change the package stylesheet.
    assert package.status_code == 200
    assert 'data-tori-ui-theme="acme"' not in package.text
    assert 'data-tori-ui-skin="compact"' not in package.text
    assert missing.status_code == 404


def test_stylesheet_link_adds_one_link_for_each_application_definition() -> None:
    package = _link(STYLESHEET_PATH)

    assert stylesheet_link().value == package
    assert stylesheet_link(Theme.PAPER, Skin.ROUNDED).value == package
    assert stylesheet_link(ACME, COMPACT, ACME).value == (
        package + _link(ACME.stylesheet_path) + _link(COMPACT.stylesheet_path)
    )
    with pytest.raises(TypeError, match="definitions must be Theme or Skin"):
        stylesheet_link("acme")  # ty: ignore[invalid-argument-type]


def test_document_defaults_to_the_bundled_theme_and_skin() -> None:
    class Page(UiLiveView):
        def render(self) -> str:
            return ""

    page = Page()
    document = page.render_document("", "")

    assert page.ui_theme() is Theme.PAPER
    assert page.ui_skin() is Skin.EDITORIAL
    assert page.ui_mode() == "auto"
    assert tuple(page.ui_extra_definitions()) == ()
    assert document.startswith(
        '<!doctype html><html data-tori-ui-theme="paper" data-tori-ui-mode="auto" '
        'data-tori-ui-skin="editorial"><head>'
    )
    assert document.count('rel="stylesheet"') == 1


def test_document_links_the_definitions_a_page_returns() -> None:
    class Page(UiLiveView):
        def render(self) -> str:
            return ""

        def ui_theme(self) -> Theme:
            return ACME

        def ui_mode(self):
            return "dark"

        def ui_skin(self) -> Skin:
            return COMPACT

    document = Page().render_document("", "")
    head = document.split("</head>", 1)[0]

    assert (
        '<html data-tori-ui-theme="acme" data-tori-ui-mode="dark" '
        'data-tori-ui-skin="compact">'
    ) in document
    # The package stylesheet comes first, so a definition can override it, and
    # the script still precedes the body.
    assert head.endswith(
        _link(STYLESHEET_PATH)
        + _link(ACME.stylesheet_path)
        + _link(COMPACT.stylesheet_path)
        + script_tag().value
    )
    assert SCRIPT_PATH in head


def test_document_links_extra_definitions_once() -> None:
    loose = Skin.ROUNDED.derive("loose", space_md="2rem")

    class Page(UiLiveView):
        def render(self) -> str:
            return ""

        def ui_theme(self) -> Theme:
            return ACME

        def ui_extra_definitions(self) -> list[Theme | Skin]:
            return [ACME, loose, Theme.PAPER, Skin.MINIMAL]

    document = Page().render_document("", "")

    assert document.count(_link(ACME.stylesheet_path)) == 1
    assert document.count(_link(loose.stylesheet_path)) == 1
    assert document.count('rel="stylesheet"') == 3
    assert 'data-tori-ui-skin="editorial"' in document


def test_document_accepts_names_of_definitions_styled_in_css() -> None:
    class Page(UiLiveView):
        def render(self) -> str:
            return ""

        def ui_theme(self) -> str:
            return "brand-2026"

        def ui_skin(self) -> str:
            return "rounded"

    document = Page().render_document("", "")

    assert 'data-tori-ui-theme="brand-2026"' in document
    assert 'data-tori-ui-skin="rounded"' in document
    assert document.count('rel="stylesheet"') == 1


@pytest.mark.parametrize(
    ("method", "value", "error", "message"),
    [
        ("ui_theme", 7, TypeError, "theme must be a Theme or a string"),
        ("ui_theme", COMPACT, TypeError, "theme must be a Theme or a string"),
        ("ui_skin", ACME, TypeError, "skin must be a Skin or a string"),
        ("ui_skin", None, TypeError, "skin must be a Skin or a string"),
        ("ui_theme", 'x" onload="y', ValueError, "theme must match"),
        ("ui_skin", "Rounded", ValueError, "skin must match"),
        (
            "ui_extra_definitions",
            ["acme"],
            TypeError,
            "definitions must be Theme or Skin",
        ),
    ],
)
def test_document_rejects_values_that_are_not_definitions(
    method: str, value: object, error: type[Exception], message: str
) -> None:
    class Page(UiLiveView):
        def render(self) -> str:
            return ""

    page = Page()
    setattr(page, method, lambda: value)

    with pytest.raises(error, match=message):
        page.render_document("", "")

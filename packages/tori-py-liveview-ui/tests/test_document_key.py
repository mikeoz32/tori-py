"""The look of a page is its document key, so live navigation reloads on a change."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from starlette.datastructures import QueryParams
from tori_py_liveview import MountContext
from tori_py_liveview_ui import Skin, Theme, UiLiveView
from tori_py_liveview_ui import module as ui_module

ACME = Theme(
    "acme",
    light=Theme.PAPER.light.derive(accent="#0b5cad", accent_ink="#ffffff"),
    dark=Theme.PAPER.dark.derive(accent="#7cc4ff", accent_ink="#0b1b2b"),
)
COMPACT = Skin.MINIMAL.derive("compact", radius_control="0.5rem")


class _Page(UiLiveView):
    def __init__(self) -> None:
        self.theme: Theme | str = Theme.PAPER
        self.mode = "auto"
        self.skin: Skin | str = Skin.EDITORIAL
        self.extra: list[Theme | Skin] = []

    def render(self) -> str:
        return ""

    def ui_theme(self) -> Theme | str:
        return self.theme

    def ui_mode(self) -> Any:
        return self.mode

    def ui_skin(self) -> Skin | str:
        return self.skin

    def ui_extra_definitions(self) -> list[Theme | Skin]:
        return self.extra


def test_the_default_look_is_the_default_key() -> None:
    class Plain(UiLiveView):
        def render(self) -> str:
            return ""

    assert Plain().document_key() == "paper|auto|editorial"


def test_pages_with_the_same_look_share_a_key() -> None:
    class First(_Page):
        pass

    class Second(_Page):
        def title(self) -> str:
            return "Another title"

    assert First().document_key() == Second().document_key()


@pytest.mark.parametrize(
    ("change", "value", "key"),
    [
        ("theme", Theme.SLATE, "slate|auto|editorial"),
        ("mode", "dark", "paper|dark|editorial"),
        ("skin", Skin.ROUNDED, "paper|auto|rounded"),
        ("theme", "brand-2026", "brand-2026|auto|editorial"),
        ("skin", "acme", "paper|auto|acme"),
    ],
)
def test_each_part_of_the_look_changes_the_key(
    change: str, value: object, key: str
) -> None:
    page = _Page()
    setattr(page, change, value)

    assert page.document_key() == key
    assert page.document_key() != _Page().document_key()


def test_application_definitions_add_their_stylesheets_to_the_key() -> None:
    page = _Page()
    page.theme = ACME
    page.skin = COMPACT

    assert page.document_key() == "|".join(
        (
            "acme",
            "auto",
            "compact",
            *sorted((ACME.stylesheet_path, COMPACT.stylesheet_path)),
        )
    )


def test_the_stylesheets_a_page_needs_are_part_of_its_key() -> None:
    page = _Page()
    plain = page.document_key()
    page.extra = [ACME]

    assert page.document_key() == f"paper|auto|editorial|{ACME.stylesheet_path}"
    assert page.document_key() != plain


def test_the_order_and_repeats_of_definitions_do_not_change_the_key() -> None:
    first, second = _Page(), _Page()
    first.extra = [ACME, COMPACT]
    second.extra = [COMPACT, ACME, ACME]

    assert first.document_key() == second.document_key()


def test_bundled_definitions_need_no_stylesheet() -> None:
    page = _Page()
    page.extra = [Theme.SLATE, Theme.CONTRAST, Skin.MINIMAL, Skin.ROUNDED]

    assert page.document_key() == "paper|auto|editorial"


def test_the_key_changes_with_the_values_of_a_definition() -> None:
    page = _Page()
    page.skin = COMPACT
    before = page.document_key()
    page.skin = COMPACT.derive("compact", radius_control="0.6rem")

    # The name is the same, the stylesheet is not.
    assert page.document_key() != before


def test_the_key_is_read_after_mount_sets_what_it_depends_on() -> None:
    class Mounted(_Page):
        async def mount(self, context: MountContext) -> None:
            del context
            self.skin = Skin.ROUNDED

    page = Mounted()
    before = page.document_key()

    assert before == "paper|auto|editorial"
    asyncio.run(page.mount(MountContext(object(), {}, "/", True, QueryParams())))
    assert page.document_key() == "paper|auto|rounded"


@pytest.mark.parametrize(
    ("change", "value", "error", "message"),
    [
        ("theme", 'x" onload="y', ValueError, "theme must match"),
    ],
)
def test_an_invalid_look_fails_like_the_document_render(
    change: str, value: object, error: type[Exception], message: str
) -> None:
    page = _Page()
    setattr(page, change, value)

    with pytest.raises(error, match=message):
        page.document_key()
    with pytest.raises(error, match=message):
        page.render_document("", "")


def test_the_document_and_its_key_describe_the_same_look() -> None:
    page = _Page()
    page.theme = ACME
    page.mode = "dark"
    page.skin = COMPACT
    document = page.render_document("", "")

    assert (
        '<html data-tori-ui-theme="acme" data-tori-ui-mode="dark" '
        'data-tori-ui-skin="compact">'
    ) in document
    key = page.document_key()
    assert key is not None
    assert key.startswith("acme|dark|compact|")
    assert ACME.stylesheet_path in document
    assert COMPACT.stylesheet_path in document


def test_the_script_sends_no_connect_params_of_its_own() -> None:
    # The page, not the browser, tells LiveView which document it renders into.
    script = ui_module._SCRIPT.decode("utf-8")

    assert "ToriLiveParams" not in script

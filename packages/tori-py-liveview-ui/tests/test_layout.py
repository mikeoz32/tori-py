from __future__ import annotations

from collections.abc import Callable
from html import escape
from string.templatelib import Template
from typing import Any

import pytest
import tori_py_liveview_ui
from tori_py_liveview import JS, html
from tori_py_liveview_ui import (
    app_shell,
    center,
    container,
    divider,
    layout,
    page_header,
    row,
    scroll_area,
    section,
    spacer,
    split,
    toolbar,
)

ui = tori_py_liveview_ui


def _render(template: Template) -> str:
    return html(template).to_html()


def _command(commands: JS) -> str:
    return escape(commands.encode(), quote=True)


def test_layout_family_is_explicit() -> None:
    assert layout.__all__ == [
        "app_shell",
        "card",
        "center",
        "container",
        "divider",
        "grid",
        "page_header",
        "row",
        "scroll_area",
        "section",
        "spacer",
        "split",
        "stack",
        "toolbar",
    ]


def test_row_renders_closed_flex_options_and_escapes_children() -> None:
    assert _render(row(["<a>", t"<b>x</b>"], gap="sm", justify="between")) == (
        '<div class="tori-ui-row tori-ui-row--gap-sm tori-ui-row--align-center '
        'tori-ui-row--justify-between">&lt;a&gt;<b>x</b></div>'
    )
    assert "tori-ui-row--nowrap" in _render(row([], wrap=False))
    assert "tori-ui-row--align-baseline" in _render(row([], align="baseline"))


def test_row_consumes_its_children_once() -> None:
    consumed: list[int] = []

    def children():
        for index in range(2):
            consumed.append(index)
            yield index

    assert _render(row(children())).endswith(">01</div>")
    assert consumed == [0, 1]


def test_container_center_and_spacer_render_their_closed_sizes() -> None:
    assert _render(container("x")) == (
        '<div class="tori-ui-container tori-ui-container--lg '
        'tori-ui-container--padded">x</div>'
    )
    assert _render(container("x", size="full", padded=False)) == (
        '<div class="tori-ui-container tori-ui-container--full">x</div>'
    )
    assert _render(center("x", min_height="screen")) == (
        '<div class="tori-ui-center tori-ui-center--screen">x</div>'
    )
    assert _render(spacer()) == (
        '<span class="tori-ui-spacer tori-ui-spacer--grow" aria-hidden="true"></span>'
    )
    assert "tori-ui-spacer--lg" in _render(spacer(size="lg"))


def test_divider_is_a_rule_a_labeled_separator_or_a_vertical_separator() -> None:
    assert _render(divider()) == '<hr class="tori-ui-divider">'
    assert _render(divider(label="or <else>")) == (
        '<div class="tori-ui-divider tori-ui-divider--labeled" role="separator">'
        '<span class="tori-ui-divider__label">or &lt;else&gt;</span></div>'
    )
    assert _render(divider(orientation="vertical")) == (
        '<div class="tori-ui-divider tori-ui-divider--vertical" role="separator" '
        'aria-orientation="vertical"></div>'
    )
    with pytest.raises(ValueError, match="requires the horizontal orientation"):
        ui.divider(label="or", orientation="vertical")


def test_section_names_its_region_from_the_title_when_it_has_an_id() -> None:
    assert _render(
        section("body", title="Team", description="People", actions="add", id="team")
    ) == (
        '<section id="team" class="tori-ui-section" aria-labelledby="team-title">'
        '<header class="tori-ui-section__header">'
        '<div class="tori-ui-section__heading">'
        '<h2 id="team-title" class="tori-ui-section__title">Team</h2>'
        '<p class="tori-ui-section__description">People</p></div>'
        '<div class="tori-ui-section__actions">add</div></header>'
        '<div class="tori-ui-section__body">body</div></section>'
    )
    plain = _render(section("body", title="Team"))
    assert plain.startswith('<section class="tori-ui-section"><header')
    assert "aria-labelledby" not in plain
    assert "tori-ui-section__actions" not in plain


def test_page_header_renders_the_first_level_heading_and_optional_regions() -> None:
    assert _render(page_header("Orders")) == (
        '<header class="tori-ui-page-header"><div class="tori-ui-page-header__row">'
        '<div class="tori-ui-page-header__heading">'
        '<h1 class="tori-ui-page-header__title">Orders</h1></div></div></header>'
    )
    full = _render(
        page_header(
            "Orders",
            eyebrow="Shop",
            description="All orders",
            actions="new",
            navigation="crumbs",
        )
    )
    assert '<div class="tori-ui-page-header__navigation">crumbs</div>' in full
    assert '<p class="tori-ui-page-header__eyebrow">Shop</p>' in full
    assert '<p class="tori-ui-page-header__description">All orders</p>' in full
    assert '<div class="tori-ui-page-header__actions">new</div>' in full


def test_toolbar_is_a_labeled_group_with_an_optional_end_group() -> None:
    assert _render(toolbar(["a", "b"], label="Filters")) == (
        '<div class="tori-ui-toolbar" role="group" aria-label="Filters">'
        '<div class="tori-ui-toolbar__group">ab</div></div>'
    )
    assert _render(toolbar(["a"], label="Filters", end=iter(["z"]))).endswith(
        '<div class="tori-ui-toolbar__group tori-ui-toolbar__group--end">z</div></div>'
    )


def test_split_and_scroll_area_render_their_closed_options() -> None:
    assert _render(split("p", "s", ratio="1:3", gap="sm")) == (
        '<div class="tori-ui-split tori-ui-split--1-3 tori-ui-split--gap-sm">'
        '<div class="tori-ui-split__pane">p</div>'
        '<div class="tori-ui-split__pane">s</div></div>'
    )
    assert _render(scroll_area("log", label="Build log", max_height="lg")) == (
        '<div class="tori-ui-scroll-area tori-ui-scroll-area--lg" role="region" '
        'aria-label="Build log" tabindex="0">log</div>'
    )


def test_app_shell_without_regions_renders_only_the_main_landmark() -> None:
    assert _render(app_shell("content", id="app")) == (
        '<div id="app" class="tori-ui-app-shell">'
        '<main id="app-main" class="tori-ui-app-shell__main" tabindex="-1">'
        "content</main></div>"
    )


def test_app_shell_sidebar_is_opened_and_closed_by_js_commands() -> None:
    result = _render(
        app_shell(
            "content",
            id="app",
            header="brand",
            sidebar="links",
            aside="details",
            footer="legal",
            sidebar_label="Sections",
            menu_label="Open sections",
        )
    )
    toggle = (
        JS()
        .toggle_class("tori-ui-app-shell--sidebar-open", to="#app")
        .toggle_attribute("aria-expanded", "true", "false")
    )
    close = (
        JS()
        .remove_class("tori-ui-app-shell--sidebar-open", to="#app")
        .set_attribute("aria-expanded", "false", to="#app .tori-ui-app-shell__menu")
    )

    assert result.startswith(
        '<div id="app" class="tori-ui-app-shell" phx-window-keydown="'
    )
    assert 'phx-key="Escape"' in result
    assert f'phx-click="{_command(toggle)}"' in result
    assert f'phx-window-keydown="{_command(close)}"' in result
    assert (
        f'<div class="tori-ui-app-shell__scrim" phx-click="{_command(close)}"></div>'
        in result
    )
    assert (
        '<button type="button" class="tori-ui-app-shell__menu" '
        'aria-label="Open sections" aria-controls="app-sidebar" '
        'aria-expanded="false" phx-click="'
    ) in result
    assert (
        '<aside id="app-sidebar" class="tori-ui-app-shell__sidebar" '
        'aria-label="Sections">links</aside>'
    ) in result
    assert '<div class="tori-ui-app-shell__header-content">brand</div>' in result
    assert (
        '<main id="app-main" class="tori-ui-app-shell__main" tabindex="-1">content'
        "</main>"
    ) in result
    assert '<aside class="tori-ui-app-shell__aside">details</aside>' in result
    assert '<footer class="tori-ui-app-shell__footer">legal</footer>' in result
    # The scrim follows the sidebar and precedes the main landmark.
    assert result.index("tori-ui-app-shell__scrim") < result.index("<main")


def test_app_shell_header_without_a_sidebar_has_no_menu_button() -> None:
    result = _render(app_shell("content", id="app", header="brand"))

    assert "tori-ui-app-shell__menu" not in result
    assert "phx-window-keydown" not in result
    assert '<div class="tori-ui-app-shell__header-content">brand</div>' in result


@pytest.mark.parametrize(
    ("call", "error", "message"),
    [
        (lambda: ui.divider(label=" "), ValueError, "divider label cannot be empty"),
        (
            lambda: ui.section("x", title=""),
            ValueError,
            "section title cannot be empty",
        ),
        (
            lambda: ui.section("x", title="T", id="a b"),
            ValueError,
            "section id cannot contain whitespace",
        ),
        (lambda: ui.page_header(" "), ValueError, "page header title cannot be empty"),
        (lambda: ui.toolbar([], label=""), ValueError, "toolbar label cannot be empty"),
        (
            lambda: ui.scroll_area("x", label=""),
            ValueError,
            "scroll area label cannot be empty",
        ),
        (
            lambda: ui.app_shell("x", id="a.b"),
            ValueError,
            "app shell id must match",
        ),
        (
            lambda: ui.app_shell("x", id="1app"),
            ValueError,
            "app shell id must match",
        ),
        (
            lambda: ui.app_shell("x", id="app", menu_label=""),
            ValueError,
            "app shell menu label cannot be empty",
        ),
    ],
)
def test_layout_helpers_reject_values_outside_their_contract(
    call: Callable[[], Any], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        call()

from __future__ import annotations

import re
from collections.abc import Callable
from html import escape
from string.templatelib import Template
from typing import Any

import pytest
import tori_py_liveview_ui
from tori_py_liveview import JS, html
from tori_py_liveview_ui import accordion, collapsible, disclosure, icon, tabs

ui = tori_py_liveview_ui


def _render(template: Template) -> str:
    return html(template).to_html()


def _command(commands: JS) -> str:
    return escape(commands.encode(), quote=True)


def test_disclosure_family_is_explicit() -> None:
    assert disclosure.__all__ == ["accordion", "collapsible", "tabs"]


def test_collapsible_is_a_native_disclosure_whose_state_the_browser_keeps() -> None:
    keep = JS().ignore_attributes(["open"])

    assert _render(collapsible("More", "Details")) == (
        f'<details class="tori-ui-collapsible" phx-mounted="{_command(keep)}">'
        '<summary class="tori-ui-collapsible__summary">'
        '<span class="tori-ui-collapsible__label">More</span>'
        f"{_render(icon('chevron-down', size='sm'))}</summary>"
        '<div class="tori-ui-collapsible__content">Details</div></details>'
    )
    opened = _render(collapsible("More", "Details", open=True, id="faq-1", group="faq"))
    assert opened.startswith(
        '<details id="faq-1" class="tori-ui-collapsible" open name="faq" phx-mounted="'
    )


def test_accordion_joins_its_sections() -> None:
    assert _render(accordion(["A", "B"])) == '<div class="tori-ui-accordion">AB</div>'


def test_browser_owned_tabs_render_every_panel_and_switch_with_js() -> None:
    result = _render(
        tabs(
            [("one", "One", "First"), ("two", "Two", "Second")],
            id="views",
            label="Views",
            active="two",
        )
    )
    select_one = (
        JS()
        .set_attribute("aria-selected", "false", to="#views-tabs > [role=tab]")
        .set_attribute("tabindex", "-1", to="#views-tabs > [role=tab]")
        .set_attribute("aria-selected", "true")
        .set_attribute("tabindex", "0")
        .add_class("tori-ui-tabs__panel--hidden", to="#views > [role=tabpanel]")
        .remove_class("tori-ui-tabs__panel--hidden", to="#views-panel-one")
    )

    assert result.startswith(
        '<tori-ui-tabs id="views" class="tori-ui-tabs"><div id="views-tabs" '
        'class="tori-ui-tabs__list" role="tablist" aria-label="Views">'
    )
    assert (
        '<button type="button" role="tab" id="views-tab-one" '
        'class="tori-ui-tabs__tab" aria-selected="false" '
        'aria-controls="views-panel-one" tabindex="-1" '
        f'phx-click="{_command(select_one)}">One</button>'
    ) in result
    assert (
        'id="views-tab-two" class="tori-ui-tabs__tab" aria-selected="true" '
        'aria-controls="views-panel-two" tabindex="0"'
    ) in result
    assert (
        '<div role="tabpanel" id="views-panel-one" class="tori-ui-tabs__panel '
        'tori-ui-tabs__panel--hidden" aria-labelledby="views-tab-one" tabindex="0">'
        "First</div>"
    ) in result
    assert (
        '<div role="tabpanel" id="views-panel-two" class="tori-ui-tabs__panel" '
        'aria-labelledby="views-tab-two" tabindex="0">Second</div>'
    ) in result
    assert "phx-value-tab" not in result


def test_page_owned_tabs_push_the_key_and_render_only_the_active_panel() -> None:
    result = _render(
        tabs(
            [("one", "One", "First"), ("two", "Two", "never rendered")],
            id="views",
            label="Views",
            event="show",
            target=4,
        )
    )

    assert (
        '<button type="button" role="tab" id="views-tab-one" '
        'class="tori-ui-tabs__tab" aria-selected="true" '
        'aria-controls="views-panel-one" tabindex="0" phx-click="show" '
        'phx-target="4" phx-value-tab="one">One</button>'
    ) in result
    assert (
        '<button type="button" role="tab" id="views-tab-two" '
        'class="tori-ui-tabs__tab" aria-selected="false" tabindex="-1" '
        'phx-click="show" phx-target="4" phx-value-tab="two">Two</button>'
    ) in result
    assert result.count('role="tabpanel"') == 1
    assert "never rendered" not in result


@pytest.mark.parametrize(
    ("call", "error", "message"),
    [
        (
            lambda: ui.collapsible("a", "b", id="a b"),
            ValueError,
            "collapsible id cannot contain whitespace",
        ),
        (
            lambda: ui.collapsible("a", "b", group=""),
            ValueError,
            "collapsible group cannot be empty",
        ),
        (
            lambda: ui.tabs([], id="t", label="T"),
            ValueError,
            "tabs requires at least one item",
        ),
        (
            lambda: ui.tabs([("a b", "A", "x")], id="t", label="T"),
            ValueError,
            "tabs keys must match [A-Za-z0-9_-]+",
        ),
        (
            lambda: ui.tabs([("a", "A", "x"), ("a", "B", "y")], id="t", label="T"),
            ValueError,
            "tabs keys must be unique",
        ),
        (
            lambda: ui.tabs([("a", "A", "x")], id="t.x", label="T"),
            ValueError,
            "tabs id must match",
        ),
        (
            lambda: ui.tabs([("a", "A", "x")], id="t", label=""),
            ValueError,
            "tabs label cannot be empty",
        ),
        (
            lambda: ui.tabs([("a", "A", "x")], id="t", label="T", target=1),
            ValueError,
            "tabs target requires an event",
        ),
    ],
)
def test_disclosure_helpers_reject_values_outside_their_contract(
    call: Callable[[], Any], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=re.escape(message)):
        call()

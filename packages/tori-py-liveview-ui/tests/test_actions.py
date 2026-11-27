from __future__ import annotations

from collections.abc import Callable
from html import escape
from string.templatelib import Template
from typing import Any

import pytest
import tori_py_liveview_ui
from tori_py_liveview import JS, html
from tori_py_liveview_ui import (
    actions,
    button,
    button_group,
    copy_button,
    icon,
    icon_button,
    link_button,
    theme_toggle,
)

ui = tori_py_liveview_ui


def _render(template: Template) -> str:
    return html(template).to_html()


def _command(commands: JS) -> str:
    return escape(commands.encode(), quote=True)


def test_actions_family_is_explicit() -> None:
    assert actions.__all__ == [
        "button",
        "button_group",
        "copy_button",
        "icon_button",
        "link_button",
        "theme_toggle",
    ]


def test_plain_button_markup_is_unchanged() -> None:
    assert _render(button("Save")) == (
        '<button type="button" class="tori-ui-button tori-ui-button--primary '
        'tori-ui-button--md">Save</button>'
    )


def test_button_carries_event_values_as_phx_value_attributes() -> None:
    result = _render(
        button(
            "Archive",
            event="archive",
            target=3,
            values={"id": "m1", "position": 2, "ratio": 0.5, "pinned": True},
        )
    )

    assert (
        'phx-click="archive" phx-target="3" phx-value-id="m1" '
        'phx-value-position="2" phx-value-ratio="0.5" phx-value-pinned="true"'
    ) in result
    assert 'phx-value-off="false"' in _render(
        button("x", event="e", values={"off": False})
    )


def test_button_values_are_escaped_and_need_an_event() -> None:
    assert 'phx-value-id="&quot;&gt;&lt;x"' in _render(
        button("x", event="e", values={"id": '"><x'})
    )
    with pytest.raises(ValueError, match="button values require an event"):
        button("x", values={"id": "1"})


@pytest.mark.parametrize("key", ["", "Id", "1st", "on click", "id=x", "a" * 64])
def test_button_rejects_event_value_names_that_are_not_attribute_safe(
    key: str,
) -> None:
    with pytest.raises(ValueError, match="button values keys must match"):
        button("x", event="e", values={key: "1"})


def test_button_icons_surround_the_label() -> None:
    result = _render(button("Next", icon="check", icon_end="arrow-right", size="sm"))
    lead = _render(icon("check", size="sm"))
    trail = _render(icon("arrow-right", size="sm"))

    assert result.endswith(f">{lead}Next{trail}</button>")
    assert _render(icon("check")) in _render(button("Done", icon="check"))


def test_loading_button_is_disabled_busy_and_shows_a_spinner() -> None:
    assert _render(button("Save", loading=True)) == (
        '<button type="button" class="tori-ui-button tori-ui-button--primary '
        'tori-ui-button--md" disabled aria-busy="true">'
        '<span class="tori-ui-spinner tori-ui-spinner--sm" aria-hidden="true"></span>'
        "Save</button>"
    )


def test_button_maps_disable_with_confirm_and_full_width() -> None:
    result = _render(
        button(
            "Delete",
            button_type="submit",
            disable_with="Deleting <it>",
            confirm='Delete "everything"?',
            full_width=True,
        )
    )

    assert "tori-ui-button--full" in result
    assert 'phx-disable-with="Deleting &lt;it&gt;"' in result
    assert 'data-tori-ui-confirm="Delete &quot;everything&quot;?"' in result


def test_icon_button_is_named_by_its_label() -> None:
    assert _render(icon_button("trash", label="Delete", event="delete")) == (
        '<button type="button" class="tori-ui-icon-button '
        'tori-ui-icon-button--ghost tori-ui-icon-button--md" aria-label="Delete" '
        f'title="Delete" phx-click="delete">{_render(icon("trash"))}</button>'
    )
    pressed = _render(icon_button("star", label="Favorite", pressed=True, size="sm"))
    assert 'aria-pressed="true"' in pressed
    assert _render(icon("star", size="sm")) in pressed
    assert 'aria-pressed="false"' in _render(
        icon_button("star", label="Favorite", pressed=False)
    )
    assert "disabled" in _render(icon_button("x", label="Close", disabled=True))


def test_link_button_is_an_anchor_with_button_classes() -> None:
    assert _render(link_button("Open", href="/reports", variant="secondary")) == (
        '<a class="tori-ui-button tori-ui-button--secondary tori-ui-button--md" '
        'href="/reports">Open</a>'
    )
    live = _render(link_button("Next", href="/reports?page=2", live="patch"))
    assert 'data-phx-link="patch" data-phx-link-state="push"' in live
    external = _render(link_button("Docs", href="https://example.com", external=True))
    assert 'target="_blank" rel="noopener noreferrer"' in external
    with pytest.raises(ValueError, match="unsafe URL scheme"):
        link_button("x", href="javascript:alert(1)")


def test_button_group_is_a_labeled_group() -> None:
    assert _render(button_group(["a", "b"], label="View")) == (
        '<div class="tori-ui-button-group tori-ui-button-group--attached" '
        'role="group" aria-label="View">ab</div>'
    )
    assert _render(button_group([], label="View", attached=False)) == (
        '<div class="tori-ui-button-group" role="group" aria-label="View"></div>'
    )


def test_copy_button_dispatches_the_copy_event_to_its_target() -> None:
    result = _render(copy_button(to="#snippet", label="Copy code", copied_label="Done"))
    dispatch = JS().dispatch("tori-ui:copy", to="#snippet")

    assert result.startswith(
        '<button type="button" class="tori-ui-button tori-ui-button--ghost '
        'tori-ui-button--sm tori-ui-copy-button" aria-label="Copy code" '
        f'phx-click="{_command(dispatch)}" data-tori-ui-copied-label="Done">'
    )
    assert f"{_render(icon('copy', size='sm'))}Copy code</span>" in result
    assert (
        '<span class="tori-ui-copy-button__done" aria-hidden="true">'
        f"{_render(icon('check', size='sm'))}Done</span>"
    ) in result
    assert result.endswith(
        '<span class="tori-ui-visually-hidden" role="status"></span></button>'
    )
    relative = _render(copy_button(to=("closest", ".message")))
    assert "&quot;closest&quot;:&quot;.message&quot;" in relative


def test_theme_toggle_is_a_browser_owned_group_of_three_options() -> None:
    result = _render(theme_toggle(id="theme"))

    assert result.startswith(
        '<div id="theme" class="tori-ui-theme-toggle" role="group" '
        'aria-label="Color theme" phx-hook="ToriUiTheme" phx-update="ignore">'
    )
    for value, label in (("auto", "System"), ("light", "Light"), ("dark", "Dark")):
        assert (
            '<button type="button" class="tori-ui-theme-toggle__option" '
            f'data-tori-ui-theme-value="{value}" aria-label="{label}" '
            f'title="{label}" aria-pressed="false">'
        ) in result
    assert result.count("<button") == 3
    assert 'aria-label="Hell"' in _render(theme_toggle(id="t", light_label="Hell"))


@pytest.mark.parametrize(
    ("call", "error", "message"),
    [
        (
            lambda: ui.button("x", disable_with=" "),
            ValueError,
            "button disable with cannot be empty",
        ),
        (
            lambda: ui.button("x", confirm=""),
            ValueError,
            "button confirm cannot be empty",
        ),
        (
            lambda: ui.icon_button("x", label=""),
            ValueError,
            "icon button label cannot be empty",
        ),
        (
            lambda: ui.icon_button("x", label="Close", target=1),
            ValueError,
            "icon button target requires an event",
        ),
        (
            lambda: ui.link_button("x", href=""),
            ValueError,
            "link button href cannot be empty",
        ),
        (
            lambda: ui.link_button("x", href="docs", live="navigate"),
            ValueError,
            "link button live href must be a root-relative path",
        ),
        (
            lambda: ui.button_group([], label=""),
            ValueError,
            "button group label cannot be empty",
        ),
        (
            lambda: ui.copy_button(to="#x", label=""),
            ValueError,
            "copy button label cannot be empty",
        ),
        (lambda: ui.theme_toggle(id="a b"), ValueError, "theme toggle id must match"),
        (
            lambda: ui.theme_toggle(id="t", dark_label=""),
            ValueError,
            "theme toggle option label cannot be empty",
        ),
    ],
)
def test_action_helpers_reject_values_outside_their_contract(
    call: Callable[[], Any], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        call()

from __future__ import annotations

import re
from collections.abc import Callable
from html import escape
from string.templatelib import Template
from typing import Any, cast

import pytest
import tori_py_liveview_ui
from tori_py_liveview import JS, html
from tori_py_liveview_ui import (
    close_overlay,
    confirm_dialog,
    drawer,
    dropdown,
    icon,
    menu_item,
    modal,
    open_overlay,
    overlays,
    popover,
)

ui = tori_py_liveview_ui

_KEEP_OPEN = JS().ignore_attributes(["open"])


def _render(template: Template) -> str:
    return html(template).to_html()


def _command(commands: JS) -> str:
    return escape(commands.encode(), quote=True)


def _icon(name: str) -> str:
    return _render(icon(cast(Any, name), size="sm"))


def test_overlays_family_is_explicit() -> None:
    assert overlays.__all__ == [
        "close_overlay",
        "confirm_dialog",
        "drawer",
        "dropdown",
        "menu_item",
        "modal",
        "open_overlay",
        "popover",
    ]


def test_open_and_close_commands_dispatch_to_the_overlay() -> None:
    assert open_overlay("settings") == JS().dispatch("tori-ui:open", to="#settings")
    assert close_overlay("settings") == JS().dispatch("tori-ui:close", to="#settings")
    with pytest.raises(ValueError, match="overlay id must match"):
        open_overlay("a b")


def test_modal_is_a_named_native_dialog_the_browser_owns_by_default() -> None:
    assert _render(
        modal("BODY", id="settings", title="Settings", description="For this account")
    ) == (
        '<dialog id="settings" class="tori-ui-dialog tori-ui-modal tori-ui-modal--md" '
        'aria-labelledby="settings-title" aria-describedby="settings-description" '
        f'phx-hook="ToriUiDialog" phx-mounted="{_command(_KEEP_OPEN)}">'
        '<div class="tori-ui-dialog__surface">'
        '<header class="tori-ui-dialog__header">'
        '<h2 id="settings-title" class="tori-ui-dialog__title">Settings</h2>'
        '<button type="button" class="tori-ui-dialog__close" aria-label="Close" '
        f'data-tori-ui-dismiss phx-click="{_command(close_overlay("settings"))}">'
        f"{_icon('x')}</button></header>"
        '<p id="settings-description" class="tori-ui-dialog__description">'
        "For this account</p>"
        '<div class="tori-ui-dialog__body">BODY</div></div></dialog>'
    )


def test_page_owned_modal_reports_its_state_and_hears_the_close() -> None:
    result = _render(
        modal(
            "BODY",
            id="edit",
            title="Edit",
            footer="ACTIONS",
            size="lg",
            open=True,
            close_event="close_edit",
            target=3,
        )
    )

    assert 'class="tori-ui-dialog tori-ui-modal tori-ui-modal--lg"' in result
    assert 'data-tori-ui-open="true"' in result
    assert 'data-tori-ui-dismiss phx-click="close_edit" phx-target="3"' in result
    assert '<footer class="tori-ui-dialog__footer">ACTIONS</footer>' in result
    assert "aria-describedby" not in result
    assert 'data-tori-ui-open="false"' in _render(
        modal("x", id="edit", title="Edit", open=False, close_event="close_edit")
    )


def test_modal_that_is_not_dismissible_has_no_close_control() -> None:
    result = _render(modal("BODY", id="terms", title="Terms", dismissible=False))

    assert 'data-tori-ui-dismissible="false"' in result
    assert "tori-ui-dialog__close" not in result
    assert "data-tori-ui-dismiss " not in result


def test_drawer_is_a_dialog_on_one_side() -> None:
    result = _render(drawer("BODY", id="filters", title="Filters", side="start"))

    assert result.startswith(
        '<dialog id="filters" class="tori-ui-dialog tori-ui-drawer '
        'tori-ui-drawer--start" aria-labelledby="filters-title" '
        'phx-hook="ToriUiDialog"'
    )
    assert "tori-ui-drawer--end" in _render(drawer("x", id="d", title="T"))


def test_confirm_dialog_is_an_alert_dialog_with_two_actions() -> None:
    assert _render(
        confirm_dialog(
            "This cannot be undone.",
            id="confirm-delete",
            title="Delete the project?",
            confirm_event="delete",
            confirm_label="Delete",
            tone="danger",
            values={"id": 7},
        )
    ) == (
        '<dialog id="confirm-delete" class="tori-ui-dialog tori-ui-modal '
        'tori-ui-modal--sm" role="alertdialog" '
        'aria-labelledby="confirm-delete-title" '
        'aria-describedby="confirm-delete-description" phx-hook="ToriUiDialog" '
        f'phx-mounted="{_command(_KEEP_OPEN)}">'
        '<div class="tori-ui-dialog__surface">'
        '<header class="tori-ui-dialog__header">'
        '<h2 id="confirm-delete-title" class="tori-ui-dialog__title">'
        "Delete the project?</h2></header>"
        '<div id="confirm-delete-description" class="tori-ui-dialog__body">'
        "This cannot be undone.</div>"
        '<footer class="tori-ui-dialog__footer">'
        '<button type="button" class="tori-ui-button tori-ui-button--ghost '
        'tori-ui-button--md" data-tori-ui-dismiss '
        f'phx-click="{_command(close_overlay("confirm-delete"))}">Cancel</button>'
        '<button type="button" class="tori-ui-button tori-ui-button--danger '
        'tori-ui-button--md" data-tori-ui-confirm-action phx-click="delete" '
        'phx-value-id="7">Delete</button></footer></div></dialog>'
    )


def test_page_owned_confirm_dialog_pushes_a_cancel_event() -> None:
    result = _render(
        confirm_dialog(
            "Sure?",
            id="confirm",
            title="Leave?",
            confirm_event="leave",
            cancel_event="stay",
            target=2,
            open=True,
        )
    )

    assert 'data-tori-ui-open="true"' in result
    assert 'data-tori-ui-dismiss phx-click="stay" phx-target="2">Cancel' in result
    assert 'phx-click="leave" phx-target="2">Confirm' in result
    assert "tori-ui-button--primary" in result


def test_dropdown_is_a_button_that_toggles_a_menu() -> None:
    toggle = (
        JS()
        .toggle_class("tori-ui-popup--open", to="#actions")
        .toggle_attribute("aria-expanded", "true", "false", to="#actions-trigger")
    )
    close = (
        JS()
        .remove_class("tori-ui-popup--open", to="#actions")
        .set_attribute("aria-expanded", "false", to="#actions-trigger")
    )

    assert _render(dropdown("Actions", ["ITEMS"], id="actions", align="end")) == (
        '<div id="actions" class="tori-ui-popup tori-ui-popup--end" '
        f'phx-hook="ToriUiPopup" phx-click-away="{_command(close)}">'
        '<button type="button" id="actions-trigger" class="tori-ui-button '
        'tori-ui-button--secondary tori-ui-button--md" aria-haspopup="menu" '
        'aria-expanded="false" aria-controls="actions-panel" '
        f'phx-click="{_command(toggle)}">Actions{_icon("chevron-down")}</button>'
        '<div id="actions-panel" class="tori-ui-popup__panel tori-ui-menu" '
        'role="menu" aria-labelledby="actions-trigger" tabindex="-1">ITEMS</div>'
        "</div>"
    )
    with_icon = _render(dropdown("More", [], id="more", icon="settings", size="sm"))
    assert f">{_icon('settings')}More{_icon('chevron-down')}</button>" in with_icon


def test_menu_item_is_a_button_or_a_link_with_the_menuitem_role() -> None:
    assert _render(
        menu_item("Archive", event="archive", values={"id": 3}, icon="folder", target=2)
    ) == (
        '<button type="button" role="menuitem" class="tori-ui-menu-item '
        'tori-ui-menu-item--neutral" tabindex="-1" phx-click="archive" '
        f'phx-target="2" phx-value-id="3">{_icon("folder")}Archive</button>'
    )
    assert _render(menu_item("Docs", href="/docs", live="navigate")) == (
        '<a role="menuitem" class="tori-ui-menu-item tori-ui-menu-item--neutral" '
        'tabindex="-1" href="/docs" data-phx-link="redirect" '
        'data-phx-link-state="push">Docs</a>'
    )
    danger = _render(menu_item("Delete", event="delete", tone="danger", disabled=True))
    assert "tori-ui-menu-item--danger" in danger
    assert 'tabindex="-1" disabled phx-click="delete"' in danger


def test_popover_opens_a_labeled_panel_of_any_content() -> None:
    result = _render(
        popover("Filters", "CONTROLS", id="filters", panel_label="Filter orders")
    )

    assert (
        'aria-haspopup="dialog" aria-expanded="false" aria-controls="filters-panel"'
        in (result)
    )
    assert (
        '<div id="filters-panel" class="tori-ui-popup__panel tori-ui-popover" '
        'role="dialog" aria-label="Filter orders" tabindex="-1">CONTROLS</div>'
    ) in result


@pytest.mark.parametrize(
    ("call", "error", "message"),
    [
        (lambda: ui.modal("x", id="a.b", title="T"), ValueError, "modal id must match"),
        (lambda: ui.modal("x", id="m", title=""), ValueError, "modal title cannot be"),
        (
            lambda: ui.modal("x", id="m", title="T", target=1),
            ValueError,
            "modal target requires an event",
        ),
        (
            lambda: ui.menu_item("x"),
            ValueError,
            "menu item requires either an event or an href",
        ),
        (
            lambda: ui.menu_item("x", event="e", href="/a"),
            ValueError,
            "menu item requires either an event or an href",
        ),
        (
            lambda: ui.menu_item("x", href="/a", disabled=True),
            ValueError,
            "menu item links cannot be disabled",
        ),
        (
            lambda: ui.menu_item("x", event="e", live="patch"),
            ValueError,
            "menu item live requires an href",
        ),
        (
            lambda: ui.popover("x", "y", id="p", panel_label=""),
            ValueError,
            "popover panel label cannot be empty",
        ),
    ],
)
def test_overlay_helpers_reject_values_outside_their_contract(
    call: Callable[[], Any], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=re.escape(message)):
        call()

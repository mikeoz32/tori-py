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
    alert,
    banner,
    busy,
    connection_status,
    feedback,
    flash_group,
    icon,
    skeleton,
    spinner,
    toast,
    toast_region,
)

# Calls that break a helper's contract go through an untyped alias.
ui = cast(Any, tori_py_liveview_ui)


def _render(template: Template) -> str:
    return html(template).to_html()


def _command(commands: JS) -> str:
    return escape(commands.encode(), quote=True)


def _close() -> str:
    return _render(icon("x", size="sm"))


def test_feedback_family_is_explicit() -> None:
    assert feedback.__all__ == [
        "alert",
        "banner",
        "busy",
        "connection_status",
        "flash_group",
        "skeleton",
        "spinner",
        "toast",
        "toast_region",
    ]


def test_dismissible_alert_is_hidden_by_the_browser() -> None:
    hide = JS().hide(to=("closest", ".tori-ui-alert"))

    assert _render(alert("Body", title="Title", actions="ACT", dismissible=True)) == (
        '<section class="tori-ui-alert tori-ui-alert--neutral" role="status">'
        '<div class="tori-ui-alert__content"><h2 class="tori-ui-alert__title">Title'
        '</h2><div class="tori-ui-alert__body">Body</div>'
        '<div class="tori-ui-alert__actions">ACT</div></div>'
        '<button type="button" class="tori-ui-alert__dismiss" aria-label="Dismiss" '
        f'phx-click="{_command(hide)}">{_close()}</button></section>'
    )


def test_alert_with_a_dismiss_event_leaves_removal_to_the_page() -> None:
    result = _render(
        alert("Body", dismiss_event="close", dismiss_label="Close", target=2)
    )

    assert (
        '<button type="button" class="tori-ui-alert__dismiss" aria-label="Close" '
        'phx-click="close" phx-target="2">'
    ) in result
    assert "hide" not in result


def test_banner_is_a_toned_strip_with_optional_actions_and_dismissal() -> None:
    assert _render(banner("Maintenance at noon.")) == (
        '<div class="tori-ui-banner tori-ui-banner--info" role="status">'
        '<div class="tori-ui-banner__content">Maintenance at noon.</div></div>'
    )
    hide = JS().hide(to=("closest", ".tori-ui-banner"))
    full = _render(banner("Down", tone="danger", actions="ACT", dismissible=True))
    assert full.startswith(
        '<div class="tori-ui-banner tori-ui-banner--danger" role="alert">'
    )
    assert '<div class="tori-ui-banner__actions">ACT</div>' in full
    assert (
        'class="tori-ui-banner__dismiss" aria-label="Dismiss" '
        f'phx-click="{_command(hide)}"'
    ) in full


def test_spinner_announces_its_label() -> None:
    assert _render(spinner()) == (
        '<span class="tori-ui-spinner-status" role="status">'
        '<span class="tori-ui-spinner tori-ui-spinner--md" aria-hidden="true"></span>'
        '<span class="tori-ui-visually-hidden">Loading</span></span>'
    )
    large = _render(spinner(label="Loading <orders>", size="lg"))
    assert "tori-ui-spinner--lg" in large
    assert "Loading &lt;orders&gt;" in large


def test_skeleton_is_hidden_from_assistive_technology() -> None:
    assert _render(skeleton(lines=2)) == (
        '<div class="tori-ui-skeleton tori-ui-skeleton--text" aria-hidden="true">'
        '<span class="tori-ui-skeleton__line"></span>'
        '<span class="tori-ui-skeleton__line"></span></div>'
    )
    assert _render(skeleton(shape="circle")) == (
        '<div class="tori-ui-skeleton tori-ui-skeleton--circle" aria-hidden="true">'
        "</div>"
    )


def test_busy_region_is_inert_and_covered_while_loading() -> None:
    assert _render(busy("content", busy=True, label="Loading rows")) == (
        '<div class="tori-ui-busy tori-ui-busy--active" aria-busy="true">'
        '<div class="tori-ui-busy__content" inert>content</div>'
        f'<div class="tori-ui-busy__overlay">{_render(spinner(label="Loading rows"))}'
        "</div></div>"
    )
    assert _render(busy("content", busy=False)) == (
        '<div class="tori-ui-busy" aria-busy="false">'
        '<div class="tori-ui-busy__content">content</div></div>'
    )


def test_toast_closes_itself_through_its_own_dismiss_button() -> None:
    hide = JS().hide(to=("closest", ".tori-ui-toast"))

    assert _render(toast("Saved", id="saved", title="Done", tone="success")) == (
        '<div id="saved" class="tori-ui-toast tori-ui-toast--success" role="status" '
        'phx-hook="ToriUiToast" data-tori-ui-duration="5000">'
        '<div class="tori-ui-toast__content"><p class="tori-ui-toast__title">Done</p>'
        '<div class="tori-ui-toast__body">Saved</div></div>'
        '<button type="button" class="tori-ui-toast__dismiss" aria-label="Dismiss" '
        f'phx-click="{_command(hide)}">{_close()}</button></div>'
    )


def test_toast_without_a_duration_has_no_hook_and_can_tell_the_page() -> None:
    result = _render(
        toast("Failed", id="failed", tone="danger", duration=None, dismiss_event="x")
    )

    assert result.startswith(
        '<div id="failed" class="tori-ui-toast tori-ui-toast--danger" role="alert">'
    )
    assert "phx-hook" not in result
    assert "data-tori-ui-duration" not in result
    assert 'phx-click="x"' in result


def test_toast_region_is_a_labeled_fixed_region() -> None:
    assert _render(toast_region(["A", "B"])) == (
        '<div id="toasts" class="tori-ui-toast-region '
        'tori-ui-toast-region--bottom-end" role="region" '
        'aria-label="Notifications">AB</div>'
    )
    assert "tori-ui-toast-region--top-start" in _render(
        toast_region([], id="notices", placement="top-start", label="Notices")
    )


def test_flash_group_renders_known_kinds_and_clears_them_through_liveview() -> None:
    result = _render(
        flash_group({"info": "Saved", "error": "Failed <hard>", "custom": "ignored"})
    )
    clear_error = (
        JS().push("lv:clear-flash", value={"key": "error"}).hide(to="#flash-error")
    )
    clear_info = (
        JS().push("lv:clear-flash", value={"key": "info"}).hide(to="#flash-info")
    )

    assert result.startswith(
        '<div id="flash" class="tori-ui-toast-region tori-ui-toast-region--top-end" '
        'role="region" aria-label="Notifications">'
        '<div id="flash-error" class="tori-ui-toast tori-ui-toast--danger" '
        'role="alert">'
    )
    assert "Failed &lt;hard&gt;" in result
    assert "ignored" not in result
    assert f'phx-click="{_command(clear_error)}"' in result
    assert f'phx-click="{_command(clear_info)}"' in result
    # Errors stay until dismissed; information closes itself.
    assert result.count("phx-hook") == 1
    assert (
        '<div id="flash-info" class="tori-ui-toast tori-ui-toast--info" '
        'role="status" phx-hook="ToriUiToast" data-tori-ui-duration="5000">'
    ) in result


def test_flash_group_without_messages_keeps_an_empty_region() -> None:
    assert _render(flash_group({}, id="notices", placement="bottom-end")) == (
        '<div id="notices" class="tori-ui-toast-region '
        'tori-ui-toast-region--bottom-end" role="region" '
        'aria-label="Notifications"></div>'
    )
    sticky = _render(flash_group({"success": "ok", "warning": "careful"}))
    assert sticky.index("flash-warning") < sticky.index("flash-success")
    assert sticky.count("phx-hook") == 1


def test_connection_status_is_a_status_message_with_a_spinner() -> None:
    assert _render(connection_status(message="Offline")) == (
        '<div class="tori-ui-connection-status" role="status">'
        '<span class="tori-ui-spinner tori-ui-spinner--sm" aria-hidden="true"></span>'
        "Offline</div>"
    )


@pytest.mark.parametrize(
    ("call", "error", "message"),
    [
        (
            lambda: ui.alert("x", dismissible=1),
            TypeError,
            "alert dismissible must be a boolean",
        ),
        (
            lambda: ui.alert("x", dismiss_event=""),
            ValueError,
            "alert dismiss event cannot be empty",
        ),
        (
            lambda: ui.alert("x", dismissible=True, dismiss_label=""),
            ValueError,
            "alert dismiss label cannot be empty",
        ),
        (
            lambda: ui.alert("x", dismissible=True, target=1),
            ValueError,
            "alert target requires an event",
        ),
        (lambda: ui.banner("x", tone="blue"), ValueError, "banner tone must be one of"),
        (lambda: ui.spinner(label=""), ValueError, "spinner label cannot be empty"),
        (lambda: ui.spinner(size="xl"), ValueError, "spinner size must be one of"),
        (lambda: ui.skeleton(shape="line"), ValueError, "skeleton shape must be one"),
        (lambda: ui.skeleton(lines=0), ValueError, "skeleton lines must be between"),
        (
            lambda: ui.skeleton(shape="block", lines=2),
            ValueError,
            "skeleton lines require the text shape",
        ),
        (lambda: ui.busy("x", busy="yes"), TypeError, "busy state must be a boolean"),
        (lambda: ui.toast("x", id="a b"), ValueError, "toast id must match"),
        (
            lambda: ui.toast("x", id="t", duration=10),
            ValueError,
            "toast duration must be between",
        ),
        (
            lambda: ui.toast("x", id="t", duration=2.5),
            TypeError,
            "toast duration must be an integer",
        ),
        (lambda: ui.toast("x", id="t", title=" "), ValueError, "toast title cannot"),
        (
            lambda: ui.toast_region([], placement="center"),
            ValueError,
            "toast region placement must be one of",
        ),
        (
            lambda: ui.flash_group([("info", "x")]),
            TypeError,
            "flash group flash must be a mapping",
        ),
        (lambda: ui.flash_group({}, id="1"), ValueError, "flash group id must match"),
        (
            lambda: ui.connection_status(message=""),
            ValueError,
            "connection status message cannot be empty",
        ),
    ],
)
def test_feedback_helpers_reject_values_outside_their_contract(
    call: Callable[[], Any], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=re.escape(message)):
        call()

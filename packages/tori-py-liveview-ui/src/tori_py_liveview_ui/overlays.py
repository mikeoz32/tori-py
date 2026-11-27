"""Helpers for content that opens over the page."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from string.templatelib import Template
from typing import Literal

from tori_py_liveview import JS, attrs, classes, fragment, raw

from tori_py_liveview_ui._shared import (
    ButtonSize,
    ButtonVariant,
    EventValue,
    LiveLink,
    event_binding,
    event_target,
    event_values,
    link_attributes,
    optional_nonempty_text,
    required_text,
    selector_id,
)
from tori_py_liveview_ui.icons import IconName
from tori_py_liveview_ui.icons import icon as render_icon

type ModalSize = Literal["sm", "md", "lg", "xl"]
type DrawerSide = Literal["start", "end"]
type PopupAlignment = Literal["start", "end"]
type MenuTone = Literal["neutral", "danger"]
type ConfirmTone = Literal["primary", "danger"]

_POPUP_OPEN = "tori-ui-popup--open"
# showModal() sets the open attribute; a server render must not remove it.
_KEEP_OPEN = JS().ignore_attributes(["open"])


def open_overlay(id: str) -> JS:
    """Return the command that opens the modal, drawer, or dialog ``id``.

    Pass it as a button's ``event``, or chain more commands onto it.
    """
    return JS().dispatch("tori-ui:open", to=f"#{selector_id('overlay id', id)}")


def close_overlay(id: str) -> JS:
    """Return the command that closes the modal, drawer, or dialog ``id``."""
    return JS().dispatch("tori-ui:close", to=f"#{selector_id('overlay id', id)}")


def _dialog(
    class_name: str,
    surface: object,
    *,
    id: str,
    open: bool | None,
    dismissible: bool,
    described: bool,
    role: str | None = None,
) -> Template:
    """Render the native dialog element every overlay shares."""
    attributes = attrs(
        {
            "id": id,
            "class": class_name,
            "role": role,
            "aria-labelledby": f"{id}-title",
            "aria-describedby": f"{id}-description" if described else None,
            "phx-mounted": _KEEP_OPEN,
            # Absent: the browser owns the state. Present: the page does.
            "data-tori-ui-open": None if open is None else str(open).lower(),
            "data-tori-ui-dismissible": None if dismissible else "false",
        }
    )
    return (
        t'<tori-ui-dialog id="{id}-component"><dialog{attributes}>'
        t'<div class="tori-ui-dialog__surface">{surface}</div>'
        t"</dialog></tori-ui-dialog>"
    )


def _panel(
    name: str,
    content: object,
    *,
    id: str,
    title: str,
    description: str | None,
    footer: object | None,
    dismissible: bool,
    close_event: str | JS | None,
    close_label: str,
    target: int | None,
) -> tuple[Template, bool]:
    """Return the header, body, and footer of a modal or a drawer."""
    title = required_text(f"{name} title", title)
    description = optional_nonempty_text(f"{name} description", description)
    close_event = event_binding(f"{name} close event", close_event)
    close_label = required_text(f"{name} close label", close_label)
    target = event_target(f"{name} target", target, close_event)
    close: object = raw("")
    if dismissible:
        button = attrs(
            {
                "type": "button",
                "class": "tori-ui-dialog__close",
                "aria-label": close_label,
                "data-tori-ui-dismiss": True,
                "phx-click": close_overlay(id) if close_event is None else close_event,
                "phx-target": target,
            }
        )
        close = t"<button{button}>{render_icon('x', size='sm')}</button>"
    description_markup = (
        t'<p id="{id}-description" class="tori-ui-dialog__description">'
        t"{description}</p>"
        if description is not None
        else raw("")
    )
    footer_markup = (
        t'<footer class="tori-ui-dialog__footer">{footer}</footer>'
        if footer is not None
        else raw("")
    )
    surface = (
        t'<header class="tori-ui-dialog__header">'
        t'<h2 id="{id}-title" class="tori-ui-dialog__title">{title}</h2>{close}'
        t"</header>{description_markup}"
        t'<div class="tori-ui-dialog__body">{content}</div>{footer_markup}'
    )
    return surface, description is not None


def modal(
    content: object,
    *,
    id: str,
    title: str,
    description: str | None = None,
    footer: object | None = None,
    size: ModalSize = "md",
    open: bool | None = None,
    dismissible: bool = True,
    close_event: str | JS | None = None,
    close_label: str = "Close",
    target: int | None = None,
) -> Template:
    """Render a dialog that opens over the page and holds the focus.

    By default the browser owns whether it is open: open it with
    ``open_overlay(id)`` and it closes on its close button, on Escape, and on a
    click outside. Pass ``open`` when the page owns that state instead, with a
    ``close_event`` so the page hears that the visitor closed it.
    ``dismissible=False`` leaves closing to the controls in the dialog.
    """
    id = selector_id("modal id", id)
    surface, described = _panel(
        "modal",
        content,
        id=id,
        title=title,
        description=description,
        footer=footer,
        dismissible=dismissible,
        close_event=close_event,
        close_label=close_label,
        target=target,
    )
    return _dialog(
        classes("tori-ui-dialog", "tori-ui-modal", f"tori-ui-modal--{size}"),
        surface,
        id=id,
        open=open,
        dismissible=dismissible,
        described=described,
    )


def drawer(
    content: object,
    *,
    id: str,
    title: str,
    description: str | None = None,
    footer: object | None = None,
    side: DrawerSide = "end",
    open: bool | None = None,
    dismissible: bool = True,
    close_event: str | JS | None = None,
    close_label: str = "Close",
    target: int | None = None,
) -> Template:
    """Render a panel that slides in from a side of the viewport.

    It opens, closes, and holds the focus like ``modal()``.
    """
    id = selector_id("drawer id", id)
    surface, described = _panel(
        "drawer",
        content,
        id=id,
        title=title,
        description=description,
        footer=footer,
        dismissible=dismissible,
        close_event=close_event,
        close_label=close_label,
        target=target,
    )
    return _dialog(
        classes("tori-ui-dialog", "tori-ui-drawer", f"tori-ui-drawer--{side}"),
        surface,
        id=id,
        open=open,
        dismissible=dismissible,
        described=described,
    )


def confirm_dialog(
    message: object,
    *,
    id: str,
    title: str,
    confirm_event: str | JS,
    confirm_label: str = "Confirm",
    cancel_label: str = "Cancel",
    tone: ConfirmTone = "primary",
    target: int | None = None,
    values: Mapping[str, EventValue] | None = None,
    open: bool | None = None,
    cancel_event: str | JS | None = None,
) -> Template:
    """Ask the visitor to confirm an action in a styled dialog.

    Open it with ``open_overlay(id)``. Confirming pushes ``confirm_event`` with
    ``values``; cancelling, Escape, and a click outside only close it. When the
    page owns ``open``, give a ``cancel_event`` as well and close the dialog
    from both handlers.
    """
    id = selector_id("confirm dialog id", id)
    title = required_text("confirm dialog title", title)
    confirm_event = event_binding("confirm dialog confirm event", confirm_event)
    confirm_label = required_text("confirm dialog confirm label", confirm_label)
    cancel_label = required_text("confirm dialog cancel label", cancel_label)
    cancel_event = event_binding("confirm dialog cancel event", cancel_event)
    target = event_target("confirm dialog target", target, confirm_event)
    value_attributes = event_values("confirm dialog values", values, confirm_event)
    cancel = attrs(
        {
            "type": "button",
            "class": "tori-ui-button tori-ui-button--ghost tori-ui-button--md",
            "data-tori-ui-dismiss": True,
            "phx-click": close_overlay(id) if cancel_event is None else cancel_event,
            "phx-target": target if cancel_event is not None else None,
        }
    )
    confirm = attrs(
        {
            "type": "button",
            "class": classes(
                "tori-ui-button",
                f"tori-ui-button--{tone}",
                "tori-ui-button--md",
            ),
            "data-tori-ui-confirm-action": True,
            "phx-click": confirm_event,
            "phx-target": target,
            **value_attributes,
        }
    )
    surface = (
        t'<header class="tori-ui-dialog__header">'
        t'<h2 id="{id}-title" class="tori-ui-dialog__title">{title}</h2></header>'
        t'<div id="{id}-description" class="tori-ui-dialog__body">{message}</div>'
        t'<footer class="tori-ui-dialog__footer"><button{cancel}>{cancel_label}'
        t"</button><button{confirm}>{confirm_label}</button></footer>"
    )
    return _dialog(
        "tori-ui-dialog tori-ui-modal tori-ui-modal--sm",
        surface,
        id=id,
        open=open,
        dismissible=True,
        described=True,
        role="alertdialog",
    )


def _popup(
    label: object,
    panel: Template,
    *,
    id: str,
    haspopup: str,
    variant: ButtonVariant,
    size: ButtonSize,
    icon: IconName | None,
    align: PopupAlignment,
) -> Template:
    """Render a button and the panel it opens next to itself."""
    glyph: object = raw("")
    if icon is not None:
        glyph = render_icon(icon, size="sm")
    trigger_selector = f"#{id}-trigger"
    toggle = (
        JS()
        .toggle_class(_POPUP_OPEN, to=f"#{id}")
        .toggle_attribute("aria-expanded", "true", "false", to=trigger_selector)
    )
    close = (
        JS()
        .remove_class(_POPUP_OPEN, to=f"#{id}")
        .set_attribute("aria-expanded", "false", to=trigger_selector)
    )
    root = attrs(
        {
            "id": id,
            "class": classes("tori-ui-popup", f"tori-ui-popup--{align}"),
            "phx-click-away": close,
        }
    )
    trigger = attrs(
        {
            "type": "button",
            "id": f"{id}-trigger",
            "class": classes(
                "tori-ui-button",
                f"tori-ui-button--{variant}",
                f"tori-ui-button--{size}",
            ),
            "aria-haspopup": haspopup,
            "aria-expanded": "false",
            "aria-controls": f"{id}-panel",
            "phx-click": toggle,
        }
    )
    return (
        t"<tori-ui-popup{root}><button{trigger}>{glyph}{label}"
        t"{render_icon('chevron-down', size='sm')}</button>{panel}</tori-ui-popup>"
    )


def dropdown(
    label: object,
    items: Iterable[object],
    *,
    id: str,
    variant: ButtonVariant = "secondary",
    size: ButtonSize = "md",
    icon: IconName | None = None,
    align: PopupAlignment = "start",
) -> Template:
    """Render a button that opens a menu of ``menu_item()`` entries.

    The menu closes on a choice, on Escape, and on a click outside, and the
    arrow keys move between its items.
    """
    id = selector_id("dropdown id", id)
    panel = attrs(
        {
            "id": f"{id}-panel",
            "class": "tori-ui-popup__panel tori-ui-menu",
            "role": "menu",
            "aria-labelledby": f"{id}-trigger",
            "tabindex": "-1",
        }
    )
    return _popup(
        label,
        t"<div{panel}>{fragment(items)}</div>",
        id=id,
        haspopup="menu",
        variant=variant,
        size=size,
        icon=icon,
        align=align,
    )


def menu_item(
    label: object,
    *,
    event: str | JS | None = None,
    href: str | None = None,
    live: LiveLink | None = None,
    target: int | None = None,
    values: Mapping[str, EventValue] | None = None,
    icon: IconName | None = None,
    tone: MenuTone = "neutral",
    disabled: bool = False,
) -> Template:
    """Render one entry of a ``dropdown()``: a button with ``event`` or a link."""
    event = event_binding("menu item event", event)
    target = event_target("menu item target", target, event)
    value_attributes = event_values("menu item values", values, event)
    if (event is None) == (href is None):
        raise ValueError("menu item requires either an event or an href")
    glyph: object = raw("")
    if icon is not None:
        glyph = render_icon(icon, size="sm")
    class_name = classes("tori-ui-menu-item", f"tori-ui-menu-item--{tone}")
    if href is not None:
        if disabled:
            raise ValueError("menu item links cannot be disabled")
        link = attrs(
            {
                "role": "menuitem",
                "class": class_name,
                "tabindex": "-1",
                **link_attributes("menu item", href, live, False, False),
            }
        )
        return t"<a{link}>{glyph}{label}</a>"
    if live is not None:
        raise ValueError("menu item live requires an href")
    button = attrs(
        {
            "type": "button",
            "role": "menuitem",
            "class": class_name,
            "tabindex": "-1",
            "disabled": disabled,
            "phx-click": event,
            "phx-target": target,
            **value_attributes,
        }
    )
    return t"<button{button}>{glyph}{label}</button>"


def popover(
    label: object,
    content: object,
    *,
    id: str,
    panel_label: str,
    variant: ButtonVariant = "secondary",
    size: ButtonSize = "md",
    icon: IconName | None = None,
    align: PopupAlignment = "start",
) -> Template:
    """Render a button that opens a small panel of any content next to itself.

    ``panel_label`` names the panel for assistive technology. The panel closes
    on Escape and on a click outside.
    """
    id = selector_id("popover id", id)
    panel_label = required_text("popover panel label", panel_label)
    panel = attrs(
        {
            "id": f"{id}-panel",
            "class": "tori-ui-popup__panel tori-ui-popover",
            "role": "dialog",
            "aria-label": panel_label,
            "tabindex": "-1",
        }
    )
    return _popup(
        label,
        t"<div{panel}>{content}</div>",
        id=id,
        haspopup="dialog",
        variant=variant,
        size=size,
        icon=icon,
        align=align,
    )


__all__ = [
    "close_overlay",
    "confirm_dialog",
    "drawer",
    "dropdown",
    "menu_item",
    "modal",
    "open_overlay",
    "popover",
]

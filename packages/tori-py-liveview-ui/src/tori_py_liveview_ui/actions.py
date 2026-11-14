"""Buttons and other controls that start an action."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from string.templatelib import Template
from typing import Literal

from tori_py_liveview import JS, attrs, classes, fragment, raw

from tori_py_liveview_ui._shared import (
    BUTTON_SIZES,
    BUTTON_TYPES,
    BUTTON_VARIANTS,
    ButtonSize,
    ButtonType,
    ButtonVariant,
    EventValue,
    LiveLink,
    boolean,
    event_binding,
    event_target,
    event_values,
    link_attributes,
    one_of,
    optional_nonempty_text,
    required_text,
    selector_id,
)
from tori_py_liveview_ui.icons import IconName, icon_name
from tori_py_liveview_ui.icons import icon as render_icon

type CopyTarget = str | tuple[Literal["closest", "inner"], str]

_SPINNER = raw(
    '<span class="tori-ui-spinner tori-ui-spinner--sm" aria-hidden="true"></span>'
)


def _button_classes(
    name: str,
    variant: ButtonVariant,
    size: ButtonSize,
    *,
    full_width: bool = False,
) -> str:
    one_of(f"{name} variant", variant, BUTTON_VARIANTS)
    one_of(f"{name} size", size, BUTTON_SIZES)
    return classes(
        "tori-ui-button",
        f"tori-ui-button--{variant}",
        f"tori-ui-button--{size}",
        **{"tori-ui-button--full": full_width},
    )


def _optional_icon(name: str, value: IconName | None, size: ButtonSize) -> object:
    if value is None:
        return raw("")
    icon_name(name, value)
    return render_icon(value, size="sm" if size == "sm" else "md")


def button(
    label: object,
    *,
    variant: ButtonVariant = "primary",
    size: ButtonSize = "md",
    button_type: ButtonType = "button",
    disabled: bool = False,
    event: str | JS | None = None,
    target: int | None = None,
    values: Mapping[str, EventValue] | None = None,
    icon: IconName | None = None,
    icon_end: IconName | None = None,
    loading: bool = False,
    disable_with: str | None = None,
    confirm: str | None = None,
    full_width: bool = False,
) -> Template:
    """Render a native button.

    ``values`` become ``phx-value-*`` attributes of the click event.
    ``loading`` shows a spinner and disables the button. ``disable_with`` is
    the label the Phoenix client shows while a form submit or click is in
    flight. ``confirm`` asks the visitor in a native dialog before the click
    reaches the page.
    """
    boolean("button full width", full_width)
    class_name = _button_classes("button", variant, size, full_width=full_width)
    one_of("button type", button_type, BUTTON_TYPES)
    if type(disabled) is not bool:
        raise TypeError("button disabled must be a boolean")
    boolean("button loading", loading)
    event = event_binding("button event", event)
    target = event_target("button target", target, event)
    value_attributes = event_values("button values", values, event)
    disable_with = optional_nonempty_text("button disable with", disable_with)
    confirm = optional_nonempty_text("button confirm", confirm)
    attributes = attrs(
        {
            "type": button_type,
            "class": class_name,
            "disabled": disabled or loading,
            "aria-busy": "true" if loading else None,
            "phx-click": event,
            "phx-target": target,
            **value_attributes,
            "phx-disable-with": disable_with,
            "data-tori-ui-confirm": confirm,
        }
    )
    spinner = _SPINNER if loading else raw("")
    leading = _optional_icon("button icon", icon, size)
    trailing = _optional_icon("button end icon", icon_end, size)
    return t"<button{attributes}>{spinner}{leading}{label}{trailing}</button>"


def icon_button(
    icon: IconName,
    *,
    label: str,
    variant: ButtonVariant = "ghost",
    size: ButtonSize = "md",
    button_type: ButtonType = "button",
    disabled: bool = False,
    pressed: bool | None = None,
    event: str | JS | None = None,
    target: int | None = None,
    values: Mapping[str, EventValue] | None = None,
    confirm: str | None = None,
) -> Template:
    """Render a square button whose only content is an icon.

    ``label`` is its accessible name and its tooltip. ``pressed`` makes it a
    toggle button that reports its state.
    """
    icon_name("icon button icon", icon)
    label = required_text("icon button label", label)
    one_of("icon button variant", variant, BUTTON_VARIANTS)
    one_of("icon button size", size, BUTTON_SIZES)
    one_of("icon button type", button_type, BUTTON_TYPES)
    boolean("icon button disabled", disabled)
    if pressed is not None:
        boolean("icon button pressed", pressed)
    event = event_binding("icon button event", event)
    target = event_target("icon button target", target, event)
    value_attributes = event_values("icon button values", values, event)
    confirm = optional_nonempty_text("icon button confirm", confirm)
    attributes = attrs(
        {
            "type": button_type,
            "class": classes(
                "tori-ui-icon-button",
                f"tori-ui-icon-button--{variant}",
                f"tori-ui-icon-button--{size}",
            ),
            "aria-label": label,
            "title": label,
            "aria-pressed": None if pressed is None else str(pressed).lower(),
            "disabled": disabled,
            "phx-click": event,
            "phx-target": target,
            **value_attributes,
            "data-tori-ui-confirm": confirm,
        }
    )
    glyph = render_icon(icon, size="sm" if size == "sm" else "md")
    return t"<button{attributes}>{glyph}</button>"


def link_button(
    label: object,
    *,
    href: str,
    variant: ButtonVariant = "primary",
    size: ButtonSize = "md",
    live: LiveLink | None = None,
    replace: bool = False,
    external: bool = False,
    icon: IconName | None = None,
    icon_end: IconName | None = None,
    full_width: bool = False,
) -> Template:
    """Render a link that looks like a button.

    ``live`` turns it into a LiveView patch or navigate link. ``external``
    opens it in a new tab without access to the opener.
    """
    boolean("link button full width", full_width)
    class_name = _button_classes("link button", variant, size, full_width=full_width)
    attributes = attrs(
        {
            "class": class_name,
            **link_attributes("link button", href, live, replace, external),
        }
    )
    leading = _optional_icon("link button icon", icon, size)
    trailing = _optional_icon("link button end icon", icon_end, size)
    return t"<a{attributes}>{leading}{label}{trailing}</a>"


def button_group(
    children: Iterable[object],
    *,
    label: str,
    attached: bool = True,
) -> Template:
    """Group related buttons under one accessible name.

    ``attached`` joins the buttons into one segmented control.
    """
    label = required_text("button group label", label)
    boolean("button group attached", attached)
    class_name = classes(
        "tori-ui-button-group",
        **{"tori-ui-button-group--attached": attached},
    )
    content = fragment(children)
    return (
        t'<div class="{class_name}" role="group" aria-label="{label}">{content}</div>'
    )


def copy_button(
    *,
    to: CopyTarget,
    label: str = "Copy",
    copied_label: str = "Copied",
    variant: ButtonVariant = "ghost",
    size: ButtonSize = "sm",
) -> Template:
    """Render a button that copies an element's text to the clipboard.

    ``to`` selects the element like a ``JS`` command target does: a CSS
    selector, or a ``("closest", selector)`` or ``("inner", selector)`` pair
    relative to the button. The text comes from the element's first
    ``data-tori-ui-copy-source`` descendant, or from the element itself.
    """
    label = required_text("copy button label", label)
    copied_label = required_text("copy button copied label", copied_label)
    class_name = classes(
        _button_classes("copy button", variant, size),
        "tori-ui-copy-button",
    )
    attributes = attrs(
        {
            "type": "button",
            "class": class_name,
            # The name stays the same while the visible label reports success.
            "aria-label": label,
            "phx-click": JS().dispatch("tori-ui:copy", to=to),
            "data-tori-ui-copied-label": copied_label,
        }
    )
    idle = render_icon("copy", size="sm")
    done = render_icon("check", size="sm")
    return (
        t'<button{attributes}><span class="tori-ui-copy-button__idle">{idle}{label}'
        t'</span><span class="tori-ui-copy-button__done" aria-hidden="true">{done}'
        t'{copied_label}</span><span class="tori-ui-visually-hidden" role="status">'
        t"</span></button>"
    )


def theme_toggle(
    *,
    id: str,
    label: str = "Color theme",
    auto_label: str = "System",
    light_label: str = "Light",
    dark_label: str = "Dark",
) -> Template:
    """Let the visitor choose the color theme and remember the choice.

    The browser stores the choice and applies it to every ``UiLiveView``
    document before it paints. The page is not told about it.
    """
    id = selector_id("theme toggle id", id)
    label = required_text("theme toggle label", label)
    options = fragment(
        _theme_option(value, glyph, required_text("theme toggle option label", text))
        for value, glyph, text in (
            ("auto", "monitor", auto_label),
            ("light", "sun", light_label),
            ("dark", "moon", dark_label),
        )
    )
    return (
        t'<div id="{id}" class="tori-ui-theme-toggle" role="group" '
        t'aria-label="{label}" phx-hook="ToriUiTheme" phx-update="ignore">'
        t"{options}</div>"
    )


def _theme_option(value: str, glyph: IconName, label: str) -> Template:
    attributes = attrs(
        {
            "type": "button",
            "class": "tori-ui-theme-toggle__option",
            "data-tori-ui-theme-value": value,
            "aria-label": label,
            "title": label,
            "aria-pressed": "false",
        }
    )
    return t"<button{attributes}>{render_icon(glyph, size='sm')}</button>"


__all__ = [
    "button",
    "button_group",
    "copy_button",
    "icon_button",
    "link_button",
    "theme_toggle",
]

"""Buttons and other controls that start an action."""

from __future__ import annotations

from string.templatelib import Template

from tori_py_liveview import JS, attrs, classes

from tori_py_liveview_ui._shared import (
    BUTTON_SIZES,
    BUTTON_TYPES,
    BUTTON_VARIANTS,
    MAX_SAFE_INTEGER,
    ButtonSize,
    ButtonType,
    ButtonVariant,
    event_binding,
    one_of,
)


def button(
    label: object,
    *,
    variant: ButtonVariant = "primary",
    size: ButtonSize = "md",
    button_type: ButtonType = "button",
    disabled: bool = False,
    event: str | JS | None = None,
    target: int | None = None,
) -> Template:
    one_of("button variant", variant, BUTTON_VARIANTS)
    one_of("button size", size, BUTTON_SIZES)
    one_of("button type", button_type, BUTTON_TYPES)
    if type(disabled) is not bool:
        raise TypeError("button disabled must be a boolean")
    event = event_binding("button event", event)
    if target is not None:
        if type(target) is not int:
            raise TypeError("button target must be an integer or None")
        if not 0 < target <= MAX_SAFE_INTEGER:
            raise ValueError("button target must be a positive safe integer")
        if event is None:
            raise ValueError("button target requires an event")

    class_name = classes(
        "tori-ui-button",
        f"tori-ui-button--{variant}",
        f"tori-ui-button--{size}",
    )
    attributes = attrs(
        {
            "type": button_type,
            "class": class_name,
            "disabled": disabled,
            "phx-click": event,
            "phx-target": target,
        }
    )
    return t"<button{attributes}>{label}</button>"


__all__ = [
    "button",
]

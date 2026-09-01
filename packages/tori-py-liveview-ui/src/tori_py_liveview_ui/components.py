"""Small, composable foundation components for LiveView templates."""

from __future__ import annotations

from collections.abc import Iterable
from string.templatelib import Template

from tori_py_liveview import attrs, classes, fragment, raw

_BUTTON_VARIANTS = ("primary", "secondary", "ghost", "danger")
_BUTTON_SIZES = ("sm", "md", "lg")
_BUTTON_TYPES = ("button", "submit", "reset")
_TONES = ("neutral", "info", "success", "warning", "danger")
_GAPS = ("xs", "sm", "md", "lg", "xl")
_STACK_ALIGNS = ("start", "center", "end", "stretch")
_GRID_COLUMNS = ("auto", 1, 2, 3, 4)


def _choice(value: object, choices: tuple[object, ...], name: str) -> None:
    if value not in choices:
        raise ValueError(f"{name} must be one of {', '.join(map(str, choices))}")


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def button(
    label: object,
    *,
    variant: str = "primary",
    size: str = "md",
    button_type: str = "button",
    disabled: bool = False,
    event: str | None = None,
    target: int | None = None,
) -> Template:
    """Render an Opal event button."""
    _string(variant, "button variant")
    _choice(variant, _BUTTON_VARIANTS, "button variant")
    _string(size, "button size")
    _choice(size, _BUTTON_SIZES, "button size")
    _string(button_type, "button type")
    _choice(button_type, _BUTTON_TYPES, "button type")
    if type(disabled) is not bool:
        raise TypeError("disabled must be a boolean")
    if event is not None:
        if not isinstance(event, str):
            raise TypeError("event must be a non-empty string")
        if not event:
            raise ValueError("event must be a non-empty string")
    if target is not None:
        if type(target) is not int:
            raise TypeError("target must be a positive integer")
        if target <= 0:
            raise ValueError("target must be a positive integer")
    if target is not None and event is None:
        raise ValueError("target requires an event")

    class_name = classes(
        "tori-ui-button",
        f"tori-ui-button--{variant}",
        f"tori-ui-button--{size}",
    )
    attributes = attrs(
        {
            "class": class_name,
            "type": button_type,
            "disabled": disabled,
            "data-opal-click": event,
            "data-opal-target": target,
        }
    )
    return t"<button{attributes}>{label}</button>"


def badge(content: object, *, tone: str = "neutral") -> Template:
    """Render a compact status label."""
    _string(tone, "badge tone")
    _choice(tone, _TONES, "badge tone")
    class_name = classes("tori-ui-badge", f"tori-ui-badge--{tone}")
    return t'<span class="{class_name}">{content}</span>'


def alert(
    content: object, *, title: str | None = None, tone: str = "neutral"
) -> Template:
    """Render a semantic status message."""
    _string(tone, "alert tone")
    _choice(tone, _TONES, "alert tone")
    if title is not None:
        _string(title, "alert title")
    class_name = classes("tori-ui-alert", f"tori-ui-alert--{tone}")
    heading = (
        raw("") if title is None else t'<h2 class="tori-ui-alert__title">{title}</h2>'
    )
    role = "alert" if tone == "danger" else "status"
    attributes = attrs({"class": class_name, "role": role})
    alert_body = t'<div class="tori-ui-alert__body">{content}</div>'
    body = t'<div class="tori-ui-alert__content">{heading}{alert_body}</div>'
    return t"<section{attributes}>{body}</section>"


def card(
    content: object,
    *,
    eyebrow: str | None = None,
    title: str | None = None,
    footer: object | None = None,
) -> Template:
    """Render a framed content panel with optional slots."""
    if eyebrow is not None:
        _string(eyebrow, "card eyebrow")
    if title is not None:
        _string(title, "card title")
    header = raw("")
    if eyebrow is not None or title is not None:
        eyebrow_html = (
            raw("")
            if eyebrow is None
            else t'<p class="tori-ui-card__eyebrow">{eyebrow}</p>'
        )
        title_html = (
            raw("")
            if title is None
            else t'<h2 class="tori-ui-card__title">{title}</h2>'
        )
        header = (
            t'<header class="tori-ui-card__header">{eyebrow_html}{title_html}</header>'
        )
    footer_html = (
        raw("")
        if footer is None
        else t'<footer class="tori-ui-card__footer">{footer}</footer>'
    )
    body = t'<div class="tori-ui-card__body">{content}</div>'
    return t'<article class="tori-ui-card">{header}{body}{footer_html}</article>'


def stack(
    children: Iterable[object],
    *,
    gap: str = "md",
    align: str = "stretch",
) -> Template:
    """Render a vertical layout stack."""
    _string(gap, "stack gap")
    _choice(gap, _GAPS, "stack gap")
    _string(align, "stack align")
    _choice(align, _STACK_ALIGNS, "stack align")
    content = fragment(children)
    class_name = classes(
        "tori-ui-stack",
        f"tori-ui-stack--gap-{gap}",
        f"tori-ui-stack--align-{align}",
    )
    return t'<div class="{class_name}">{content}</div>'


def grid(
    children: Iterable[object],
    *,
    columns: str | int = "auto",
    gap: str = "md",
) -> Template:
    """Render a responsive grid layout."""
    if type(columns) is not int and columns != "auto":
        raise TypeError("grid columns must be 'auto' or an integer")
    _choice(columns, _GRID_COLUMNS, "grid columns")
    _string(gap, "grid gap")
    _choice(gap, _GAPS, "grid gap")
    content = fragment(children)
    class_name = classes(
        "tori-ui-grid",
        f"tori-ui-grid--columns-{columns}",
        f"tori-ui-grid--gap-{gap}",
    )
    return t'<div class="{class_name}">{content}</div>'


__all__ = ["alert", "badge", "button", "card", "grid", "stack"]

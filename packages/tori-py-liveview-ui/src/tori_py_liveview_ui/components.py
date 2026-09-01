from __future__ import annotations

from collections.abc import Iterable
from string.templatelib import Template
from typing import Literal

from tori_py_liveview import attrs, classes, fragment, raw

type ButtonVariant = Literal["primary", "secondary", "ghost", "danger"]
type ButtonSize = Literal["sm", "md", "lg"]
type ButtonType = Literal["button", "submit", "reset"]
type Tone = Literal["neutral", "info", "success", "warning", "danger"]
type Gap = Literal["xs", "sm", "md", "lg", "xl"]
type Alignment = Literal["start", "center", "end", "stretch"]
type Columns = Literal["auto", "1", "2", "3", "4"]

_BUTTON_VARIANTS = frozenset({"primary", "secondary", "ghost", "danger"})
_BUTTON_SIZES = frozenset({"sm", "md", "lg"})
_BUTTON_TYPES = frozenset({"button", "submit", "reset"})
_TONES = frozenset({"neutral", "info", "success", "warning", "danger"})
_GAPS = frozenset({"xs", "sm", "md", "lg", "xl"})
_ALIGNMENTS = frozenset({"start", "center", "end", "stretch"})
_COLUMNS = frozenset({"auto", "1", "2", "3", "4"})
_MAX_SAFE_INTEGER = 2**53 - 1


def _closed(name: str, value: str, allowed: frozenset[str]) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{name} must be one of: {choices}")
    return value


def _optional_text(name: str, value: str | None) -> str | None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{name} must be a string or None")
    return value


def button(
    label: object,
    *,
    variant: ButtonVariant = "primary",
    size: ButtonSize = "md",
    button_type: ButtonType = "button",
    disabled: bool = False,
    event: str | None = None,
    target: int | None = None,
) -> Template:
    _closed("button variant", variant, _BUTTON_VARIANTS)
    _closed("button size", size, _BUTTON_SIZES)
    _closed("button type", button_type, _BUTTON_TYPES)
    if type(disabled) is not bool:
        raise TypeError("button disabled must be a boolean")
    if event is not None:
        if not isinstance(event, str):
            raise TypeError("button event must be a string or None")
        if not event:
            raise ValueError("button event cannot be empty")
    if target is not None:
        if type(target) is not int:
            raise TypeError("button target must be an integer or None")
        if not 0 < target <= _MAX_SAFE_INTEGER:
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


def badge(content: object, *, tone: Tone = "neutral") -> Template:
    _closed("badge tone", tone, _TONES)
    class_name = classes("tori-ui-badge", f"tori-ui-badge--{tone}")
    return t'<span class="{class_name}">{content}</span>'


def alert(
    content: object,
    *,
    title: str | None = None,
    tone: Tone = "neutral",
) -> Template:
    title = _optional_text("alert title", title)
    _closed("alert tone", tone, _TONES)
    class_name = classes("tori-ui-alert", f"tori-ui-alert--{tone}")
    role = "alert" if tone == "danger" else "status"
    title_markup = (
        t'<h2 class="tori-ui-alert__title">{title}</h2>'
        if title is not None
        else raw("")
    )
    return (
        t'<section class="{class_name}" role="{role}">'
        t'<div class="tori-ui-alert__content">{title_markup}'
        t'<div class="tori-ui-alert__body">{content}</div></div></section>'
    )


def card(
    content: object,
    *,
    eyebrow: str | None = None,
    title: str | None = None,
    footer: object | None = None,
) -> Template:
    eyebrow = _optional_text("card eyebrow", eyebrow)
    title = _optional_text("card title", title)
    eyebrow_markup = (
        t'<p class="tori-ui-card__eyebrow">{eyebrow}</p>'
        if eyebrow is not None
        else raw("")
    )
    title_markup = (
        t'<h2 class="tori-ui-card__title">{title}</h2>'
        if title is not None
        else raw("")
    )
    header_markup = (
        t'<header class="tori-ui-card__header">{eyebrow_markup}{title_markup}</header>'
        if eyebrow is not None or title is not None
        else raw("")
    )
    footer_markup = (
        t'<footer class="tori-ui-card__footer">{footer}</footer>'
        if footer is not None
        else raw("")
    )
    return (
        t'<article class="tori-ui-card">{header_markup}'
        t'<div class="tori-ui-card__body">{content}</div>'
        t"{footer_markup}</article>"
    )


def stack(
    children: Iterable[object],
    *,
    gap: Gap = "md",
    align: Alignment = "stretch",
) -> Template:
    _closed("stack gap", gap, _GAPS)
    _closed("stack alignment", align, _ALIGNMENTS)
    class_name = classes(
        "tori-ui-stack",
        f"tori-ui-stack--gap-{gap}",
        f"tori-ui-stack--align-{align}",
    )
    content = fragment(children)
    return t'<div class="{class_name}">{content}</div>'


def grid(
    children: Iterable[object],
    *,
    columns: Columns = "auto",
    gap: Gap = "md",
) -> Template:
    _closed("grid columns", columns, _COLUMNS)
    _closed("grid gap", gap, _GAPS)
    class_name = classes(
        "tori-ui-grid",
        f"tori-ui-grid--columns-{columns}",
        f"tori-ui-grid--gap-{gap}",
    )
    content = fragment(children)
    return t'<div class="{class_name}">{content}</div>'


__all__ = ["alert", "badge", "button", "card", "grid", "stack"]

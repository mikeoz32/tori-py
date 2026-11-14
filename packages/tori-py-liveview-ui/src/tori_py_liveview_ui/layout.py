"""Helpers that arrange content."""

from __future__ import annotations

from collections.abc import Iterable
from string.templatelib import Template

from tori_py_liveview import classes, fragment, raw

from tori_py_liveview_ui._shared import (
    ALIGNMENTS,
    COLUMNS,
    GAPS,
    Alignment,
    Columns,
    Gap,
    one_of,
    optional_text,
)


def card(
    content: object,
    *,
    eyebrow: str | None = None,
    title: str | None = None,
    footer: object | None = None,
) -> Template:
    eyebrow = optional_text("card eyebrow", eyebrow)
    title = optional_text("card title", title)
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
    one_of("stack gap", gap, GAPS)
    one_of("stack alignment", align, ALIGNMENTS)
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
    one_of("grid columns", columns, COLUMNS)
    one_of("grid gap", gap, GAPS)
    class_name = classes(
        "tori-ui-grid",
        f"tori-ui-grid--columns-{columns}",
        f"tori-ui-grid--gap-{gap}",
    )
    content = fragment(children)
    return t'<div class="{class_name}">{content}</div>'


__all__ = [
    "card",
    "grid",
    "stack",
]

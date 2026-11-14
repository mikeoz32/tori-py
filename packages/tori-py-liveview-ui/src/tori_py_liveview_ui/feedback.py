"""Helpers that report status and progress."""

from __future__ import annotations

from string.templatelib import Template

from tori_py_liveview import classes, raw

from tori_py_liveview_ui._shared import TONES, Tone, one_of, optional_text


def alert(
    content: object,
    *,
    title: str | None = None,
    tone: Tone = "neutral",
) -> Template:
    title = optional_text("alert title", title)
    one_of("alert tone", tone, TONES)
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


__all__ = [
    "alert",
]

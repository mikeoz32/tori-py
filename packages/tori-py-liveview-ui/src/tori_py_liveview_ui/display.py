"""Helpers that present data."""

from __future__ import annotations

from string.templatelib import Template

from tori_py_liveview import classes

from tori_py_liveview_ui._shared import TONES, Tone, one_of


def badge(content: object, *, tone: Tone = "neutral") -> Template:
    one_of("badge tone", tone, TONES)
    class_name = classes("tori-ui-badge", f"tori-ui-badge--{tone}")
    return t'<span class="{class_name}">{content}</span>'


__all__ = [
    "badge",
]

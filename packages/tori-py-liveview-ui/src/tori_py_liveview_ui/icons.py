"""A closed set of inline SVG icons.

Every icon is drawn on a 24 by 24 grid with a 2 unit round stroke in the
current text color. The markup is fixed package text, never caller input.
"""

from __future__ import annotations

import re
from string.templatelib import Template
from typing import Literal

from tori_py_liveview import attrs, classes, raw

from tori_py_liveview_ui._shared import Size, optional_nonempty_text

type IconName = Literal[
    "alert-circle",
    "alert-triangle",
    "arrow-down",
    "arrow-left",
    "arrow-right",
    "arrow-up",
    "bell",
    "bookmark",
    "bot",
    "calendar",
    "chart",
    "check",
    "check-circle",
    "chevron-down",
    "chevron-left",
    "chevron-right",
    "chevron-up",
    "chevrons-up-down",
    "circle",
    "circle-dot",
    "clock",
    "code",
    "copy",
    "database",
    "download",
    "edit",
    "external-link",
    "eye",
    "eye-off",
    "file",
    "filter",
    "folder",
    "globe",
    "heart",
    "help-circle",
    "home",
    "image",
    "info",
    "lightbulb",
    "link",
    "lock",
    "log-out",
    "mail",
    "maximize",
    "menu",
    "message",
    "mic",
    "minus",
    "monitor",
    "moon",
    "more-horizontal",
    "more-vertical",
    "paperclip",
    "pause",
    "play",
    "plus",
    "refresh",
    "search",
    "send",
    "settings",
    "shield",
    "sidebar",
    "sparkles",
    "star",
    "stop",
    "sun",
    "tag",
    "terminal",
    "thumbs-down",
    "thumbs-up",
    "tool",
    "trash",
    "upload",
    "user",
    "users",
    "x",
    "x-circle",
    "zap",
]

_ICONS: dict[str, str] = {
    "alert-circle": (
        '<circle cx="12" cy="12" r="9"/><path d="M12 7v6"/><path d="M12 16.5v.01"/>'
    ),
    "alert-triangle": (
        '<path d="M12 3.5 2.5 20h19z"/><path d="M12 10v4.5"/><path d="M12 17.2v.01"/>'
    ),
    "arrow-down": '<path d="M12 5v14"/><path d="m6 13 6 6 6-6"/>',
    "arrow-left": '<path d="M19 12H5"/><path d="m11 6-6 6 6 6"/>',
    "arrow-right": '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    "arrow-up": '<path d="M12 19V5"/><path d="m6 11 6-6 6 6"/>',
    "bell": '<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l2 2H4z"/><path d="M10 21h4"/>',
    "bookmark": '<path d="M6 3.5h12a1 1 0 0 1 1 1V21l-7-4.5L5 21V4.5a1 1 0 0 1 1-1z"/>',
    "bot": (
        '<rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 8V4.5"/>'
        '<circle cx="12" cy="3.5" r="1"/><path d="M9 13v2"/><path d="M15 13v2"/>'
        '<path d="M2 13v3"/><path d="M22 13v3"/>'
    ),
    "calendar": (
        '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/>'
        '<path d="M3.5 10h17"/><path d="M8 3v4"/><path d="M16 3v4"/>'
    ),
    "chart": (
        '<path d="M4 4v16h16"/><path d="M8 16v-4"/><path d="M12 16V8"/>'
        '<path d="M16 16v-6"/>'
    ),
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "check-circle": '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 3 3 5-6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-left": '<path d="m15 6-6 6 6 6"/>',
    "chevron-right": '<path d="m9 6 6 6-6 6"/>',
    "chevron-up": '<path d="m6 15 6-6 6 6"/>',
    "chevrons-up-down": '<path d="m8 9 4-4 4 4"/><path d="m8 15 4 4 4-4"/>',
    "circle": '<circle cx="12" cy="12" r="9"/>',
    "circle-dot": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
    "code": '<path d="m8 7-5 5 5 5"/><path d="m16 7 5 5-5 5"/><path d="m13.5 4-3 16"/>',
    "copy": (
        '<rect x="9" y="9" width="11" height="11" rx="2"/>'
        '<path d="M5 15V6a2 2 0 0 1 2-2h9"/>'
    ),
    "database": (
        '<ellipse cx="12" cy="6" rx="8" ry="3"/>'
        '<path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/>'
        '<path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>'
    ),
    "download": ('<path d="M12 4v11"/><path d="m7 10.5 5 5 5-5"/><path d="M5 20h14"/>'),
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13 7 4 4"/>',
    "external-link": (
        '<path d="M14 4h6v6"/><path d="M20 4 10 14"/>'
        '<path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>'
    ),
    "eye": (
        '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 '
        '2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>'
    ),
    "eye-off": (
        '<path d="m4 4 16 16"/>'
        '<path d="M10 5.7a9 9 0 0 1 2-.2c6 0 9.5 6.5 9.5 6.5a15 15 0 0 1-2.8 3.6"/>'
        '<path d="M6.2 7.3A15 15 0 0 0 2.5 12S6 18.5 12 18.5a9 9 0 0 0 4-1"/>'
    ),
    "file": (
        '<path d="M6 3h8l5 5v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/>'
        '<path d="M14 3v5h5"/>'
    ),
    "filter": '<path d="M4 5h16l-6 7.5V19l-4-2v-4.5z"/>',
    "folder": (
        '<path d="M3 6a1 1 0 0 1 1-1h5l2 2.5h9a1 1 0 0 1 1 1V18a1 1 0 0 1-1 1H4a1 '
        '1 0 0 1-1-1z"/>'
    ),
    "globe": (
        '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/>'
        '<path d="M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8'
        '-9S9.5 5.6 12 3z"/>'
    ),
    "heart": (
        '<path d="M12 20.5s-8-4.9-8-10.8a4.6 4.6 0 0 1 8-3.1 4.6 4.6 0 0 1 8 '
        '3.1c0 5.9-8 10.8-8 10.8z"/>'
    ),
    "help-circle": (
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7"/>'
        '<path d="M12 17v.01"/>'
    ),
    "home": (
        '<path d="m3 11 9-7.5 9 7.5"/><path d="M5.5 9.5V20h13V9.5"/>'
        '<path d="M10 20v-6h4v6"/>'
    ),
    "image": (
        '<rect x="3" y="4" width="18" height="16" rx="2"/>'
        '<circle cx="8.5" cy="9.5" r="1.5"/><path d="m21 15-4.5-4.5L7 20"/>'
    ),
    "info": (
        '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7.5v.01"/>'
    ),
    "lightbulb": (
        '<path d="M10 21h4"/>'
        '<path d="M8.5 14.5a6 6 0 1 1 7 0c-.6.5-1 1.2-1 2V18h-5v-1.5c0-.8-.4'
        '-1.5-1-2z"/>'
    ),
    "link": (
        '<path d="M10 14a4.5 4.5 0 0 0 6.4 0l3-3A4.5 4.5 0 0 0 13 4.6l-1.2 1.2"/>'
        '<path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1.2-1.2"/>'
    ),
    "lock": (
        '<rect x="5" y="11" width="14" height="10" rx="2"/>'
        '<path d="M8 11V7.5a4 4 0 0 1 8 0V11"/>'
    ),
    "log-out": (
        '<path d="M10 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h5"/><path d="m15 8 4 4-4 4"/>'
        '<path d="M19 12H9"/>'
    ),
    "mail": (
        '<rect x="3" y="5" width="18" height="14" rx="2"/>'
        '<path d="m3.5 7 8.5 6 8.5-6"/>'
    ),
    "maximize": (
        '<path d="M4 9V4h5"/><path d="M20 9V4h-5"/><path d="M4 15v5h5"/>'
        '<path d="M20 15v5h-5"/>'
    ),
    "menu": '<path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h16"/>',
    "message": (
        '<path d="M4 5h16a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1h-8l-5 4v-4H4a1 1 0 0 1-1-1V6'
        'a1 1 0 0 1 1-1z"/>'
    ),
    "mic": (
        '<rect x="9" y="3" width="6" height="11" rx="3"/>'
        '<path d="M5.5 11.5a6.5 6.5 0 0 0 13 0"/><path d="M12 18v3"/>'
    ),
    "minus": '<path d="M5 12h14"/>',
    "monitor": (
        '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20.5h8"/>'
        '<path d="M12 16v4.5"/>'
    ),
    "moon": '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z"/>',
    "more-horizontal": (
        '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/>'
        '<circle cx="19" cy="12" r="1"/>'
    ),
    "more-vertical": (
        '<circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/>'
        '<circle cx="12" cy="19" r="1"/>'
    ),
    "paperclip": (
        '<path d="m20 11.5-8.3 8.3a5 5 0 0 1-7-7l8.4-8.4a3.3 3.3 0 0 1 4.7 '
        '4.7l-8.4 8.4a1.7 1.7 0 0 1-2.4-2.4l7.7-7.7"/>'
    ),
    "pause": '<path d="M8 5v14"/><path d="M16 5v14"/>',
    "play": '<path d="M7 4.5v15l12-7.5z"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "refresh": '<path d="M20 12a8 8 0 1 1-2.6-5.9"/><path d="M20 4v4.5h-4.5"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
    "send": '<path d="M21 3 10 14"/><path d="m21 3-7 18-4-7-7-4z"/>',
    "settings": (
        '<path d="M4 7h10"/><path d="M18 7h2"/><circle cx="16" cy="7" r="2"/>'
        '<path d="M4 17h2"/><path d="M10 17h10"/><circle cx="8" cy="17" r="2"/>'
    ),
    "shield": (
        '<path d="M12 3 4.5 6v5.5c0 4.5 3 8 7.5 9.5 4.5-1.5 7.5-5 7.5-9.5V6z"/>'
    ),
    "sidebar": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    "sparkles": (
        '<path d="M10 3.5 11.8 9l5.7 1.8-5.7 1.8L10 18l-1.8-5.4-5.7-1.8L8.2 9z"/>'
        '<path d="M18.5 3v4"/><path d="M16.5 5h4"/><path d="M19 16v4"/>'
        '<path d="M17 18h4"/>'
    ),
    "star": (
        '<path d="m12 3 2.7 5.8 6.3.8-4.6 4.4 1.2 6.3L12 17.2l-5.6 3.1 1.2-6.3'
        'L3 9.6l6.3-.8z"/>'
    ),
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
    "sun": (
        '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2"/><path d="M12 19.5v2"/>'
        '<path d="M2.5 12h2"/><path d="M19.5 12h2"/><path d="m5.3 5.3 1.4 1.4"/>'
        '<path d="m17.3 17.3 1.4 1.4"/><path d="m5.3 18.7 1.4-1.4"/>'
        '<path d="m17.3 6.7 1.4-1.4"/>'
    ),
    "tag": (
        '<path d="M3.5 4.5a1 1 0 0 1 1-1H12l8.5 8.5a1.4 1.4 0 0 1 0 2L14 20.5a1.4 '
        '1.4 0 0 1-2 0L3.5 12z"/><circle cx="8" cy="8" r="1.3"/>'
    ),
    "terminal": (
        '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3"/>'
        '<path d="M12.5 15H17"/>'
    ),
    "thumbs-down": (
        '<path d="M7 13.5v-10H4.5a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1z"/>'
        '<path d="m7 13.5 4 7a2.3 2.3 0 0 0 3-2.8l-1-4.2h6a2 2 0 0 0 2-2.4l-1.3-6'
        'a2 2 0 0 0-2-1.6H7"/>'
    ),
    "thumbs-up": (
        '<path d="M7 10.5v10H4.5a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1z"/>'
        '<path d="m7 10.5 4-7a2.3 2.3 0 0 1 3 2.8l-1 4.2h6a2 2 0 0 1 2 2.4l-1.3 6'
        'a2 2 0 0 1-2 1.6H7"/>'
    ),
    "tool": (
        '<path d="M20.5 7.5a5 5 0 0 1-6.8 4.7L7 19a2.1 2.1 0 0 1-3-3l6.8-6.7a5 5 '
        '0 0 1 5.7-5.8l-3 3 .7 3.3 3.3.7z"/>'
    ),
    "trash": (
        '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="m6 7 1 13h10l1-13"/>'
        '<path d="M10 11v5"/><path d="M14 11v5"/>'
    ),
    "upload": '<path d="M12 16V5"/><path d="m7 9.5 5-5 5 5"/><path d="M5 20h14"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 20.5a8 8 0 0 1 16 0"/>',
    "users": (
        '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/>'
        '<path d="M16 4.6a3.5 3.5 0 0 1 0 6.8"/>'
        '<path d="M18 14.2a6.5 6.5 0 0 1 3.5 5.8"/>'
    ),
    "x": '<path d="m6 6 12 12"/><path d="m18 6-12 12"/>',
    "x-circle": (
        '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6"/><path d="m15 9-6 6"/>'
    ),
    "zap": '<path d="M13 2.5 4.5 13.5H12l-1 8 8.5-11H12z"/>',
}

ICON_NAMES = frozenset(_ICONS)
# The drawings above use the short form for readability. In the page every
# shape has an explicit end tag, as LiveView requires of stream items.
_SHAPES = {
    name: re.sub(r"<([a-z]+)([^>]*?)/>", r"<\1\2></\1>", shapes)
    for name, shapes in _ICONS.items()
}


def icon(
    name: IconName,
    *,
    size: Size = "md",
    label: str | None = None,
) -> Template:
    """Render one of the bundled icons.

    An icon without a ``label`` is decorative and hidden from assistive
    technology. Give a ``label`` only when the icon is the sole content that
    names its control or meaning.
    """
    label = optional_nonempty_text("icon label", label)
    attributes = attrs(
        {
            "class": classes("tori-ui-icon", f"tori-ui-icon--{size}"),
            "viewBox": "0 0 24 24",
            "fill": "none",
            "stroke": "currentColor",
            "stroke-width": "2",
            "stroke-linecap": "round",
            "stroke-linejoin": "round",
            "focusable": "false",
            "role": "img" if label is not None else None,
            "aria-label": label,
            "aria-hidden": "true" if label is None else None,
        }
    )
    shapes = raw(_SHAPES[name])
    return t"<svg{attributes}>{shapes}</svg>"


__all__ = ["icon"]

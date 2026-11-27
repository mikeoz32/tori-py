"""Helpers that show and hide content in place."""

from __future__ import annotations

import re
from collections.abc import Iterable
from string.templatelib import Template

from tori_py_liveview import JS, attrs, classes, fragment

from tori_py_liveview_ui._shared import (
    event_binding,
    event_target,
    html_id,
    optional_nonempty_text,
    required_text,
    selector_id,
)
from tori_py_liveview_ui.icons import icon

_TAB_KEY = re.compile(r"[A-Za-z0-9_-]+")
_PANEL_HIDDEN = "tori-ui-tabs__panel--hidden"
# The visitor's open or closed choice outlives the server's renders.
_KEEP_OPEN = JS().ignore_attributes(["open"])


def collapsible(
    summary: object,
    content: object,
    *,
    open: bool = False,
    id: str | None = None,
    group: str | None = None,
) -> Template:
    """Render a native disclosure the visitor opens and closes.

    ``open`` is only the state the section starts in: afterwards the browser
    owns it. Sections that share a ``group`` name close each other.
    """
    if id is not None:
        id = html_id("collapsible id", id)
    group = optional_nonempty_text("collapsible group", group)
    attributes = attrs(
        {
            "id": id,
            "class": "tori-ui-collapsible",
            "open": open,
            "name": group,
            "phx-mounted": _KEEP_OPEN,
        }
    )
    return (
        t'<details{attributes}><summary class="tori-ui-collapsible__summary">'
        t'<span class="tori-ui-collapsible__label">{summary}</span>'
        t"{icon('chevron-down', size='sm')}</summary>"
        t'<div class="tori-ui-collapsible__content">{content}</div></details>'
    )


def accordion(children: Iterable[object]) -> Template:
    """Join ``collapsible()`` sections into one bordered list."""
    return t'<div class="tori-ui-accordion">{fragment(children)}</div>'


def tabs(
    items: Iterable[tuple[str, object, object]],
    *,
    id: str,
    label: str,
    active: str | None = None,
    event: str | JS | None = None,
    target: int | None = None,
) -> Template:
    """Render a tab list with its panels.

    Each item is ``(key, tab label, panel content)``. Without ``event`` every
    panel is rendered and the browser switches between them, starting at
    ``active``. With ``event`` the page owns the choice: a tab pushes the
    event with its key as ``tab``, and only the ``active`` panel is rendered.
    """
    id = selector_id("tabs id", id)
    label = required_text("tabs label", label)
    event = event_binding("tabs event", event)
    target = event_target("tabs target", target, event)
    entries: list[tuple[str, object, object]] = []
    for item in items:
        key = item[0]
        if _TAB_KEY.fullmatch(key) is None:
            raise ValueError("tabs keys must match [A-Za-z0-9_-]+")
        entries.append((key, item[1], item[2]))
    keys = [key for key, _, _ in entries]
    if not keys:
        raise ValueError("tabs requires at least one item")
    if len(set(keys)) != len(keys):
        raise ValueError("tabs keys must be unique")
    if active is None:
        active = keys[0]
    elif active not in keys:
        raise ValueError("tabs active must be one of the item keys")
    all_tabs = f"#{id}-tabs > [role=tab]"
    all_panels = f"#{id} > [role=tabpanel]"
    buttons: list[Template] = []
    panels: list[Template] = []
    for key, tab_label, content in entries:
        selected = key == active
        if event is None:
            click: str | JS = (
                JS()
                .set_attribute("aria-selected", "false", to=all_tabs)
                .set_attribute("tabindex", "-1", to=all_tabs)
                .set_attribute("aria-selected", "true")
                .set_attribute("tabindex", "0")
                .add_class(_PANEL_HIDDEN, to=all_panels)
                .remove_class(_PANEL_HIDDEN, to=f"#{id}-panel-{key}")
            )
        else:
            click = event
        button = attrs(
            {
                "type": "button",
                "role": "tab",
                "id": f"{id}-tab-{key}",
                "class": "tori-ui-tabs__tab",
                "aria-selected": str(selected).lower(),
                "aria-controls": (
                    f"{id}-panel-{key}" if event is None or selected else None
                ),
                "tabindex": "0" if selected else "-1",
                "phx-click": click,
                "phx-target": target,
                "phx-value-tab": key if event is not None else None,
            }
        )
        buttons.append(t"<button{button}>{tab_label}</button>")
        if event is None or selected:
            panel = attrs(
                {
                    "role": "tabpanel",
                    "id": f"{id}-panel-{key}",
                    "class": classes(
                        "tori-ui-tabs__panel",
                        **{_PANEL_HIDDEN: not selected},
                    ),
                    "aria-labelledby": f"{id}-tab-{key}",
                    "tabindex": "0",
                }
            )
            panels.append(t"<div{panel}>{content}</div>")
    return (
        t'<tori-ui-tabs id="{id}" class="tori-ui-tabs"><div id="{id}-tabs" '
        t'class="tori-ui-tabs__list" role="tablist" aria-label="{label}">'
        t"{fragment(buttons)}</div>{fragment(panels)}</tori-ui-tabs>"
    )


__all__ = ["accordion", "collapsible", "tabs"]

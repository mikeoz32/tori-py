"""Helpers that arrange content."""

from __future__ import annotations

from collections.abc import Iterable
from string.templatelib import Template
from typing import Literal

from tori_py_liveview import JS, attrs, classes, fragment, raw

from tori_py_liveview_ui._shared import (
    Alignment,
    Columns,
    Gap,
    Justify,
    html_id,
    optional_nonempty_text,
    required_text,
    selector_id,
)
from tori_py_liveview_ui.icons import icon

type RowAlignment = Literal["start", "center", "end", "stretch", "baseline"]
type ContainerSize = Literal["sm", "md", "lg", "xl", "full"]
type CenterHeight = Literal["content", "half", "screen"]
type Orientation = Literal["horizontal", "vertical"]
type SpacerSize = Literal["grow", "xs", "sm", "md", "lg", "xl"]
type SplitRatio = Literal["1:1", "1:2", "2:1", "1:3", "3:1"]
type ScrollHeight = Literal["sm", "md", "lg", "xl"]

_SIDEBAR_OPEN = "tori-ui-app-shell--sidebar-open"


def card(
    content: object,
    *,
    eyebrow: str | None = None,
    title: str | None = None,
    footer: object | None = None,
) -> Template:
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
    class_name = classes(
        "tori-ui-grid",
        f"tori-ui-grid--columns-{columns}",
        f"tori-ui-grid--gap-{gap}",
    )
    content = fragment(children)
    return t'<div class="{class_name}">{content}</div>'


def row(
    children: Iterable[object],
    *,
    gap: Gap = "md",
    align: RowAlignment = "center",
    justify: Justify = "start",
    wrap: bool = True,
) -> Template:
    """Lay children out in a horizontal line that wraps by default."""
    class_name = classes(
        "tori-ui-row",
        f"tori-ui-row--gap-{gap}",
        f"tori-ui-row--align-{align}",
        f"tori-ui-row--justify-{justify}",
        **{"tori-ui-row--nowrap": not wrap},
    )
    content = fragment(children)
    return t'<div class="{class_name}">{content}</div>'


def container(
    content: object,
    *,
    size: ContainerSize = "lg",
    padded: bool = True,
) -> Template:
    """Center content in a column of bounded width."""
    class_name = classes(
        "tori-ui-container",
        f"tori-ui-container--{size}",
        **{"tori-ui-container--padded": padded},
    )
    return t'<div class="{class_name}">{content}</div>'


def center(content: object, *, min_height: CenterHeight = "content") -> Template:
    """Center content on both axes."""
    class_name = classes("tori-ui-center", f"tori-ui-center--{min_height}")
    return t'<div class="{class_name}">{content}</div>'


def divider(
    *,
    label: str | None = None,
    orientation: Orientation = "horizontal",
) -> Template:
    """Separate content with a rule, optionally labeled."""
    label = optional_nonempty_text("divider label", label)
    if orientation == "vertical":
        if label is not None:
            raise ValueError("divider label requires the horizontal orientation")
        return (
            t'<div class="tori-ui-divider tori-ui-divider--vertical" '
            t'role="separator" aria-orientation="vertical"></div>'
        )
    if label is None:
        return t'<hr class="tori-ui-divider">'
    return (
        t'<div class="tori-ui-divider tori-ui-divider--labeled" role="separator">'
        t'<span class="tori-ui-divider__label">{label}</span></div>'
    )


def spacer(*, size: SpacerSize = "grow") -> Template:
    """Take up space between siblings of a row or a stack."""
    class_name = classes("tori-ui-spacer", f"tori-ui-spacer--{size}")
    return t'<span class="{class_name}" aria-hidden="true"></span>'


def section(
    content: object,
    *,
    title: str,
    description: str | None = None,
    actions: object | None = None,
    id: str | None = None,
) -> Template:
    """Group content under a second-level heading."""
    title = required_text("section title", title)
    description = optional_nonempty_text("section description", description)
    if id is not None:
        id = html_id("section id", id)
    title_id = None if id is None else f"{id}-title"
    attributes = attrs(
        {"id": id, "class": "tori-ui-section", "aria-labelledby": title_id}
    )
    title_attributes = attrs({"id": title_id, "class": "tori-ui-section__title"})
    description_markup = (
        t'<p class="tori-ui-section__description">{description}</p>'
        if description is not None
        else raw("")
    )
    actions_markup = (
        t'<div class="tori-ui-section__actions">{actions}</div>'
        if actions is not None
        else raw("")
    )
    return (
        t'<section{attributes}><header class="tori-ui-section__header">'
        t'<div class="tori-ui-section__heading"><h2{title_attributes}>{title}</h2>'
        t"{description_markup}</div>{actions_markup}</header>"
        t'<div class="tori-ui-section__body">{content}</div></section>'
    )


def page_header(
    title: str,
    *,
    eyebrow: str | None = None,
    description: str | None = None,
    actions: object | None = None,
    navigation: object | None = None,
) -> Template:
    """Open a page with its first-level heading, context, and primary actions."""
    title = required_text("page header title", title)
    eyebrow = optional_nonempty_text("page header eyebrow", eyebrow)
    description = optional_nonempty_text("page header description", description)
    navigation_markup = (
        t'<div class="tori-ui-page-header__navigation">{navigation}</div>'
        if navigation is not None
        else raw("")
    )
    eyebrow_markup = (
        t'<p class="tori-ui-page-header__eyebrow">{eyebrow}</p>'
        if eyebrow is not None
        else raw("")
    )
    description_markup = (
        t'<p class="tori-ui-page-header__description">{description}</p>'
        if description is not None
        else raw("")
    )
    actions_markup = (
        t'<div class="tori-ui-page-header__actions">{actions}</div>'
        if actions is not None
        else raw("")
    )
    return (
        t'<header class="tori-ui-page-header">{navigation_markup}'
        t'<div class="tori-ui-page-header__row">'
        t'<div class="tori-ui-page-header__heading">{eyebrow_markup}'
        t'<h1 class="tori-ui-page-header__title">{title}</h1>{description_markup}'
        t"</div>{actions_markup}</div></header>"
    )


def toolbar(
    start: Iterable[object],
    *,
    label: str,
    end: Iterable[object] = (),
) -> Template:
    """Line up controls, with an optional group pushed to the far end."""
    label = required_text("toolbar label", label)
    start_content = fragment(start)
    end_items = tuple(end)
    end_markup = (
        t'<div class="tori-ui-toolbar__group tori-ui-toolbar__group--end">'
        t"{fragment(end_items)}</div>"
        if end_items
        else raw("")
    )
    return (
        t'<div class="tori-ui-toolbar" role="group" aria-label="{label}">'
        t'<div class="tori-ui-toolbar__group">{start_content}</div>'
        t"{end_markup}</div>"
    )


def split(
    primary: object,
    secondary: object,
    *,
    ratio: SplitRatio = "1:1",
    gap: Gap = "lg",
) -> Template:
    """Place two panes side by side; they stack on narrow screens."""
    class_name = classes(
        "tori-ui-split",
        f"tori-ui-split--{ratio.replace(':', '-')}",
        f"tori-ui-split--gap-{gap}",
    )
    return (
        t'<div class="{class_name}"><div class="tori-ui-split__pane">{primary}</div>'
        t'<div class="tori-ui-split__pane">{secondary}</div></div>'
    )


def scroll_area(
    content: object,
    *,
    label: str,
    max_height: ScrollHeight = "md",
) -> Template:
    """Bound tall content in a labeled region that scrolls from the keyboard."""
    label = required_text("scroll area label", label)
    class_name = classes("tori-ui-scroll-area", f"tori-ui-scroll-area--{max_height}")
    return (
        t'<div class="{class_name}" role="region" aria-label="{label}" tabindex="0">'
        t"{content}</div>"
    )


def app_shell(
    content: object,
    *,
    id: str,
    header: object | None = None,
    sidebar: object | None = None,
    aside: object | None = None,
    footer: object | None = None,
    sidebar_label: str = "Sidebar",
    menu_label: str = "Menu",
) -> Template:
    """Fill the viewport with a header, a sidebar, and a scrolling main area.

    The shell renders the page's main landmark with the ID ``<id>-main``, the
    target for a ``skip_link()``. On narrow screens the sidebar
    leaves the layout and a menu button in the header opens it over the
    content; the browser keeps that open state.
    """
    id = selector_id("app shell id", id)
    sidebar_label = required_text("app shell sidebar label", sidebar_label)
    menu_label = required_text("app shell menu label", menu_label)
    sidebar_id = f"{id}-sidebar"
    close = (
        JS()
        .remove_class(_SIDEBAR_OPEN, to=f"#{id}")
        .set_attribute("aria-expanded", "false", to=f"#{id} .tori-ui-app-shell__menu")
    )
    attributes = attrs(
        {
            "id": id,
            "class": "tori-ui-app-shell",
            "phx-window-keydown": close if sidebar is not None else None,
            "phx-key": "Escape" if sidebar is not None else None,
        }
    )
    menu_markup: object = raw("")
    sidebar_markup: object = raw("")
    if sidebar is not None:
        toggle = (
            JS()
            .toggle_class(_SIDEBAR_OPEN, to=f"#{id}")
            .toggle_attribute("aria-expanded", "true", "false")
        )
        menu_attributes = attrs(
            {
                "type": "button",
                "class": "tori-ui-app-shell__menu",
                "aria-label": menu_label,
                "aria-controls": sidebar_id,
                "aria-expanded": "false",
                "phx-click": toggle,
            }
        )
        menu_markup = t"<button{menu_attributes}>{icon('menu')}</button>"
        sidebar_markup = (
            t'<aside id="{sidebar_id}" class="tori-ui-app-shell__sidebar" '
            t'aria-label="{sidebar_label}">{sidebar}</aside>'
            t'<div class="tori-ui-app-shell__scrim" phx-click="{close}"></div>'
        )
    header_content = header if header is not None else raw("")
    header_markup = (
        t'<header class="tori-ui-app-shell__header">{menu_markup}'
        t'<div class="tori-ui-app-shell__header-content">{header_content}</div>'
        t"</header>"
        if header is not None or sidebar is not None
        else raw("")
    )
    aside_markup = (
        t'<aside class="tori-ui-app-shell__aside">{aside}</aside>'
        if aside is not None
        else raw("")
    )
    footer_markup = (
        t'<footer class="tori-ui-app-shell__footer">{footer}</footer>'
        if footer is not None
        else raw("")
    )
    return (
        t"<div{attributes}>{header_markup}{sidebar_markup}"
        t'<main id="{id}-main" class="tori-ui-app-shell__main" tabindex="-1">'
        t"{content}</main>"
        t"{aside_markup}{footer_markup}</div>"
    )


__all__ = [
    "app_shell",
    "card",
    "center",
    "container",
    "divider",
    "grid",
    "page_header",
    "row",
    "scroll_area",
    "section",
    "spacer",
    "split",
    "stack",
    "toolbar",
]

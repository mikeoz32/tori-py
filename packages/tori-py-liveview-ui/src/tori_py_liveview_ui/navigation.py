"""Helpers that move the visitor between pages and positions."""

from __future__ import annotations

from collections.abc import Iterable
from string.templatelib import Template
from typing import Literal

from tori_py_liveview import JS, attrs, classes, fragment, raw

from tori_py_liveview_ui._shared import (
    LiveLink,
    boolean,
    bounded_integer,
    event_binding,
    event_target,
    link_attributes,
    one_of,
    optional_nonempty_text,
    required_text,
)
from tori_py_liveview_ui.icons import IconName, icon_name
from tori_py_liveview_ui.icons import icon as render_icon

type NavOrientation = Literal["vertical", "horizontal"]

_NAV_ORIENTATIONS = frozenset({"vertical", "horizontal"})
_PAGE_PLACEHOLDER = "{page}"


def skip_link(*, href: str = "#main", label: str = "Skip to content") -> Template:
    """Let keyboard users jump past repeated navigation.

    Render it first in the page. It is invisible until it receives focus, and
    ``href`` is the fragment of the main content, such as the ``<id>-main``
    that ``app_shell()`` gives its main area.
    """
    href = required_text("skip link href", href)
    if not href.startswith("#") or len(href) < 2:
        raise ValueError("skip link href must be a fragment such as #main")
    label = required_text("skip link label", label)
    attributes = attrs({"class": "tori-ui-skip-link", "href": href})
    return t"<a{attributes}>{label}</a>"


def navbar(
    *,
    brand: object,
    items: object | None = None,
    actions: object | None = None,
    label: str = "Main",
) -> Template:
    """Render a horizontal bar with a brand, navigation, and actions.

    ``items`` is usually ``nav_item()`` entries; they are wrapped in a list.
    ``actions`` sits at the far end.
    """
    label = required_text("navbar label", label)
    items_markup = (
        t'<ul class="tori-ui-nav tori-ui-nav--horizontal">{items}</ul>'
        if items is not None
        else raw("")
    )
    actions_markup = (
        t'<div class="tori-ui-navbar__actions">{actions}</div>'
        if actions is not None
        else raw("")
    )
    return (
        t'<nav class="tori-ui-navbar" aria-label="{label}">'
        t'<div class="tori-ui-navbar__brand">{brand}</div>{items_markup}'
        t"{actions_markup}</nav>"
    )


def nav(
    items: Iterable[object],
    *,
    label: str,
    orientation: NavOrientation = "vertical",
) -> Template:
    """Render ``nav_item()`` entries as a labeled navigation list."""
    label = required_text("nav label", label)
    one_of("nav orientation", orientation, _NAV_ORIENTATIONS)
    class_name = classes("tori-ui-nav", f"tori-ui-nav--{orientation}")
    return (
        t'<nav aria-label="{label}"><ul class="{class_name}">{fragment(items)}</ul>'
        t"</nav>"
    )


def nav_item(
    label: object,
    *,
    href: str,
    live: LiveLink | None = None,
    replace: bool = False,
    external: bool = False,
    current: bool = False,
    icon: IconName | None = None,
    badge: object | None = None,
) -> Template:
    """Render one link of a ``nav()`` or a ``navbar()``.

    ``current`` marks the link to the page the visitor is on.
    """
    boolean("nav item current", current)
    glyph: object = raw("")
    if icon is not None:
        icon_name("nav item icon", icon)
        glyph = render_icon(icon, size="sm")
    badge_markup = (
        t'<span class="tori-ui-nav__badge">{badge}</span>'
        if badge is not None
        else raw("")
    )
    attributes = attrs(
        {
            "class": "tori-ui-nav__link",
            **link_attributes("nav item", href, live, replace, external),
            "aria-current": "page" if current else None,
        }
    )
    return (
        t'<li class="tori-ui-nav__item"><a{attributes}>{glyph}'
        t'<span class="tori-ui-nav__label">{label}</span>{badge_markup}</a></li>'
    )


def breadcrumbs(
    items: Iterable[tuple[object, str | None]],
    *,
    label: str = "Breadcrumb",
    live: LiveLink | None = None,
) -> Template:
    """Show where the page sits, as ``(label, href)`` pairs from the top down.

    The last item is the current page and is not a link; pass ``None`` as its
    ``href``. ``live`` makes every link a LiveView link of that kind.
    """
    label = required_text("breadcrumbs label", label)
    entries = list(items)
    if not entries:
        raise ValueError("breadcrumbs requires at least one item")
    crumbs: list[Template] = []
    for index, item in enumerate(entries):
        if not isinstance(item, tuple) or len(item) != 2:
            raise TypeError("breadcrumbs items must be (label, href) tuples")
        text, href = item
        if index == len(entries) - 1 or href is None:
            crumbs.append(
                t'<li class="tori-ui-breadcrumbs__item">'
                t'<span aria-current="page">{text}</span></li>'
            )
        else:
            link = attrs(
                {
                    "class": "tori-ui-breadcrumbs__link",
                    **link_attributes("breadcrumbs", href, live, False, False),
                }
            )
            crumbs.append(
                t'<li class="tori-ui-breadcrumbs__item"><a{link}>{text}</a></li>'
            )
    return (
        t'<nav aria-label="{label}"><ol class="tori-ui-breadcrumbs">'
        t"{fragment(crumbs)}</ol></nav>"
    )


def _page_numbers(page: int, pages: int, siblings: int) -> list[int | None]:
    """Return the page numbers to show, with ``None`` where pages are skipped."""
    shown = {1, pages}
    shown.update(range(max(1, page - siblings), min(pages, page + siblings) + 1))
    numbers: list[int | None] = []
    previous = 0
    for number in sorted(shown):
        if number - previous == 2:
            numbers.append(previous + 1)
        elif number - previous > 2:
            numbers.append(None)
        numbers.append(number)
        previous = number
    return numbers


def pagination(
    *,
    page: int,
    pages: int,
    href: str | None = None,
    live: LiveLink | None = None,
    event: str | JS | None = None,
    target: int | None = None,
    siblings: int = 1,
    label: str = "Pagination",
    previous_label: str = "Previous page",
    next_label: str = "Next page",
) -> Template:
    """Render the controls that move through numbered pages.

    Give either ``href``, a URL that contains ``{page}``, to render links, or
    ``event``, to render buttons that push it with the number as ``page``.
    ``siblings`` is how many pages to show on each side of the current one.
    """
    bounded_integer("pagination pages", pages, 1, 10**9)
    bounded_integer("pagination page", page, 1, pages)
    bounded_integer("pagination siblings", siblings, 0, 5)
    label = required_text("pagination label", label)
    previous_label = required_text("pagination previous label", previous_label)
    next_label = required_text("pagination next label", next_label)
    event = event_binding("pagination event", event)
    target = event_target("pagination target", target, event)
    if (href is None) == (event is None):
        raise ValueError("pagination requires either an href or an event")
    if href is not None:
        href = required_text("pagination href", href)
        if _PAGE_PLACEHOLDER not in href:
            raise ValueError("pagination href must contain {page}")
    elif live is not None:
        raise ValueError("pagination live requires an href")

    def control(
        number: int, content: object, name: str | None, modifier: str
    ) -> Template:
        current = number == page and name is None
        disabled = name is not None and not 1 <= number <= pages
        class_name = classes("tori-ui-pagination__control", modifier)
        if href is not None:
            if disabled:
                return (
                    t'<span class="{class_name}" aria-disabled="true">{content}</span>'
                )
            link = attrs(
                {
                    "class": class_name,
                    **link_attributes(
                        "pagination",
                        href.replace(_PAGE_PLACEHOLDER, str(number)),
                        live,
                        False,
                        False,
                    ),
                    "aria-label": name,
                    "aria-current": "page" if current else None,
                }
            )
            return t"<a{link}>{content}</a>"
        button = attrs(
            {
                "type": "button",
                "class": class_name,
                "aria-label": name,
                "aria-current": "page" if current else None,
                "disabled": disabled,
                "phx-click": event,
                "phx-target": target,
                "phx-value-page": number,
            }
        )
        return t"<button{button}>{content}</button>"

    parts: list[Template] = [
        control(
            page - 1,
            render_icon("chevron-left", size="sm"),
            previous_label,
            "tori-ui-pagination__control--step",
        )
    ]
    for number in _page_numbers(page, pages, siblings):
        if number is None:
            parts.append(
                t'<span class="tori-ui-pagination__gap" aria-hidden="true">…</span>'
            )
        else:
            parts.append(
                control(number, number, None, "tori-ui-pagination__control--page")
            )
    parts.append(
        control(
            page + 1,
            render_icon("chevron-right", size="sm"),
            next_label,
            "tori-ui-pagination__control--step",
        )
    )
    items = fragment(t"<li>{part}</li>" for part in parts)
    return (
        t'<nav aria-label="{label}"><ul class="tori-ui-pagination">{items}</ul></nav>'
    )


def steps(
    items: Iterable[str | tuple[str, str]],
    *,
    current: int,
    label: str = "Progress",
    complete_label: str = "Completed",
) -> Template:
    """Show the stages of a process and which one the visitor is at.

    An item is a title, or a ``(title, description)`` pair. ``current`` counts
    from 1; the stages before it are complete, and a value one past the last
    stage means all of them are.
    """
    label = required_text("steps label", label)
    complete_label = required_text("steps complete label", complete_label)
    entries = list(items)
    if not entries:
        raise ValueError("steps requires at least one item")
    bounded_integer("steps current", current, 1, len(entries) + 1)
    stages: list[Template] = []
    for number, item in enumerate(entries, start=1):
        if isinstance(item, tuple):
            if len(item) != 2:
                raise TypeError("steps items must be strings or two-item tuples")
            title, description = item
        else:
            title, description = item, None
        title = required_text("steps title", title)
        description = optional_nonempty_text("steps description", description)
        state = (
            "complete"
            if number < current
            else "current"
            if number == current
            else "upcoming"
        )
        marker: object = (
            t"{render_icon('check', size='sm')}"
            t'<span class="tori-ui-visually-hidden">{complete_label}: </span>'
            if state == "complete"
            else number
        )
        description_markup = (
            t'<span class="tori-ui-steps__description">{description}</span>'
            if description is not None
            else raw("")
        )
        attributes = attrs(
            {
                "class": classes(
                    "tori-ui-steps__step", f"tori-ui-steps__step--{state}"
                ),
                "aria-current": "step" if state == "current" else None,
            }
        )
        stages.append(
            t'<li{attributes}><span class="tori-ui-steps__marker">{marker}</span>'
            t'<span class="tori-ui-steps__text">'
            t'<span class="tori-ui-steps__title">{title}</span>{description_markup}'
            t"</span></li>"
        )
    return t'<ol class="tori-ui-steps" aria-label="{label}">{fragment(stages)}</ol>'


def tab_links(
    items: Iterable[tuple[object, str]],
    *,
    current: str,
    label: str,
    live: LiveLink | None = None,
) -> Template:
    """Render links to sibling pages in the look of tabs.

    An item is a ``(label, href)`` pair, and ``current`` is the ``href`` of the
    page the visitor is on. These are links, not ARIA tabs: each one loads its
    own page or, with ``live``, patches or navigates.
    """
    label = required_text("tab links label", label)
    current = required_text("tab links current", current)
    links: list[Template] = []
    for item in items:
        if not isinstance(item, tuple) or len(item) != 2:
            raise TypeError("tab links items must be (label, href) tuples")
        text, href = item
        attributes = attrs(
            {
                "class": "tori-ui-tab-links__link",
                **link_attributes("tab links", href, live, False, False),
                "aria-current": "page" if href == current else None,
            }
        )
        links.append(t"<li><a{attributes}>{text}</a></li>")
    if not links:
        raise ValueError("tab links requires at least one item")
    return (
        t'<nav aria-label="{label}"><ul class="tori-ui-tab-links">{fragment(links)}'
        t"</ul></nav>"
    )


__all__ = [
    "breadcrumbs",
    "nav",
    "nav_item",
    "navbar",
    "pagination",
    "skip_link",
    "steps",
    "tab_links",
]

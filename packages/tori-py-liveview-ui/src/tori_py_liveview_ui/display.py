"""Helpers that present data."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from string.templatelib import Template
from typing import Literal

from tori_py_liveview import JS, attrs, classes, fragment, raw

from tori_py_liveview_ui._shared import (
    SIZES,
    TONES,
    EventValue,
    LiveLink,
    Size,
    Tone,
    boolean,
    bounded_integer,
    event_binding,
    event_target,
    event_values,
    html_id,
    link_attributes,
    one_of,
    optional_nonempty_text,
    required_text,
)
from tori_py_liveview_ui.icons import IconName, icon_name
from tori_py_liveview_ui.icons import icon as render_icon

type CellAlignment = Literal["start", "center", "end"]
type SortDirection = Literal["asc", "desc"]
type Density = Literal["comfortable", "compact"]
type Trend = Literal["up", "down", "flat"]
type TooltipPlacement = Literal["top", "bottom"]

_CELL_ALIGNMENTS = frozenset({"start", "center", "end"})
_SORT_DIRECTIONS = frozenset({"asc", "desc"})
_DENSITIES = frozenset({"comfortable", "compact"})
_TRENDS = frozenset({"up", "down", "flat"})
_TREND_ICONS: dict[str, IconName] = {
    "up": "arrow-up",
    "down": "arrow-down",
    "flat": "minus",
}
_TOOLTIP_PLACEMENTS = frozenset({"top", "bottom"})
_ARIA_SORT = {"asc": "ascending", "desc": "descending"}


def badge(content: object, *, tone: Tone = "neutral") -> Template:
    one_of("badge tone", tone, TONES)
    class_name = classes("tori-ui-badge", f"tori-ui-badge--{tone}")
    return t'<span class="{class_name}">{content}</span>'


@dataclass(frozen=True, slots=True)
class TableColumn:
    """One column of a ``table``.

    ``key`` identifies the column in sort events and defaults to the label.
    """

    label: str
    key: str | None = None
    align: CellAlignment = "start"
    sortable: bool = False

    def __post_init__(self) -> None:
        required_text("table column label", self.label)
        if self.key is not None:
            required_text("table column key", self.key)
        one_of("table column alignment", self.align, _CELL_ALIGNMENTS)
        boolean("table column sortable", self.sortable)

    @property
    def sort_key(self) -> str:
        return self.label if self.key is None else self.key


def _columns(columns: Iterable[str | TableColumn]) -> tuple[TableColumn, ...]:
    resolved: list[TableColumn] = []
    for column in columns:
        if isinstance(column, str):
            column = TableColumn(column)
        elif not isinstance(column, TableColumn):
            raise TypeError("table columns must be strings or TableColumn values")
        resolved.append(column)
    if not resolved:
        raise ValueError("table requires at least one column")
    return tuple(resolved)


def _cell(value: object, column: TableColumn) -> Template:
    class_name = classes("tori-ui-table__cell", f"tori-ui-table__cell--{column.align}")
    return t'<td class="{class_name}">{value}</td>'


def _cells(cells: Iterable[object], columns: tuple[TableColumn, ...]) -> object:
    values = tuple(cells)
    if len(values) != len(columns):
        raise ValueError("table row must have one cell per column")
    return fragment(
        _cell(value, column) for value, column in zip(values, columns, strict=True)
    )


def table_row(
    cells: Iterable[object],
    *,
    columns: Iterable[str | TableColumn],
    id: str | None = None,
) -> Template:
    """Render one body row, for a table whose rows are a LiveView stream.

    Pass the table's ``columns`` so the cells get their alignment, and the
    stream item ID as ``id``.
    """
    if id is not None:
        id = html_id("table row id", id)
    attributes = attrs({"id": id, "class": "tori-ui-table__row"})
    return t"<tr{attributes}>{_cells(cells, _columns(columns))}</tr>"


def table(
    columns: Iterable[str | TableColumn],
    rows: Iterable[Iterable[object]] = (),
    *,
    caption: str | None = None,
    density: Density = "comfortable",
    striped: bool = False,
    empty: object | None = None,
    sort: tuple[str, SortDirection] | None = None,
    sort_event: str | JS | None = None,
    target: int | None = None,
    stream: tuple[str, object] | None = None,
) -> Template:
    """Render a data table that scrolls sideways when it is too wide.

    ``rows`` holds one iterable of cells per row. For rows the browser owns,
    pass ``stream=(container_id, self.stream_contents(container_id))`` instead
    and build each stream item with ``table_row()``.

    The page owns sorting: a sortable column's header pushes ``sort_event``
    with the column's ``key``, and ``sort=(key, direction)`` marks the column
    the page sorted by.
    """
    resolved = _columns(columns)
    caption = optional_nonempty_text("table caption", caption)
    one_of("table density", density, _DENSITIES)
    boolean("table striped", striped)
    sort_event = event_binding("table sort event", sort_event)
    target = event_target("table target", target, sort_event)
    if sort is not None:
        if not isinstance(sort, tuple) or len(sort) != 2:
            raise TypeError("table sort must be a (key, direction) tuple")
        required_text("table sort key", sort[0])
        one_of("table sort direction", sort[1], _SORT_DIRECTIONS)
    if any(column.sortable for column in resolved) and sort_event is None:
        raise ValueError("table sortable columns require a sort event")
    headers = fragment(_header(column, sort, sort_event, target) for column in resolved)
    body: object
    if stream is not None:
        if not isinstance(stream, tuple) or len(stream) != 2:
            raise TypeError("table stream must be a (container id, contents) tuple")
        container_id = html_id("table stream id", stream[0])
        body = t'<tbody id="{container_id}" phx-update="stream">{stream[1]}</tbody>'
    else:
        body_rows = [
            t'<tr class="tori-ui-table__row">{_cells(row, resolved)}</tr>'
            for row in rows
        ]
        if not body_rows and empty is not None:
            body_rows = [
                t'<tr class="tori-ui-table__row"><td class="tori-ui-table__empty" '
                t'colspan="{len(resolved)}">{empty}</td></tr>'
            ]
        body = t"<tbody>{fragment(body_rows)}</tbody>"
    caption_markup = (
        t'<caption class="tori-ui-table__caption">{caption}</caption>'
        if caption is not None
        else raw("")
    )
    class_name = classes(
        "tori-ui-table",
        f"tori-ui-table--{density}",
        **{"tori-ui-table--striped": striped},
    )
    return (
        t'<div class="{class_name}"><table class="tori-ui-table__table">'
        t"{caption_markup}<thead><tr>{headers}</tr></thead>{body}</table></div>"
    )


def _header(
    column: TableColumn,
    sort: tuple[str, SortDirection] | None,
    sort_event: str | JS | None,
    target: int | None,
) -> Template:
    class_name = classes(
        "tori-ui-table__header", f"tori-ui-table__header--{column.align}"
    )
    if not column.sortable:
        return t'<th scope="col" class="{class_name}">{column.label}</th>'
    direction = sort[1] if sort is not None and sort[0] == column.sort_key else None
    glyph: IconName = (
        "chevron-up"
        if direction == "asc"
        else "chevron-down"
        if direction == "desc"
        else "chevrons-up-down"
    )
    header_attributes = attrs(
        {
            "scope": "col",
            "class": class_name,
            "aria-sort": "none" if direction is None else _ARIA_SORT[direction],
        }
    )
    button_attributes = attrs(
        {
            "type": "button",
            "class": "tori-ui-table__sort",
            "phx-click": sort_event,
            "phx-target": target,
            "phx-value-key": column.sort_key,
        }
    )
    return (
        t"<th{header_attributes}><button{button_attributes}>{column.label}"
        t"{render_icon(glyph, size='sm')}</button></th>"
    )


def list_group(items: Iterable[object], *, label: str | None = None) -> Template:
    """Render ``list_item()`` rows as one bordered list."""
    label = optional_nonempty_text("list group label", label)
    attributes = attrs({"class": "tori-ui-list-group", "aria-label": label})
    return t"<ul{attributes}>{fragment(items)}</ul>"


def list_item(
    title: object,
    *,
    description: object | None = None,
    leading: object | None = None,
    trailing: object | None = None,
    href: str | None = None,
    live: LiveLink | None = None,
    event: str | JS | None = None,
    target: int | None = None,
    values: Mapping[str, EventValue] | None = None,
    selected: bool = False,
    id: str | None = None,
) -> Template:
    """Render one row of a ``list_group``.

    With ``href`` the row is a link, with ``event`` a button, and otherwise
    plain content. ``leading`` and ``trailing`` hold an avatar, an icon, a
    badge, or a control.
    """
    boolean("list item selected", selected)
    event = event_binding("list item event", event)
    target = event_target("list item target", target, event)
    value_attributes = event_values("list item values", values, event)
    if href is not None and event is not None:
        raise ValueError("list item cannot have both an href and an event")
    if href is None and live is not None:
        raise ValueError("list item live requires an href")
    if id is not None:
        id = html_id("list item id", id)
    leading_markup = (
        t'<span class="tori-ui-list-item__leading">{leading}</span>'
        if leading is not None
        else raw("")
    )
    description_markup = (
        t'<span class="tori-ui-list-item__description">{description}</span>'
        if description is not None
        else raw("")
    )
    trailing_markup = (
        t'<span class="tori-ui-list-item__trailing">{trailing}</span>'
        if trailing is not None
        else raw("")
    )
    text = (
        t'{leading_markup}<span class="tori-ui-list-item__text">'
        t'<span class="tori-ui-list-item__title">{title}</span>'
        t"{description_markup}</span>"
    )
    current = "true" if selected else None
    body: Template
    if href is not None:
        link = attrs(
            {
                "class": "tori-ui-list-item__action",
                **link_attributes("list item", href, live, False, False),
                "aria-current": current,
            }
        )
        body = t"<a{link}>{text}</a>"
    elif event is not None:
        action = attrs(
            {
                "type": "button",
                "class": "tori-ui-list-item__action",
                "phx-click": event,
                "phx-target": target,
                **value_attributes,
                "aria-current": current,
            }
        )
        body = t"<button{action}>{text}</button>"
    else:
        body = t'<div class="tori-ui-list-item__action">{text}</div>'
    attributes = attrs(
        {
            "id": id,
            "class": classes(
                "tori-ui-list-item",
                **{"tori-ui-list-item--selected": selected},
            ),
        }
    )
    return t"<li{attributes}>{body}{trailing_markup}</li>"


def stat(
    label: str,
    value: object,
    *,
    delta: str | None = None,
    trend: Trend | None = None,
    tone: Tone = "neutral",
    help_text: str | None = None,
    chart: object | None = None,
) -> Template:
    """Render one figure with its label, change, and an optional small chart."""
    label = required_text("stat label", label)
    delta = optional_nonempty_text("stat delta", delta)
    if trend is not None:
        one_of("stat trend", trend, _TRENDS)
    one_of("stat tone", tone, TONES)
    help_text = optional_nonempty_text("stat help text", help_text)
    delta_markup: object = raw("")
    if delta is not None or trend is not None:
        glyph = render_icon(_TREND_ICONS[trend], size="sm") if trend else raw("")
        delta_class = classes("tori-ui-stat__delta", f"tori-ui-stat__delta--{tone}")
        delta_text = "" if delta is None else delta
        delta_markup = t'<span class="{delta_class}">{glyph}{delta_text}</span>'
    help_markup = (
        t'<p class="tori-ui-stat__help">{help_text}</p>'
        if help_text is not None
        else raw("")
    )
    chart_markup = (
        t'<div class="tori-ui-stat__chart">{chart}</div>'
        if chart is not None
        else raw("")
    )
    return (
        t'<div class="tori-ui-stat"><p class="tori-ui-stat__label">{label}</p>'
        t'<p class="tori-ui-stat__figure"><span class="tori-ui-stat__value">'
        t"{value}</span>{delta_markup}</p>{help_markup}{chart_markup}</div>"
    )


def _number(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def sparkline(
    values: Iterable[float],
    *,
    label: str,
    tone: Tone = "neutral",
    area: bool = False,
) -> Template:
    """Render a small line chart as inline SVG.

    ``label`` describes the trend in words for readers who cannot see it.
    """
    label = required_text("sparkline label", label)
    one_of("sparkline tone", tone, TONES)
    boolean("sparkline area", area)
    numbers = [float(_number("sparkline value", value)) for value in values]
    if len(numbers) < 2:
        raise ValueError("sparkline requires at least two values")
    low, high = min(numbers), max(numbers)
    span = high - low
    step = 100 / (len(numbers) - 1)
    # The line keeps two units of room above and below for its stroke.
    heights = [
        15.0 if span == 0 else 28 - (value - low) / span * 26 for value in numbers
    ]
    line = " ".join(
        f"{index * step:.2f},{height:.2f}" for index, height in enumerate(heights)
    )
    area_markup = (
        t'<polygon class="tori-ui-sparkline__area" points="0,30 {line} 100,30">'
        t"</polygon>"
        if area
        else raw("")
    )
    class_name = classes("tori-ui-sparkline", f"tori-ui-sparkline--{tone}")
    return (
        t'<svg class="{class_name}" viewBox="0 0 100 30" preserveAspectRatio="none" '
        t'role="img" aria-label="{label}" focusable="false">{area_markup}'
        t'<polyline class="tori-ui-sparkline__line" points="{line}"></polyline></svg>'
    )


def _initials(name: str) -> str:
    words = name.split()
    letters = words[0][0] + (words[-1][0] if len(words) > 1 else "")
    return letters.upper()


def avatar(name: str, *, src: str | None = None, size: Size = "md") -> Template:
    """Render a person's picture, or their initials without one.

    ``name`` is the avatar's accessible name.
    """
    name = required_text("avatar name", name)
    one_of("avatar size", size, SIZES)
    class_name = classes("tori-ui-avatar", f"tori-ui-avatar--{size}")
    content: object
    if src is None:
        content = _initials(name)
    else:
        src = required_text("avatar source", src)
        image = attrs({"class": "tori-ui-avatar__image", "src": src, "alt": ""})
        content = t"<img{image}>"
    return t'<span class="{class_name}" role="img" aria-label="{name}">{content}</span>'


def avatar_group(
    children: Iterable[object],
    *,
    label: str,
    extra: int = 0,
) -> Template:
    """Overlap avatars; ``extra`` counts the people the group leaves out."""
    label = required_text("avatar group label", label)
    bounded_integer("avatar group extra", extra, 0, 9999)
    more = (
        t'<span class="tori-ui-avatar tori-ui-avatar--md tori-ui-avatar--more">'
        t"+{extra}</span>"
        if extra
        else raw("")
    )
    return (
        t'<span class="tori-ui-avatar-group" role="group" aria-label="{label}">'
        t"{fragment(children)}{more}</span>"
    )


def tag(
    content: object,
    *,
    tone: Tone = "neutral",
    icon: IconName | None = None,
    remove_event: str | JS | None = None,
    remove_label: str = "Remove",
    target: int | None = None,
    values: Mapping[str, EventValue] | None = None,
) -> Template:
    """Render a chip for a category, a filter, or a selected value.

    With ``remove_event`` the tag ends in a button that pushes the event.
    """
    one_of("tag tone", tone, TONES)
    remove_event = event_binding("tag remove event", remove_event)
    remove_label = required_text("tag remove label", remove_label)
    target = event_target("tag target", target, remove_event)
    value_attributes = event_values("tag values", values, remove_event)
    leading: object = raw("")
    if icon is not None:
        icon_name("tag icon", icon)
        leading = render_icon(icon, size="sm")
    remove: object = raw("")
    if remove_event is not None:
        remove_attributes = attrs(
            {
                "type": "button",
                "class": "tori-ui-tag__remove",
                "aria-label": remove_label,
                "phx-click": remove_event,
                "phx-target": target,
                **value_attributes,
            }
        )
        remove = t"<button{remove_attributes}>{render_icon('x', size='sm')}</button>"
    class_name = classes("tori-ui-tag", f"tori-ui-tag--{tone}")
    return (
        t'<span class="{class_name}">{leading}'
        t'<span class="tori-ui-tag__label">{content}</span>{remove}</span>'
    )


def status_dot(
    label: str,
    *,
    tone: Tone = "neutral",
    pulse: bool = False,
) -> Template:
    """Render a colored dot with the state it stands for in words."""
    label = required_text("status dot label", label)
    one_of("status dot tone", tone, TONES)
    boolean("status dot pulse", pulse)
    class_name = classes(
        "tori-ui-status-dot",
        f"tori-ui-status-dot--{tone}",
        **{"tori-ui-status-dot--pulse": pulse},
    )
    return (
        t'<span class="{class_name}"><span class="tori-ui-status-dot__dot" '
        t'aria-hidden="true"></span>{label}</span>'
    )


def timeline(items: Iterable[object]) -> Template:
    """Render ``timeline_item()`` entries as an ordered list of events."""
    return t'<ol class="tori-ui-timeline">{fragment(items)}</ol>'


def timeline_item(
    title: object,
    *,
    time: object | None = None,
    description: object | None = None,
    tone: Tone = "neutral",
    id: str | None = None,
) -> Template:
    """Render one event of a ``timeline``."""
    one_of("timeline item tone", tone, TONES)
    if id is not None:
        id = html_id("timeline item id", id)
    time_markup = (
        t'<span class="tori-ui-timeline__time">{time}</span>'
        if time is not None
        else raw("")
    )
    description_markup = (
        t'<div class="tori-ui-timeline__description">{description}</div>'
        if description is not None
        else raw("")
    )
    attributes = attrs(
        {
            "id": id,
            "class": classes(
                "tori-ui-timeline__item", f"tori-ui-timeline__item--{tone}"
            ),
        }
    )
    return (
        t'<li{attributes}><span class="tori-ui-timeline__marker" aria-hidden="true">'
        t'</span><div class="tori-ui-timeline__content">'
        t'<p class="tori-ui-timeline__title">{title}{time_markup}</p>'
        t"{description_markup}</div></li>"
    )


def empty_state(
    title: str,
    *,
    description: object | None = None,
    icon: IconName | None = None,
    actions: object | None = None,
) -> Template:
    """Fill a region that has nothing to show yet, and say what to do next."""
    title = required_text("empty state title", title)
    glyph: object = raw("")
    if icon is not None:
        icon_name("empty state icon", icon)
        drawing = render_icon(icon, size="lg")
        glyph = t'<div class="tori-ui-empty-state__icon">{drawing}</div>'
    description_markup = (
        t'<p class="tori-ui-empty-state__description">{description}</p>'
        if description is not None
        else raw("")
    )
    actions_markup = (
        t'<div class="tori-ui-empty-state__actions">{actions}</div>'
        if actions is not None
        else raw("")
    )
    return (
        t'<div class="tori-ui-empty-state">{glyph}'
        t'<p class="tori-ui-empty-state__title">{title}</p>{description_markup}'
        t"{actions_markup}</div>"
    )


def progress(
    *,
    label: str,
    value: float | None = None,
    maximum: float = 100,
    tone: Tone = "neutral",
    show_value: bool = False,
) -> Template:
    """Render a native progress bar; without a ``value`` it is indeterminate."""
    label = required_text("progress label", label)
    _number("progress maximum", maximum)
    if maximum <= 0:
        raise ValueError("progress maximum must be positive")
    if value is not None:
        _number("progress value", value)
        if not 0 <= value <= maximum:
            raise ValueError("progress value must be between 0 and the maximum")
    one_of("progress tone", tone, TONES)
    boolean("progress show value", show_value)
    attributes = attrs(
        {
            "class": "tori-ui-progress__bar",
            "aria-label": label,
            "value": value,
            "max": maximum,
        }
    )
    percent: object = raw("")
    if show_value and value is not None:
        share = round(value / maximum * 100)
        percent = t'<span class="tori-ui-progress__value">{share}%</span>'
    class_name = classes("tori-ui-progress", f"tori-ui-progress--{tone}")
    return t'<div class="{class_name}"><progress{attributes}></progress>{percent}</div>'


def meter(
    *,
    label: str,
    value: float,
    minimum: float = 0,
    maximum: float = 100,
    low: float | None = None,
    high: float | None = None,
    optimum: float | None = None,
) -> Template:
    """Render a native meter for a measurement within a known range."""
    label = required_text("meter label", label)
    _number("meter value", value)
    _number("meter minimum", minimum)
    _number("meter maximum", maximum)
    if minimum >= maximum:
        raise ValueError("meter minimum must be below the maximum")
    if not minimum <= value <= maximum:
        raise ValueError("meter value must be within the range")
    for name, bound in (("low", low), ("high", high), ("optimum", optimum)):
        if bound is not None:
            _number(f"meter {name}", bound)
            if not minimum <= bound <= maximum:
                raise ValueError(f"meter {name} must be within the range")
    attributes = attrs(
        {
            "class": "tori-ui-meter",
            "aria-label": label,
            "value": value,
            "min": minimum,
            "max": maximum,
            "low": low,
            "high": high,
            "optimum": optimum,
        }
    )
    return t"<meter{attributes}></meter>"


def tooltip(
    content: object,
    *,
    text: str,
    id: str,
    placement: TooltipPlacement = "top",
) -> Template:
    """Describe text, an icon, or a badge on hover and on keyboard focus.

    The helper makes its content focusable, so it is not for buttons and
    links: give those a visible label, or use ``icon_button()``.
    """
    text = required_text("tooltip text", text)
    id = html_id("tooltip id", id)
    one_of("tooltip placement", placement, _TOOLTIP_PLACEMENTS)
    class_name = classes("tori-ui-tooltip", f"tori-ui-tooltip--{placement}")
    return (
        t'<span class="{class_name}" tabindex="0" aria-describedby="{id}">{content}'
        t'<span id="{id}" class="tori-ui-tooltip__bubble" role="tooltip">{text}'
        t"</span></span>"
    )


__all__ = [
    "TableColumn",
    "avatar",
    "avatar_group",
    "badge",
    "empty_state",
    "list_group",
    "list_item",
    "meter",
    "progress",
    "sparkline",
    "stat",
    "status_dot",
    "table",
    "table_row",
    "tag",
    "timeline",
    "timeline_item",
    "tooltip",
]

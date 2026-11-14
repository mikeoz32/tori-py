from __future__ import annotations

import re
from collections.abc import Callable
from string.templatelib import Template
from typing import Any, cast

import pytest
import tori_py_liveview_ui
from tori_py_liveview import html
from tori_py_liveview_ui import (
    TableColumn,
    avatar,
    avatar_group,
    display,
    empty_state,
    icon,
    list_group,
    list_item,
    meter,
    progress,
    sparkline,
    stat,
    status_dot,
    table,
    table_row,
    tag,
    timeline,
    timeline_item,
    tooltip,
)

# Calls that break a helper's contract go through an untyped alias.
ui = cast(Any, tori_py_liveview_ui)


def _render(template: Template) -> str:
    return html(template).to_html()


def test_display_family_is_explicit() -> None:
    assert display.__all__ == [
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


def test_table_renders_headers_aligned_cells_and_escapes_values() -> None:
    columns = ["Name", TableColumn("Total", align="end")]

    assert _render(table(columns, [["<Ada>", 3]], caption="Team")) == (
        '<div class="tori-ui-table tori-ui-table--comfortable">'
        '<table class="tori-ui-table__table">'
        '<caption class="tori-ui-table__caption">Team</caption><thead><tr>'
        '<th scope="col" class="tori-ui-table__header tori-ui-table__header--start">'
        "Name</th>"
        '<th scope="col" class="tori-ui-table__header tori-ui-table__header--end">'
        "Total</th></tr></thead><tbody>"
        '<tr class="tori-ui-table__row">'
        '<td class="tori-ui-table__cell tori-ui-table__cell--start">&lt;Ada&gt;</td>'
        '<td class="tori-ui-table__cell tori-ui-table__cell--end">3</td></tr>'
        "</tbody></table></div>"
    )
    styled = _render(table(["A"], [], density="compact", striped=True))
    assert 'class="tori-ui-table tori-ui-table--compact tori-ui-table--striped"' in (
        styled
    )


def test_table_shows_the_empty_content_across_all_columns() -> None:
    result = _render(table(["A", "B"], [], empty="No rows"))

    assert (
        '<tbody><tr class="tori-ui-table__row">'
        '<td class="tori-ui-table__empty" colspan="2">No rows</td></tr></tbody>'
    ) in result
    assert "<tbody></tbody>" in _render(table(["A"], []))


def test_sortable_header_pushes_its_key_and_reports_the_sort_state() -> None:
    columns = [
        TableColumn("Name", key="name", sortable=True),
        TableColumn("Created", sortable=True),
        "Notes",
    ]
    result = _render(
        table(columns, [], sort=("name", "desc"), sort_event="sort", target=5)
    )

    assert (
        '<th scope="col" class="tori-ui-table__header tori-ui-table__header--start" '
        'aria-sort="descending"><button type="button" class="tori-ui-table__sort" '
        f'phx-click="sort" phx-target="5" phx-value-key="name">Name'
        f"{_render(icon('chevron-down', size='sm'))}</button></th>"
    ) in result
    # A column without a key sorts by its label and is not sorted yet.
    assert 'aria-sort="none"' in result
    assert 'phx-value-key="Created"' in result
    assert result.count("aria-sort") == 2
    ascending = _render(table(columns, [], sort=("name", "asc"), sort_event="sort"))
    assert 'aria-sort="ascending"' in ascending
    assert _render(icon("chevron-up", size="sm")) in ascending


def test_stream_table_body_is_the_stream_container() -> None:
    columns = ["Name", TableColumn("Total", align="end")]

    assert '<tbody id="orders" phx-update="stream">ITEMS</tbody>' in _render(
        table(columns, stream=("orders", "ITEMS"))
    )
    assert _render(table_row(["Ada", 3], columns=columns, id="orders-1")) == (
        '<tr id="orders-1" class="tori-ui-table__row">'
        '<td class="tori-ui-table__cell tori-ui-table__cell--start">Ada</td>'
        '<td class="tori-ui-table__cell tori-ui-table__cell--end">3</td></tr>'
    )


def test_list_item_is_a_link_a_button_or_plain_content() -> None:
    link = _render(
        list_item(
            "Inbox",
            description="3 new",
            leading="L",
            trailing="T",
            href="/inbox",
            live="navigate",
            selected=True,
            id="inbox",
        )
    )
    assert link == (
        '<li id="inbox" class="tori-ui-list-item tori-ui-list-item--selected">'
        '<a class="tori-ui-list-item__action" href="/inbox" '
        'data-phx-link="redirect" data-phx-link-state="push" aria-current="true">'
        '<span class="tori-ui-list-item__leading">L</span>'
        '<span class="tori-ui-list-item__text">'
        '<span class="tori-ui-list-item__title">Inbox</span>'
        '<span class="tori-ui-list-item__description">3 new</span></span></a>'
        '<span class="tori-ui-list-item__trailing">T</span></li>'
    )
    button = _render(list_item("Archive", event="open", values={"id": 7}, target=2))
    assert (
        '<button type="button" class="tori-ui-list-item__action" phx-click="open" '
        'phx-target="2" phx-value-id="7">'
    ) in button
    plain = _render(list_item("Plain"))
    assert '<div class="tori-ui-list-item__action">' in plain
    assert "aria-current" not in plain


def test_list_group_wraps_items_in_an_optionally_labeled_list() -> None:
    assert _render(list_group(["A", "B"], label="Folders")) == (
        '<ul class="tori-ui-list-group" aria-label="Folders">AB</ul>'
    )
    assert _render(list_group([])) == '<ul class="tori-ui-list-group"></ul>'


def test_stat_shows_the_figure_its_change_and_optional_parts() -> None:
    assert _render(stat("Revenue", "$12k")) == (
        '<div class="tori-ui-stat"><p class="tori-ui-stat__label">Revenue</p>'
        '<p class="tori-ui-stat__figure"><span class="tori-ui-stat__value">$12k'
        "</span></p></div>"
    )
    full = _render(
        stat(
            "Revenue",
            "$12k",
            delta="12%",
            trend="up",
            tone="success",
            help_text="vs last month",
            chart="CHART",
        )
    )
    assert (
        '<span class="tori-ui-stat__delta tori-ui-stat__delta--success">'
        f"{_render(icon('arrow-up', size='sm'))}12%</span>"
    ) in full
    assert '<p class="tori-ui-stat__help">vs last month</p>' in full
    assert '<div class="tori-ui-stat__chart">CHART</div>' in full
    assert _render(icon("arrow-down", size="sm")) in _render(
        stat("Errors", 3, trend="down")
    )


def test_sparkline_scales_values_into_a_labeled_drawing() -> None:
    assert _render(sparkline([0, 10, 5], label="Rising, then easing")) == (
        '<svg class="tori-ui-sparkline tori-ui-sparkline--neutral" '
        'viewBox="0 0 100 30" preserveAspectRatio="none" role="img" '
        'aria-label="Rising, then easing" focusable="false">'
        '<polyline class="tori-ui-sparkline__line" '
        'points="0.00,28.00 50.00,2.00 100.00,15.00"/></svg>'
    )
    filled = _render(sparkline([1, 2], label="Up", tone="info", area=True))
    assert "tori-ui-sparkline--info" in filled
    assert (
        '<polygon class="tori-ui-sparkline__area" '
        'points="0,30 0.00,28.00 100.00,2.00 100,30"/>'
    ) in filled
    # A flat series is drawn through the middle.
    assert 'points="0.00,15.00 100.00,15.00"' in _render(
        sparkline([4, 4], label="Flat")
    )


def test_avatar_shows_a_picture_or_initials_under_the_name() -> None:
    assert _render(avatar("ada lovelace")) == (
        '<span class="tori-ui-avatar tori-ui-avatar--md" role="img" '
        'aria-label="ada lovelace">AL</span>'
    )
    assert ">M</span>" in _render(avatar("Madonna", size="sm"))
    assert ">AT</span>" in _render(avatar("Alan Mathison Turing"))
    assert _render(avatar("Ada", src="/ada.png", size="lg")) == (
        '<span class="tori-ui-avatar tori-ui-avatar--lg" role="img" aria-label="Ada">'
        '<img class="tori-ui-avatar__image" src="/ada.png" alt=""></span>'
    )


def test_avatar_group_counts_the_people_it_leaves_out() -> None:
    assert _render(avatar_group(["A"], label="Team", extra=3)) == (
        '<span class="tori-ui-avatar-group" role="group" aria-label="Team">A'
        '<span class="tori-ui-avatar tori-ui-avatar--md tori-ui-avatar--more">+3'
        "</span></span>"
    )
    assert "tori-ui-avatar--more" not in _render(avatar_group(["A"], label="Team"))


def test_tag_can_carry_an_icon_and_a_remove_button() -> None:
    assert _render(tag("python")) == (
        '<span class="tori-ui-tag tori-ui-tag--neutral">'
        '<span class="tori-ui-tag__label">python</span></span>'
    )
    removable = _render(
        tag(
            "python",
            tone="info",
            icon="code",
            remove_event="untag",
            remove_label="Remove python",
            values={"tag": "python"},
        )
    )
    glyph = _render(icon("code", size="sm"))
    assert removable.startswith(f'<span class="tori-ui-tag tori-ui-tag--info">{glyph}')
    assert (
        '<button type="button" class="tori-ui-tag__remove" '
        'aria-label="Remove python" phx-click="untag" phx-value-tag="python">'
    ) in removable


def test_status_dot_pairs_the_color_with_words() -> None:
    assert _render(status_dot("Online", tone="success", pulse=True)) == (
        '<span class="tori-ui-status-dot tori-ui-status-dot--success '
        'tori-ui-status-dot--pulse"><span class="tori-ui-status-dot__dot" '
        'aria-hidden="true"></span>Online</span>'
    )


def test_timeline_is_an_ordered_list_of_events() -> None:
    item = timeline_item(
        "Deployed", time="12:00", description="v2", tone="success", id="event-1"
    )

    assert _render(timeline([item])) == (
        '<ol class="tori-ui-timeline"><li id="event-1" '
        'class="tori-ui-timeline__item tori-ui-timeline__item--success">'
        '<span class="tori-ui-timeline__marker" aria-hidden="true"></span>'
        '<div class="tori-ui-timeline__content"><p class="tori-ui-timeline__title">'
        'Deployed<span class="tori-ui-timeline__time">12:00</span></p>'
        '<div class="tori-ui-timeline__description">v2</div></div></li></ol>'
    )
    bare = _render(timeline_item("Created"))
    assert "tori-ui-timeline__time" not in bare
    assert "tori-ui-timeline__description" not in bare


def test_empty_state_names_the_gap_and_the_next_step() -> None:
    assert _render(empty_state("No orders")) == (
        '<div class="tori-ui-empty-state">'
        '<p class="tori-ui-empty-state__title">No orders</p></div>'
    )
    full = _render(
        empty_state("No orders", description="Create one", icon="file", actions="NEW")
    )
    assert (
        f'<div class="tori-ui-empty-state__icon">{_render(icon("file", size="lg"))}'
        "</div>"
    ) in full
    assert '<p class="tori-ui-empty-state__description">Create one</p>' in full
    assert '<div class="tori-ui-empty-state__actions">NEW</div>' in full


def test_progress_is_native_and_indeterminate_without_a_value() -> None:
    assert _render(progress(label="Upload", value=30, show_value=True)) == (
        '<div class="tori-ui-progress tori-ui-progress--neutral">'
        '<progress class="tori-ui-progress__bar" aria-label="Upload" value="30" '
        'max="100"></progress><span class="tori-ui-progress__value">30%</span></div>'
    )
    working = _render(progress(label="Working", show_value=True, tone="info"))
    assert "value=" not in working
    assert "tori-ui-progress__value" not in working
    assert ">50%<" in _render(
        progress(label="Half", value=1, maximum=2, show_value=True)
    )
    assert 'value="0"' in _render(progress(label="Start", value=0))


def test_meter_is_native_with_its_range_and_thresholds() -> None:
    assert _render(meter(label="Disk", value=70, low=20, high=80, optimum=10)) == (
        '<meter class="tori-ui-meter" aria-label="Disk" value="70" min="0" '
        'max="100" low="20" high="80" optimum="10"></meter>'
    )


def test_tooltip_describes_focusable_content() -> None:
    assert _render(tooltip("API", text="Application <interface>", id="tip")) == (
        '<span class="tori-ui-tooltip tori-ui-tooltip--top" tabindex="0" '
        'aria-describedby="tip">API<span id="tip" class="tori-ui-tooltip__bubble" '
        'role="tooltip">Application &lt;interface&gt;</span></span>'
    )
    assert "tori-ui-tooltip--bottom" in _render(
        tooltip("x", text="y", id="t", placement="bottom")
    )


def test_table_column_validates_itself() -> None:
    assert TableColumn("Name").sort_key == "Name"
    assert TableColumn("Name", key="n").sort_key == "n"
    with pytest.raises(ValueError, match="table column label cannot be empty"):
        TableColumn(" ")
    with pytest.raises(ValueError, match="table column alignment must be one of"):
        ui.TableColumn("A", align="left")
    with pytest.raises(TypeError, match="table column sortable must be a boolean"):
        ui.TableColumn("A", sortable=1)


@pytest.mark.parametrize(
    ("call", "error", "message"),
    [
        (lambda: ui.table([]), ValueError, "table requires at least one column"),
        (lambda: ui.table([1]), TypeError, "table columns must be strings or"),
        (
            lambda: ui.table(["A", "B"], [["only"]]),
            ValueError,
            "table row must have one cell per column",
        ),
        (
            lambda: ui.table(["A"], density="tight"),
            ValueError,
            "table density must be one of",
        ),
        (
            lambda: ui.table([ui.TableColumn("A", sortable=True)]),
            ValueError,
            "table sortable columns require a sort event",
        ),
        (
            lambda: ui.table(["A"], sort=("A", "up"), sort_event="sort"),
            ValueError,
            "table sort direction must be one of",
        ),
        (
            lambda: ui.table(["A"], sort="A", sort_event="sort"),
            TypeError,
            "table sort must be a",
        ),
        (lambda: ui.table(["A"], target=1), ValueError, "table target requires"),
        (lambda: ui.table(["A"], stream="rows"), TypeError, "table stream must be"),
        (
            lambda: ui.table(["A"], stream=("a b", "x")),
            ValueError,
            "table stream id cannot contain whitespace",
        ),
        (
            lambda: ui.table_row(["x"], columns=["A"], id=""),
            ValueError,
            "table row id cannot be empty",
        ),
        (
            lambda: ui.list_item("x", href="/a", event="e"),
            ValueError,
            "list item cannot have both an href and an event",
        ),
        (
            lambda: ui.list_item("x", live="patch"),
            ValueError,
            "list item live requires an href",
        ),
        (
            lambda: ui.list_item("x", values={"id": 1}),
            ValueError,
            "list item values require an event",
        ),
        (
            lambda: ui.list_item("x", selected="yes"),
            TypeError,
            "list item selected must be a boolean",
        ),
        (lambda: ui.stat("", 1), ValueError, "stat label cannot be empty"),
        (lambda: ui.stat("A", 1, trend="sideways"), ValueError, "stat trend must be"),
        (lambda: ui.stat("A", 1, tone="blue"), ValueError, "stat tone must be"),
        (
            lambda: ui.sparkline([1], label="x"),
            ValueError,
            "sparkline requires at least two values",
        ),
        (
            lambda: ui.sparkline([1, "2"], label="x"),
            TypeError,
            "sparkline value must be a number",
        ),
        (
            lambda: ui.sparkline([1, float("nan")], label="x"),
            ValueError,
            "sparkline value must be finite",
        ),
        (lambda: ui.sparkline([1, 2], label=""), ValueError, "sparkline label cannot"),
        (lambda: ui.avatar(" "), ValueError, "avatar name cannot be empty"),
        (lambda: ui.avatar("A", size="xl"), ValueError, "avatar size must be one of"),
        (
            lambda: ui.avatar("A", src="javascript:alert(1)"),
            ValueError,
            "unsafe URL scheme",
        ),
        (
            lambda: ui.avatar_group([], label="T", extra=-1),
            ValueError,
            "avatar group extra must be between",
        ),
        (lambda: ui.tag("x", icon="unicorn"), ValueError, "tag icon must be one of"),
        (lambda: ui.tag("x", target=1), ValueError, "tag target requires an event"),
        (lambda: ui.status_dot(""), ValueError, "status dot label cannot be empty"),
        (
            lambda: ui.timeline_item("x", tone="blue"),
            ValueError,
            "timeline item tone must be one of",
        ),
        (
            lambda: ui.empty_state("x", icon="unicorn"),
            ValueError,
            "empty state icon must be one of",
        ),
        (
            lambda: ui.progress(label="x", value=101),
            ValueError,
            "progress value must be between 0 and the maximum",
        ),
        (
            lambda: ui.progress(label="x", maximum=0),
            ValueError,
            "progress maximum must be positive",
        ),
        (
            lambda: ui.progress(label="x", value=True),
            TypeError,
            "progress value must be a number",
        ),
        (
            lambda: ui.meter(label="x", value=5, minimum=10, maximum=1),
            ValueError,
            "meter minimum must be below the maximum",
        ),
        (
            lambda: ui.meter(label="x", value=101),
            ValueError,
            "meter value must be within the range",
        ),
        (
            lambda: ui.meter(label="x", value=1, high=500),
            ValueError,
            "meter high must be within the range",
        ),
        (
            lambda: ui.tooltip("x", text="", id="t"),
            ValueError,
            "tooltip text cannot be empty",
        ),
        (
            lambda: ui.tooltip("x", text="y", id="t", placement="left"),
            ValueError,
            "tooltip placement must be one of",
        ),
    ],
)
def test_display_helpers_reject_values_outside_their_contract(
    call: Callable[[], Any], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=re.escape(message)):
        call()

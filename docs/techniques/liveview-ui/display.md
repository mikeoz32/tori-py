# Data Display

Display helpers present what your page already knows: records, figures, people,
and progress. The page computes, sorts, and filters; the helpers render.

## Tables

```python
from string.templatelib import Template

from tori_py_liveview import LiveView, UnknownEventError
from tori_py_liveview_ui import TableColumn, table

COLUMNS = [
    TableColumn("Customer", key="customer", sortable=True),
    "Item",
    TableColumn("Total", key="total", align="end", sortable=True),
]


class OrdersLive(LiveView):
    def __init__(self) -> None:
        self.orders = [("Ada", "Engine", 1200), ("Grace", "Compiler", 870)]
        self.sort_key = "customer"
        self.descending = False

    async def handle_event(self, event: str, value: object) -> None:
        match event, value:
            case "sort", {"key": str(key)} if key in ("customer", "total"):
                self.descending = key == self.sort_key and not self.descending
                self.sort_key = key
            case _:
                raise UnknownEventError(event)

    def render(self) -> Template:
        index = 0 if self.sort_key == "customer" else 2
        orders = sorted(self.orders, key=lambda o: o[index], reverse=self.descending)
        return table(
            COLUMNS,
            ([name, item, f"${total}"] for name, item, total in orders),
            caption="Orders",
            sort=(self.sort_key, "desc" if self.descending else "asc"),
            sort_event="sort",
            empty="No orders yet.",
        )
```

`table(columns, rows, *, caption, density, striped, empty, sort, sort_event,
target, stream)` renders a table in a wrapper that scrolls sideways when the
table is wider than its container.

- A column is a label, or a `TableColumn(label, key, align, sortable)`. `align`
  is `start`, `center`, or `end`; use `end` for numbers.
- Each row is an iterable with one cell per column. A row of another length
  raises `ValueError`.
- `empty` is shown across all columns when there are no rows.
- `density` is `comfortable` or `compact`, and `striped` shades every second
  row.

### Sorting

The page sorts. A sortable column's header is a button that pushes `sort_event`
with the column's `key` (its label when it has none). Pass the current order as
`sort=(key, direction)`, with `direction` `"asc"` or `"desc"`; the header then
reports it through `aria-sort` and an arrow. Sortable columns without a
`sort_event` raise `ValueError`.

### Streamed Rows

For a table the browser owns row by row, make the body a
[stream](../liveview/streams.md) container and build each item with
`table_row()`:

<!-- docs-test: skip -->

```python
def add(self, order_id: int, name: str, total: int) -> None:
    row_id = f"orders-{order_id}"
    self.stream_insert(
        "orders", row_id, table_row([name, total], columns=COLUMNS, id=row_id)
    )

def render(self) -> Template:
    return table(COLUMNS, stream=("orders", self.stream_contents("orders")))
```

Pass the same `columns` to `table_row()` so the cells get their alignment.

## Lists

`list_group(items, *, label)` joins `list_item()` rows in one bordered list.

```python
from tori_py_liveview_ui import avatar, badge, list_group, list_item

inbox = list_group(
    [
        list_item(
            "Ada Lovelace",
            description="Notes on the engine",
            leading=avatar("Ada Lovelace", size="sm"),
            trailing=badge("New", tone="info"),
            href="/messages/1",
            live="navigate",
            selected=True,
        ),
        list_item("Archive", event="open_archive"),
        list_item("Nothing else"),
    ],
    label="Messages",
)
```

A row with `href` is a link, a row with `event` is a button, and a row with
neither is plain content. `selected=True` highlights the row and sets
`aria-current`. Controls in `trailing` sit outside the row's own link or button,
so they stay separately clickable.

## Figures

| Helper | Output |
| --- | --- |
| `stat(label, value, *, delta, trend, tone, help_text, chart)` | One figure with its change |
| `sparkline(values, *, label, tone, area)` | A small line chart as inline SVG |
| `progress(*, label, value, maximum, tone, show_value)` | A native `<progress>` bar |
| `meter(*, label, value, minimum, maximum, low, high, optimum)` | A native `<meter>` |

```python
from tori_py_liveview_ui import sparkline, stat

revenue = stat(
    "Revenue",
    "$12.4k",
    delta="12%",
    trend="up",
    tone="success",
    chart=sparkline([4, 6, 5, 8, 9, 12], label="Rising for six weeks", area=True),
)
```

`trend` is `up`, `down`, or `flat` and draws an arrow; `tone` colors the change.
They are separate because a rise is not always good news.

`sparkline` needs at least two finite numbers and scales them to its box. Its
`label` is required and should say what the line shows, for readers who cannot
see it.

`progress` without a `value` is indeterminate. Use `progress` for a task that
moves toward completion and `meter` for a measurement within a range, such as
disk use.

## People and Labels

| Helper | Output |
| --- | --- |
| `avatar(name, *, src, size)` | A picture, or the initials of `name` |
| `avatar_group(children, *, label, extra)` | Overlapping avatars and a `+N` for the rest |
| `tag(content, *, tone, icon, remove_event, ...)` | A chip, optionally removable |
| `status_dot(label, *, tone, pulse)` | A colored dot with its meaning in words |
| `badge(content, *, tone)` | A small status label |

`avatar` always takes the person's `name`: it is the accessible name, and the
source of the initials when there is no `src`.

A `tag` with `remove_event` ends in a button. Give it `values` so the handler
knows which tag to remove, and a `remove_label` that names it:

```python
from tori_py_liveview_ui import tag

tag(
    "python",
    remove_event="untag",
    remove_label="Remove python",
    values={"tag": "python"},
)
```

`status_dot` always shows its `label`: color alone does not carry the state.

## Timeline, Empty State, Tooltip

`timeline(items)` renders `timeline_item(title, *, time, description, tone, id)`
entries as an ordered list with a marker per event.

`empty_state(title, *, description, icon, actions)` fills a region that has
nothing to show and says what to do next.

`tooltip(content, *, text, id, placement)` describes a term, an icon, or a badge
on hover and on keyboard focus. Escape hides it. The helper makes its content
focusable, so do not wrap a button or a link in it; give those a visible label,
or use [`icon_button`](actions.md#icon-buttons), whose label is also its
tooltip.

```python
from tori_py_liveview_ui import tooltip

tooltip("SLA", text="Service level agreement", id="tip-sla")
```

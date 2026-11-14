"""Gallery page for the helpers that present data."""

from __future__ import annotations

from string.templatelib import Template

from tori_py_liveview import UnknownEventError, live_view
from tori_py_liveview_ui import (
    TableColumn,
    avatar,
    avatar_group,
    badge,
    button,
    empty_state,
    grid,
    icon,
    list_group,
    list_item,
    meter,
    progress,
    row,
    sparkline,
    stack,
    stat,
    status_dot,
    table,
    tag,
    text,
    timeline,
    timeline_item,
    tooltip,
)

from examples.tori_py.liveview_ui_gallery.shell import GalleryPage, demo

_ORDERS = [
    ("Ada Lovelace", "Analytical engine", 1200),
    ("Grace Hopper", "Compiler", 870),
    ("Edsger Dijkstra", "Shortest path", 430),
]
_COLUMNS = [
    TableColumn("Customer", key="customer", sortable=True),
    "Item",
    TableColumn("Total", key="total", align="end", sortable=True),
]


@live_view("/display")
class DisplayLive(GalleryPage):
    heading = "Display"
    summary = "Tables, lists, figures, people, tags, and progress."
    path = "/display"

    def __init__(self) -> None:
        super().__init__()
        self.sort_key = "customer"
        self.descending = False
        self.folder = "inbox"
        self.tags = ["python", "liveview", "phoenix"]
        self.uploaded = 30

    async def handle_event(self, event: str, value: object) -> None:
        match event, value:
            case "sort", {"key": str(key)} if key in ("customer", "total"):
                self.descending = key == self.sort_key and not self.descending
                self.sort_key = key
            case "folder", {"name": str(name)}:
                self.folder = name
            case "untag", {"tag": str(name)}:
                self.tags = [item for item in self.tags if item != name]
            case "upload", _:
                self.uploaded = min(self.uploaded + 20, 100)
            case _:
                raise UnknownEventError(event)

    def render(self) -> Template:
        index = 0 if self.sort_key == "customer" else 2
        orders = sorted(
            _ORDERS, key=lambda order: order[index], reverse=self.descending
        )
        orders_table = table(
            _COLUMNS,
            ([name, item, f"${total}"] for name, item, total in orders),
            caption="Orders",
            sort=(self.sort_key, "desc" if self.descending else "asc"),
            sort_event="sort",
            striped=True,
        )
        empty_table = table(
            ["Invoice", "Due"], [], density="compact", empty="No invoices yet."
        )
        folders = list_group(
            (
                list_item(
                    label,
                    description=description,
                    leading=icon(glyph),
                    trailing=badge(count, tone="info") if count else None,
                    event="folder",
                    values={"name": name},
                    selected=self.folder == name,
                    id=f"folder-{name}",
                )
                for name, label, description, glyph, count in (
                    ("inbox", "Inbox", "New messages", "mail", 3),
                    ("starred", "Starred", "Kept for later", "star", 0),
                    ("archive", "Archive", "Everything else", "folder", 0),
                )
            ),
            label="Folders",
        )
        stats = grid(
            [
                stat(
                    "Revenue",
                    "$12.4k",
                    delta="12%",
                    trend="up",
                    tone="success",
                    chart=sparkline(
                        [4, 6, 5, 8, 9, 12], label="Rising", tone="success", area=True
                    ),
                ),
                stat(
                    "Errors",
                    "38",
                    delta="5%",
                    trend="down",
                    tone="danger",
                    help_text="In the last hour",
                ),
                stat("Latency", "120 ms", trend="flat"),
            ],
            columns="3",
        )
        people = stack(
            [
                row(
                    [
                        avatar("Ada Lovelace", size="sm"),
                        avatar("Grace Hopper"),
                        avatar("Edsger Dijkstra", size="lg"),
                    ],
                    gap="sm",
                ),
                avatar_group(
                    [avatar("Ada Lovelace"), avatar("Grace Hopper")],
                    label="Reviewers",
                    extra=4,
                ),
            ],
            align="start",
        )
        tags = row(
            (
                tag(
                    name,
                    tone="info",
                    remove_event="untag",
                    remove_label=f"Remove {name}",
                    values={"tag": name},
                )
                for name in self.tags
            ),
            gap="xs",
        )
        states = row(
            [
                status_dot("Online", tone="success", pulse=True),
                status_dot("Degraded", tone="warning"),
                status_dot("Offline", tone="danger"),
                tag("draft"),
                tag("beta", tone="warning", icon="zap"),
            ],
            gap="md",
        )
        history = timeline(
            [
                timeline_item(
                    "Deployed", time="12:04", description="Version 2.1", tone="success"
                ),
                timeline_item(
                    "Tests failed",
                    time="11:50",
                    description="2 failures",
                    tone="danger",
                ),
                timeline_item("Opened", time="11:32"),
            ]
        )
        nothing = empty_state(
            "No reports yet",
            description="Reports appear here once the first one has run.",
            icon="chart",
            actions=button("Run a report", size="sm"),
        )
        bars = stack(
            [
                progress(label="Upload", value=self.uploaded, show_value=True),
                progress(label="Working", tone="info"),
                meter(label="Disk use", value=72, low=50, high=80, optimum=20),
                row([button("Upload more", size="sm", event="upload")]),
            ]
        )
        term = tooltip("API", text="Application programming interface", id="tip-api")
        hint = text(t"The {term} answers in JSON.")
        return self.page(
            stack(
                [
                    orders_table,
                    stats,
                    grid(
                        [
                            demo("List group", folders),
                            demo("Empty table", empty_table),
                            demo("Avatars", people),
                            demo("Tags", stack([tags, states])),
                            demo("Timeline", history),
                            demo("Empty state", nothing),
                            demo("Progress and meter", bars),
                            demo("Tooltip", hint),
                        ],
                        columns="2",
                        gap="lg",
                    ),
                ],
                gap="lg",
            )
        )

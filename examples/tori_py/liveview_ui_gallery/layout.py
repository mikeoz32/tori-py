"""Gallery page for the helpers that arrange content."""

from __future__ import annotations

from string.templatelib import Template

from tori_py_liveview import live_view
from tori_py_liveview_ui import (
    badge,
    button,
    card,
    center,
    container,
    divider,
    grid,
    item_list,
    row,
    scroll_area,
    section,
    spacer,
    split,
    stack,
    text,
    toolbar,
)

from examples.tori_py.liveview_ui_gallery.shell import GalleryPage, demo


def _box(label: str) -> Template:
    return card(label)


@live_view("/layout")
class LayoutLive(GalleryPage):
    heading = "Layout"
    summary = "Rows, stacks, grids, panes, and regions. This page sits in app_shell."
    path = "/layout"

    def render(self) -> Template:
        rows = stack(
            [
                row([_box("One"), _box("Two"), _box("Three")], gap="sm"),
                row([_box("Start"), spacer(), _box("End")], gap="sm"),
                row(
                    [_box("Left"), divider(orientation="vertical"), _box("Right")],
                    gap="md",
                    align="stretch",
                ),
                row([_box("A"), _box("B")], justify="between"),
            ]
        )
        dividers = stack([text("Above"), divider(), divider(label="or"), text("Below")])
        panes = split(
            _box("Primary, one part"), _box("Secondary, two parts"), ratio="1:2"
        )
        tools = toolbar(
            [button("Filter", variant="secondary", icon="filter"), badge("12 results")],
            label="Results",
            end=[button("Export", variant="ghost", icon="download")],
        )
        centered = center(_box("Centered"), min_height="content")
        scrolling = scroll_area(
            item_list(f"Log line {number}" for number in range(1, 41)),
            label="Build log",
            max_height="sm",
        )
        narrow = container(_box("A small container"), size="sm", padded=False)
        team = section(
            grid([_box("Ada"), _box("Grace"), _box("Edsger")], columns="3"),
            title="Team",
            description="A section groups content under a heading.",
            actions=button("Invite", size="sm", icon="plus"),
            id="team",
        )
        return self.page(
            stack(
                [
                    grid(
                        [
                            demo("Row and spacer", rows),
                            demo("Divider", dividers),
                            demo("Split", panes),
                            demo("Toolbar", tools),
                            demo("Center", centered),
                            demo("Scroll area", scrolling),
                            demo("Container", narrow),
                        ],
                        columns="2",
                        gap="lg",
                    ),
                    team,
                ],
                gap="xl",
            )
        )

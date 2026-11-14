# Layout

Layout helpers arrange content and add no content of their own. They nest
freely: a `row` inside a `card` inside a `grid` inside an `app_shell`.

## A Page Layout

```python
from string.templatelib import Template

from tori_py_liveview import live_view
from tori_py_liveview_ui import (
    UiLiveView,
    app_shell,
    badge,
    button,
    card,
    container,
    grid,
    item_list,
    link,
    page_header,
    row,
    spacer,
    stack,
    toolbar,
)


@live_view("/orders")
class OrdersLive(UiLiveView):
    def render(self) -> Template:
        header = row([t"<strong>Shop</strong>", spacer(), badge("Beta")], wrap=False)
        sidebar = item_list(
            [
                link("Orders", href="/orders", live="navigate"),
                link("Customers", href="/customers", live="navigate"),
            ],
            marker="none",
        )
        filters = toolbar(
            [button("Filter", variant="secondary", icon="filter")],
            label="Orders",
            end=[button("Export", variant="ghost", icon="download")],
        )
        body = container(
            stack(
                [
                    page_header(
                        "Orders",
                        eyebrow="Shop",
                        description="Everything placed in the last 30 days.",
                        actions=button("New order", icon="plus"),
                    ),
                    filters,
                    grid([card("Open: 12"), card("Shipped: 48")], columns="2"),
                ],
                gap="lg",
            )
        )
        return app_shell(body, id="shop", header=header, sidebar=sidebar)
```

## Flow

| Helper | Use it for |
| --- | --- |
| `stack(children, *, gap, align)` | Children one under another |
| `row(children, *, gap, align, justify, wrap)` | Children side by side; wraps unless `wrap=False` |
| `grid(children, *, columns, gap)` | Equal columns that collapse on narrow screens |
| `split(primary, secondary, *, ratio, gap)` | Two panes that stack below 48rem |
| `spacer(*, size)` | Space between siblings; `"grow"` takes all that is free |
| `divider(*, label, orientation)` | A rule between siblings |

`gap` is `xs`, `sm`, `md`, `lg`, or `xl` everywhere and maps to the skin's
spacing tokens. `row` aligns its children with `align` (`start`, `center`,
`end`, `stretch`, `baseline`) and distributes them with `justify` (`start`,
`center`, `end`, `between`). `split` takes a `ratio` of `"1:1"`, `"1:2"`,
`"2:1"`, `"1:3"`, or `"3:1"`.

`stack` stretches its children to its own width by default, so a button in a
stack becomes full width. Pass `align="start"`, or wrap the button in a `row`.

A divider is horizontal by default and may carry a `label`. With
`orientation="vertical"` it separates the children of a row and stretches to
their height.

## Regions

| Helper | Output |
| --- | --- |
| `container(content, *, size, padded)` | A centered column of bounded width: `sm`, `md`, `lg`, `xl`, or `full` |
| `center(content, *, min_height)` | Content centered on both axes; `min_height` is `content`, `half`, or `screen` |
| `card(content, *, eyebrow, title, footer)` | An `<article>` with optional header and footer |
| `section(content, *, title, description, actions, id)` | A `<section>` under an `<h2>` |
| `page_header(title, *, eyebrow, description, actions, navigation)` | A `<header>` with the page's `<h1>` |
| `toolbar(start, *, label, end)` | A labeled group of controls with an optional group at the far end |
| `scroll_area(content, *, label, max_height)` | A labeled region that scrolls, also from the keyboard |

Give a `section` an `id` when the page links to it: the section then names
itself from its title for assistive technology. `toolbar` and `scroll_area`
require a `label`, their accessible name. A scroll area's `max_height` is `sm`,
`md`, `lg`, or `xl`.

A page has one `<h1>`. `page_header` renders it; use `heading` from the
[content helpers](content.md) for the rest of the outline.

## App Shell

`app_shell(content, *, id, header, sidebar, aside, footer)` fills the viewport.
The header and footer stay in place, and the sidebar, the main area, and the
aside scroll on their own. The shell renders the page's `<main>` landmark, so do
not wrap its content in another one.

| Region | Element | On screens narrower than 56rem |
| --- | --- | --- |
| `header` | `<header>` | Gains a menu button when there is a sidebar |
| `sidebar` | `<aside>` | Leaves the layout; the menu button opens it over the content |
| `content` | `<main>` | Takes the full width |
| `aside` | `<aside>` | Moves below the main area |
| `footer` | `<footer>` | Unchanged |

The browser keeps the open state of the sidebar, so opening it costs no round
trip and a server render does not close it. Escape, a click outside the
sidebar, and a live navigation close it. `sidebar_label` and `menu_label` name
the sidebar and the menu button; translate them with the rest of your interface.

`id` is required, must start with a letter, and may contain letters, digits,
`-`, and `_`, because the open and close commands select the shell by it. The
main area gets the ID `<id>-main`, the target for a
[`skip_link`](navigation.md#skip-link). The
sidebar's width and the aside's width are the CSS custom properties
`--tori-ui-sidebar-width` and `--tori-ui-aside-width`.

Pages that do not need an application frame can use `container` directly:

```python
from tori_py_liveview_ui import container, heading, text


def article() -> Template:
    return container(
        stack([heading("Changelog", level=1), text("Nothing yet.")]),
        size="md",
    )
```

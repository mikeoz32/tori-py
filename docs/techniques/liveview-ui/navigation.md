# Navigation

Navigation helpers render links between pages and positions within a set:
bars, link lists, breadcrumbs, pagination, steps, and tab links. Every link
takes the `live` option of [`link`](content.md#links), so it can be a normal
link, a patch of the current page, or a navigation to another live page.

```python
from string.templatelib import Template

from tori_py_liveview_ui import (
    app_shell,
    breadcrumbs,
    nav,
    nav_item,
    page_header,
    skip_link,
)


def frame(current: str, content: object) -> Template:
    sections = nav(
        [
            nav_item(
                label,
                href=path,
                live="navigate",
                icon=icon,
                current=path == current,
            )
            for label, path, icon in (
                ("Orders", "/orders", "file"),
                ("Customers", "/customers", "users"),
                ("Settings", "/settings", "settings"),
            )
        ],
        label="Sections",
    )
    header = page_header(
        "Orders",
        navigation=breadcrumbs([("Shop", "/"), ("Orders", None)], live="navigate"),
    )
    shell = app_shell(t"{header}{content}", id="shop", sidebar=sections)
    return t"{skip_link(href='#shop-main')}{shell}"
```

## Link Lists

`nav(items, *, label, orientation)` renders a `<nav>` landmark around a list of
`nav_item()` links. `label` names the landmark, which matters as soon as a page
has more than one. `orientation` is `vertical` or `horizontal`.

`nav_item(label, *, href, live, replace, external, current, icon, badge)`
renders one link. `current=True` marks the link to the page the visitor is on
with `aria-current="page"`. The page decides which one that is, usually by
comparing paths as above.

`navbar(*, brand, items, actions, label)` is a horizontal bar: a brand at the
start, `nav_item()` entries after it, and `actions` at the far end. Put it in
the header of an [`app_shell`](layout.md#app-shell), or at the top of a page.

## Skip Link

`skip_link(*, href, label)` lets keyboard users jump past the navigation that
repeats on every page. Render it first in the page. It stays off screen until
it receives focus.

`href` is the fragment of the main content. `app_shell(id="shop")` gives its
main area the ID `shop-main`, so the link is `skip_link(href="#shop-main")`.

## Breadcrumbs

`breadcrumbs(items, *, label, live)` shows where the page sits. Items are
`(label, href)` pairs from the top down. The last item is the current page and
is not a link, whatever its `href`.

## Pagination

`pagination(*, page, pages, href, live, event, target, siblings, ...)` renders
previous and next controls around page numbers. It always shows the first and
the last page and `siblings` pages on each side of the current one, with an
ellipsis where pages are skipped.

Give it one of two things:

```python
from tori_py_liveview_ui import pagination

# Links. The pattern must contain {page}.
pagination(page=2, pages=12, href="/orders?page={page}", live="patch")

# Buttons that push an event with {"page": "3"}.
pagination(page=2, pages=12, event="page")
```

Links keep the page number in the URL, so it survives a reload and can be
shared; with `live="patch"` the page reads it in
[`handle_params()`](../liveview/navigation.md). Use the event form for a list
whose position is not worth an address.

## Steps

`steps(items, *, current, label, complete_label)` shows the stages of a process.
An item is a title, or a `(title, description)` pair. `current` counts from 1:
earlier stages are complete, and a value one past the last stage means all of
them are.

```python
from tori_py_liveview_ui import steps

steps(["Cart", ("Payment", "Card or invoice"), "Review"], current=2)
```

## Tab Links

`tab_links(items, *, current, label, live)` renders links to sibling pages in
the look of tabs. Items are `(label, href)` pairs, and `current` is the `href`
of the page the visitor is on.

```python
from tori_py_liveview_ui import tab_links

tab_links(
    [("Profile", "/settings"), ("Billing", "/settings/billing")],
    current="/settings/billing",
    label="Settings",
    live="navigate",
)
```

These are links in a navigation landmark, and each one has its own URL. For
panels that switch within one page, use [`tabs`](disclosure.md#tabs).

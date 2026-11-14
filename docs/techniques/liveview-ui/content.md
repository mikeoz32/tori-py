# Content and Icons

Content helpers render text, code, lists, and media with the theme's
typography. Each one styles only the element it renders, so they sit next to
your own markup without a global reset.

```python
from string.templatelib import Template

from tori_py_liveview_ui import (
    code,
    code_block,
    description_list,
    heading,
    icon,
    item_list,
    kbd,
    link,
    stack,
    text,
)


def release_notes(version: str, changes: list[str]) -> Template:
    return stack(
        [
            heading(t"Release {version}", level=2),
            text(
                t"Install it with {code('uv add')} and read the "
                t"{link('migration guide', href='/docs/migrate', live='navigate')}."
            ),
            code_block("uv add tori-py-liveview-ui", language="shell"),
            item_list(changes),
            description_list([("Released", "1 March"), ("Python", "3.14")]),
            text(t"Press {kbd('?')} for shortcuts. {icon('info')}", size="sm"),
        ]
    )
```

## Text

| Helper | Output |
| --- | --- |
| `heading(content, *, level, size, id)` | `<h1>` to `<h6>` |
| `text(content, *, size, muted)` | `<p>`; `size` is `sm`, `md`, or `lg` |
| `link(label, *, href, live, replace, external)` | `<a>` |
| `code(content)` | Inline `<code>` |
| `kbd(content)` | `<kbd>` |
| `blockquote(content, *, cite)` | `<figure>` with a `<blockquote>` and an optional attribution |

`heading` separates the outline from the look. `level` (1 to 6) selects the
element, and `size` (`xs`, `sm`, `md`, `lg`, `xl`, `2xl`) selects the look. Each
level has a default size, so pass `size` only to depart from it:

```python
heading("Billing", level=3)             # third level, its default "lg" size
heading("Billing", level=3, size="sm")  # third level, small
```

## Links

`link` renders three kinds of link:

| Call | Result |
| --- | --- |
| `link("Docs", href="/docs")` | A normal link; the browser loads the page |
| `link("Next", href="/items?page=2", live="patch")` | Stays on the current live page and calls `handle_params()` |
| `link("Settings", href="/settings", live="navigate")` | Mounts another live page over the same connection |
| `link("Site", href="https://example.com", external=True)` | Opens a new tab without access to the opener |

Live links need a root-relative `href` such as `/settings`, and follow the rules
of [live navigation](../liveview/navigation.md). `replace=True` replaces the
current history entry instead of adding one. `href` values with an executable
scheme, such as `javascript:`, raise `ValueError`.

## Code

`code_block(content, *, language, copy, wrap)` renders a `<pre>` in a figure.
`language` is only a label. The copy button is on by default and copies the
code as the visitor sees it; `copy=False` removes it. `wrap=True` wraps long
lines instead of scrolling.

The block does not highlight. A string is escaped like any other content; pass
markup you have highlighted yourself as trusted content with `raw()`.

## Lists

`item_list(items, *, marker)` renders `<ul>`, or `<ol>` for `marker="number"`.
`marker="none"` drops the markers and the indent, for a list of links or rows.

`description_list(items, *, layout)` renders `(term, detail)` pairs as a `<dl>`.
The `"rows"` layout puts each detail beside its term and stacks below 48rem;
`"stacked"` always puts it underneath.

## Prose

`prose(content)` styles plain elements that carry no classes: headings,
paragraphs, lists, links, tables, code, and quotations. Use it around HTML you
did not build with the helpers, such as rendered Markdown.

```python
from tori_py_liveview import raw
from tori_py_liveview_ui import prose

article = prose(raw("<h2>Notes</h2><p>Plain <strong>markup</strong>.</p>"))
```

`prose` does not sanitize. Its content follows LiveView's
[escaping rules](../liveview/templates.md), so `raw()` content must already be
safe.

## Images

`image(*, src, alt, caption, ratio, fit, width, height, lazy)` renders an
`<img>` in a `<figure>`.

- `alt` is required. Pass `""` for an image that only decorates.
- `ratio` (`auto`, `square`, `video`, `wide`) reserves the image's box before it
  loads, so the page does not jump. `fit` is `cover` or `contain`.
- Images load lazily unless `lazy=False`. Turn it off for the image at the top
  of the page.

## Icons

`icon(name, *, size, label)` renders one of the bundled icons as inline SVG in
the current text color. The set is closed: an unknown name raises `ValueError`.
`size` is `sm`, `md`, or `lg`, relative to the surrounding text.

An icon is decorative by default and hidden from assistive technology. Give it a
`label` only when nothing else names its meaning:

```python
icon("check")                       # decoration next to visible text
icon("lock", label="Private")       # the only sign that the item is private
```

For a control that shows only an icon, use
[`icon_button`](actions.md#icon-buttons), which takes the name itself.

| Group | Names |
| --- | --- |
| Arrows | `arrow-down`, `arrow-left`, `arrow-right`, `arrow-up`, `chevron-down`, `chevron-left`, `chevron-right`, `chevron-up`, `external-link` |
| Actions | `check`, `copy`, `download`, `edit`, `filter`, `maximize`, `menu`, `minus`, `more-horizontal`, `more-vertical`, `paperclip`, `pause`, `play`, `plus`, `refresh`, `search`, `send`, `settings`, `stop`, `trash`, `upload`, `x` |
| Status | `alert-circle`, `alert-triangle`, `check-circle`, `circle`, `circle-dot`, `clock`, `help-circle`, `info`, `x-circle` |
| People and AI | `bot`, `lightbulb`, `message`, `mic`, `sparkles`, `thumbs-down`, `thumbs-up`, `user`, `users`, `zap` |
| Objects | `bell`, `bookmark`, `calendar`, `chart`, `code`, `database`, `file`, `folder`, `globe`, `heart`, `home`, `image`, `link`, `lock`, `log-out`, `mail`, `shield`, `sidebar`, `star`, `tag`, `terminal`, `tool` |
| Display | `eye`, `eye-off`, `monitor`, `moon`, `sun` |

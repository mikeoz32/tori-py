"""Helpers for text, code, lists, and media."""

from __future__ import annotations

from collections.abc import Iterable
from string.templatelib import Template
from typing import Literal

from tori_py_liveview import attrs, classes, fragment, raw

from tori_py_liveview_ui._shared import (
    LiveLink,
    boolean,
    bounded_integer,
    html_id,
    link_attributes,
    one_of,
    optional_nonempty_text,
    required_text,
)
from tori_py_liveview_ui.actions import copy_button
from tori_py_liveview_ui.icons import icon

type HeadingLevel = Literal[1, 2, 3, 4, 5, 6]
type HeadingSize = Literal["xs", "sm", "md", "lg", "xl", "2xl"]
type TextSize = Literal["sm", "md", "lg"]
type ListMarker = Literal["bullet", "number", "none"]
type DescriptionLayout = Literal["rows", "stacked"]
type ImageRatio = Literal["auto", "square", "video", "wide"]
type ImageFit = Literal["cover", "contain"]

_HEADING_SIZES = frozenset({"xs", "sm", "md", "lg", "xl", "2xl"})
_HEADING_DEFAULT_SIZES: dict[int, HeadingSize] = {
    1: "2xl",
    2: "xl",
    3: "lg",
    4: "md",
    5: "sm",
    6: "xs",
}
_TEXT_SIZES = frozenset({"sm", "md", "lg"})
_LIST_MARKERS = frozenset({"bullet", "number", "none"})
_DESCRIPTION_LAYOUTS = frozenset({"rows", "stacked"})
_IMAGE_RATIOS = frozenset({"auto", "square", "video", "wide"})
_IMAGE_FITS = frozenset({"cover", "contain"})


def heading(
    content: object,
    *,
    level: HeadingLevel = 2,
    size: HeadingSize | None = None,
    id: str | None = None,
) -> Template:
    """Render a heading whose visual size is independent of its level.

    Choose ``level`` for the document outline and, when the design calls for
    it, ``size`` for the look. Without ``size`` each level has its own.
    """
    if type(level) is not int or not 1 <= level <= 6:
        raise ValueError("heading level must be an integer between 1 and 6")
    if size is None:
        size = _HEADING_DEFAULT_SIZES[level]
    one_of("heading size", size, _HEADING_SIZES)
    if id is not None:
        id = html_id("heading id", id)
    attributes = attrs(
        {"id": id, "class": classes("tori-ui-heading", f"tori-ui-heading--{size}")}
    )
    match level:
        case 1:
            return t"<h1{attributes}>{content}</h1>"
        case 2:
            return t"<h2{attributes}>{content}</h2>"
        case 3:
            return t"<h3{attributes}>{content}</h3>"
        case 4:
            return t"<h4{attributes}>{content}</h4>"
        case 5:
            return t"<h5{attributes}>{content}</h5>"
        case _:
            return t"<h6{attributes}>{content}</h6>"


def text(
    content: object,
    *,
    size: TextSize = "md",
    muted: bool = False,
) -> Template:
    """Render a paragraph."""
    one_of("text size", size, _TEXT_SIZES)
    boolean("text muted", muted)
    class_name = classes(
        "tori-ui-text",
        f"tori-ui-text--{size}",
        **{"tori-ui-text--muted": muted},
    )
    return t'<p class="{class_name}">{content}</p>'


def link(
    label: object,
    *,
    href: str,
    live: LiveLink | None = None,
    replace: bool = False,
    external: bool = False,
) -> Template:
    """Render a text link.

    ``live="patch"`` stays on the current page and ``live="navigate"`` moves to
    another live page without a full reload; both need a root-relative
    ``href``. ``external`` opens the link in a new tab without access to the
    opener.
    """
    attributes = attrs(
        {
            "class": "tori-ui-link",
            **link_attributes("link", href, live, replace, external),
        }
    )
    marker = icon("external-link", size="sm") if external else raw("")
    return t"<a{attributes}>{label}{marker}</a>"


def code(content: object) -> Template:
    """Render inline code."""
    return t'<code class="tori-ui-code">{content}</code>'


def code_block(
    content: object,
    *,
    language: str | None = None,
    copy: bool = True,
    wrap: bool = False,
    copy_label: str = "Copy",
    copied_label: str = "Copied",
) -> Template:
    """Render a block of code with an optional language label and copy button.

    The block does not highlight the code. Pass already highlighted markup as
    trusted content when you have it.
    """
    language = optional_nonempty_text("code block language", language)
    boolean("code block copy", copy)
    boolean("code block wrap", wrap)
    class_name = classes(
        "tori-ui-code-block",
        **{"tori-ui-code-block--wrap": wrap},
    )
    language_markup = (
        t'<span class="tori-ui-code-block__language">{language}</span>'
        if language is not None
        else raw("")
    )
    copy_markup = (
        copy_button(
            to=("closest", ".tori-ui-code-block"),
            label=copy_label,
            copied_label=copied_label,
        )
        if copy
        else raw("")
    )
    header_markup = (
        t'<figcaption class="tori-ui-code-block__header">{language_markup}'
        t"{copy_markup}</figcaption>"
        if language is not None or copy
        else raw("")
    )
    return (
        t'<figure class="{class_name}">{header_markup}'
        t'<pre class="tori-ui-code-block__pre" tabindex="0">'
        t"<code data-tori-ui-copy-source>{content}</code></pre></figure>"
    )


def kbd(content: object) -> Template:
    """Render a keyboard key or shortcut."""
    return t'<kbd class="tori-ui-kbd">{content}</kbd>'


def blockquote(content: object, *, cite: object | None = None) -> Template:
    """Render a quotation with an optional attribution."""
    cite_markup = (
        t'<figcaption class="tori-ui-blockquote__cite">{cite}</figcaption>'
        if cite is not None
        else raw("")
    )
    return (
        t'<figure class="tori-ui-blockquote"><blockquote '
        t'class="tori-ui-blockquote__quote">{content}</blockquote>{cite_markup}'
        t"</figure>"
    )


def prose(content: object) -> Template:
    """Style plain HTML elements, such as rendered Markdown, inside one block.

    The helper styles headings, paragraphs, lists, links, tables, code, and
    quotations that carry no classes of their own. It does not sanitize: the
    content follows the usual escaping rules, so pass trusted markup only.
    """
    return t'<div class="tori-ui-prose">{content}</div>'


def item_list(
    items: Iterable[object],
    *,
    marker: ListMarker = "bullet",
) -> Template:
    """Render a list; ``marker="number"`` makes it an ordered list."""
    one_of("item list marker", marker, _LIST_MARKERS)
    class_name = classes("tori-ui-list", f"tori-ui-list--{marker}")
    content = fragment(t"<li>{item}</li>" for item in items)
    if marker == "number":
        return t'<ol class="{class_name}">{content}</ol>'
    return t'<ul class="{class_name}">{content}</ul>'


def description_list(
    items: Iterable[tuple[object, object]],
    *,
    layout: DescriptionLayout = "rows",
) -> Template:
    """Render term and detail pairs, side by side or stacked."""
    one_of("description list layout", layout, _DESCRIPTION_LAYOUTS)
    class_name = classes(
        "tori-ui-description-list",
        f"tori-ui-description-list--{layout}",
    )
    rows: list[Template] = []
    for item in items:
        if not isinstance(item, tuple) or len(item) != 2:
            raise TypeError("description list items must be two-item tuples")
        term, detail = item
        rows.append(
            t'<div class="tori-ui-description-list__item"><dt>{term}</dt>'
            t"<dd>{detail}</dd></div>"
        )
    return t'<dl class="{class_name}">{fragment(rows)}</dl>'


def image(
    *,
    src: str,
    alt: str,
    caption: object | None = None,
    ratio: ImageRatio = "auto",
    fit: ImageFit = "cover",
    width: int | None = None,
    height: int | None = None,
    lazy: bool = True,
) -> Template:
    """Render an image in a figure with an optional caption.

    ``alt`` is required; pass an empty string for a decorative image. A fixed
    ``ratio`` reserves the image's space before it loads.
    """
    src = required_text("image source", src)
    if not isinstance(alt, str):
        raise TypeError("image alternative text must be a string")
    one_of("image ratio", ratio, _IMAGE_RATIOS)
    one_of("image fit", fit, _IMAGE_FITS)
    if width is not None:
        bounded_integer("image width", width, 1, 16384)
    if height is not None:
        bounded_integer("image height", height, 1, 16384)
    boolean("image lazy", lazy)
    attributes = attrs(
        {
            "class": classes("tori-ui-image__media", f"tori-ui-image__media--{fit}"),
            "src": src,
            "alt": alt,
            "width": width,
            "height": height,
            "loading": "lazy" if lazy else None,
            "decoding": "async",
        }
    )
    caption_markup = (
        t'<figcaption class="tori-ui-image__caption">{caption}</figcaption>'
        if caption is not None
        else raw("")
    )
    class_name = classes("tori-ui-image", f"tori-ui-image--{ratio}")
    return t'<figure class="{class_name}"><img{attributes}>{caption_markup}</figure>'


__all__ = [
    "blockquote",
    "code",
    "code_block",
    "description_list",
    "heading",
    "image",
    "item_list",
    "kbd",
    "link",
    "prose",
    "text",
]

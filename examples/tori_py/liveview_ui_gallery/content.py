"""Gallery page for text, code, lists, media, and icons."""

from __future__ import annotations

from string.templatelib import Template
from typing import get_args

from tori_py_liveview import live_view, raw
from tori_py_liveview_ui import (
    blockquote,
    code,
    code_block,
    description_list,
    grid,
    heading,
    icon,
    image,
    item_list,
    kbd,
    link,
    prose,
    row,
    stack,
    text,
)
from tori_py_liveview_ui.icons import IconName

from examples.tori_py.liveview_ui_gallery.shell import GalleryPage, demo

SAMPLE_IMAGE = "/gallery/sample.svg"

_SNIPPET = """@live_view("/hello")
class HelloLive(UiLiveView):
    def render(self) -> Template:
        return container(heading("Hello", level=1))
"""

# Trusted markup, as a Markdown renderer would produce it.
_ARTICLE = raw(
    "<h2>Release notes</h2>"
    "<p>Version <code>0.2</code> adds a <a href='/content'>component library</a> "
    "with <strong>stateless</strong> helpers.</p>"
    "<ul><li>Layout and content</li><li>Icons</li></ul>"
    "<blockquote>Plain elements get their look from the prose block.</blockquote>"
    "<table><thead><tr><th>Family</th><th>Helpers</th></tr></thead>"
    "<tbody><tr><td>Layout</td><td>14</td></tr>"
    "<tr><td>Content</td><td>11</td></tr></tbody></table>"
    "<pre><code>uv add tori-py-liveview-ui</code></pre>"
)


@live_view("/content")
class ContentLive(GalleryPage):
    heading = "Content"
    summary = "Headings, text, code, lists, media, and the bundled icons."
    path = "/content"

    def render(self) -> Template:
        headings = stack(
            [
                heading("Heading 2xl", level=3, size="2xl"),
                heading("Heading xl", level=3, size="xl"),
                heading("Heading lg", level=3, size="lg"),
                heading("Heading md", level=3, size="md"),
                heading("Heading sm", level=3, size="sm"),
                heading("Heading xs", level=3, size="xs"),
            ],
            gap="sm",
        )
        shortcut = t"{kbd('Ctrl')} + {kbd('K')}"
        live = link("live link", href=self.href("/layout"), live="navigate")
        external = link("external link", href="https://example.com", external=True)
        texts = stack(
            [
                text("A lead paragraph introduces the page.", size="lg"),
                text(
                    t"Body text can hold {code('inline code')}, a {live}, an "
                    t"{external}, and a shortcut such as {shortcut}."
                ),
                text("Small muted text recedes.", size="sm", muted=True),
            ]
        )
        codes = stack(
            [
                code_block(_SNIPPET, language="python"),
                code_block("a very long line " * 12, wrap=True, copy=False),
            ]
        )
        quote = blockquote(
            "Make it work, make it right, make it fast.", cite="Kent Beck"
        )
        lists = grid(
            [
                item_list(["Bulleted", "items", "by default"]),
                item_list(["Numbered", "when", "ordered"], marker="number"),
                item_list(["No markers", "for menus"], marker="none"),
            ],
            columns="3",
        )
        details = description_list(
            [("Plan", "Team"), ("Seats", 12), ("Renews", "1 March")]
        )
        media = image(
            src=SAMPLE_IMAGE,
            alt="Three overlapping circles",
            caption="A local image with a reserved 16:9 box.",
            ratio="video",
        )
        icons = row(
            (
                t'<span title="{name}">{icon(name)}</span>'
                for name in get_args(IconName.__value__)
            ),
            gap="md",
        )
        return self.page(
            stack(
                [
                    grid(
                        [
                            demo("Headings", headings),
                            demo("Text, links, and keys", texts),
                            demo("Code blocks", codes),
                            demo("Blockquote", quote),
                            demo("Lists", lists),
                            demo("Description list", details),
                            demo("Image", media),
                            demo("Prose", prose(_ARTICLE)),
                        ],
                        columns="2",
                        gap="lg",
                    ),
                    demo("Icons", icons),
                ],
                gap="lg",
            )
        )

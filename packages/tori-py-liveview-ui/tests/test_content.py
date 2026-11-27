from __future__ import annotations

from collections.abc import Callable
from string.templatelib import Template
from typing import Any, cast

import pytest
import tori_py_liveview_ui
from tori_py_liveview import html, raw
from tori_py_liveview_ui import (
    blockquote,
    code,
    code_block,
    content,
    description_list,
    heading,
    image,
    item_list,
    kbd,
    link,
    prose,
    text,
)

ui = tori_py_liveview_ui


def _render(template: Template) -> str:
    return html(template).to_html()


def test_content_family_is_explicit() -> None:
    assert content.__all__ == [
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


@pytest.mark.parametrize(
    ("level", "size"),
    [(1, "2xl"), (2, "xl"), (3, "lg"), (4, "md"), (5, "sm"), (6, "xs")],
)
def test_heading_level_selects_the_element_and_the_default_size(
    level: int, size: str
) -> None:
    assert _render(heading("A<b", level=cast(Any, level))) == (
        f'<h{level} class="tori-ui-heading tori-ui-heading--{size}">A&lt;b</h{level}>'
    )


def test_heading_size_is_independent_of_its_level() -> None:
    assert _render(heading("Title", level=1, size="md", id="title")) == (
        '<h1 id="title" class="tori-ui-heading tori-ui-heading--md">Title</h1>'
    )
    assert _render(heading("Title")).startswith("<h2 ")


def test_text_code_and_kbd_escape_their_content() -> None:
    assert _render(text("a < b")) == (
        '<p class="tori-ui-text tori-ui-text--md">a &lt; b</p>'
    )
    assert _render(text("note", size="sm", muted=True)) == (
        '<p class="tori-ui-text tori-ui-text--sm tori-ui-text--muted">note</p>'
    )
    assert _render(code("<x>")) == '<code class="tori-ui-code">&lt;x&gt;</code>'
    assert _render(kbd("Ctrl")) == '<kbd class="tori-ui-kbd">Ctrl</kbd>'


def test_link_is_plain_live_or_external() -> None:
    assert _render(link("Docs", href="/docs")) == (
        '<a class="tori-ui-link" href="/docs">Docs</a>'
    )
    assert _render(link("Next", href="/items?page=2", live="patch")) == (
        '<a class="tori-ui-link" href="/items?page=2" data-phx-link="patch" '
        'data-phx-link-state="push">Next</a>'
    )
    assert _render(link("Home", href="/", live="navigate", replace=True)) == (
        '<a class="tori-ui-link" href="/" data-phx-link="redirect" '
        'data-phx-link-state="replace">Home</a>'
    )
    external = _render(link("Site", href="https://example.com", external=True))
    assert external.startswith(
        '<a class="tori-ui-link" href="https://example.com" target="_blank" '
        'rel="noopener noreferrer">Site<svg class="tori-ui-icon tori-ui-icon--sm"'
    )
    assert 'aria-hidden="true"' in external


@pytest.mark.parametrize(
    "href", ["https://example.com/x", "//example.com/x", "docs", "/a\\b"]
)
def test_live_link_requires_a_root_relative_path(href: str) -> None:
    with pytest.raises(ValueError, match="live href must be a root-relative path"):
        link("x", href=href, live="navigate")


def test_link_rejects_executable_url_schemes() -> None:
    with pytest.raises(ValueError, match="unsafe URL scheme"):
        link("x", href="javascript:alert(1)")


def test_code_block_marks_the_copy_source_and_targets_its_own_figure() -> None:
    result = _render(code_block("print('<hi>')", language="python"))

    assert result.startswith(
        '<figure class="tori-ui-code-block">'
        '<figcaption class="tori-ui-code-block__header" data-tori-ui-copy-exclude>'
        '<span class="tori-ui-code-block__language">python</span>'
        '<button type="button" class="tori-ui-button tori-ui-button--ghost '
        'tori-ui-button--sm tori-ui-copy-button" aria-label="Copy" phx-click="'
    )
    assert "&quot;closest&quot;:&quot;.tori-ui-code-block&quot;" in result
    assert result.endswith(
        '</figcaption><pre class="tori-ui-code-block__pre" tabindex="0">'
        "<code data-tori-ui-copy-source>print(&#x27;&lt;hi&gt;&#x27;)</code></pre>"
        "</figure>"
    )


def test_code_block_without_language_or_copy_has_no_header() -> None:
    assert _render(code_block("x", copy=False, wrap=True)) == (
        '<figure class="tori-ui-code-block tori-ui-code-block--wrap">'
        '<pre class="tori-ui-code-block__pre" tabindex="0">'
        "<code data-tori-ui-copy-source>x</code></pre></figure>"
    )
    labeled = _render(code_block("x", language="sql", copy=False))
    assert "tori-ui-code-block__language" in labeled
    assert "tori-ui-copy-button" not in labeled


def test_code_block_keeps_trusted_highlighted_markup() -> None:
    result = _render(code_block(raw('<span class="k">def</span>'), copy=False))

    assert '<code data-tori-ui-copy-source><span class="k">def</span></code>' in result


def test_blockquote_and_prose_wrap_their_content() -> None:
    assert _render(blockquote("Less is more.", cite="Mies")) == (
        '<figure class="tori-ui-blockquote">'
        '<blockquote class="tori-ui-blockquote__quote">Less is more.</blockquote>'
        '<figcaption class="tori-ui-blockquote__cite">Mies</figcaption></figure>'
    )
    assert "figcaption" not in _render(blockquote("Less is more."))
    assert _render(prose(t"<p>{'<b>'}</p>")) == (
        '<div class="tori-ui-prose"><p>&lt;b&gt;</p></div>'
    )


def test_item_list_marker_selects_the_list_element() -> None:
    assert _render(item_list(["a", t"<b>b</b>"])) == (
        '<ul class="tori-ui-list tori-ui-list--bullet"><li>a</li><li><b>b</b></li></ul>'
    )
    assert _render(item_list(["a"], marker="number")) == (
        '<ol class="tori-ui-list tori-ui-list--number"><li>a</li></ol>'
    )
    assert _render(item_list([], marker="none")) == (
        '<ul class="tori-ui-list tori-ui-list--none"></ul>'
    )


def test_description_list_groups_each_term_with_its_detail() -> None:
    assert _render(description_list([("Plan", "Pro"), ("Seats", 5)])) == (
        '<dl class="tori-ui-description-list tori-ui-description-list--rows">'
        '<div class="tori-ui-description-list__item"><dt>Plan</dt><dd>Pro</dd></div>'
        '<div class="tori-ui-description-list__item"><dt>Seats</dt><dd>5</dd></div>'
        "</dl>"
    )
    assert "tori-ui-description-list--stacked" in _render(
        description_list([], layout="stacked")
    )


def test_image_requires_alternative_text_and_reserves_its_ratio() -> None:
    assert _render(
        image(src="/cat.png", alt="A cat", caption="Tom", ratio="video", width=640)
    ) == (
        '<figure class="tori-ui-image tori-ui-image--video">'
        '<img class="tori-ui-image__media tori-ui-image__media--cover" '
        'src="/cat.png" alt="A cat" width="640" loading="lazy" decoding="async">'
        '<figcaption class="tori-ui-image__caption">Tom</figcaption></figure>'
    )
    decorative = _render(image(src="/rule.png", alt="", fit="contain", lazy=False))
    assert 'alt=""' in decorative
    assert "loading=" not in decorative
    assert "tori-ui-image__media--contain" in decorative
    assert "figcaption" not in decorative


@pytest.mark.parametrize(
    ("call", "error", "message"),
    [
        (lambda: ui.heading("x", id=""), ValueError, "heading id cannot be empty"),
        (lambda: ui.link("x", href=""), ValueError, "link href cannot be empty"),
        (
            lambda: ui.link("x", href="/a", replace=True),
            ValueError,
            "link replace requires a live link",
        ),
        (
            lambda: ui.link("x", href="/a", live="patch", external=True),
            ValueError,
            "link cannot be both live and external",
        ),
        (
            lambda: ui.code_block("x", language=" "),
            ValueError,
            "code block language cannot be empty",
        ),
        (
            lambda: ui.image(src="", alt="x"),
            ValueError,
            "image source cannot be empty",
        ),
        (
            lambda: ui.image(src="/a.png", alt="x", width=0),
            ValueError,
            "image width must be between",
        ),
        (
            lambda: ui.image(src="javascript:alert(1)", alt="x"),
            ValueError,
            "unsafe URL scheme",
        ),
    ],
)
def test_content_helpers_reject_values_outside_their_contract(
    call: Callable[[], Any], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        call()

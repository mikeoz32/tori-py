"""Markdown rendering behind the optional ``markdown`` and ``highlight`` extras."""

from __future__ import annotations

import re
from functools import cache
from string.templatelib import Template
from typing import TYPE_CHECKING, Any

from tori_py_liveview import html, raw

from tori_py_liveview_ui._shared import boolean
from tori_py_liveview_ui.content import code_block, prose

if TYPE_CHECKING:
    from markdown_it import MarkdownIt

_ABSOLUTE = re.compile(r"(?:https?:)?//", re.IGNORECASE)
_LANGUAGE = re.compile(r"[A-Za-z0-9_+#.-]{1,32}")
_MARKDOWN_EXTRA = (
    'markdown() requires the "markdown" extra: uv add "tori-py-liveview-ui[markdown]"'
)
_HIGHLIGHT_EXTRA = (
    'markdown(highlight=True) requires the "highlight" extra: '
    'uv add "tori-py-liveview-ui[highlight]"'
)


def _language(info: str) -> str | None:
    """Return a fence's language when it is a plain identifier."""
    words = info.split()
    if not words or _LANGUAGE.fullmatch(words[0]) is None:
        return None
    return words[0]


def _highlighted(code: str, language: str | None) -> object:
    try:
        from pygments import highlight
        from pygments.formatters.html import HtmlFormatter
        from pygments.lexers import get_lexer_by_name
        from pygments.util import ClassNotFound
    except ImportError as error:
        raise RuntimeError(_HIGHLIGHT_EXTRA) from error
    if language is None:
        return code
    try:
        lexer = get_lexer_by_name(language)
    except ClassNotFound:
        return code
    # Pygments escapes the code; its output is spans with prefixed classes.
    formatter = HtmlFormatter(nowrap=True, classprefix="tori-ui-hl-")
    return raw(highlight(code, lexer, formatter))


@cache
def _parser(highlight: bool, images: bool) -> MarkdownIt:
    try:
        from markdown_it import MarkdownIt
    except ImportError as error:
        raise RuntimeError(_MARKDOWN_EXTRA) from error
    # Raw HTML stays text, and the parser refuses javascript:, vbscript:,
    # file:, and non-image data: link targets.
    parser = MarkdownIt("commonmark", {"html": False}).enable(
        ["table", "strikethrough"]
    )
    if not images:
        # Without the rule, image syntax becomes an ordinary link.
        parser.disable("image")

    def fence(self: Any, tokens: Any, index: int, options: Any, env: Any) -> str:
        token = tokens[index]
        language = _language(token.info)
        code = token.content.removesuffix("\n")
        content = _highlighted(code, language) if highlight else code
        return html(code_block(content, language=language)).to_html()

    def link_open(self: Any, tokens: Any, index: int, options: Any, env: Any) -> str:
        token = tokens[index]
        if _ABSOLUTE.match(token.attrGet("href") or ""):
            token.attrSet("target", "_blank")
            token.attrSet("rel", "noopener noreferrer nofollow")
        return self.renderToken(tokens, index, options, env)

    parser.add_render_rule("fence", fence)
    parser.add_render_rule("code_block", fence)
    parser.add_render_rule("link_open", link_open)
    return parser


def markdown(
    source: str,
    *,
    highlight: bool = False,
    images: bool = False,
) -> Template:
    """Render CommonMark, with tables and strikethrough, as styled prose.

    The source is untrusted text, such as a model's answer: raw HTML in it is
    shown as text, and links with an executable scheme are not made links.
    Links to other sites open in a new tab without access to the opener. Fenced
    code becomes a ``code_block()`` with a copy button.

    ``images`` is off by default, so image syntax renders as a plain link and
    nothing is fetched from an address the text chose. ``highlight`` colors
    fenced code and needs the ``highlight`` extra.
    """
    if not isinstance(source, str):
        raise TypeError("markdown source must be a string")
    boolean("markdown highlight", highlight)
    boolean("markdown images", images)
    return prose(raw(_parser(highlight, images).render(source)))


__all__ = ["markdown"]

from __future__ import annotations

import builtins
from string.templatelib import Template
from typing import Any

import pytest
import tori_py_liveview_ui
from tori_py_liveview import LiveView, html
from tori_py_liveview_ui import chat_message, markdown, rich_text
from tori_py_liveview_ui.rich_text import _parser

ui = tori_py_liveview_ui


def _render(template: Template) -> str:
    return html(template).to_html()


def test_rich_text_family_is_explicit() -> None:
    assert rich_text.__all__ == ["markdown"]


def test_markdown_renders_commonmark_inside_prose() -> None:
    result = _render(markdown("# Title\n\nSome **bold** and `code`.\n\n- one\n- two"))

    assert result.startswith('<div class="tori-ui-prose"><h1>Title</h1>')
    assert "<p>Some <strong>bold</strong> and <code>code</code>.</p>" in result
    assert "<ul>\n<li>one</li>\n<li>two</li>\n</ul>" in result


def test_markdown_renders_tables_and_strikethrough() -> None:
    result = _render(markdown("| a | b |\n|---|---|\n| 1 | 2 |\n\n~~old~~"))

    assert "<table>" in result
    assert "<th>a</th>" in result
    assert "<td>2</td>" in result
    assert "<s>old</s>" in result


def test_markdown_shows_raw_html_as_text() -> None:
    result = _render(
        markdown('<script>alert(1)</script>\n\n<img src=x onerror="alert(1)">\n\n<b>x')
    )

    assert "<script" not in result
    assert "<img" not in result
    assert "<b>" not in result
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in result
    assert "onerror=&quot;alert(1)&quot;" in result


@pytest.mark.parametrize(
    "target",
    [
        "javascript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "vbscript:msgbox(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
    ],
)
def test_markdown_does_not_link_executable_or_local_schemes(target: str) -> None:
    result = _render(markdown(f"[click]({target})"))

    assert "<a " not in result
    assert "href=" not in result


def test_markdown_opens_other_sites_in_a_new_tab_without_the_opener() -> None:
    result = _render(
        markdown("[site](https://example.com/a) [same](/docs) [frag](#top)")
    )

    assert (
        '<a href="https://example.com/a" target="_blank" '
        'rel="noopener noreferrer nofollow">site</a>'
    ) in result
    assert '<a href="/docs">same</a>' in result
    assert '<a href="#top">frag</a>' in result
    assert 'target="_blank"' in _render(markdown("[cdn](//example.com/x)"))


def test_markdown_does_not_fetch_images_unless_asked() -> None:
    source = "![chart](https://example.com/chart.png)"
    plain = _render(markdown(source))

    assert "<img" not in plain
    assert ">chart</a>" in plain
    with_images = _render(markdown(source, images=True))
    assert '<img src="https://example.com/chart.png" alt="chart"' in with_images


def test_fenced_code_becomes_a_code_block_with_a_copy_button() -> None:
    result = _render(markdown('```python\nprint("<hi>")\n```'))

    assert '<figure class="tori-ui-code-block">' in result
    assert '<span class="tori-ui-code-block__language">python</span>' in result
    assert "tori-ui-copy-button" in result
    assert (
        "<code data-tori-ui-copy-source>print(&quot;&lt;hi&gt;&quot;)</code></pre>"
    ) in result


def test_fence_language_must_be_a_plain_identifier() -> None:
    odd = _render(markdown('```"><script>alert(1)</script>\nx\n```'))

    assert "tori-ui-code-block__language" not in odd
    assert "<script" not in odd
    indented = _render(markdown("    indented code"))
    assert "<code data-tori-ui-copy-source>indented code</code>" in indented
    assert "tori-ui-code-block__language" not in indented


def test_an_unclosed_fence_renders_as_code_while_it_streams() -> None:
    result = _render(markdown("Here:\n\n```python\ndef f():"))

    assert "<code data-tori-ui-copy-source>def f():</code>" in result


def test_highlight_colors_known_languages_with_prefixed_classes() -> None:
    result = _render(markdown('```python\ndef f(): return "<x>"\n```', highlight=True))

    assert '<span class="tori-ui-hl-k">def</span>' in result
    assert "&lt;x&gt;" in result
    assert "<x>" not in result
    # Classes come only from Pygments' token names behind the prefix.
    assert 'class="k"' not in result
    unknown = _render(markdown("```nosuchlanguage\nx < y\n```", highlight=True))
    assert "<code data-tori-ui-copy-source>x &lt; y</code>" in unknown
    assert "tori-ui-hl-" not in unknown


def test_markdown_output_is_a_valid_stream_item_inside_a_message() -> None:
    class Page(LiveView):
        def render(self) -> str:
            return ""

    source = (
        "Line one  \nline two\n\n---\n\n```python\nx = 1\n```\n\n| a |\n|---|\n| 1 |"
    )
    message = chat_message(markdown(source, highlight=True), id="m1")

    # Raises when the item is not one balanced root element with this ID.
    Page().stream_insert("messages", "m1", message)


def test_missing_extras_are_reported_with_the_install_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def without(blocked: str):
        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == blocked or name.startswith(f"{blocked}."):
                raise ImportError(f"No module named {name!r}")
            return real_import(name, *args, **kwargs)

        return fake_import

    _parser.cache_clear()
    monkeypatch.setattr(builtins, "__import__", without("markdown_it"))
    with pytest.raises(RuntimeError, match=r"tori-py-liveview-ui\[markdown\]"):
        markdown("x")

    _parser.cache_clear()
    monkeypatch.setattr(builtins, "__import__", without("pygments"))
    with pytest.raises(RuntimeError, match=r"tori-py-liveview-ui\[highlight\]"):
        markdown("```python\nx\n```", highlight=True)
    monkeypatch.undo()
    _parser.cache_clear()

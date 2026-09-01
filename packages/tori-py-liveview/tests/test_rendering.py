from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import cast

import pytest
from tori_py_liveview import LiveView, Rendered, raw, rendered


def _set_attribute(target: object, name: str, value: object) -> None:
    setattr(target, name, value)


def test_structured_render_escapes_values_and_diffs_changed_positions() -> None:
    initial = rendered(
        ("<p>", ": ", "</p>"),
        '<Mike & "Tori">',
        1,
    )
    updated = rendered(
        ("<p>", ": ", "</p>"),
        '<Mike & "Tori">',
        2,
    )

    assert initial.to_html() == "<p>&lt;Mike &amp; &quot;Tori&quot;&gt;: 1</p>"
    assert initial.statics == ("<p>", ": ", "</p>")
    assert initial.dynamics == ("&lt;Mike &amp; &quot;Tori&quot;&gt;", "1")
    assert updated.fingerprint == initial.fingerprint
    assert updated.diff(initial) == {1: "2"}
    assert rendered(("<section>", "</section>"), 2).diff(initial) is None


def test_structured_render_accepts_only_explicit_trusted_markup() -> None:
    nested = rendered(("<em>", "</em>"), "trusted")
    result = rendered(
        ("<div>", "", "</div>"),
        raw("<strong>framework</strong>"),
        nested,
    )

    assert result.to_html() == ("<div><strong>framework</strong><em>trusted</em></div>")


def test_rendered_values_are_immutable_and_validate_their_shape() -> None:
    value = Rendered(("<p>", "</p>"), ("value",))

    with pytest.raises(FrozenInstanceError):
        _set_attribute(value, "statics", ("changed",))
    with pytest.raises(ValueError, match="one more static"):
        Rendered(("<p>",), ("value",))
    with pytest.raises(TypeError, match="static fragments"):
        Rendered(cast(tuple[str, ...], ("<p>", 1)), ("value",))


def test_default_document_escapes_the_title_and_keeps_framework_markup() -> None:
    class Page(LiveView):
        def render(self) -> str:
            return ""

        def title(self) -> str:
            return '<Members & "settings">'

    document = Page().render_document(
        "<main data-opal-live-root></main>",
        '<script type="module"></script>',
    )

    assert "<title>&lt;Members &amp; &quot;settings&quot;&gt;</title>" in document
    assert '<main data-opal-live-root></main><script type="module"></script>' in (
        document
    )

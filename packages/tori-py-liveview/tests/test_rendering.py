from __future__ import annotations

from dataclasses import FrozenInstanceError
from string.templatelib import Template
from typing import cast

import pytest
from tori_py_liveview import (
    LiveComponent,
    LiveView,
    Rendered,
    classes,
    fragment,
    html,
    raw,
    rendered,
)


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


def test_template_render_escapes_values_and_preserves_structure() -> None:
    name = '<Mike & "Tori">'
    initial_count = 1
    updated_count = 2

    initial = html(t"<p>{name}: {initial_count:02d}</p>")
    updated = html(t"<p>{name}: {updated_count:02d}</p>")

    assert initial.to_html() == "<p>&lt;Mike &amp; &quot;Tori&quot;&gt;: 01</p>"
    assert initial.statics == ("<p>", ": ", "</p>")
    assert initial.dynamics == ("&lt;Mike &amp; &quot;Tori&quot;&gt;", "01")
    assert updated.fingerprint == initial.fingerprint
    assert updated.diff(initial) == {1: "02"}


def test_template_render_applies_conversions_before_escaping() -> None:
    value = '<span class="message">'

    result = html(t"<p>{value!r}</p>")

    assert result.to_html() == (
        "<p>&#x27;&lt;span class=&quot;message&quot;&gt;&#x27;</p>"
    )


def test_template_render_requires_a_template() -> None:
    with pytest.raises(TypeError, match="template must be a Template"):
        html(cast(Template, "<p>not a template</p>"))


def test_template_render_composes_only_explicit_trusted_markup() -> None:
    name = "<framework>"
    nested_template = t"<em>{name}</em>"
    nested_rendered = rendered(("<strong>", "</strong>"), name)

    result = html(
        t"<div>{nested_template}{nested_rendered}{raw('<small>safe</small>')}</div>"
    )

    assert result.to_html() == (
        "<div><em>&lt;framework&gt;</em>"
        "<strong>&lt;framework&gt;</strong><small>safe</small></div>"
    )


def test_fragment_composes_an_iterable_and_escapes_ordinary_values() -> None:
    names = ["<Alice>", "Bob"]

    result = fragment(t"<li>{name}</li>" for name in names)

    assert result.to_html() == "<li>&lt;Alice&gt;</li><li>Bob</li>"


def test_fragment_preserves_positional_diffs_and_trusted_values() -> None:
    initial = fragment(
        [
            t"<span>{1}</span>",
            "<unsafe>",
            raw("<hr>"),
            rendered(("<strong>", "</strong>"), "safe"),
        ]
    )
    updated = fragment(
        [
            t"<span>{2}</span>",
            "<changed>",
            raw("<hr>"),
            rendered(("<strong>", "</strong>"), "safe"),
        ]
    )

    assert initial.to_html() == (
        "<span>1</span>&lt;unsafe&gt;<hr><strong>safe</strong>"
    )
    assert updated.fingerprint == initial.fingerprint
    assert updated.diff(initial) == {
        0: "<span>2</span>",
        1: "&lt;changed&gt;",
    }


def test_fragment_accepts_an_empty_iterable() -> None:
    result = fragment([])

    assert result == Rendered(("",), ())


def test_classes_combines_names_and_enabled_conditions_in_order() -> None:
    result = classes(
        "button button-primary",
        "  rounded   shadow  ",
        "",
        active=True,
        disabled=False,
        **{"is-selected": True},
    )

    assert result == "button button-primary rounded shadow active is-selected"
    assert classes() == ""


def test_classes_remains_escaped_when_interpolated() -> None:
    unsafe_name = 'admin" onclick="alert(1)'
    class_name = classes("button", unsafe_name)

    result = html(t'<button class="{class_name}">Save</button>')

    assert result.to_html() == (
        '<button class="button admin&quot; onclick=&quot;alert(1)">Save</button>'
    )


def test_classes_requires_string_names_and_boolean_conditions() -> None:
    with pytest.raises(TypeError, match="class names must be strings"):
        classes(cast(str, 1))
    with pytest.raises(TypeError, match="conditional class flags must be booleans"):
        classes(active=cast(bool, 1))


@pytest.mark.asyncio
async def test_page_and_component_render_accept_templates() -> None:
    class Badge(LiveComponent):
        def render(self) -> Template:
            label = "<primary>"
            return t'<strong data-opal-target="{self.myself}">{label}</strong>'

    class Page(LiveView):
        def render(self) -> Template:
            badge = self.live_component(Badge, "primary")
            return t"<main>{badge}</main>"

    result = await Page()._render_liveview()

    assert result.to_html() == (
        '<main><strong data-opal-target="1">&lt;primary&gt;</strong></main>'
    )


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

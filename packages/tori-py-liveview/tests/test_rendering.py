from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from string.templatelib import Template
from typing import Any, cast

import pytest
from tori_py_liveview import (
    LiveComponent,
    LiveView,
    LiveViewError,
    Rendered,
    attrs,
    classes,
    fragment,
    html,
    raw,
    rendered,
)
from tori_py_liveview.rendering import _ChildRendered, _ComponentRendered


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


def test_template_render_preserves_nested_render_trees() -> None:
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
    assert isinstance(result.dynamics[0], Rendered)
    assert result.dynamics[0] == html(nested_template)
    assert result.dynamics[1] is nested_rendered
    assert result.dynamics[2] == "<small>safe</small>"


def test_fragment_composes_an_iterable_and_escapes_ordinary_values() -> None:
    names = ["<Alice>", "Bob"]

    result = fragment(t"<li>{name}</li>" for name in names)

    assert result.to_html() == "<li>&lt;Alice&gt;</li><li>Bob</li>"


def test_fragment_preserves_positional_diffs_and_render_trees() -> None:
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
        0: html(t"<span>{2}</span>"),
        1: "&lt;changed&gt;",
    }


def test_fragment_accepts_an_empty_iterable() -> None:
    assert fragment([]) == Rendered(("",), ())


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


def test_attrs_encodes_values_and_omits_disabled_attributes() -> None:
    result = attrs(
        {
            "id": "save-button",
            "disabled": True,
            "hidden": False,
            "title": None,
            "phx-click": "save",
            "aria-label": '<Save & "close">',
        }
    )

    assert result == raw(
        ' id="save-button" disabled phx-click="save" '
        'aria-label="&lt;Save &amp; &quot;close&quot;&gt;"'
    )


@pytest.mark.parametrize(
    "name", ["", "not valid", "onclick", "ONFOCUS", "srcdoc", "style"]
)
def test_attrs_rejects_unsafe_attribute_names(name: str) -> None:
    with pytest.raises(ValueError, match="unsafe HTML attribute name"):
        attrs({name: "value"})


def test_attrs_requires_a_mapping_with_string_names() -> None:
    with pytest.raises(TypeError, match="attributes must be a mapping"):
        attrs(cast(dict[str, object], []))
    with pytest.raises(TypeError, match="attribute names must be strings"):
        attrs(cast(dict[str, object], {1: "value"}))


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        " JAVA\nSCRIPT:alert(1)",
        "vbscript:msgbox(1)",
        "data:text/html,<script>alert(1)</script>",
    ],
)
def test_attrs_rejects_executable_url_schemes(value: str) -> None:
    with pytest.raises(ValueError, match="unsafe URL scheme"):
        attrs({"href": value})


def test_attrs_rejects_executable_object_data_urls() -> None:
    with pytest.raises(ValueError, match="unsafe URL scheme"):
        attrs({"data": "data:text/html,<script>alert(1)</script>"})


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ping", "https://safe.example/a javascript:alert(1)"),
        ("srcset", "https://safe.example/a 1x, javascript:alert(1) 2x"),
        ("srcset", "https://safe.example/a 1x, java\nscript:alert(1) 2x"),
    ],
)
def test_attrs_rejects_executable_schemes_in_url_lists(name: str, value: str) -> None:
    with pytest.raises(ValueError, match="unsafe URL scheme"):
        attrs({name: value})


def test_attrs_allows_relative_and_network_urls() -> None:
    assert attrs({"href": "/settings", "src": "https://cdn.example/icon.svg"}) == raw(
        ' href="/settings" src="https://cdn.example/icon.svg"'
    )


def test_attrs_validates_the_exact_string_it_emits() -> None:
    class StatefulUrl:
        calls = 0

        def __str__(self) -> str:
            self.calls += 1
            return "https://safe.example" if self.calls == 1 else "javascript:alert(1)"

    value = StatefulUrl()

    assert attrs({"href": value}) == raw(' href="https://safe.example"')
    assert value.calls == 1


# Phoenix parses a phx-* value starting with "[" as JS commands and runs them.
_JS_COMMAND = '[["set_attr",{"to":"body","attr":["onclick","alert(1)"]}]]'


@pytest.mark.parametrize(
    "name", ["phx-click", "PHX-CLICK", "phx-submit", "phx-mounted", "phx-remove"]
)
def test_attrs_rejects_phoenix_js_command_values(name: str) -> None:
    with pytest.raises(ValueError, match="unsafe phx-"):
        attrs({name: _JS_COMMAND})


def test_attrs_allows_brackets_in_phoenix_data_attributes() -> None:
    assert attrs(
        {
            "phx-value-tags": "[1]",
            "phx-target": "[data-role=list]",
            "phx-key": "[",
            "phx-disable-with": "[Saving]",
            "phx-click": " [not a command]",
            "title": "[note]",
        }
    ) == raw(
        ' phx-value-tags="[1]" phx-target="[data-role=list]" phx-key="["'
        ' phx-disable-with="[Saving]" phx-click=" [not a command]" title="[note]"'
    )


@pytest.mark.parametrize(
    "template",
    [
        t'<button phx-click="{_JS_COMMAND}">Go</button>',
        t"<button phx-click='{_JS_COMMAND}'>Go</button>",
        t"<div phx-mounted={_JS_COMMAND}></div>",
        t'<b title="x"PHX-CLICK = "{_JS_COMMAND}">Go</b>',
        t'<button phx-click="{""}{_JS_COMMAND}">Go</button>',
    ],
)
def test_html_rejects_interpolated_phoenix_js_commands(template: Template) -> None:
    with pytest.raises(ValueError, match="unsafe phx-"):
        html(template)


def test_rendered_rejects_interpolated_phoenix_js_commands() -> None:
    with pytest.raises(ValueError, match="unsafe phx-"):
        rendered(('<button phx-click="', '">Go</button>'), _JS_COMMAND)


def test_html_allows_brackets_outside_phoenix_command_values() -> None:
    value = "[1]"
    assert html(
        t'<p phx-click="do-{value}" phx-value-id="{value}" title="{value}">{value}</p>'
    ).to_html() == ('<p phx-click="do-[1]" phx-value-id="[1]" title="[1]">[1]</p>')
    # Trusted application HTML may still carry JS commands.
    assert html(t"<button phx-click='{raw(_JS_COMMAND)}'>Go</button>").to_html() == (
        f"<button phx-click='{_JS_COMMAND}'>Go</button>"
    )
    first, second = "a", "[b"
    assert html(
        t'<p phx-click="do-{first}-{second}" title="x">{second}</p>'
    ).to_html() == ('<p phx-click="do-a-[b" title="x">[b</p>')


def test_html_checks_the_phoenix_value_it_emits() -> None:
    class StatefulEvent:
        calls = 0

        def __str__(self) -> str:
            self.calls += 1
            return "save" if self.calls == 1 else _JS_COMMAND

    event = StatefulEvent()

    assert html(t'<b phx-click="{event}">Go</b>').to_html() == (
        '<b phx-click="save">Go</b>'
    )
    assert event.calls == 1


def test_html_rejects_phoenix_js_commands_from_nested_values() -> None:
    nested = t"{_JS_COMMAND}"
    empty = raw("")
    with pytest.raises(ValueError, match="unsafe phx-"):
        html(t'<b phx-click="{nested}">Go</b>')
    with pytest.raises(ValueError, match="unsafe phx-"):
        html(t'<b phx-click="{fragment([_JS_COMMAND])}">Go</b>')
    with pytest.raises(ValueError, match="unsafe phx-"):
        html(t'<b phx-click="{empty}{_JS_COMMAND}">Go</b>')


def test_html_rejects_data_inside_static_phoenix_js_commands() -> None:
    # HTML escaping does not stop data from leaving a JSON string: the browser
    # decodes &quot; before Phoenix parses the command.
    event = (
        'x"}],["set_attr",{"to":"body","attr":["onclick","alert(1)"]}],["push",{"a":"'
    )
    with pytest.raises(ValueError, match="unsafe phx-"):
        rendered(('<b phx-click=\'[["push",{"event":"', "\"}]]'>Go</b>"), event)
    with pytest.raises(ValueError, match="unsafe phx-"):
        rendered(('<b phx-click=\'[["push",{"event":"', "\"}]]'>Go</b>"), "save")


@pytest.mark.asyncio
async def test_page_and_component_render_accept_templates() -> None:
    class Badge(LiveComponent):
        def render(self) -> Template:
            label = "<primary>"
            return t'<strong phx-target="{self.myself}">{label}</strong>'

    class Page(LiveView):
        def render(self) -> Template:
            badge = self.live_component(Badge, "primary")
            return t"<main>{badge}</main>"

    result = await Page()._render_liveview()

    assert result.to_html() == (
        '<main><strong phx-target="1">&lt;primary&gt;</strong></main>'
    )
    component = result.dynamics[0]
    assert isinstance(component, _ComponentRendered)
    assert component.cid == 1


@pytest.mark.asyncio
async def test_components_render_nested_components_owned_by_the_page() -> None:
    class Leaf(LiveComponent):
        def render(self) -> Template:
            return t'<i phx-target="{self.myself}">{self.id}</i>'

    class Branch(LiveComponent):
        def render(self) -> Template:
            leaf = self.live_component(Leaf, "leaf")
            return t'<b phx-target="{self.myself}">{leaf}</b>'

    class Page(LiveView):
        def render(self) -> Template:
            return t"<main>{self.live_component(Branch, 'branch')}</main>"

    result = await Page()._render_liveview()

    assert result.to_html() == (
        '<main><b phx-target="1"><i phx-target="2">leaf</i></b></main>'
    )
    branch = result.dynamics[0]
    assert isinstance(branch, _ComponentRendered)
    leaf = branch.dynamics[1]
    assert isinstance(leaf, _ComponentRendered)
    assert (branch.cid, leaf.cid) == (1, 2)


@pytest.mark.asyncio
async def test_nested_component_identity_is_unique_across_the_page() -> None:
    class Leaf(LiveComponent):
        def render(self) -> str:
            return "<i></i>"

    class Branch(LiveComponent):
        def render(self) -> Template:
            return t"<b>{self.live_component(Leaf, 'same')}</b>"

    class Page(LiveView):
        def render(self) -> Template:
            leaf = self.live_component(Leaf, "same")
            return t"<main>{leaf}{self.live_component(Branch, 'branch')}</main>"

    with pytest.raises(LiveViewError, match="Duplicate LiveView component identity"):
        await Page()._render_liveview()


def test_components_render_nested_components_only_while_the_page_renders() -> None:
    class Leaf(LiveComponent):
        def render(self) -> str:
            return "<i></i>"

    branch = Leaf()
    with pytest.raises(LiveViewError, match="not attached"):
        branch.live_component(Leaf, "leaf")

    class Page(LiveView):
        def render(self) -> str:
            return ""

    branch._attach_liveview("branch", 1, False, Page())
    with pytest.raises(LiveViewError, match="while their page renders"):
        branch.live_component(Leaf, "leaf")


class _ChildPage(LiveView):
    def render(self) -> str:
        return "<p>child</p>"


def _signed(page_type: type[LiveView], view_id: str, params: Mapping[str, str]) -> str:
    return f"{page_type.__name__}.{view_id}.{len(params)}"


@pytest.mark.asyncio
async def test_live_render_places_a_child_container_with_a_stable_token() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def signer(
        page_type: type[LiveView], view_id: str, params: Mapping[str, str]
    ) -> str:
        calls.append((view_id, dict(params)))
        return _signed(page_type, view_id, params)

    class Page(LiveView):
        def __init__(self) -> None:
            self.store = "kyiv"

        def render(self) -> Template:
            cart = self.live_render(_ChildPage, "cart", {"store": self.store})
            return t"<main>{cart}</main>"

    page = Page()
    page._liveview_child_signer = signer
    first = await page._render_liveview()
    child = first.dynamics[0]
    assert isinstance(child, _ChildRendered)
    assert first.to_html() == (
        '<main><div id="cart" data-phx-session="_ChildPage.cart.1" '
        'data-phx-static="" data-phx-parent-id="tori-live-root"></div></main>'
    )
    assert (child.view_id, child.page_type, child.params) == (
        "cart",
        _ChildPage,
        (("store", "kyiv"),),
    )
    # Unchanged params keep the token, so the container stays out of diffs.
    assert (await page._render_liveview()).dynamics[0] == child
    page.store = "lviv"
    await page._render_liveview()
    assert calls == [("cart", {"store": "kyiv"}), ("cart", {"store": "lviv"})]

    page._liveview_view_id = "outer"
    nested = await page._render_liveview()
    assert 'data-phx-parent-id="outer"' in nested.to_html()


@pytest.mark.asyncio
async def test_a_child_rendered_again_after_leaving_gets_a_fresh_token() -> None:
    issued: list[str] = []

    def signer(
        page_type: type[LiveView], view_id: str, params: Mapping[str, str]
    ) -> str:
        issued.append(f"{_signed(page_type, view_id, params)}.{len(issued)}")
        return issued[-1]

    class Page(LiveView):
        def __init__(self) -> None:
            self.show = True

        def render(self) -> Template:
            cart = self.live_render(_ChildPage, "cart") if self.show else ""
            return t"<main>{cart}</main>"

    def session(rendered: Rendered) -> str | None:
        child = rendered.dynamics[0]
        return child.session if isinstance(child, _ChildRendered) else None

    page = Page()
    page._liveview_child_signer = signer
    first = session(await page._render_liveview())
    # While every render includes the child, it keeps its token.
    assert session(await page._render_liveview()) == first
    page.show = False
    assert session(await page._render_liveview()) is None
    # Left out once, it mounts afresh and must not reuse a token that may have
    # expired meanwhile.
    page.show = True
    again = session(await page._render_liveview())
    assert again is not None and again != first
    assert issued == [first, again]


@pytest.mark.asyncio
async def test_live_render_validates_children_and_runs_only_while_rendering() -> None:
    page = _ChildPage()
    page._liveview_child_signer = _signed
    with pytest.raises(LiveViewError, match="while their page renders"):
        page.live_render(_ChildPage, "cart")

    def render_with(*args: object) -> type[LiveView]:
        class Page(LiveView):
            def render(self) -> Template:
                return t"{cast(Any, self.live_render)(*args)}"

        return Page

    async def render(page_type: type[LiveView]) -> None:
        page = page_type()
        page._liveview_child_signer = _signed
        await page._render_liveview()

    with pytest.raises(TypeError, match="LiveView subclass"):
        await render(render_with(_NotAPage, "cart"))
    with pytest.raises(TypeError, match="must be a string"):
        await render(render_with(_ChildPage, 1))
    for invalid in ("", "has space", "a" * 129, "tori-live-root"):
        with pytest.raises(ValueError, match="letters, digits"):
            await render(render_with(_ChildPage, invalid))
    with pytest.raises(TypeError, match="map strings to strings"):
        await render(render_with(_ChildPage, "cart", {"store": 1}))

    class Twice(LiveView):
        def render(self) -> Template:
            first = self.live_render(_ChildPage, "cart")
            return t"{first}{self.live_render(_ChildPage, 'cart')}"

    with pytest.raises(LiveViewError, match="Duplicate child LiveView id"):
        await render(Twice)

    class Unserved(LiveView):
        def render(self) -> Template:
            return t"{self.live_render(_ChildPage, 'cart')}"

    with pytest.raises(LiveViewError, match="served by LiveViewModule"):
        await Unserved()._render_liveview()


class _NotAPage:
    pass


def test_only_the_main_view_can_push_patch() -> None:
    page = _ChildPage()
    page.push_patch("/here")
    child = _ChildPage()
    child._liveview_view_id = "cart"
    with pytest.raises(LiveViewError, match="only the root LiveView can push_patch"):
        child.push_patch("/here")
    child.push_navigate("/elsewhere")


def test_stream_insert_accepts_a_template() -> None:
    class Page(LiveView):
        def render(self) -> str:
            return ""

    page = Page()
    label = "<unsafe>"
    page.stream_insert(
        "activity-stream",
        "activity-template",
        t'<li id="activity-template">{label}</li>',
    )

    assert page.stream_contents("activity-stream").value == (
        '<li id="activity-template">&lt;unsafe&gt;</li>'
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
        "<main data-phx-session></main>",
        "<script defer></script>",
    )

    assert (
        '<title data-default="">&lt;Members &amp; &quot;settings&quot;&gt;</title>'
        in document
    )
    assert "<main data-phx-session></main><script defer></script>" in (document)

    class UntitledPage(LiveView):
        def render(self) -> str:
            return ""

    assert '<title data-default=""></title>' in UntitledPage().render_document("", "")

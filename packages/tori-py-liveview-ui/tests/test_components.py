from __future__ import annotations

from string.templatelib import Template
from typing import Any, cast

import pytest
from tori_py_liveview import html, raw
from tori_py_liveview_ui import alert, badge, button, card, grid, stack


def _render(template: Template) -> str:
    return html(template).to_html()


def test_button_renders_closed_options_events_and_escaped_content() -> None:
    assert _render(button('<Save & "close">')) == (
        '<button type="button" '
        'class="tori-ui-button tori-ui-button--primary tori-ui-button--md">'
        "&lt;Save &amp; &quot;close&quot;&gt;</button>"
    )
    assert _render(
        button(
            "Remove",
            variant="danger",
            size="lg",
            button_type="submit",
            disabled=True,
            event="delete",
            target=4,
        )
    ) == (
        '<button type="submit" '
        'class="tori-ui-button tori-ui-button--danger tori-ui-button--lg" '
        'disabled phx-click="delete" phx-target="4">Remove</button>'
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"variant": "loud"}, "button variant"),
        ({"size": "xl"}, "button size"),
        ({"button_type": "link"}, "button type"),
        ({"event": ""}, "event cannot be empty"),
        ({"target": 1}, "target requires an event"),
        ({"event": "save", "target": 0}, "target must be a positive safe integer"),
        (
            {"event": "save", "target": 2**53},
            "target must be a positive safe integer",
        ),
    ],
)
def test_button_rejects_invalid_options(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        button("Save", **kwargs)


def test_button_rejects_invalid_option_types() -> None:
    with pytest.raises(TypeError, match="button variant must be a string"):
        button("Save", variant=cast(Any, 1))
    with pytest.raises(TypeError, match="button disabled must be a boolean"):
        button("Save", disabled=cast(Any, 1))
    with pytest.raises(TypeError, match="button event must be a string or None"):
        button("Save", event=cast(Any, 1))
    with pytest.raises(TypeError, match="button target must be an integer or None"):
        button("Save", event="save", target=cast(Any, "1"))


def test_badge_and_alert_render_semantics_and_tones() -> None:
    assert _render(badge("Ready", tone="success")) == (
        '<span class="tori-ui-badge tori-ui-badge--success">Ready</span>'
    )
    assert _render(alert("Saved", title="Account", tone="info")) == (
        '<section class="tori-ui-alert tori-ui-alert--info" role="status">'
        '<div class="tori-ui-alert__content">'
        '<h2 class="tori-ui-alert__title">Account</h2>'
        '<div class="tori-ui-alert__body">Saved</div></div></section>'
    )
    assert 'role="alert"' in _render(alert("Failed", tone="danger"))
    with pytest.raises(ValueError, match="badge tone"):
        badge("Ready", tone=cast(Any, "purple"))
    with pytest.raises(ValueError, match="alert tone"):
        alert("Ready", tone=cast(Any, "purple"))
    with pytest.raises(TypeError, match="alert title"):
        alert("Ready", title=cast(Any, 1))


def test_card_composes_optional_trusted_regions_and_escaped_content() -> None:
    result = _render(
        card(
            "<body>",
            eyebrow="Status",
            title="<Overview>",
            footer=button("Refresh", variant="ghost", event="refresh"),
        )
    )

    assert result == (
        '<article class="tori-ui-card"><header class="tori-ui-card__header">'
        '<p class="tori-ui-card__eyebrow">Status</p>'
        '<h2 class="tori-ui-card__title">&lt;Overview&gt;</h2></header>'
        '<div class="tori-ui-card__body">&lt;body&gt;</div>'
        '<footer class="tori-ui-card__footer">'
        '<button type="button" '
        'class="tori-ui-button tori-ui-button--ghost tori-ui-button--md" '
        'phx-click="refresh">Refresh</button></footer></article>'
    )
    with pytest.raises(TypeError, match="card eyebrow"):
        card("Body", eyebrow=cast(Any, 1))


def test_stack_and_grid_consume_children_once_and_preserve_templates() -> None:
    def children():
        yield badge("New", tone="info")
        yield "<unsafe>"
        yield raw("<hr>")

    assert _render(stack(children(), gap="lg", align="center")) == (
        '<div class="tori-ui-stack tori-ui-stack--gap-lg '
        'tori-ui-stack--align-center">'
        '<span class="tori-ui-badge tori-ui-badge--info">New</span>'
        "&lt;unsafe&gt;<hr></div>"
    )
    assert _render(grid(["A", "B"], columns="3", gap="sm")) == (
        '<div class="tori-ui-grid tori-ui-grid--columns-3 '
        'tori-ui-grid--gap-sm">AB</div>'
    )


@pytest.mark.parametrize(
    ("component", "kwargs", "message"),
    [
        (stack, {"gap": "xxl"}, "stack gap"),
        (stack, {"align": "around"}, "stack alignment"),
        (grid, {"columns": "5"}, "grid columns"),
        (grid, {"gap": "xxl"}, "grid gap"),
    ],
)
def test_layout_components_reject_open_ended_options(
    component: Any,
    kwargs: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        component([], **kwargs)


def test_every_component_returns_a_template() -> None:
    assert isinstance(button("Save"), Template)
    assert isinstance(badge("Ready"), Template)
    assert isinstance(alert("Ready"), Template)
    assert isinstance(card("Body"), Template)
    assert isinstance(stack([]), Template)
    assert isinstance(grid([]), Template)

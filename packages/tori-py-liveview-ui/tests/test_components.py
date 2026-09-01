from __future__ import annotations

from string.templatelib import Template
from typing import Any, cast

import pytest
from tori_py_liveview import html
from tori_py_liveview_ui import alert, badge, button, card, grid, stack


def test_button_renders_liveview_attributes_and_escapes_its_label() -> None:
    result = html(
        button(
            "<Save>",
            variant="danger",
            size="sm",
            disabled=True,
            event="save",
            target=7,
        )
    )

    assert result.to_html() == (
        '<button class="tori-ui-button tori-ui-button--danger '
        'tori-ui-button--sm" type="button" disabled data-opal-click="save" '
        'data-opal-target="7">&lt;Save&gt;</button>'
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"variant": "unknown"}, "button variant"),
        ({"size": "xl"}, "button size"),
        ({"button_type": "menu"}, "button type"),
        ({"disabled": 1}, "disabled must be a boolean"),
        ({"event": ""}, "event must be a non-empty string"),
        ({"target": 0, "event": "save"}, "target must be a positive integer"),
        ({"target": 1}, "target requires an event"),
    ],
)
def test_button_validates_its_closed_options(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        button("Save", **cast(Any, changes))


def test_badge_and_alert_render_typed_tones_and_nested_content() -> None:
    detail = t"<strong>{'<Check settings>'}</strong>"

    badge_result = html(badge("<Ready>", tone="success"))
    alert_result = html(alert(detail, title="Attention", tone="warning"))

    assert badge_result.to_html() == (
        '<span class="tori-ui-badge tori-ui-badge--success">&lt;Ready&gt;</span>'
    )
    assert alert_result.to_html() == (
        '<section class="tori-ui-alert tori-ui-alert--warning" role="status">'
        '<div class="tori-ui-alert__content">'
        '<h2 class="tori-ui-alert__title">Attention</h2>'
        '<div class="tori-ui-alert__body">'
        "<strong>&lt;Check settings&gt;</strong></div></div></section>"
    )


def test_card_supports_optional_header_and_footer_slots() -> None:
    result = html(
        card(
            t"<p>{'<Balance>'}</p>",
            eyebrow="Account",
            title="Overview",
            footer=t"<small>{'Updated now'}</small>",
        )
    )

    assert result.to_html() == (
        '<article class="tori-ui-card"><header class="tori-ui-card__header">'
        '<p class="tori-ui-card__eyebrow">Account</p>'
        '<h2 class="tori-ui-card__title">Overview</h2></header>'
        '<div class="tori-ui-card__body"><p>&lt;Balance&gt;</p></div>'
        '<footer class="tori-ui-card__footer">'
        "<small>Updated now</small></footer></article>"
    )


def test_stack_and_grid_compose_one_shot_template_iterables() -> None:
    def items() -> object:
        yield t"<span>{'<One>'}</span>"
        yield t"<span>{'Two'}</span>"

    stack_result = html(stack(cast(Any, items()), gap="lg", align="center"))
    grid_result = html(grid((t"<span>{value}</span>" for value in range(2)), columns=3))

    assert stack_result.to_html() == (
        '<div class="tori-ui-stack tori-ui-stack--gap-lg '
        'tori-ui-stack--align-center">'
        "<span>&lt;One&gt;</span><span>Two</span></div>"
    )
    assert grid_result.to_html() == (
        '<div class="tori-ui-grid tori-ui-grid--columns-3 tori-ui-grid--gap-md">'
        "<span>0</span><span>1</span></div>"
    )


@pytest.mark.parametrize(
    "component",
    [
        lambda: badge("Badge", tone="unknown"),
        lambda: alert("Alert", tone="unknown"),
        lambda: stack([], gap="unknown"),
        lambda: stack([], align="unknown"),
        lambda: grid([], columns=5),
        lambda: grid([], gap="unknown"),
    ],
)
def test_components_reject_unknown_visual_options(component: object) -> None:
    with pytest.raises(ValueError):
        cast(Any, component)()


def test_foundation_components_return_templates() -> None:
    assert isinstance(button("Button"), Template)
    assert isinstance(badge("Badge"), Template)
    assert isinstance(alert("Alert"), Template)
    assert isinstance(card("Card"), Template)
    assert isinstance(stack([]), Template)
    assert isinstance(grid([]), Template)

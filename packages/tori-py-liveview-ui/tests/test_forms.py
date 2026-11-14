from __future__ import annotations

import re
from collections.abc import Callable
from string.templatelib import Template
from typing import Any, cast

import pytest
import tori_py_liveview_ui
from tori_py_liveview import html
from tori_py_liveview_ui import (
    checkbox_group,
    combobox,
    fieldset,
    form_actions,
    forms,
    hidden,
    icon,
    input,
    multi_select,
    radio_group,
    search,
    segmented,
    slider,
    switch,
    textarea,
)

# Calls that break a helper's contract go through an untyped alias.
ui = cast(Any, tori_py_liveview_ui)

_OPTIONS = [("a", "Alpha"), ("b", "Beta <b>")]


def _render(template: Template) -> str:
    return html(template).to_html()


def test_forms_family_is_explicit() -> None:
    assert forms.__all__ == [
        "checkbox",
        "checkbox_group",
        "combobox",
        "field",
        "field_error",
        "fieldset",
        "form",
        "form_actions",
        "hidden",
        "input",
        "multi_select",
        "radio_group",
        "search",
        "segmented",
        "select",
        "slider",
        "switch",
        "textarea",
    ]


def test_radio_group_is_a_described_fieldset_of_native_radios() -> None:
    assert _render(
        radio_group(
            "Plan",
            _OPTIONS,
            id="plan",
            name="account[plan]",
            value="b",
            help_text="Pick one",
            error="Choose a plan",
            required=True,
            change_event="validate",
            target=2,
        )
    ) == (
        '<fieldset id="plan" class="tori-ui-field tori-ui-fieldset '
        'tori-ui-field--invalid" role="radiogroup" aria-required="true" '
        'aria-invalid="true" aria-describedby="plan-help plan-error">'
        '<legend class="tori-ui-field__label">Plan'
        '<span class="tori-ui-field__required" aria-hidden="true"> *</span></legend>'
        '<div class="tori-ui-choice"><label class="tori-ui-choice__option">'
        '<input type="radio" id="plan-1" name="account[plan]" '
        'class="tori-ui-choice__control" value="a" required phx-change="validate" '
        'phx-target="2"><span class="tori-ui-choice__label">Alpha</span></label>'
        '<label class="tori-ui-choice__option">'
        '<input type="radio" id="plan-2" name="account[plan]" '
        'class="tori-ui-choice__control" value="b" checked required '
        'phx-change="validate" phx-target="2">'
        '<span class="tori-ui-choice__label">Beta &lt;b&gt;</span></label></div>'
        '<p id="plan-help" class="tori-ui-field__help">Pick one</p>'
        '<p id="plan-error" class="tori-ui-field__error" role="alert">Choose a plan'
        "</p></fieldset>"
    )


def test_checkbox_group_checks_its_values_and_leaves_requiredness_to_the_page() -> None:
    result = _render(
        checkbox_group(
            "Tags",
            _OPTIONS,
            id="tags",
            name="task[tags][]",
            values=iter(["a"]),
            required=True,
            inline=True,
        )
    )

    assert 'role="group"' in result
    assert "aria-required" not in result
    assert '<div class="tori-ui-choice tori-ui-choice--inline">' in result
    assert (
        '<input type="checkbox" id="tags-1" name="task[tags][]" '
        'class="tori-ui-choice__control" value="a" checked>'
    ) in result
    assert (
        '<input type="checkbox" id="tags-2" name="task[tags][]" '
        'class="tori-ui-choice__control" value="b">'
    ) in result
    # The label still shows that the group is required.
    assert "tori-ui-field__required" in result


def test_segmented_is_a_radio_group_with_its_own_look() -> None:
    result = _render(segmented("View", _OPTIONS, id="view", name="view", value="a"))

    assert 'role="radiogroup"' in result
    assert (
        '<div class="tori-ui-segmented"><label class="tori-ui-segmented__option">'
        '<input type="radio" id="view-1" name="view" '
        'class="tori-ui-segmented__control" value="a" checked>'
        '<span class="tori-ui-segmented__label">Alpha</span></label>'
    ) in result


def test_switch_is_a_checkbox_with_the_switch_role() -> None:
    assert _render(
        switch("Email me", id="mail", name="mail", checked=True, help_text="Weekly")
    ) == (
        '<div class="tori-ui-field"><div class="tori-ui-switch">'
        '<input type="checkbox" role="switch" id="mail" name="mail" '
        'class="tori-ui-switch__control" value="true" checked '
        'aria-describedby="mail-help">'
        '<label class="tori-ui-switch__label" for="mail">Email me</label></div>'
        '<p id="mail-help" class="tori-ui-field__help">Weekly</p></div>'
    )
    failed = _render(switch("Email me", id="mail", name="mail", error="Not saved"))
    assert 'class="tori-ui-field tori-ui-field--invalid"' in failed
    assert 'aria-invalid="true" aria-describedby="mail-error"' in failed


def test_multi_select_selects_every_given_value() -> None:
    assert _render(
        multi_select(
            "Roles", _OPTIONS, id="roles", name="user[roles][]", values={"b"}, size=3
        )
    ) == (
        '<div class="tori-ui-field"><label class="tori-ui-field__label" for="roles">'
        'Roles</label><select id="roles" name="user[roles][]" '
        'class="tori-ui-select tori-ui-select--multiple" multiple size="3">'
        '<option value="a">Alpha</option>'
        '<option value="b" selected>Beta &lt;b&gt;</option></select></div>'
    )


def test_combobox_pairs_a_text_input_with_a_native_suggestion_list() -> None:
    assert _render(
        combobox(
            "City",
            ["Kyiv", ("lviv", "Lviv")],
            id="city",
            name="city",
            value="Ky",
            debounce=200,
        )
    ) == (
        '<div class="tori-ui-field"><label class="tori-ui-field__label" for="city">'
        'City</label><input type="text" id="city" name="city" class="tori-ui-input" '
        'list="city-options" value="Ky" autocomplete="off" phx-debounce="200">'
        '<datalist id="city-options"><option value="Kyiv"></option>'
        '<option value="lviv">Lviv</option></datalist></div>'
    )


def test_search_has_a_hidden_label_and_debounces_by_default() -> None:
    assert _render(search("Search orders", id="q", name="q", placeholder="Search")) == (
        '<div class="tori-ui-search">'
        '<label class="tori-ui-visually-hidden" for="q">Search orders</label>'
        f"{_render(icon('search', size='sm'))}"
        '<input type="search" id="q" name="q" class="tori-ui-input '
        'tori-ui-search__input" value="" placeholder="Search" autocomplete="off" '
        'phx-debounce="300"></div>'
    )
    assert "phx-debounce" not in _render(search("S", id="q", name="q", debounce=None))
    assert 'phx-debounce="blur"' in _render(
        search("S", id="q", name="q", debounce="blur")
    )


def test_slider_is_a_native_range_with_the_rendered_value() -> None:
    assert _render(
        slider("Volume", id="vol", name="vol", value=30, step=5, help_text="Loud")
    ) == (
        '<div class="tori-ui-field"><label class="tori-ui-field__label" for="vol">'
        'Volume</label><div class="tori-ui-slider"><input type="range" id="vol" '
        'name="vol" class="tori-ui-slider__control" value="30" min="0" max="100" '
        'step="5" aria-describedby="vol-help">'
        '<output class="tori-ui-slider__value" for="vol">30</output></div>'
        '<p id="vol-help" class="tori-ui-field__help">Loud</p></div>'
    )
    quiet = _render(
        slider("V", id="v", name="v", value=0.5, maximum=1, step=0.1, show_value=False)
    )
    assert "<output" not in quiet
    assert 'value="0.5" min="0" max="1" step="0.1"' in quiet


def test_hidden_fieldset_and_form_actions() -> None:
    assert _render(hidden(name="token", value='a"b', id="token")) == (
        '<input type="hidden" id="token" name="token" value="a&quot;b">'
    )
    assert _render(
        fieldset("Billing", "FIELDS", description="Where invoices go", disabled=True)
    ) == (
        '<fieldset class="tori-ui-fieldset tori-ui-fieldset--section" disabled>'
        '<legend class="tori-ui-fieldset__legend">Billing</legend>'
        '<p class="tori-ui-fieldset__description">Where invoices go</p>'
        '<div class="tori-ui-fieldset__content">FIELDS</div></fieldset>'
    )
    assert _render(form_actions(["A", "B"], align="between")) == (
        '<div class="tori-ui-form-actions tori-ui-form-actions--between">AB</div>'
    )


def test_input_bounds_timing_and_affixes() -> None:
    assert _render(
        input(
            "Price",
            id="price",
            name="price",
            input_type="number",
            minimum=0,
            maximum=100,
            step=0.5,
            readonly=True,
            autofocus=True,
            debounce="blur",
            prefix="$",
            suffix="USD",
        )
    ) == (
        '<div class="tori-ui-field"><label class="tori-ui-field__label" for="price">'
        'Price</label><div class="tori-ui-input-group">'
        '<span class="tori-ui-input-group__affix">$</span>'
        '<input type="number" id="price" name="price" class="tori-ui-input" readonly '
        'autofocus min="0" max="100" step="0.5" phx-debounce="blur">'
        '<span class="tori-ui-input-group__affix">USD</span></div></div>'
    )
    bounded = _render(
        input("Code", id="code", name="code", min_length=2, max_length=8, throttle=500)
    )
    assert 'minlength="2" maxlength="8" phx-throttle="500"' in bounded
    dated = _render(
        input("Day", id="d", name="d", input_type="date", minimum="2026-01-01")
    )
    assert 'min="2026-01-01"' in dated
    assert 'step="any"' in _render(input("N", id="n", name="n", step="any"))


def test_textarea_takes_length_bounds_and_timing() -> None:
    result = _render(
        textarea(
            "Bio", id="bio", name="bio", max_length=200, debounce=300, readonly=True
        )
    )

    assert 'rows="4" readonly maxlength="200" phx-debounce="300"></textarea>' in result


@pytest.mark.parametrize(
    ("call", "error", "message"),
    [
        (
            lambda: ui.radio_group("P", [("a",)], id="p", name="p"),
            TypeError,
            "radio group options must be two-item tuples",
        ),
        (
            lambda: ui.radio_group("P", [(1, "One")], id="p", name="p"),
            TypeError,
            "radio group option values must be strings",
        ),
        (
            lambda: ui.radio_group("", [], id="p", name="p"),
            ValueError,
            "radio group label cannot be empty",
        ),
        (
            lambda: ui.radio_group("P", [], id="p", name="p", target=1),
            ValueError,
            "radio group target requires an event",
        ),
        (
            lambda: ui.checkbox_group("T", [], id="t", name="t[]", values="a"),
            TypeError,
            "checkbox group values must be an iterable of strings",
        ),
        (
            lambda: ui.checkbox_group("T", [], id="t", name="t[]", values=[1]),
            TypeError,
            "checkbox group values must be an iterable of strings",
        ),
        (
            lambda: ui.segmented("V", [], id="a b", name="v"),
            ValueError,
            "segmented id cannot contain whitespace",
        ),
        (
            lambda: ui.switch("S", id="s", name="s", checked="yes"),
            TypeError,
            "switch checked must be a boolean",
        ),
        (
            lambda: ui.multi_select("R", [], id="r", name="r[]", size=1),
            ValueError,
            "multi select size must be between",
        ),
        (
            lambda: ui.combobox("C", [1], id="c", name="c"),
            TypeError,
            "combobox options must be strings or (value, label) tuples",
        ),
        (
            lambda: ui.combobox("C", [], id="c", name="c", value=None),
            TypeError,
            "combobox value must be a string",
        ),
        (
            lambda: ui.search("S", id="q", name="q", debounce=-1),
            ValueError,
            "search debounce must be between",
        ),
        (
            lambda: ui.slider("V", id="v", name="v", value=101),
            ValueError,
            "slider value must be within the range",
        ),
        (
            lambda: ui.slider("V", id="v", name="v", value=1, minimum=5, maximum=5),
            ValueError,
            "slider minimum must be below the maximum",
        ),
        (
            lambda: ui.slider("V", id="v", name="v", value=1, step=0),
            ValueError,
            "slider step must be positive",
        ),
        (
            lambda: ui.slider("V", id="v", name="v", value="1"),
            TypeError,
            "slider value must be a number",
        ),
        (
            lambda: ui.slider("V", id="v", name="v", value=1, debounce=1, throttle=1),
            ValueError,
            "slider cannot both debounce and throttle",
        ),
        (
            lambda: ui.hidden(name="t", value=True),
            TypeError,
            "hidden value must be a string or a number",
        ),
        (lambda: ui.fieldset("", "x"), ValueError, "fieldset legend cannot be empty"),
        (
            lambda: ui.form_actions([], align="center"),
            ValueError,
            "form actions alignment must be one of",
        ),
        (
            lambda: ui.input("L", id="i", name="n", readonly=1),
            TypeError,
            "input readonly must be a boolean",
        ),
        (
            lambda: ui.input("L", id="i", name="n", minimum=True),
            TypeError,
            "input minimum must be a string, number, or None",
        ),
        (
            lambda: ui.input("L", id="i", name="n", step=0),
            ValueError,
            "input step must be a positive number",
        ),
        (
            lambda: ui.input("L", id="i", name="n", min_length=5, max_length=2),
            ValueError,
            "input minimum length cannot exceed the maximum length",
        ),
        (
            lambda: ui.input("L", id="i", name="n", debounce="change"),
            TypeError,
            "input debounce must be an integer",
        ),
        (
            lambda: ui.textarea("L", id="i", name="n", max_length=-1),
            ValueError,
            "textarea maximum length must be between",
        ),
    ],
)
def test_form_helpers_reject_values_outside_their_contract(
    call: Callable[[], Any], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=re.escape(message)):
        call()

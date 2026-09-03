from __future__ import annotations

from string.templatelib import Template
from typing import Any, cast

import pytest
from tori_py_liveview import html, raw
from tori_py_liveview_ui import (
    alert,
    badge,
    button,
    card,
    checkbox,
    field,
    field_error,
    form,
    grid,
    input,
    select,
    stack,
    textarea,
)


def _render(template: Template) -> str:
    return html(template).to_html()


def test_form_renders_phoenix_events_target_and_escaped_content() -> None:
    result = _render(
        form(
            "<fields>",
            id="profile-form",
            change_event="validate",
            submit_event="save",
            target=7,
        )
    )

    assert result == (
        '<form id="profile-form" method="post" class="tori-ui-form" '
        'phx-change="validate" phx-submit="save" phx-target="7">'
        "&lt;fields&gt;</form>"
    )


@pytest.mark.parametrize(
    ("kwargs", "error", "message"),
    [
        ({"id": ""}, ValueError, "form id cannot be empty"),
        ({"id": "profile form"}, ValueError, "form id cannot contain whitespace"),
        (
            {"id": "profile", "change_event": ""},
            ValueError,
            "form change event cannot be empty",
        ),
        (
            {"id": "profile", "submit_event": ""},
            ValueError,
            "form submit event cannot be empty",
        ),
        (
            {"id": "profile", "target": 1},
            ValueError,
            "form target requires an event",
        ),
        (
            {"id": "profile", "submit_event": "save", "target": 0},
            ValueError,
            "form target must be a positive safe integer",
        ),
        ({"id": 1}, TypeError, "form id must be a string"),
        (
            {"id": "profile", "submit_event": 1},
            TypeError,
            "form submit event must be a string or None",
        ),
    ],
)
def test_form_rejects_invalid_bindings(
    kwargs: dict[str, Any], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        form("Fields", **kwargs)


def test_field_composes_an_accessible_label_help_and_error() -> None:
    control = (
        t'<input id="email" required aria-invalid="true" '
        t'aria-describedby="email-help email-error">'
    )

    assert _render(
        field(
            "Email <address>",
            control,
            control_id="email",
            help_text="Used for notices",
            error="Enter a valid address",
            required=True,
        )
    ) == (
        '<div class="tori-ui-field tori-ui-field--invalid">'
        '<label class="tori-ui-field__label" for="email">'
        'Email &lt;address&gt;<span class="tori-ui-field__required" '
        'aria-hidden="true"> *</span></label>'
        '<input id="email" required aria-invalid="true" '
        'aria-describedby="email-help email-error">'
        '<p id="email-help" class="tori-ui-field__help">Used for notices</p>'
        '<p id="email-error" class="tori-ui-field__error" role="alert">'
        "Enter a valid address</p></div>"
    )


def test_field_error_renders_escaped_live_validation_feedback() -> None:
    assert _render(field_error("Name must not contain <", id="name-error")) == (
        '<p id="name-error" class="tori-ui-field__error" role="alert">'
        "Name must not contain &lt;</p>"
    )


def test_input_renders_a_complete_accessible_live_field() -> None:
    assert _render(
        input(
            "Email",
            id="profile-email",
            name="profile[email]",
            value='person@example.test"',
            input_type="email",
            placeholder="you@example.test",
            autocomplete="email",
            help_text="Where notices are sent",
            error="Address is invalid",
            required=True,
            change_event="validate",
            blur_event="validate",
            target=4,
        )
    ) == (
        '<div class="tori-ui-field tori-ui-field--invalid">'
        '<label class="tori-ui-field__label" for="profile-email">Email'
        '<span class="tori-ui-field__required" aria-hidden="true"> *</span></label>'
        '<input type="email" id="profile-email" name="profile[email]" '
        'class="tori-ui-input" value="person@example.test&quot;" '
        'placeholder="you@example.test" autocomplete="email" required '
        'aria-invalid="true" '
        'aria-describedby="profile-email-help profile-email-error" '
        'phx-change="validate" phx-blur="validate" phx-target="4">'
        '<p id="profile-email-help" class="tori-ui-field__help">'
        "Where notices are sent</p>"
        '<p id="profile-email-error" class="tori-ui-field__error" role="alert">'
        "Address is invalid</p></div>"
    )


def test_textarea_renders_rows_value_and_accessible_help() -> None:
    assert _render(
        textarea(
            "Biography",
            id="profile-bio",
            name="profile[bio]",
            value="<builder>",
            rows=6,
            placeholder="Tell us about yourself",
            help_text="Plain text only",
            blur_event="validate",
        )
    ) == (
        '<div class="tori-ui-field"><label class="tori-ui-field__label" '
        'for="profile-bio">Biography</label>'
        '<textarea id="profile-bio" name="profile[bio]" '
        'class="tori-ui-textarea" rows="6" placeholder="Tell us about yourself" '
        'aria-describedby="profile-bio-help" phx-blur="validate">'
        "&lt;builder&gt;</textarea>"
        '<p id="profile-bio-help" class="tori-ui-field__help">'
        "Plain text only</p></div>"
    )


def test_select_renders_prompt_options_and_selected_value() -> None:
    assert _render(
        select(
            "Role",
            [("member", "Member"), ("admin", "<Administrator>")],
            id="profile-role",
            name="profile[role]",
            value="admin",
            prompt="Choose a role",
            required=True,
            change_event="validate",
        )
    ) == (
        '<div class="tori-ui-field"><label class="tori-ui-field__label" '
        'for="profile-role">Role<span class="tori-ui-field__required" '
        'aria-hidden="true"> *</span></label>'
        '<select id="profile-role" name="profile[role]" class="tori-ui-select" '
        'required phx-change="validate">'
        '<option value="">Choose a role</option>'
        '<option value="member">Member</option>'
        '<option value="admin" selected>&lt;Administrator&gt;</option>'
        "</select></div>"
    )


def test_checkbox_renders_checked_value_and_accessible_label() -> None:
    assert _render(
        checkbox(
            "Accept terms",
            id="profile-terms",
            name="profile[terms]",
            value="accepted",
            checked=True,
            help_text="Required to continue",
            required=True,
            change_event="validate",
        )
    ) == (
        '<div class="tori-ui-field"><div class="tori-ui-checkbox">'
        '<input type="checkbox" id="profile-terms" name="profile[terms]" '
        'class="tori-ui-checkbox__control" value="accepted" checked required '
        'aria-describedby="profile-terms-help" phx-change="validate">'
        '<label class="tori-ui-checkbox__label" for="profile-terms">'
        'Accept terms<span class="tori-ui-field__required" '
        'aria-hidden="true"> *</span></label></div>'
        '<p id="profile-terms-help" class="tori-ui-field__help">'
        "Required to continue</p></div>"
    )


@pytest.mark.parametrize(
    ("component", "args", "kwargs", "error", "message"),
    [
        (field, ("", "Control"), {"control_id": "name"}, ValueError, "field label"),
        (
            field,
            ("   ", "Control"),
            {"control_id": "name"},
            ValueError,
            "field label",
        ),
        (
            field,
            ("Name", "Control"),
            {"control_id": "name", "required": 1},
            TypeError,
            "field required must be a boolean",
        ),
        (
            field_error,
            ("",),
            {"id": "name-error"},
            ValueError,
            "field error message",
        ),
        (
            input,
            ("Name",),
            {"id": "name", "name": "", "input_type": "text"},
            ValueError,
            "input name",
        ),
        (
            input,
            ("Name",),
            {"id": "name", "name": "name", "input_type": "color"},
            ValueError,
            "input type",
        ),
        (
            input,
            ("Name",),
            {"id": "name", "name": "name", "disabled": 1},
            TypeError,
            "input disabled must be a boolean",
        ),
        (
            input,
            ("Name",),
            {"id": "name", "name": "name", "value": object()},
            TypeError,
            "input value must be a string, number, or None",
        ),
        (
            input,
            ("Name",),
            {"id": "name", "name": "name", "error": ""},
            ValueError,
            "input error cannot be empty",
        ),
        (
            textarea,
            ("Biography",),
            {"id": "bio", "name": "bio", "rows": 0},
            ValueError,
            "textarea rows must be between 1 and 100",
        ),
        (
            textarea,
            ("Biography",),
            {"id": "bio", "name": "bio", "rows": True},
            TypeError,
            "textarea rows must be an integer",
        ),
        (
            textarea,
            ("Biography",),
            {"id": "bio", "name": "bio", "value": None},
            TypeError,
            "textarea value must be a string",
        ),
        (
            select,
            ("Role", [(1, "Admin")]),
            {"id": "role", "name": "role"},
            TypeError,
            "select option values must be strings",
        ),
        (
            select,
            ("Role", [("admin",)]),
            {"id": "role", "name": "role"},
            TypeError,
            "select options must be two-item tuples",
        ),
        (
            checkbox,
            ("Terms",),
            {"id": "terms", "name": "terms", "checked": 1},
            TypeError,
            "checkbox checked must be a boolean",
        ),
        (
            checkbox,
            ("Terms",),
            {"id": "terms", "name": "terms", "target": 1},
            ValueError,
            "checkbox target requires an event",
        ),
    ],
)
def test_form_components_reject_invalid_contract_values(
    component: Any,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error, match=message):
        component(*args, **kwargs)


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
    assert isinstance(form("Fields", id="profile"), Template)
    assert isinstance(field("Name", "Control", control_id="profile-name"), Template)
    assert isinstance(field_error("Required", id="profile-name-error"), Template)
    assert isinstance(input("Name", id="profile-name", name="profile[name]"), Template)
    assert isinstance(textarea("Bio", id="profile-bio", name="profile[bio]"), Template)
    assert isinstance(
        select("Role", [], id="profile-role", name="profile[role]"), Template
    )
    assert isinstance(
        checkbox("Terms", id="profile-terms", name="profile[terms]"), Template
    )
    assert isinstance(button("Save"), Template)
    assert isinstance(badge("Ready"), Template)
    assert isinstance(alert("Ready"), Template)
    assert isinstance(card("Body"), Template)
    assert isinstance(stack([]), Template)
    assert isinstance(grid([]), Template)

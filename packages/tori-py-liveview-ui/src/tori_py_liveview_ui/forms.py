"""Forms, fields, and form controls."""

from __future__ import annotations

from collections.abc import Iterable
from string.templatelib import Template

from tori_py_liveview import JS, attrs, classes, fragment, raw

from tori_py_liveview_ui._shared import (
    INPUT_TYPES,
    InputType,
    boolean,
    control_description,
    event_binding,
    event_target,
    html_id,
    input_value,
    one_of,
    optional_nonempty_text,
    optional_text,
    required_text,
)


def form(
    content: object,
    *,
    id: str,
    change_event: str | JS | None = None,
    submit_event: str | JS | None = None,
    target: int | None = None,
) -> Template:
    id = html_id("form id", id)
    change_event = event_binding("form change event", change_event)
    submit_event = event_binding("form submit event", submit_event)
    target = event_target("form target", target, change_event, submit_event)
    attributes = attrs(
        {
            "id": id,
            "method": "post",
            "class": "tori-ui-form",
            "phx-change": change_event,
            "phx-submit": submit_event,
            "phx-target": target,
        }
    )
    return t"<form{attributes}>{content}</form>"


def field_error(message: str, *, id: str) -> Template:
    message = required_text("field error message", message)
    id = html_id("field error id", id)
    attributes = attrs(
        {
            "id": id,
            "class": "tori-ui-field__error",
            "role": "alert",
        }
    )
    return t"<p{attributes}>{message}</p>"


def field(
    label: str,
    control: object,
    *,
    control_id: str,
    help_text: str | None = None,
    error: str | None = None,
    required: bool = False,
) -> Template:
    label = required_text("field label", label)
    control_id = html_id("field control id", control_id)
    help_text = optional_nonempty_text("field help text", help_text)
    error = optional_nonempty_text("field error", error)
    required = boolean("field required", required)
    class_name = classes(
        "tori-ui-field",
        **{"tori-ui-field--invalid": error is not None},
    )
    label_attributes = attrs({"class": "tori-ui-field__label", "for": control_id})
    required_markup = (
        t'<span class="tori-ui-field__required" aria-hidden="true"> *</span>'
        if required
        else raw("")
    )
    help_markup = (
        t'<p id="{control_id}-help" class="tori-ui-field__help">{help_text}</p>'
        if help_text is not None
        else raw("")
    )
    error_markup = (
        field_error(error, id=f"{control_id}-error") if error is not None else raw("")
    )
    return (
        t'<div class="{class_name}"><label{label_attributes}>{label}'
        t"{required_markup}</label>{control}{help_markup}{error_markup}</div>"
    )


def input(
    label: str,
    *,
    id: str,
    name: str,
    value: str | int | float | None = None,
    input_type: InputType = "text",
    placeholder: str | None = None,
    autocomplete: str | None = None,
    help_text: str | None = None,
    error: str | None = None,
    required: bool = False,
    disabled: bool = False,
    change_event: str | JS | None = None,
    blur_event: str | JS | None = None,
    target: int | None = None,
) -> Template:
    label = required_text("input label", label)
    id = html_id("input id", id)
    name = required_text("input name", name)
    value = input_value(value)
    one_of("input type", input_type, INPUT_TYPES)
    placeholder = optional_text("input placeholder", placeholder)
    autocomplete = optional_text("input autocomplete", autocomplete)
    help_text = optional_nonempty_text("input help text", help_text)
    error = optional_nonempty_text("input error", error)
    required = boolean("input required", required)
    disabled = boolean("input disabled", disabled)
    change_event = event_binding("input change event", change_event)
    blur_event = event_binding("input blur event", blur_event)
    target = event_target("input target", target, change_event, blur_event)
    attributes = attrs(
        {
            "type": input_type,
            "id": id,
            "name": name,
            "class": "tori-ui-input",
            "value": value,
            "placeholder": placeholder,
            "autocomplete": autocomplete,
            "required": required,
            "disabled": disabled,
            "aria-invalid": "true" if error is not None else None,
            "aria-describedby": control_description(id, help_text, error),
            "phx-change": change_event,
            "phx-blur": blur_event,
            "phx-target": target,
        }
    )
    control = t"<input{attributes}>"
    return field(
        label,
        control,
        control_id=id,
        help_text=help_text,
        error=error,
        required=required,
    )


def textarea(
    label: str,
    *,
    id: str,
    name: str,
    value: str = "",
    rows: int = 4,
    placeholder: str | None = None,
    help_text: str | None = None,
    error: str | None = None,
    required: bool = False,
    disabled: bool = False,
    change_event: str | JS | None = None,
    blur_event: str | JS | None = None,
    target: int | None = None,
) -> Template:
    label = required_text("textarea label", label)
    id = html_id("textarea id", id)
    name = required_text("textarea name", name)
    if not isinstance(value, str):
        raise TypeError("textarea value must be a string")
    if type(rows) is not int:
        raise TypeError("textarea rows must be an integer")
    if not 1 <= rows <= 100:
        raise ValueError("textarea rows must be between 1 and 100")
    placeholder = optional_text("textarea placeholder", placeholder)
    help_text = optional_nonempty_text("textarea help text", help_text)
    error = optional_nonempty_text("textarea error", error)
    required = boolean("textarea required", required)
    disabled = boolean("textarea disabled", disabled)
    change_event = event_binding("textarea change event", change_event)
    blur_event = event_binding("textarea blur event", blur_event)
    target = event_target("textarea target", target, change_event, blur_event)
    attributes = attrs(
        {
            "id": id,
            "name": name,
            "class": "tori-ui-textarea",
            "rows": rows,
            "placeholder": placeholder,
            "required": required,
            "disabled": disabled,
            "aria-invalid": "true" if error is not None else None,
            "aria-describedby": control_description(id, help_text, error),
            "phx-change": change_event,
            "phx-blur": blur_event,
            "phx-target": target,
        }
    )
    control = t"<textarea{attributes}>{value}</textarea>"
    return field(
        label,
        control,
        control_id=id,
        help_text=help_text,
        error=error,
        required=required,
    )


def select(
    label: str,
    options: Iterable[tuple[str, object]],
    *,
    id: str,
    name: str,
    value: str | None = None,
    prompt: str | None = None,
    help_text: str | None = None,
    error: str | None = None,
    required: bool = False,
    disabled: bool = False,
    change_event: str | JS | None = None,
    blur_event: str | JS | None = None,
    target: int | None = None,
) -> Template:
    label = required_text("select label", label)
    id = html_id("select id", id)
    name = required_text("select name", name)
    value = optional_text("select value", value)
    prompt = optional_text("select prompt", prompt)
    help_text = optional_nonempty_text("select help text", help_text)
    error = optional_nonempty_text("select error", error)
    required = boolean("select required", required)
    disabled = boolean("select disabled", disabled)
    change_event = event_binding("select change event", change_event)
    blur_event = event_binding("select blur event", blur_event)
    target = event_target("select target", target, change_event, blur_event)
    option_markup: list[Template] = []
    if prompt is not None:
        prompt_attributes = attrs({"value": "", "selected": value is None})
        option_markup.append(t"<option{prompt_attributes}>{prompt}</option>")
    for option in options:
        if not isinstance(option, tuple) or len(option) != 2:
            raise TypeError("select options must be two-item tuples")
        option_value, option_label = option
        if not isinstance(option_value, str):
            raise TypeError("select option values must be strings")
        option_attributes = attrs(
            {"value": option_value, "selected": option_value == value}
        )
        option_markup.append(t"<option{option_attributes}>{option_label}</option>")
    attributes = attrs(
        {
            "id": id,
            "name": name,
            "class": "tori-ui-select",
            "required": required,
            "disabled": disabled,
            "aria-invalid": "true" if error is not None else None,
            "aria-describedby": control_description(id, help_text, error),
            "phx-change": change_event,
            "phx-blur": blur_event,
            "phx-target": target,
        }
    )
    option_content = fragment(option_markup)
    control = t"<select{attributes}>{option_content}</select>"
    return field(
        label,
        control,
        control_id=id,
        help_text=help_text,
        error=error,
        required=required,
    )


def checkbox(
    label: str,
    *,
    id: str,
    name: str,
    value: str = "true",
    checked: bool = False,
    help_text: str | None = None,
    error: str | None = None,
    required: bool = False,
    disabled: bool = False,
    change_event: str | JS | None = None,
    blur_event: str | JS | None = None,
    target: int | None = None,
) -> Template:
    label = required_text("checkbox label", label)
    id = html_id("checkbox id", id)
    name = required_text("checkbox name", name)
    value = required_text("checkbox value", value)
    help_text = optional_nonempty_text("checkbox help text", help_text)
    error = optional_nonempty_text("checkbox error", error)
    checked = boolean("checkbox checked", checked)
    required = boolean("checkbox required", required)
    disabled = boolean("checkbox disabled", disabled)
    change_event = event_binding("checkbox change event", change_event)
    blur_event = event_binding("checkbox blur event", blur_event)
    target = event_target("checkbox target", target, change_event, blur_event)
    class_name = classes(
        "tori-ui-field",
        **{"tori-ui-field--invalid": error is not None},
    )
    control_attributes = attrs(
        {
            "type": "checkbox",
            "id": id,
            "name": name,
            "class": "tori-ui-checkbox__control",
            "value": value,
            "checked": checked,
            "required": required,
            "disabled": disabled,
            "aria-invalid": "true" if error is not None else None,
            "aria-describedby": control_description(id, help_text, error),
            "phx-change": change_event,
            "phx-blur": blur_event,
            "phx-target": target,
        }
    )
    label_attributes = attrs({"class": "tori-ui-checkbox__label", "for": id})
    required_markup = (
        t'<span class="tori-ui-field__required" aria-hidden="true"> *</span>'
        if required
        else raw("")
    )
    help_markup = (
        t'<p id="{id}-help" class="tori-ui-field__help">{help_text}</p>'
        if help_text is not None
        else raw("")
    )
    error_markup = (
        field_error(error, id=f"{id}-error") if error is not None else raw("")
    )
    return (
        t'<div class="{class_name}"><div class="tori-ui-checkbox">'
        t"<input{control_attributes}><label{label_attributes}>{label}"
        t"{required_markup}</label></div>{help_markup}{error_markup}</div>"
    )


__all__ = [
    "checkbox",
    "field",
    "field_error",
    "form",
    "input",
    "select",
    "textarea",
]

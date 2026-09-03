from __future__ import annotations

from collections.abc import Iterable
from string.templatelib import Template
from typing import Literal

from tori_py_liveview import attrs, classes, fragment, raw

type ButtonVariant = Literal["primary", "secondary", "ghost", "danger"]
type ButtonSize = Literal["sm", "md", "lg"]
type ButtonType = Literal["button", "submit", "reset"]
type InputType = Literal[
    "date",
    "datetime-local",
    "email",
    "month",
    "number",
    "password",
    "search",
    "tel",
    "text",
    "time",
    "url",
    "week",
]
type Tone = Literal["neutral", "info", "success", "warning", "danger"]
type Gap = Literal["xs", "sm", "md", "lg", "xl"]
type Alignment = Literal["start", "center", "end", "stretch"]
type Columns = Literal["auto", "1", "2", "3", "4"]

_BUTTON_VARIANTS = frozenset({"primary", "secondary", "ghost", "danger"})
_BUTTON_SIZES = frozenset({"sm", "md", "lg"})
_BUTTON_TYPES = frozenset({"button", "submit", "reset"})
_INPUT_TYPES = frozenset(
    {
        "date",
        "datetime-local",
        "email",
        "month",
        "number",
        "password",
        "search",
        "tel",
        "text",
        "time",
        "url",
        "week",
    }
)
_TONES = frozenset({"neutral", "info", "success", "warning", "danger"})
_GAPS = frozenset({"xs", "sm", "md", "lg", "xl"})
_ALIGNMENTS = frozenset({"start", "center", "end", "stretch"})
_COLUMNS = frozenset({"auto", "1", "2", "3", "4"})
_MAX_SAFE_INTEGER = 2**53 - 1


def _closed(name: str, value: str, allowed: frozenset[str]) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{name} must be one of: {choices}")
    return value


def _optional_text(name: str, value: str | None) -> str | None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{name} must be a string or None")
    return value


def _optional_nonempty_text(name: str, value: str | None) -> str | None:
    value = _optional_text(name, value)
    if value is not None and not value.strip():
        raise ValueError(f"{name} cannot be empty")
    return value


def _required_text(name: str, value: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} cannot be empty")
    return value


def _boolean(name: str, value: bool) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a boolean")
    return value


def _html_id(name: str, value: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value:
        raise ValueError(f"{name} cannot be empty")
    if any(character.isspace() for character in value):
        raise ValueError(f"{name} cannot contain whitespace")
    return value


def _event(name: str, value: str | None) -> str | None:
    if value is not None:
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string or None")
        if not value.strip():
            raise ValueError(f"{name} cannot be empty")
    return value


def _event_target(name: str, target: int | None, *events: str | None) -> int | None:
    if target is not None:
        if type(target) is not int:
            raise TypeError(f"{name} must be an integer or None")
        if not 0 < target <= _MAX_SAFE_INTEGER:
            raise ValueError(f"{name} must be a positive safe integer")
        if not any(event is not None for event in events):
            raise ValueError(f"{name} requires an event")
    return target


def _control_description(
    control_id: str,
    help_text: str | None,
    error: str | None,
) -> str | None:
    ids = []
    if help_text is not None:
        ids.append(f"{control_id}-help")
    if error is not None:
        ids.append(f"{control_id}-error")
    return " ".join(ids) or None


def _input_value(value: str | int | float | None) -> str | int | float | None:
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, (str, int, float))
    ):
        raise TypeError("input value must be a string, number, or None")
    return value


def button(
    label: object,
    *,
    variant: ButtonVariant = "primary",
    size: ButtonSize = "md",
    button_type: ButtonType = "button",
    disabled: bool = False,
    event: str | None = None,
    target: int | None = None,
) -> Template:
    _closed("button variant", variant, _BUTTON_VARIANTS)
    _closed("button size", size, _BUTTON_SIZES)
    _closed("button type", button_type, _BUTTON_TYPES)
    if type(disabled) is not bool:
        raise TypeError("button disabled must be a boolean")
    if event is not None:
        if not isinstance(event, str):
            raise TypeError("button event must be a string or None")
        if not event:
            raise ValueError("button event cannot be empty")
    if target is not None:
        if type(target) is not int:
            raise TypeError("button target must be an integer or None")
        if not 0 < target <= _MAX_SAFE_INTEGER:
            raise ValueError("button target must be a positive safe integer")
        if event is None:
            raise ValueError("button target requires an event")

    class_name = classes(
        "tori-ui-button",
        f"tori-ui-button--{variant}",
        f"tori-ui-button--{size}",
    )
    attributes = attrs(
        {
            "type": button_type,
            "class": class_name,
            "disabled": disabled,
            "phx-click": event,
            "phx-target": target,
        }
    )
    return t"<button{attributes}>{label}</button>"


def form(
    content: object,
    *,
    id: str,
    change_event: str | None = None,
    submit_event: str | None = None,
    target: int | None = None,
) -> Template:
    id = _html_id("form id", id)
    change_event = _event("form change event", change_event)
    submit_event = _event("form submit event", submit_event)
    target = _event_target("form target", target, change_event, submit_event)
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
    message = _required_text("field error message", message)
    id = _html_id("field error id", id)
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
    label = _required_text("field label", label)
    control_id = _html_id("field control id", control_id)
    help_text = _optional_nonempty_text("field help text", help_text)
    error = _optional_nonempty_text("field error", error)
    required = _boolean("field required", required)
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
    change_event: str | None = None,
    blur_event: str | None = None,
    target: int | None = None,
) -> Template:
    label = _required_text("input label", label)
    id = _html_id("input id", id)
    name = _required_text("input name", name)
    value = _input_value(value)
    _closed("input type", input_type, _INPUT_TYPES)
    placeholder = _optional_text("input placeholder", placeholder)
    autocomplete = _optional_text("input autocomplete", autocomplete)
    help_text = _optional_nonempty_text("input help text", help_text)
    error = _optional_nonempty_text("input error", error)
    required = _boolean("input required", required)
    disabled = _boolean("input disabled", disabled)
    change_event = _event("input change event", change_event)
    blur_event = _event("input blur event", blur_event)
    target = _event_target("input target", target, change_event, blur_event)
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
            "aria-describedby": _control_description(id, help_text, error),
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
    change_event: str | None = None,
    blur_event: str | None = None,
    target: int | None = None,
) -> Template:
    label = _required_text("textarea label", label)
    id = _html_id("textarea id", id)
    name = _required_text("textarea name", name)
    if not isinstance(value, str):
        raise TypeError("textarea value must be a string")
    if type(rows) is not int:
        raise TypeError("textarea rows must be an integer")
    if not 1 <= rows <= 100:
        raise ValueError("textarea rows must be between 1 and 100")
    placeholder = _optional_text("textarea placeholder", placeholder)
    help_text = _optional_nonempty_text("textarea help text", help_text)
    error = _optional_nonempty_text("textarea error", error)
    required = _boolean("textarea required", required)
    disabled = _boolean("textarea disabled", disabled)
    change_event = _event("textarea change event", change_event)
    blur_event = _event("textarea blur event", blur_event)
    target = _event_target("textarea target", target, change_event, blur_event)
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
            "aria-describedby": _control_description(id, help_text, error),
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
    change_event: str | None = None,
    blur_event: str | None = None,
    target: int | None = None,
) -> Template:
    label = _required_text("select label", label)
    id = _html_id("select id", id)
    name = _required_text("select name", name)
    value = _optional_text("select value", value)
    prompt = _optional_text("select prompt", prompt)
    help_text = _optional_nonempty_text("select help text", help_text)
    error = _optional_nonempty_text("select error", error)
    required = _boolean("select required", required)
    disabled = _boolean("select disabled", disabled)
    change_event = _event("select change event", change_event)
    blur_event = _event("select blur event", blur_event)
    target = _event_target("select target", target, change_event, blur_event)
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
            "aria-describedby": _control_description(id, help_text, error),
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
    change_event: str | None = None,
    blur_event: str | None = None,
    target: int | None = None,
) -> Template:
    label = _required_text("checkbox label", label)
    id = _html_id("checkbox id", id)
    name = _required_text("checkbox name", name)
    value = _required_text("checkbox value", value)
    help_text = _optional_nonempty_text("checkbox help text", help_text)
    error = _optional_nonempty_text("checkbox error", error)
    checked = _boolean("checkbox checked", checked)
    required = _boolean("checkbox required", required)
    disabled = _boolean("checkbox disabled", disabled)
    change_event = _event("checkbox change event", change_event)
    blur_event = _event("checkbox blur event", blur_event)
    target = _event_target("checkbox target", target, change_event, blur_event)
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
            "aria-describedby": _control_description(id, help_text, error),
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


def badge(content: object, *, tone: Tone = "neutral") -> Template:
    _closed("badge tone", tone, _TONES)
    class_name = classes("tori-ui-badge", f"tori-ui-badge--{tone}")
    return t'<span class="{class_name}">{content}</span>'


def alert(
    content: object,
    *,
    title: str | None = None,
    tone: Tone = "neutral",
) -> Template:
    title = _optional_text("alert title", title)
    _closed("alert tone", tone, _TONES)
    class_name = classes("tori-ui-alert", f"tori-ui-alert--{tone}")
    role = "alert" if tone == "danger" else "status"
    title_markup = (
        t'<h2 class="tori-ui-alert__title">{title}</h2>'
        if title is not None
        else raw("")
    )
    return (
        t'<section class="{class_name}" role="{role}">'
        t'<div class="tori-ui-alert__content">{title_markup}'
        t'<div class="tori-ui-alert__body">{content}</div></div></section>'
    )


def card(
    content: object,
    *,
    eyebrow: str | None = None,
    title: str | None = None,
    footer: object | None = None,
) -> Template:
    eyebrow = _optional_text("card eyebrow", eyebrow)
    title = _optional_text("card title", title)
    eyebrow_markup = (
        t'<p class="tori-ui-card__eyebrow">{eyebrow}</p>'
        if eyebrow is not None
        else raw("")
    )
    title_markup = (
        t'<h2 class="tori-ui-card__title">{title}</h2>'
        if title is not None
        else raw("")
    )
    header_markup = (
        t'<header class="tori-ui-card__header">{eyebrow_markup}{title_markup}</header>'
        if eyebrow is not None or title is not None
        else raw("")
    )
    footer_markup = (
        t'<footer class="tori-ui-card__footer">{footer}</footer>'
        if footer is not None
        else raw("")
    )
    return (
        t'<article class="tori-ui-card">{header_markup}'
        t'<div class="tori-ui-card__body">{content}</div>'
        t"{footer_markup}</article>"
    )


def stack(
    children: Iterable[object],
    *,
    gap: Gap = "md",
    align: Alignment = "stretch",
) -> Template:
    _closed("stack gap", gap, _GAPS)
    _closed("stack alignment", align, _ALIGNMENTS)
    class_name = classes(
        "tori-ui-stack",
        f"tori-ui-stack--gap-{gap}",
        f"tori-ui-stack--align-{align}",
    )
    content = fragment(children)
    return t'<div class="{class_name}">{content}</div>'


def grid(
    children: Iterable[object],
    *,
    columns: Columns = "auto",
    gap: Gap = "md",
) -> Template:
    _closed("grid columns", columns, _COLUMNS)
    _closed("grid gap", gap, _GAPS)
    class_name = classes(
        "tori-ui-grid",
        f"tori-ui-grid--columns-{columns}",
        f"tori-ui-grid--gap-{gap}",
    )
    content = fragment(children)
    return t'<div class="{class_name}">{content}</div>'


__all__ = [
    "alert",
    "badge",
    "button",
    "card",
    "checkbox",
    "field",
    "field_error",
    "form",
    "grid",
    "input",
    "select",
    "stack",
    "textarea",
]

"""Forms, fields, and form controls."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from string.templatelib import Template
from typing import Literal

from tori_py_liveview import JS, attrs, classes, fragment, raw

from tori_py_liveview_ui._shared import (
    InputType,
    bounded_integer,
    control_description,
    event_binding,
    event_target,
    html_id,
    optional_nonempty_text,
    required_text,
)
from tori_py_liveview_ui.icons import icon

type Debounce = int | Literal["blur"]
type FormActionsAlignment = Literal["start", "end", "between"]


@dataclass(frozen=True, slots=True, kw_only=True)
class _ChoiceClasses:
    block: str
    option: str
    control: str
    label: str


_CHOICE = _ChoiceClasses(
    block="tori-ui-choice",
    option="tori-ui-choice__option",
    control="tori-ui-choice__control",
    label="tori-ui-choice__label",
)
_SEGMENTED = _ChoiceClasses(
    block="tori-ui-segmented",
    option="tori-ui-segmented__option",
    control="tori-ui-segmented__control",
    label="tori-ui-segmented__label",
)


def _timing(
    name: str, debounce: Debounce | None, throttle: int | None
) -> dict[str, object]:
    """Return the attributes that slow a control's events down."""
    if debounce is not None and throttle is not None:
        raise ValueError(f"{name} cannot both debounce and throttle")
    if debounce is not None and debounce != "blur":
        bounded_integer(f"{name} debounce", debounce, 0, 60000)
    if throttle is not None:
        bounded_integer(f"{name} throttle", throttle, 0, 60000)
    return {"phx-debounce": debounce, "phx-throttle": throttle}


def _lengths(
    name: str, min_length: int | None, max_length: int | None
) -> dict[str, object]:
    if min_length is not None:
        bounded_integer(f"{name} minimum length", min_length, 0, 1_000_000)
    if max_length is not None:
        bounded_integer(f"{name} maximum length", max_length, 0, 1_000_000)
    if min_length is not None and max_length is not None and min_length > max_length:
        raise ValueError(f"{name} minimum length cannot exceed the maximum length")
    return {"minlength": min_length, "maxlength": max_length}


def _step(value: int | float | Literal["any"] | None) -> int | float | str | None:
    if value is None or value == "any":
        return value
    if value <= 0:
        raise ValueError('input step must be a positive number, "any", or None')
    return value


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
    readonly: bool = False,
    autofocus: bool = False,
    minimum: str | int | float | None = None,
    maximum: str | int | float | None = None,
    step: int | float | Literal["any"] | None = None,
    min_length: int | None = None,
    max_length: int | None = None,
    debounce: Debounce | None = None,
    throttle: int | None = None,
    prefix: object | None = None,
    suffix: object | None = None,
    change_event: str | JS | None = None,
    blur_event: str | JS | None = None,
    target: int | None = None,
) -> Template:
    """Render a labeled single-line input with help and error text.

    ``minimum``, ``maximum``, and ``step`` bound numbers and dates, and
    ``min_length`` and ``max_length`` bound text; the browser enforces them and
    the page still validates. ``debounce`` waits that many milliseconds, or for
    ``"blur"``, before a change event; ``throttle`` limits how often one fires.
    ``prefix`` and ``suffix`` attach short content, such as a unit, to the
    control.
    """
    label = required_text("input label", label)
    id = html_id("input id", id)
    name = required_text("input name", name)
    help_text = optional_nonempty_text("input help text", help_text)
    error = optional_nonempty_text("input error", error)
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
            "readonly": readonly,
            "autofocus": autofocus,
            "min": minimum,
            "max": maximum,
            "step": _step(step),
            **_lengths("input", min_length, max_length),
            "aria-invalid": "true" if error is not None else None,
            "aria-describedby": control_description(id, help_text, error),
            "phx-change": change_event,
            "phx-blur": blur_event,
            "phx-target": target,
            **_timing("input", debounce, throttle),
        }
    )
    control = t"<input{attributes}>"
    if prefix is not None or suffix is not None:
        before = (
            t'<span class="tori-ui-input-group__affix">{prefix}</span>'
            if prefix is not None
            else raw("")
        )
        after = (
            t'<span class="tori-ui-input-group__affix">{suffix}</span>'
            if suffix is not None
            else raw("")
        )
        control = t'<div class="tori-ui-input-group">{before}{control}{after}</div>'
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
    readonly: bool = False,
    min_length: int | None = None,
    max_length: int | None = None,
    debounce: Debounce | None = None,
    throttle: int | None = None,
    change_event: str | JS | None = None,
    blur_event: str | JS | None = None,
    target: int | None = None,
) -> Template:
    label = required_text("textarea label", label)
    id = html_id("textarea id", id)
    name = required_text("textarea name", name)
    if not 1 <= rows <= 100:
        raise ValueError("textarea rows must be between 1 and 100")
    help_text = optional_nonempty_text("textarea help text", help_text)
    error = optional_nonempty_text("textarea error", error)
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
            "readonly": readonly,
            **_lengths("textarea", min_length, max_length),
            "aria-invalid": "true" if error is not None else None,
            "aria-describedby": control_description(id, help_text, error),
            "phx-change": change_event,
            "phx-blur": blur_event,
            "phx-target": target,
            **_timing("textarea", debounce, throttle),
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
    help_text = optional_nonempty_text("select help text", help_text)
    error = optional_nonempty_text("select error", error)
    change_event = event_binding("select change event", change_event)
    blur_event = event_binding("select blur event", blur_event)
    target = event_target("select target", target, change_event, blur_event)
    option_markup: list[Template] = []
    if prompt is not None:
        prompt_attributes = attrs({"value": "", "selected": value is None})
        option_markup.append(t"<option{prompt_attributes}>{prompt}</option>")
    for option in options:
        option_value, option_label = option
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


def _messages(
    control_id: str, help_text: str | None, error: str | None
) -> tuple[object, object]:
    help_markup = (
        t'<p id="{control_id}-help" class="tori-ui-field__help">{help_text}</p>'
        if help_text is not None
        else raw("")
    )
    error_markup = (
        field_error(error, id=f"{control_id}-error") if error is not None else raw("")
    )
    return help_markup, error_markup


def _required_marker(required: bool) -> object:
    if not required:
        return raw("")
    return t'<span class="tori-ui-field__required" aria-hidden="true"> *</span>'


def _choices(
    name: str,
    kind: Literal["radio", "checkbox"],
    label: str,
    options: Iterable[tuple[str, object]],
    chosen: frozenset[str],
    *,
    id: str,
    field_name: str,
    names: _ChoiceClasses,
    help_text: str | None,
    error: str | None,
    required: bool,
    disabled: bool,
    inline: bool,
    change_event: str | JS | None,
    target: int | None,
) -> Template:
    """Render a labeled group of native radio buttons or checkboxes."""
    label = required_text(f"{name} label", label)
    id = html_id(f"{name} id", id)
    field_name = required_text(f"{name} name", field_name)
    help_text = optional_nonempty_text(f"{name} help text", help_text)
    error = optional_nonempty_text(f"{name} error", error)
    change_event = event_binding(f"{name} change event", change_event)
    target = event_target(f"{name} target", target, change_event)
    choices: list[Template] = []
    for index, (value, option_label) in enumerate(options, start=1):
        control = attrs(
            {
                "type": kind,
                "id": f"{id}-{index}",
                "name": field_name,
                "class": names.control,
                "value": value,
                "checked": value in chosen,
                # A group of checkboxes is required as a whole, by the page.
                "required": required and kind == "radio",
                "disabled": disabled,
                "phx-change": change_event,
                "phx-target": target,
            }
        )
        choices.append(
            t'<label class="{names.option}"><input{control}>'
            t'<span class="{names.label}">{option_label}</span></label>'
        )
    help_markup, error_markup = _messages(id, help_text, error)
    group = attrs(
        {
            "id": id,
            "class": classes(
                "tori-ui-field",
                "tori-ui-fieldset",
                **{"tori-ui-field--invalid": error is not None},
            ),
            "role": "radiogroup" if kind == "radio" else "group",
            "aria-required": "true" if required and kind == "radio" else None,
            "aria-invalid": "true" if error is not None else None,
            "aria-describedby": control_description(id, help_text, error),
        }
    )
    options_class = classes(names.block, **{"tori-ui-choice--inline": inline})
    return (
        t'<fieldset{group}><legend class="tori-ui-field__label">{label}'
        t"{_required_marker(required)}</legend>"
        t'<div class="{options_class}">{fragment(choices)}</div>'
        t"{help_markup}{error_markup}</fieldset>"
    )


def radio_group(
    label: str,
    options: Iterable[tuple[str, object]],
    *,
    id: str,
    name: str,
    value: str | None = None,
    help_text: str | None = None,
    error: str | None = None,
    required: bool = False,
    disabled: bool = False,
    inline: bool = False,
    change_event: str | JS | None = None,
    target: int | None = None,
) -> Template:
    """Render a labeled group of radio buttons over ``(value, label)`` pairs."""
    return _choices(
        "radio group",
        "radio",
        label,
        options,
        frozenset() if value is None else frozenset({value}),
        id=id,
        field_name=name,
        names=_CHOICE,
        help_text=help_text,
        error=error,
        required=required,
        disabled=disabled,
        inline=inline,
        change_event=change_event,
        target=target,
    )


def checkbox_group(
    label: str,
    options: Iterable[tuple[str, object]],
    *,
    id: str,
    name: str,
    values: Iterable[str] = (),
    help_text: str | None = None,
    error: str | None = None,
    required: bool = False,
    disabled: bool = False,
    inline: bool = False,
    change_event: str | JS | None = None,
    target: int | None = None,
) -> Template:
    """Render a labeled group of checkboxes that submit a list.

    End ``name`` in ``[]``, as in ``"task[tags][]"``, so the form event
    carries every checked value. ``required`` only marks the label: the page
    decides whether an empty selection is an error.
    """
    return _choices(
        "checkbox group",
        "checkbox",
        label,
        options,
        frozenset(values),
        id=id,
        field_name=name,
        names=_CHOICE,
        help_text=help_text,
        error=error,
        required=required,
        disabled=disabled,
        inline=inline,
        change_event=change_event,
        target=target,
    )


def segmented(
    label: str,
    options: Iterable[tuple[str, object]],
    *,
    id: str,
    name: str,
    value: str | None = None,
    help_text: str | None = None,
    error: str | None = None,
    required: bool = False,
    disabled: bool = False,
    change_event: str | JS | None = None,
    target: int | None = None,
) -> Template:
    """Render radio buttons as one segmented control, for a few short options."""
    return _choices(
        "segmented",
        "radio",
        label,
        options,
        frozenset() if value is None else frozenset({value}),
        id=id,
        field_name=name,
        names=_SEGMENTED,
        help_text=help_text,
        error=error,
        required=required,
        disabled=disabled,
        inline=False,
        change_event=change_event,
        target=target,
    )


def switch(
    label: str,
    *,
    id: str,
    name: str,
    value: str = "true",
    checked: bool = False,
    help_text: str | None = None,
    error: str | None = None,
    disabled: bool = False,
    change_event: str | JS | None = None,
    target: int | None = None,
) -> Template:
    """Render a checkbox as an on/off switch, for a setting that applies at once."""
    label = required_text("switch label", label)
    id = html_id("switch id", id)
    name = required_text("switch name", name)
    value = required_text("switch value", value)
    help_text = optional_nonempty_text("switch help text", help_text)
    error = optional_nonempty_text("switch error", error)
    change_event = event_binding("switch change event", change_event)
    target = event_target("switch target", target, change_event)
    control = attrs(
        {
            "type": "checkbox",
            "role": "switch",
            "id": id,
            "name": name,
            "class": "tori-ui-switch__control",
            "value": value,
            "checked": checked,
            "disabled": disabled,
            "aria-invalid": "true" if error is not None else None,
            "aria-describedby": control_description(id, help_text, error),
            "phx-change": change_event,
            "phx-target": target,
        }
    )
    help_markup, error_markup = _messages(id, help_text, error)
    class_name = classes(
        "tori-ui-field", **{"tori-ui-field--invalid": error is not None}
    )
    return (
        t'<div class="{class_name}"><div class="tori-ui-switch"><input{control}>'
        t'<label class="tori-ui-switch__label" for="{id}">{label}</label></div>'
        t"{help_markup}{error_markup}</div>"
    )


def multi_select(
    label: str,
    options: Iterable[tuple[str, object]],
    *,
    id: str,
    name: str,
    values: Iterable[str] = (),
    size: int = 4,
    help_text: str | None = None,
    error: str | None = None,
    required: bool = False,
    disabled: bool = False,
    change_event: str | JS | None = None,
    blur_event: str | JS | None = None,
    target: int | None = None,
) -> Template:
    """Render a native list box that selects several ``(value, label)`` options.

    End ``name`` in ``[]`` so the form event carries every selected value.
    """
    label = required_text("multi select label", label)
    id = html_id("multi select id", id)
    name = required_text("multi select name", name)
    chosen = frozenset(values)
    bounded_integer("multi select size", size, 2, 20)
    help_text = optional_nonempty_text("multi select help text", help_text)
    error = optional_nonempty_text("multi select error", error)
    change_event = event_binding("multi select change event", change_event)
    blur_event = event_binding("multi select blur event", blur_event)
    target = event_target("multi select target", target, change_event, blur_event)
    option_markup = [
        t"<option{attrs({'value': value, 'selected': value in chosen})}>{text}</option>"
        for value, text in options
    ]
    attributes = attrs(
        {
            "id": id,
            "name": name,
            "class": "tori-ui-select tori-ui-select--multiple",
            "multiple": True,
            "size": size,
            "required": required,
            "disabled": disabled,
            "aria-invalid": "true" if error is not None else None,
            "aria-describedby": control_description(id, help_text, error),
            "phx-change": change_event,
            "phx-blur": blur_event,
            "phx-target": target,
        }
    )
    control = t"<select{attributes}>{fragment(option_markup)}</select>"
    return field(
        label,
        control,
        control_id=id,
        help_text=help_text,
        error=error,
        required=required,
    )


def combobox(
    label: str,
    options: Iterable[str | tuple[str, object]],
    *,
    id: str,
    name: str,
    value: str = "",
    placeholder: str | None = None,
    help_text: str | None = None,
    error: str | None = None,
    required: bool = False,
    disabled: bool = False,
    debounce: Debounce | None = None,
    change_event: str | JS | None = None,
    blur_event: str | JS | None = None,
    target: int | None = None,
) -> Template:
    """Render a text field that suggests options and still accepts any text.

    An option is a value, or a ``(value, label)`` pair. The browser filters the
    native suggestion list as the visitor types; to load suggestions from the
    server, handle the change event and render new options.
    """
    label = required_text("combobox label", label)
    id = html_id("combobox id", id)
    name = required_text("combobox name", name)
    help_text = optional_nonempty_text("combobox help text", help_text)
    error = optional_nonempty_text("combobox error", error)
    change_event = event_binding("combobox change event", change_event)
    blur_event = event_binding("combobox blur event", blur_event)
    target = event_target("combobox target", target, change_event, blur_event)
    list_id = f"{id}-options"
    suggestions: list[Template] = []
    for option in options:
        if isinstance(option, str):
            suggestions.append(t"<option{attrs({'value': option})}></option>")
        else:
            suggestions.append(
                t"<option{attrs({'value': option[0]})}>{option[1]}</option>"
            )
    attributes = attrs(
        {
            "type": "text",
            "id": id,
            "name": name,
            "class": "tori-ui-input",
            "list": list_id,
            "value": value,
            "placeholder": placeholder,
            "autocomplete": "off",
            "required": required,
            "disabled": disabled,
            "aria-invalid": "true" if error is not None else None,
            "aria-describedby": control_description(id, help_text, error),
            "phx-change": change_event,
            "phx-blur": blur_event,
            "phx-target": target,
            **_timing("combobox", debounce, None),
        }
    )
    listing = fragment(suggestions)
    control = t'<input{attributes}><datalist id="{list_id}">{listing}</datalist>'
    return field(
        label,
        control,
        control_id=id,
        help_text=help_text,
        error=error,
        required=required,
    )


def search(
    label: str,
    *,
    id: str,
    name: str,
    value: str = "",
    placeholder: str | None = None,
    disabled: bool = False,
    debounce: Debounce | None = 300,
    change_event: str | JS | None = None,
    target: int | None = None,
) -> Template:
    """Render a search field with an icon and a visually hidden label.

    Changes are debounced by 300 milliseconds unless ``debounce`` says
    otherwise, so a form's change event fires when the visitor pauses.
    """
    label = required_text("search label", label)
    id = html_id("search id", id)
    name = required_text("search name", name)
    change_event = event_binding("search change event", change_event)
    target = event_target("search target", target, change_event)
    attributes = attrs(
        {
            "type": "search",
            "id": id,
            "name": name,
            "class": "tori-ui-input tori-ui-search__input",
            "value": value,
            "placeholder": placeholder,
            "autocomplete": "off",
            "disabled": disabled,
            "phx-change": change_event,
            "phx-target": target,
            **_timing("search", debounce, None),
        }
    )
    glass = icon("search", size="sm")
    return (
        t'<div class="tori-ui-search"><label class="tori-ui-visually-hidden" '
        t'for="{id}">{label}</label>{glass}<input{attributes}></div>'
    )


def slider(
    label: str,
    *,
    id: str,
    name: str,
    value: int | float,
    minimum: int | float = 0,
    maximum: int | float = 100,
    step: int | float = 1,
    show_value: bool = True,
    help_text: str | None = None,
    disabled: bool = False,
    debounce: Debounce | None = None,
    throttle: int | None = None,
    change_event: str | JS | None = None,
    target: int | None = None,
) -> Template:
    """Render a native range input, with the value the page last rendered."""
    label = required_text("slider label", label)
    id = html_id("slider id", id)
    name = required_text("slider name", name)
    if minimum >= maximum:
        raise ValueError("slider minimum must be below the maximum")
    if not minimum <= value <= maximum:
        raise ValueError("slider value must be within the range")
    if step <= 0:
        raise ValueError("slider step must be positive")
    help_text = optional_nonempty_text("slider help text", help_text)
    change_event = event_binding("slider change event", change_event)
    target = event_target("slider target", target, change_event)
    attributes = attrs(
        {
            "type": "range",
            "id": id,
            "name": name,
            "class": "tori-ui-slider__control",
            "value": value,
            "min": minimum,
            "max": maximum,
            "step": step,
            "disabled": disabled,
            "aria-describedby": control_description(id, help_text, None),
            "phx-change": change_event,
            "phx-target": target,
            **_timing("slider", debounce, throttle),
        }
    )
    shown = (
        t'<output class="tori-ui-slider__value" for="{id}">{value}</output>'
        if show_value
        else raw("")
    )
    control = t'<div class="tori-ui-slider"><input{attributes}>{shown}</div>'
    return field(label, control, control_id=id, help_text=help_text)


def hidden(*, name: str, value: str | int | float, id: str | None = None) -> Template:
    """Render a hidden input that travels with its form."""
    name = required_text("hidden name", name)
    if id is not None:
        id = html_id("hidden id", id)
    attributes = attrs({"type": "hidden", "id": id, "name": name, "value": value})
    return t"<input{attributes}>"


def fieldset(
    legend: str,
    content: object,
    *,
    description: str | None = None,
    disabled: bool = False,
) -> Template:
    """Group related fields under a legend.

    ``disabled`` disables every control inside, natively.
    """
    legend = required_text("fieldset legend", legend)
    description = optional_nonempty_text("fieldset description", description)
    attributes = attrs(
        {"class": "tori-ui-fieldset tori-ui-fieldset--section", "disabled": disabled}
    )
    description_markup = (
        t'<p class="tori-ui-fieldset__description">{description}</p>'
        if description is not None
        else raw("")
    )
    return (
        t'<fieldset{attributes}><legend class="tori-ui-fieldset__legend">{legend}'
        t"</legend>{description_markup}"
        t'<div class="tori-ui-fieldset__content">{content}</div></fieldset>'
    )


def form_actions(
    children: Iterable[object],
    *,
    align: FormActionsAlignment = "end",
) -> Template:
    """Line up a form's buttons under its fields."""
    class_name = classes("tori-ui-form-actions", f"tori-ui-form-actions--{align}")
    return t'<div class="{class_name}">{fragment(children)}</div>'


__all__ = [
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

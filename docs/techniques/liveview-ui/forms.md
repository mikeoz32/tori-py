# Forms

The form helpers render native, labeled controls with help text, error text, and
the matching ARIA relationships. They emit Phoenix bindings but do not coerce,
validate, or remember values. The page holds the current values and errors and
passes them back on every render.

## A Validated Form

```python
from dataclasses import dataclass
from string.templatelib import Template

from tori_py_liveview import UnknownEventError, live_view
from tori_py_liveview_ui import (
    UiLiveView,
    alert,
    button,
    checkbox,
    form,
    input,
    select,
    stack,
    textarea,
)

ROLES = (("dev", "Developer"), ("ops", "Operations"), ("pm", "Product"))


@dataclass
class ProfileDraft:
    email: str = ""
    role: str = ""
    bio: str = ""
    newsletter: bool = False


@live_view("/profile")
class ProfileLive(UiLiveView):
    def __init__(self) -> None:
        self.draft = ProfileDraft()
        self.errors: dict[str, str] = {}
        self.saved = False

    async def handle_event(self, event: str, value: object) -> None:
        if event not in {"validate", "save"} or not isinstance(value, dict):
            raise UnknownEventError(event)
        fields = value.get("profile")
        if not isinstance(fields, dict):
            raise UnknownEventError(event)
        self.draft = ProfileDraft(
            email=str(fields.get("email", "")).strip(),
            role=str(fields.get("role", "")),
            bio=str(fields.get("bio", "")),
            newsletter=fields.get("newsletter") == "yes",
        )
        self.errors = self.validate(self.draft)
        self.saved = event == "save" and not self.errors

    @staticmethod
    def validate(draft: ProfileDraft) -> dict[str, str]:
        errors: dict[str, str] = {}
        if "@" not in draft.email:
            errors["email"] = "Enter an email address."
        if draft.role not in {value for value, _ in ROLES}:
            errors["role"] = "Choose a role."
        if len(draft.bio) > 500:
            errors["bio"] = "Keep the bio under 500 characters."
        return errors

    def render(self) -> Template:
        controls = stack(
            [
                input(
                    "Email",
                    id="profile-email",
                    name="profile[email]",
                    value=self.draft.email,
                    input_type="email",
                    autocomplete="email",
                    error=self.errors.get("email"),
                    required=True,
                ),
                select(
                    "Role",
                    ROLES,
                    id="profile-role",
                    name="profile[role]",
                    value=self.draft.role or None,
                    prompt="Choose…",
                    error=self.errors.get("role"),
                    required=True,
                ),
                textarea(
                    "Bio",
                    id="profile-bio",
                    name="profile[bio]",
                    value=self.draft.bio,
                    help_text="Shown on your public profile.",
                    error=self.errors.get("bio"),
                ),
                checkbox(
                    "Send me the newsletter",
                    id="profile-newsletter",
                    name="profile[newsletter]",
                    value="yes",
                    checked=self.draft.newsletter,
                ),
                button("Save", button_type="submit"),
            ],
            gap="sm",
            align="start",
        )
        notice = alert("Profile saved.", tone="success") if self.saved else ""
        profile_form = form(
            controls,
            id="profile-form",
            change_event="validate",
            submit_event="save",
        )
        return t"<main>{notice}{profile_form}</main>"
```

`validate` runs on every change and re-renders the errors; `save` runs on submit.
A real page would call an application service from `save` and authorize the
change there.

## Names and Decoded Values

`name` is emitted unchanged, so Phoenix bracket notation works:

| Control `name` | Decoded value |
| --- | --- |
| `profile[email]` | `{"profile": {"email": "..."}}` |
| `tags[]` on several controls | `{"tags": ["a", "b"]}` |
| `items[0][qty]` | `{"items": {"0": {"qty": "..."}}}` |

Every leaf is a string. An unchecked checkbox is absent; a checked one submits
its `value` (`"true"` by default). A `select` submits the chosen option value,
or `""` for the prompt. `phx-change` events also carry `_target`, the token list
of the control that changed, so you can validate only that field:

<!-- docs-test: skip -->

```python
match value:
    case {"_target": ["profile", "email"], "profile": {"email": str(email)}}:
        self.errors.pop("email", None)
        if "@" not in email:
            self.errors["email"] = "Enter an email address."
```

`blur_event` binds `phx-blur`. Its handler receives the control's event value,
normally `{"value": "..."}`, not the whole form.

## Control Options

All controls take `label`, `id`, and `name`, plus:

| Option | Controls | Notes |
| --- | --- | --- |
| `value` | all | `input`: `str`, `int`, `float`, or `None`; `textarea`: `str`; `select`: selected option value or `None`; `checkbox`: submitted value |
| `help_text` | all | Rendered as `<p id="<id>-help">` |
| `error` | all | Rendered with `field_error()` as `<p id="<id>-error" role="alert">` |
| `required` | all | Native `required` plus a visual marker hidden from screen readers |
| `disabled` | all | Native `disabled` |
| `change_event`, `blur_event` | all | Event name or `JS` chain |
| `target` | all | Component `myself`; requires an event |
| `input_type` | `input` | `text`, `email`, `password`, `search`, `tel`, `url`, `number`, `date`, `time`, `datetime-local`, `month`, `week` |
| `placeholder` | `input`, `textarea` | Not a substitute for a label |
| `autocomplete` | `input` | Passed through as the native attribute |
| `rows` | `textarea` | 1 to 100, default 4 |
| `prompt` | `select` | First option with an empty value |
| `checked` | `checkbox` | Initial state |

Help and error IDs are joined into the control's `aria-describedby`, and an
error also sets `aria-invalid="true"`. Keep control IDs unique on the page.

### Bounds, Timing, and Affixes

`input` and `textarea` take further options:

| Option | Controls | Notes |
| --- | --- | --- |
| `minimum`, `maximum`, `step` | `input` | Native `min`, `max`, and `step` for numbers and dates; `step` may be `"any"` |
| `min_length`, `max_length` | `input`, `textarea` | Native `minlength` and `maxlength` |
| `readonly` | `input`, `textarea` | Shown and submitted, not editable |
| `autofocus` | `input` | Focus on page load; use it for at most one control |
| `debounce` | `input`, `textarea` | Milliseconds to wait after the last keystroke, or `"blur"` |
| `throttle` | `input`, `textarea` | At most one change event per that many milliseconds |
| `prefix`, `suffix` | `input` | Short content attached to the control, such as a unit |

The browser enforces the bounds, which helps the visitor; the page still
validates, because a request does not have to come from a browser.

`debounce` and `throttle` slow down the form's change event for that control:

```python
from tori_py_liveview_ui import input

price = input(
    "Price",
    id="price",
    name="product[price]",
    input_type="number",
    minimum=0,
    step=0.01,
    prefix="$",
    debounce=300,
)
```

## Choices

| Helper | Renders | Submits |
| --- | --- | --- |
| `radio_group(label, options, *, id, name, value, inline, ...)` | Radio buttons in a `<fieldset>` | One value |
| `segmented(label, options, *, id, name, value, ...)` | Radio buttons as one segmented control | One value |
| `checkbox_group(label, options, *, id, name, values, inline, ...)` | Checkboxes in a `<fieldset>` | A list |
| `multi_select(label, options, *, id, name, values, size, ...)` | A native list box | A list |
| `select(label, options, *, id, name, value, prompt, ...)` | A native drop-down | One value |
| `switch(label, *, id, name, value, checked, ...)` | A checkbox with the switch role | Its value, or nothing when off |
| `checkbox(label, *, id, name, value, checked, ...)` | One checkbox | Its value, or nothing when unchecked |

Options are `(value, label)` pairs with string values, as for `select`.

```python
from tori_py_liveview_ui import checkbox_group, radio_group, segmented, switch

plan = radio_group(
    "Plan",
    [("free", "Free"), ("team", "Team")],
    id="plan",
    name="account[plan]",
    value="team",
    inline=True,
)
topics = checkbox_group(
    "Email topics",
    [("product", "Product news"), ("tips", "Tips")],
    id="topics",
    name="account[topics][]",
    values=["product"],
)
view = segmented(
    "Default view",
    [("list", "List"), ("board", "Board")],
    id="view",
    name="account[view]",
    value="list",
)
replies = switch("Notify me about replies", id="notify", name="account[notify]")
```

- End the `name` of `checkbox_group` and `multi_select` in `[]`, so the form
  event carries every chosen value as a list. With nothing chosen the key is
  absent.
- A radio group follows the native keyboard model: Tab enters the group and the
  arrow keys move the choice. `segmented` is the same group with another look;
  use it for two to five short options.
- `required` on a `radio_group` is enforced by the browser. On a
  `checkbox_group` it only marks the label, because the browser has no rule for
  "at least one"; check it on the page.
- Use `switch` for a setting that takes effect at once and `checkbox` for a
  choice that is submitted with the rest of a form.

## Other Controls

| Helper | Renders |
| --- | --- |
| `combobox(label, options, *, id, name, value, ...)` | A text field with native suggestions |
| `search(label, *, id, name, value, debounce, ...)` | A search field with an icon and a hidden label |
| `slider(label, *, id, name, value, minimum, maximum, step, ...)` | A native range input |
| `hidden(*, name, value, id)` | A hidden input |

`combobox` accepts any text; the options are suggestions, each a value or a
`(value, label)` pair, and the browser filters them as the visitor types. To
load suggestions from the server, handle the change event and render new
options.

`search` debounces by 300 milliseconds by default, so a form's change event
fires when the visitor pauses. Its label is read by screen readers and not
shown; say what is searched, not only "Search".

`slider` shows the value the page last rendered next to the track. Handle the
form's change event to keep it current while the visitor drags, and pass
`throttle` to limit how often that happens.

## Grouping

`fieldset(legend, content, *, description, disabled)` groups related fields
under a legend, and `disabled=True` disables every control inside natively.
`form_actions(children, *, align)` lines up the form's buttons under the
fields; `align` is `start`, `end`, or `between`.

```python
from tori_py_liveview_ui import button, fieldset, form, form_actions, stack

account_form = form(
    stack(
        [
            fieldset("Plan and topics", stack([plan, topics, view, replies])),
            form_actions(
                [
                    button("Cancel", variant="ghost", event="cancel"),
                    button("Save", button_type="submit", disable_with="Saving"),
                ]
            ),
        ],
        gap="lg",
    ),
    id="account-form",
    change_event="validate",
    submit_event="save",
)
```

## Form-Level Events

`form(content, *, id, change_event, submit_event, target)` renders
`<form method="post">`. Put `change_event` on the form to validate as the user
types, and `submit_event` to handle submission. A submit button inside a
`phx-submit` form needs no click event of its own; adding one would send two
events.

A control-level `change_event` works only inside a form, because the Phoenix
client sends change events for forms. Use it to send one control's changes to a
different handler or component.

`method="post"` keeps values out of the URL if the form is submitted before the
socket connects. The package does not handle that POST. If you need a
non-JavaScript fallback, add your own HTTP endpoint and point the form at it.

## Custom Controls with `field()`

Wrap a control the helpers do not provide with `field()` to get the same label,
help, and error layout. Your control must use `control_id` as its `id` and wire
the descriptions itself:

<!-- docs-test: skip -->

```python
from tori_py_liveview import attrs
from tori_py_liveview_ui import field

color_id = "theme-color"
color = attrs(
    {
        "type": "color",
        "id": color_id,
        "name": "theme[color]",
        "value": self.color,
        "aria-describedby": f"{color_id}-help",
    }
)
picker = field(
    "Accent color",
    t"<input{color}>",
    control_id=color_id,
    help_text="Used for buttons and links.",
)
```

When you pass `error=`, also add `{control_id}-error` to `aria-describedby` and
set `aria-invalid="true"` on the control.

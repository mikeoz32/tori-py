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

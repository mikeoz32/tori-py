# Overlays

Overlay helpers render content that opens over the page: modals, drawers,
confirmations, menus, and popovers.

Modals, drawers, and confirmations are native `<dialog>` elements. The browser
holds the keyboard focus inside an open dialog, makes the rest of the page
inert, closes it on Escape, and returns the focus to where it was. Menus and
popovers are small panels next to the button that opens them.

## Modals

Whether a modal is open is usually presentation state, so by default the
browser owns it and opening costs no round trip:

```python
from string.templatelib import Template

from tori_py_liveview_ui import button, close_overlay, modal, open_overlay, text


def settings() -> Template:
    dialog = modal(
        text("Notifications are sent to your account email."),
        id="settings",
        title="Settings",
        description="These apply to this browser.",
        footer=button("Done", event=close_overlay("settings")),
    )
    return t"{button('Open settings', event=open_overlay('settings'))}{dialog}"
```

`open_overlay(id)` and `close_overlay(id)` return
[`JS` commands](../liveview/js-commands.md). Pass one as a button's `event`, or
chain more commands onto it, for example to push an event and close:

```python
from tori_py_liveview import JS

save_and_close = JS().push("save").dispatch("tori-ui:close", to="#settings")
```

`modal(content, *, id, title, description, footer, size, open, dismissible,
close_event, close_label, target)`:

- `id` is required and must be unique. It starts with a letter and may contain
  letters, digits, `-`, and `_`.
- `title` is required and names the dialog. `description` is announced with it.
- `size` is `sm`, `md`, `lg`, or `xl`.
- The visitor closes the dialog with its close button, with Escape, or with a
  click outside it. `dismissible=False` removes all three, for a step the
  visitor must finish with the controls in the dialog.

Render the modal anywhere in the page; an open dialog is drawn above everything
else regardless of where it sits in the markup.

### When the Page Owns the State

Pass `open` when the page decides, for example to open a dialog after loading
data or to keep it open until a form validates. Give a `close_event` too, so the
page hears that the visitor closed it:

```python
from tori_py_liveview import LiveView, UnknownEventError


class ProfileLive(LiveView):
    def __init__(self) -> None:
        self.editing = False

    async def handle_event(self, event: str, value: object) -> None:
        match event:
            case "edit":
                self.editing = True
            case "close_edit":
                self.editing = False
            case _:
                raise UnknownEventError(event)

    def render(self) -> Template:
        dialog = modal(
            text("Edit your profile here."),
            id="edit",
            title="Edit profile",
            open=self.editing,
            close_event="close_edit",
        )
        return t"{button('Edit profile', event='edit')}{dialog}"
```

With `open` set, the dialog follows what the page renders. Escape, the close
button, and a click outside push `close_event` instead of closing the dialog
directly, and the page closes it by rendering `open=False`.

Leave `open` out, as in the first example, unless the page needs to decide.

## Drawers

`drawer(content, *, id, title, side, ...)` is a dialog that slides in from the
`start` or `end` side and takes the full height. It takes the same options as
`modal`, opens with `open_overlay(id)`, and suits filters, details, and forms
that should not hide the whole page.

## Confirmations

`confirm_dialog(message, *, id, title, confirm_event, confirm_label,
cancel_label, tone, target, values, open, cancel_event)` asks before an action:

```python
from tori_py_liveview_ui import confirm_dialog

delete = confirm_dialog(
    "The project and its history are removed for everyone.",
    id="confirm-delete",
    title="Delete the project?",
    confirm_event="delete",
    confirm_label="Delete",
    tone="danger",
    values={"id": 7},
)
trigger = button("Delete project", variant="danger", event=open_overlay("confirm-delete"))
```

Confirming pushes `confirm_event` with `values` and closes the dialog.
Cancelling, Escape, and a click outside only close it. `tone="danger"` colors
the confirm button for destructive actions.

For a quick question without a styled dialog, `button(confirm="...")` uses the
browser's own prompt; see [Actions](actions.md#confirm).

## Menus

`dropdown(label, items, *, id, variant, size, icon, align)` renders a button
that opens a menu of `menu_item()` entries:

```python
from tori_py_liveview_ui import divider, dropdown, menu_item

actions = dropdown(
    "Actions",
    [
        menu_item("Rename", event="rename", icon="edit"),
        menu_item("Open in a new page", href="/projects/7", live="navigate"),
        divider(),
        menu_item("Delete", event="delete", icon="trash", tone="danger"),
    ],
    id="project-actions",
    align="end",
)
```

`menu_item(label, *, event, href, live, target, values, icon, tone, disabled)`
is a button with `event` or a link with `href`; it takes one of the two.

The menu follows the menu pattern: opening it moves the focus to the first
item, the arrow keys and Home and End move between items, Escape closes it and
returns the focus to the button, and it also closes on a choice, on a click
outside, and when the focus leaves. `align` is `start` or `end` and says which
edge of the button the menu lines up with.

## Popovers

`popover(label, content, *, id, panel_label, ...)` renders a button that opens a
small panel of any content, such as a few filters or an explanation.
`panel_label` names the panel for assistive technology. It closes on Escape and
on a click outside.

```python
from tori_py_liveview_ui import popover

help_panel = popover(
    "Shortcuts",
    text("Press ? anywhere to see every shortcut."),
    id="shortcuts",
    panel_label="Keyboard shortcuts",
    icon="help-circle",
)
```

Use a popover for content the visitor may read and leave, a `dropdown` for a
list of actions, and a `modal` when the page should wait for an answer.

Menus and popovers are placed below their button and are not moved when they
would leave the viewport. Use `align="end"` for a button near the right edge.

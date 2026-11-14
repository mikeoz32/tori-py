# Disclosure and Tabs

Disclosure helpers show and hide content in place. Whether a section is open is
presentation state, so the browser keeps it and a server render does not reset
it.

## Collapsible Sections

`collapsible(summary, content, *, open, id, group)` renders a native
`<details>` element:

```python
from tori_py_liveview_ui import accordion, collapsible, text

shipping = collapsible(
    "Shipping details",
    text("Orders leave the warehouse within two days."),
)

faq = accordion(
    [
        collapsible("How do I pay?", text("By card or invoice."), group="faq"),
        collapsible("Can I return an item?", text("Within 30 days."), group="faq"),
    ]
)
```

- `open` is only the state the section starts in. After that the visitor's
  choice wins: the helper tells the LiveView client to leave the `open`
  attribute alone when it patches the page.
- Sections with the same `group` close each other, so at most one is open.
- `accordion(children)` joins sections into one bordered list.

Because it is a native element, a collapsible section works before the page
connects, opens from the keyboard, and is found by the browser's find-in-page.

## Tabs

`tabs(items, *, id, label, active, event, target)` renders a tab list and its
panels. Each item is `(key, tab label, panel content)`. `id` and `label` are
required; keys may contain letters, digits, `-`, and `_`.

Tabs come in two forms. Choose by where the content comes from.

### Tabs the Browser Switches

Without `event`, every panel is rendered and the browser switches between them
with no round trip:

```python
from tori_py_liveview_ui import tabs

settings = tabs(
    [
        ("profile", "Profile", text("Name and picture.")),
        ("security", "Security", text("Password and sessions.")),
    ],
    id="settings",
    label="Settings",
    active="profile",
)
```

`active` is the tab that starts selected, the first one by default. The
visitor's choice survives server renders. Use this form when all panels are
cheap to render.

### Tabs the Page Switches

With `event`, a tab pushes the event with its key as `tab`, and only the
`active` panel is rendered. Keep the active key in page state and pass `None`
as the content of the other items:

```python
from string.templatelib import Template

from tori_py_liveview import LiveView, UnknownEventError

REPORTS = {"daily": "42 orders", "weekly": "310 orders"}


class ReportsLive(LiveView):
    def __init__(self) -> None:
        self.report = "daily"

    async def handle_event(self, event: str, value: object) -> None:
        match event, value:
            case "report", {"tab": str(key)} if key in REPORTS:
                self.report = key
            case _:
                raise UnknownEventError(event)

    def render(self) -> Template:
        return tabs(
            [
                (key, key.title(), text(body) if key == self.report else None)
                for key, body in REPORTS.items()
            ],
            id="reports",
            label="Reports",
            active=self.report,
            event="report",
        )
```

Use this form when a panel is expensive, loads data, or should be reflected in
the URL: handle the event with
[`push_patch()`](../liveview/navigation.md) and derive `active` from the
parameters.

### Keyboard

Both forms follow the tabs pattern: Tab moves into the list and on to the
panel, the left and right arrow keys move between tabs and select the one they
land on, and Home and End jump to the first and last tab.

For tabs that are links to different pages, use navigation links instead.

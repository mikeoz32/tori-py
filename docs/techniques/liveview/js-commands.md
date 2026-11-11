# JS Commands

Some interaction should happen in the browser without a server round trip:
opening a menu, toggling a class, moving focus, or running a transition while an
event is pushed. The Phoenix client supports this through JS commands, a JSON
list in a `phx-*` binding value. `JS` builds those lists in Python, like
`Phoenix.LiveView.JS` does in Elixir.

```python
from string.templatelib import Template

from tori_py_liveview import JS, LiveView, UnknownEventError, fragment, live_view


@live_view("/inbox")
class InboxLive(LiveView):
    def __init__(self) -> None:
        self.messages: dict[str, str] = {"m1": "Welcome", "m2": "Weekly report"}

    async def handle_event(self, event: str, value: object) -> None:
        match event, value:
            case "archive", {"id": str(message_id)}:
                self.messages.pop(message_id, None)
            case _:
                raise UnknownEventError(event)

    def render(self) -> Template:
        toggle = JS().toggle(to="#filters", transition_in="fade-in")
        rows = fragment(
            self.row(message_id, subject)
            for message_id, subject in self.messages.items()
        )
        return (
            t'<button phx-click="{toggle}">Filters</button>'
            t'<aside id="filters" style="display: none">…</aside><ul>{rows}</ul>'
        )

    def row(self, message_id: str, subject: str) -> Template:
        archive = (
            JS()
            .push("archive", value={"id": message_id})
            .hide(to=f"#message-{message_id}", transition="fade-out")
        )
        return (
            t'<li id="message-{message_id}">{subject}'
            t'<button phx-click="{archive}">Archive</button></li>'
        )
```

The archive button hides its row immediately and pushes `archive` with
`{"id": ...}` to the server in the same click.

## Building Chains

`JS()` is an empty, immutable chain. Every method returns a new chain with one
more command, so a shared base chain is safe to reuse:

```python
close = JS().hide(to="#dialog").pop_focus()
save_and_close = JS().push("save").hide(to="#dialog").pop_focus()
```

Interpolate a chain into a `phx-*` attribute value, pass it as an `attrs()`
value, or pass it to a [LiveView UI](../liveview-ui/index.md) helper's `event`,
`change_event`, `submit_event`, or `blur_event`. `encode()` returns the JSON
string, and two chains with the same commands are equal.

## Commands

| Method | Phoenix command | Main arguments |
| --- | --- | --- |
| `push(event, *, value, target, loading, page_loading)` | `push` | Event name, optional value mapping, component `target` (`self.myself`) or selector |
| `navigate(href, *, replace)` | `navigate` | Root-relative path to another live route |
| `patch(href, *, replace)` | `patch` | Root-relative path handled by the current page |
| `dispatch(event, *, to, detail, bubbles, blocking)` | `dispatch` | DOM `CustomEvent` name and `detail` mapping |
| `show(*, to, transition, time, display, blocking)` | `show` | Element to show |
| `hide(*, to, transition, time, display, blocking)` | `hide` | Element to hide |
| `toggle(*, to, transition_in, transition_out, time, display, blocking)` | `toggle` | Element to show or hide |
| `add_class(names, *, to, transition, time, blocking)` | `add_class` | Class names |
| `remove_class(names, *, to, transition, time, blocking)` | `remove_class` | Class names |
| `toggle_class(names, *, to, transition, time, blocking)` | `toggle_class` | Class names |
| `transition(transition, *, to, time, blocking)` | `transition` | Transition classes |
| `set_attribute(name, value, *, to)` | `set_attr` | Attribute name and value |
| `remove_attribute(name, *, to)` | `remove_attr` | Attribute name |
| `toggle_attribute(name, value, alternate=None, *, to)` | `toggle_attr` | Toggle between `value` and absent, or `value` and `alternate` |
| `ignore_attributes(names, *, to)` | `ignore_attrs` | Attributes the client keeps across patches |
| `focus(*, to)` | `focus` | Element to focus |
| `focus_first(*, to)` | `focus_first` | Container whose first focusable child gets focus |
| `push_focus(*, to)` | `push_focus` | Remember the element to refocus later |
| `pop_focus()` | `pop_focus` | Refocus the last remembered element |
| `exec(attribute, *, to)` | `exec` | Run the commands stored in another element's `phx-*` attribute |

Without `to`, a command targets the element that owns the binding. Defaults
follow the Phoenix client: `time=200`, `blocking=True`, and `bubbles=True`.

## Targets

`to` is one of:

- a CSS selector string, matched against the whole document;
- `("closest", selector)`, the nearest matching ancestor of the bound element;
- `("inner", selector)`, matching descendants of the bound element.

```python
JS().hide(to=("closest", ".toast"))
JS().focus_first(to=("inner", ".dialog-body"))
```

## Transitions

A transition is either a class string applied during the transition, or a
`(transition, start, end)` triple of class strings:

```python
JS().show(
    to="#panel",
    transition=("ease-out duration-200", "opacity-0", "opacity-100"),
    time=200,
)
```

`toggle()` takes separate `transition_in` and `transition_out` values. The
transition classes are your own CSS; the client only adds and removes them.

## Running Stored Commands

Keep one definition of a command list in a `phx-*` attribute and run it from
several places with `exec()`:

```python
hide_modal = JS().hide(to="#modal").pop_focus()
close = JS().exec("phx-remove", to="#modal")
return (
    t'<div id="modal" phx-remove="{hide_modal}">'
    t'<button phx-click="{close}">Close</button></div>'
)
```

`exec()` accepts only a `phx-*` attribute that the client can run as commands.
`phx-value-*`, `phx-target`, `phx-key`, and `phx-disable-with` are rejected.

## Validation

Arguments are validated and JSON encoded when a command is added, so data in an
argument cannot add commands of its own.

- Event names, selectors, and display values must be non-empty strings.
- `value` and `detail` must be mappings with string keys and JSON-encodable
  values.
- `time` is a non-negative integer; flags are real `bool` values.
- `navigate()` and `patch()` accept only root-relative paths. Absolute URLs,
  protocol-relative URLs, and backslash tricks raise `ValueError`.
- Attribute commands follow the `attrs()` rules: no `on*`, `style`, or `srcdoc`
  attributes, no `javascript:`, `data:`, or `vbscript:` URLs, and no `phx-*`
  value that starts with `[`.
- A `push()` target is a positive integer component ID or a selector.

Invalid arguments raise `TypeError` or `ValueError` immediately, at render time,
rather than producing a binding the browser later rejects.

Commands remain client-side behavior. Anything that changes server state must
still go through an event the page validates and authorizes.

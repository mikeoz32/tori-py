# Templates and Rendering

Pages and components render with Python 3.14 template strings (`t"..."`). A
template keeps its literal parts (statics) apart from its interpolated values
(dynamics), which is exactly the shape of a Phoenix render tree. Static parts are
trusted markup you wrote. Dynamic values are escaped unless they are explicitly
structural or trusted.

## What `render()` May Return

| Return value | Treatment |
| --- | --- |
| `Template` | Converted with `html()`: statics trusted, values escaped |
| `Rendered` | Used as is |
| `str` | The whole string is trusted HTML with no dynamics |

Prefer templates. Returning `str` is only safe for markup that contains no data
from users, storage, or the network.

## Escaping Rules

| Interpolated value | Rendered as |
| --- | --- |
| `str`, `int`, `float`, `None`, any other object | `str(value)`, HTML escaped including quotes |
| Nested `Template` | A nested render tree; its own values are escaped |
| `Rendered` from `html()`, `fragment()`, or `rendered()` | A nested render tree |
| `SafeHtml` from `raw()` or `attrs()` | Inserted without escaping |
| `JS` command chain | Its JSON encoding, HTML escaped |
| Component from `live_component()` | A component reference |
| Stream from `stream_contents()` | A stream container |

Because `None` renders as `"None"`, choose explicit text or an empty string for
absent values:

```python
note = self.note or ""
return t"<p>{note}</p>"
```

Do not apply `!s`, `!r`, `!a`, or a format specification to a structural value
such as a nested template, fragment, component, or stream. A conversion turns it
into escaped text. Format specifications are fine for scalars:

```python
return t"<td>{order.total:.2f}</td><td>{order.created_at:%Y-%m-%d}</td>"
```

## Where Values May Appear

Interpolate ordinary values only in:

- HTML text content;
- quoted attribute values, written as `name="{value}"` or `name='{value}'`.

Do not interpolate into tag names, attribute names, `<script>` or `<style>`
bodies, `style` attributes, or `on*` handler attributes. HTML escaping does not
make data safe in CSS or JavaScript contexts. Build dynamic attribute sets with
`attrs()` instead.

A quoted `href` or `src` interpolation is escaped but not checked for a URL
scheme, so `javascript:` in user data would survive. Pass user-controlled URLs
through `attrs()`, which rejects `javascript:`, `data:`, and `vbscript:` URLs:

```python
from tori_py_liveview import attrs

link = attrs({"href": profile.website, "rel": "nofollow"})
return t"<a{link}>Website</a>"
```

## Composition Helpers

### `html(template)`

Converts a template to `Rendered`. Pages call it for you when `render()` returns
a template; call it yourself when you need a `Rendered` value, for example to
render HTML in a test:

```python
from tori_py_liveview import html

assert html(t"<b>{'<x>'}</b>").to_html() == "<b>&lt;x&gt;</b>"
```

### `fragment(values)`

Concatenates a finite iterable once. Each item follows the escaping rules above,
so templates stay nested trees and plain strings stay escaped:

```python
from tori_py_liveview import fragment

rows = fragment(t"<tr><td>{task.title}</td></tr>" for task in self.tasks)
return t"<table><tbody>{rows}</tbody></table>"
```

### `classes(*names, **conditional)`

Builds a class string from fixed names and boolean flags. The result is ordinary
escaped text, so interpolate it inside a quoted `class` attribute:

```python
from tori_py_liveview import classes

css = classes("task", "card", done=task.done, **{"is-overdue": task.overdue})
return t'<li class="{css}">{task.title}</li>'
```

Flags must be real `bool` values. Use `**{...}` for class names that are not
Python identifiers.

### `attrs(mapping)`

Builds validated, escaped attributes and returns trusted `SafeHtml` that starts
with a space:

```python
from tori_py_liveview import attrs

field = attrs(
    {
        "name": "title",
        "value": self.title,
        "required": True,
        "disabled": self.locked,
        "placeholder": None,
    }
)
return t"<input{field}>"
```

| Value | Output |
| --- | --- |
| `True` | Bare attribute, such as ` required` |
| `False` or `None` | Omitted |
| `JS` chain | Escaped JSON command list |
| Anything else | `name="escaped str(value)"` |

`attrs()` raises `ValueError` for invalid attribute names, any `on*` handler,
`style`, `srcdoc`, unsafe URL schemes in URL attributes (`href`, `src`,
`action`, `formaction`, `srcset`, `ping`, and the other URL-valued attributes),
and a `phx-*` command value that starts with `[` unless it is a `JS` chain.

### `raw(text)` and `SafeHtml`

`raw()` marks a string as trusted HTML. Use it only for markup your code
produced, such as output from a sanitizer you trust or a fixed snippet:

```python
from tori_py_liveview import raw

icon = raw('<svg aria-hidden="true" width="16" height="16"></svg>')
return t"<button>{icon} Save</button>"
```

Never pass request data, database text, or messages from other services to
`raw()`.

### `rendered(statics, *values)` and `Rendered`

`rendered()` builds a render tree from explicit statics and values. It applies
the same escaping and `phx-*` checks as templates and is mainly useful for
generated markup. `Rendered(statics, dynamics)` is the immutable tree type;
`to_html()` returns the HTML string.

## How Updates Reach the Browser

After every event, info message, or patch, the page renders again and the server
sends the render tree with its statics and dynamics. The Phoenix client merges it
with its copy and patches only the DOM nodes whose content changed, so focus,
scroll position, and unchanged elements survive. Keep `render()` free of side
effects and reasonably cheap: it runs after every state change.

Choosing between whole templates also works naturally:

```python
def render(self) -> Template:
    body = self.render_editor() if self.editing else self.render_view()
    return t"<article>{body}</article>"
```

## `phx-*` Binding Values

The Phoenix client runs a `phx-*` value that starts with `[` as a list of JS
commands. To stop data from becoming commands, rendering raises `ValueError`
when an escaped dynamic value would start such a value or extend one that starts
with `[`.

```python
from tori_py_liveview import html

event = '[["navigate",{"href":"/admin"}]]'  # data from a client
html(t'<button phx-click="{event}">Go</button>')  # raises ValueError
```

Only `JS` chains and `raw()` values may write command lists. Use the
[`JS` builder](js-commands.md) for commands. These attributes are exempt because
the client never runs them as commands: `phx-value-*`, `phx-target`, `phx-key`,
and `phx-disable-with`. Commands you type in a template's static text are trusted
application code.

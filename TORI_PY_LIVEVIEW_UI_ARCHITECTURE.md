# ToriPy LiveView UI Architecture

## 1. Purpose

`tori-py-liveview-ui` is an optional, separately installable component library
for `tori-py-liveview`. It provides stateless Python 3.14 template helpers
grouped in families, one locally bundled, themeable and skinnable stylesheet,
and one locally bundled script of Phoenix hooks. It does not introduce a second
LiveView runtime, browser protocol, or state model.

```text
tori-py-liveview-ui -> tori-py-framework, tori-py-liveview
tori-py-framework    -X-> tori-py-liveview-ui
tori-py-liveview     -X-> tori-py-liveview-ui
```

Applications explicitly import `LiveViewUiModule.for_root()` alongside their
`LiveViewModule`. The UI module materializes one ordinary ToriPy controller for
the stylesheet and the script; it creates no providers and performs no
discovery, package scan, or global registration.

## 2. Public Surface

The public facade is the flat `tori_py_liveview_ui` namespace:

- helper functions that return `string.templatelib.Template` values, listed by
  family in section 4;
- `LiveViewUiModule.for_root(key="default")` exposes the asset routes;
- `STYLESHEET_PATH` and `SCRIPT_PATH` are those routes' content-addressed paths;
- `stylesheet_link()` and `script_tag()` return the trusted `<link>` and
  `<script>` markup for a custom document;
- `UiLiveView` is a `LiveView` base class that installs both tags and
  independent document theme and skin attributes.

The implementation modules behind the facade are private. Applications import
names from `tori_py_liveview_ui` only.

## 3. Helper Rules

Every helper follows the same contract:

- It is a stateless render function, not a `LiveComponent`. It never mounts,
  receives events, retains assigns, or owns page or component state. Pages and
  components supply current values on every render.
- Its visual vocabulary is closed. Variants, sizes, tones, gaps, alignments,
  and similar options accept only their documented values, and invalid values
  fail immediately rather than becoming CSS class or attribute injection.
- It offers no arbitrary attribute dictionary, `class` parameter, selector
  escape hatch, or automatic class injection. Applications can wrap a helper in
  their own template where they need a separately owned extension point.
- An event parameter accepts a non-empty event name or a LiveView `JS` command
  chain and maps to the documented `phx-*` binding. An optional `target` is a
  positive JavaScript-safe integer, normally a component's connection-local
  `myself`, maps to `phx-target`, and requires at least one event.
- DOM ID parameters are non-empty strings without whitespace. A helper that
  needs an ID for a label, an ARIA reference, or a hook requires it explicitly
  and never generates a random one.
- Content parameters accept any value LiveView can interpolate. Strings are
  escaped; `Template`, `Rendered`, component, stream, and explicitly trusted
  `SafeHtml` content composes according to LiveView's Phoenix render-tree
  contract. Finite iterables of children are consumed once through
  `fragment()`.

## 4. Families

### 4.1 Actions

| Helper | Closed values | Other documented inputs |
| --- | --- | --- |
| `button` | variants: `primary`, `secondary`, `ghost`, `danger`; sizes: `sm`, `md`, `lg`; types: `button`, `submit`, `reset`; icons: the bundled set | `label`, `disabled`, optional `event` and `target`, event `values`, `loading`, `disable_with`, `confirm`, `full_width` |
| `icon_button` | the `button` variants, sizes, and types; icon: the bundled set | required `label`, `disabled`, optional `pressed`, `event`, `target`, `values`, `confirm` |
| `link_button` | the `button` variants and sizes; live: `patch`, `navigate` | `label`, `href`, `replace`, `external`, icons, `full_width` |
| `button_group` | - | finite `children` iterable, required `label`, `attached` |
| `copy_button` | the `button` variants and sizes | `to` target, `label`, `copied_label` |
| `theme_toggle` | - | required selector-safe `id`, group and option labels |

`button(event=..., target=...)` emits `phx-click` and `phx-target`. A page
button normally omits `target`; a stateful LiveView component passes its
`myself` value. `button` is a native button with a closed HTML `type`, disabled
state, and visible focus styling. A submit button inside a `phx-submit` form
normally omits its own click event so one user action does not intentionally
dispatch two application events.

Event `values` is a mapping whose keys match `[a-z][a-z0-9_-]{0,62}` and whose
values are strings, numbers, or booleans. It maps to `phx-value-*` attributes,
with booleans as `true` and `false`, and requires an event. `loading` disables
the button, sets `aria-busy`, and shows a spinner. `disable_with` maps to
`phx-disable-with`. `confirm` maps to `data-tori-ui-confirm`: the script asks in
the browser's native dialog from a capturing click listener it adds to `window`
before the LiveView client adds its own, and a declined click neither reaches
LiveView nor performs its default action.

`icon_button` has no visible text, so `label` is required and becomes both
`aria-label` and `title`. `pressed` renders `aria-pressed` for a toggle whose
state the page owns.

`link_button` and `link` share one link contract. `href` is required and
subject to the `attrs()` scheme rules. `live` maps `patch` and `navigate` to
`data-phx-link="patch"` and `data-phx-link="redirect"` with
`data-phx-link-state` of `push`, or `replace` when `replace` is set. A live
`href` is a root-relative path without a leading `//` or a backslash.
`external` adds `target="_blank"` and `rel="noopener noreferrer"`. A link is not
both live and external, and `replace` requires a live link.

`copy_button` dispatches the `tori-ui:copy` DOM event to its `to` target through
a `JS` command. `to` is a CSS selector or a `("closest", selector)` or
`("inner", selector)` pair. One `window` listener in the script copies the text
of the target's first `data-tori-ui-copy-source` descendant, or of the target
itself, and marks the dispatching button with `data-tori-ui-copied` for two
seconds while a `role="status"` element inside it announces `copied_label`. The
button keeps `label` as its accessible name throughout. The page is not
notified.

`theme_toggle` renders three `aria-pressed` buttons for the `auto`, `light`,
and `dark` themes in a `phx-update="ignore"` group with the `ToriUiTheme` hook.
The hook applies the chosen theme to `<html>`, stores it in `localStorage`
under `tori-ui-theme`, and keeps every toggle on the page in step.

### 4.2 Layout

| Helper | Closed values | Other documented inputs |
| --- | --- | --- |
| `card` | - | `content`, optional string `eyebrow` and `title`, optional `footer` |
| `stack` | gaps: `xs`, `sm`, `md`, `lg`, `xl`; alignment: `start`, `center`, `end`, `stretch` | finite `children` iterable |
| `grid` | columns: `auto`, `1`, `2`, `3`, `4`; gaps: `xs`, `sm`, `md`, `lg`, `xl` | finite `children` iterable |
| `row` | the gaps; alignment: `start`, `center`, `end`, `stretch`, `baseline`; justification: `start`, `center`, `end`, `between` | finite `children` iterable, `wrap` |
| `container` | sizes: `sm`, `md`, `lg`, `xl`, `full` | `content`, `padded` |
| `center` | minimum heights: `content`, `half`, `screen` | `content` |
| `divider` | orientations: `horizontal`, `vertical` | optional non-empty `label`, horizontal only |
| `spacer` | sizes: `grow` and the gaps | - |
| `section` | - | `content`, required `title`, optional `description`, `actions`, and `id` |
| `page_header` | - | required `title`, optional `eyebrow`, `description`, `actions`, and `navigation` |
| `toolbar` | - | finite `start` and `end` iterables, required `label` |
| `split` | ratios: `1:1`, `1:2`, `2:1`, `1:3`, `3:1`; the gaps | `primary` and `secondary` content |
| `scroll_area` | maximum heights: `sm`, `md`, `lg`, `xl` | `content`, required `label` |
| `app_shell` | - | `content`, required selector-safe `id`, optional `header`, `sidebar`, `aside`, and `footer`, sidebar and menu labels |

`card` uses an `article`, optional header and footer, and an `h2` title.
`section` uses a `section` with an `h2` title; with an `id` the title receives
`<id>-title` and labels the section. `page_header` renders the page's `h1`.
`toolbar` is a `role="group"` named by its label, and `scroll_area` is a
focusable `role="region"` named by its label, so it scrolls from the keyboard.
An unlabeled horizontal `divider` is an `hr`; the other forms use
`role="separator"`.

`app_shell` fills the viewport, renders the page's `main` landmark, and lets the
sidebar, main area, and aside scroll independently. Below 56rem the sidebar
leaves the grid and a menu button in the header opens it over the content with
`JS` commands that toggle a class on the shell and `aria-expanded` on the
button. Escape, a click on the scrim, and a `phx:navigate` event close it. The
open state belongs to the browser and survives server renders. The shell `id`
matches `[A-Za-z][A-Za-z0-9_-]*` because the commands select the shell by it.

### 4.3 Content

| Helper | Closed values | Other documented inputs |
| --- | --- | --- |
| `heading` | levels: 1 through 6; sizes: `xs`, `sm`, `md`, `lg`, `xl`, `2xl` | `content`, optional `id` |
| `text` | sizes: `sm`, `md`, `lg` | `content`, `muted` |
| `link` | live: `patch`, `navigate` | `label`, `href`, `replace`, `external` |
| `code` | - | `content` |
| `code_block` | - | `content`, optional non-empty `language`, `copy`, `wrap`, copy labels |
| `kbd` | - | `content` |
| `blockquote` | - | `content`, optional `cite` |
| `prose` | - | `content` |
| `item_list` | markers: `bullet`, `number`, `none` | finite `items` iterable |
| `description_list` | layouts: `rows`, `stacked` | finite iterable of `(term, detail)` pairs |
| `image` | ratios: `auto`, `square`, `video`, `wide`; fits: `cover`, `contain` | required `src` and string `alt`, optional `caption`, `width`, `height`, `lazy` |

A heading's `level` selects the element and its `size` the look; each level has
a default size. `code_block` does not highlight: its `pre` is focusable so it
scrolls from the keyboard, its `code` element is the copy source, and its copy
button targets the enclosing block. `prose` styles descendant elements that
carry no class through zero-specificity selectors, so helper classes inside it
keep their own rules; it does not sanitize its content. `item_list` renders an
`ol` for the `number` marker and a `ul` otherwise. `image` requires `alt`, which
may be empty for a decorative image, and bounds `width` and `height` to 1
through 16384.

### 4.4 Icons

`icon(name, *, size, label)` renders one of the bundled icons as inline SVG:
static shapes on a 24 by 24 grid with a round 2 unit stroke in the current text
color. The set of names is closed and the markup is fixed package text; callers
cannot supply paths. Every shape has an explicit end tag, because LiveView
accepts only explicitly balanced markup as a stream item and icons appear inside
stream items such as chat messages. Sizes are `sm`, `md`, and `lg`, relative to the text size.
An icon without a `label` has `aria-hidden="true"`; with a non-empty `label` it
has `role="img"` and that accessible name. Helpers that take an icon take its
name.

### 4.5 Display

| Helper | Closed values | Other documented inputs |
| --- | --- | --- |
| `badge` | tones: `neutral`, `info`, `success`, `warning`, `danger` | `content` |
| `table` | densities: `comfortable`, `compact`; sort directions: `asc`, `desc` | `columns`, finite `rows`, optional `caption`, `striped`, `empty`, `sort`, `sort_event`, `target`, `stream` |
| `table_row` | - | finite `cells`, the table's `columns`, optional `id` |
| `list_group` | - | finite `items` iterable, optional `label` |
| `list_item` | live: `patch`, `navigate` | `title`, optional `description`, `leading`, `trailing`, `href`, `event`, `target`, `values`, `selected`, `id` |
| `stat` | trends: `up`, `down`, `flat`; the tones | required `label`, `value`, optional `delta`, `help_text`, `chart` |
| `sparkline` | the tones | at least two finite numbers, required `label`, `area` |
| `avatar` | sizes: `sm`, `md`, `lg` | required `name`, optional `src` |
| `avatar_group` | - | finite `children` iterable, required `label`, `extra` from 0 through 9999 |
| `tag` | the tones; icon: the bundled set | `content`, optional `remove_event`, `remove_label`, `target`, `values` |
| `status_dot` | the tones | required `label`, `pulse` |
| `timeline` | - | finite `items` iterable |
| `timeline_item` | the tones | `title`, optional `time`, `description`, `id` |
| `empty_state` | icon: the bundled set | required `title`, optional `description`, `actions` |
| `progress` | the tones | required `label`, optional `value`, positive `maximum`, `show_value` |
| `meter` | - | required `label`, `value`, `minimum`, `maximum`, optional `low`, `high`, `optimum` |
| `tooltip` | placements: `top`, `bottom` | `content`, required `text` and `id` |

A table column is a label or a frozen `TableColumn(label, key, align, sortable)`
with `align` of `start`, `center`, or `end`. Every row has one cell per column.
The page owns sorting: a sortable header is a button that pushes `sort_event`
with `phx-value-key`, and `sort=(key, direction)` sets `aria-sort` on the
matching header and `none` on the other sortable ones. With
`stream=(container_id, contents)` the `tbody` is a `phx-update="stream"`
container whose items are `table_row` results. The table sits in a wrapper that
scrolls horizontally.

A `list_item` is a link with `href`, a button with `event`, and otherwise plain
content; it is not both, and `trailing` content stays outside the row's own
action. `selected` sets `aria-current`. `avatar` names itself from `name` and
derives initials from it without a picture. `sparkline` is static inline SVG
with `role="img"` and its `label`. `progress` and `meter` are the native
elements; a `progress` without a value is indeterminate. `status_dot` always
shows its label. `tooltip` makes its content focusable, references a
`role="tooltip"` element through `aria-describedby`, opens on hover and focus
through CSS, stays open while the pointer is over its bubble, and is dismissed
by Escape through one `document` listener in the script.

### 4.6 Feedback

| Helper | Closed values | Other documented inputs |
| --- | --- | --- |
| `alert` | tones: `neutral`, `info`, `success`, `warning`, `danger` | `content`, optional string `title`, `actions`, `dismissible`, `dismiss_event`, `dismiss_label`, `target` |
| `banner` | the tones | `content`, optional `actions`, `dismissible`, `dismiss_event`, `dismiss_label`, `target` |
| `spinner` | sizes: `sm`, `md`, `lg` | `label` |
| `skeleton` | shapes: `text`, `block`, `circle` | `lines` from 1 through 20, text shape only |
| `busy` | - | `content`, required boolean `busy`, `label` |
| `toast` | the tones | `content`, required selector-safe `id`, optional `title`, `duration` from 1000 through 600000 or none, `dismiss_event`, `dismiss_label`, `target` |
| `toast_region` | placements: `top-start`, `top-end`, `bottom-start`, `bottom-end` | finite `children` iterable, `id`, `label` |
| `flash_group` | the placements | the page's flash mapping, `id`, `label`, `duration` |
| `connection_status` | - | `message` |

`alert`, `banner`, and `toast` use `role="alert"` for the `danger` tone and
`role="status"` otherwise. An alert's optional title is an `h2`. Their dismiss
button runs `JS().hide()` on the enclosing block when only `dismissible` is
set, so the browser hides it and the page is not told; with `dismiss_event` it
pushes that event and the page owns removal.

A `toast` with a duration carries the `ToriUiToast` hook, which presses the
toast's own dismiss button when the time is up and pauses while the pointer or
the focus is inside. `toast_region` is a fixed `role="region"` in a viewport
corner. `flash_group` renders the `error`, `warning`, `success`, and `info`
flash kinds as toasts in that order; each dismiss button pushes LiveView's
built-in `lv:clear-flash` with its kind and hides the toast, and only `info`
and `success` close themselves.

`spinner` announces its label through `role="status"`. `skeleton` is hidden
from assistive technology. `busy` sets `aria-busy`, and while busy makes its
content `inert` and covers it with a spinner. `connection_status` is hidden
until the LiveView client puts `phx-client-error` or `phx-server-error` on the
page's root element; it uses no script.

### 4.7 Disclosure

| Helper | Closed values | Other documented inputs |
| --- | --- | --- |
| `collapsible` | - | `summary`, `content`, `open`, optional `id` and `group` |
| `accordion` | - | finite `children` iterable |
| `tabs` | - | finite `(key, label, content)` items, required selector-safe `id` and `label`, optional `active`, `event`, `target` |

`collapsible` is a native `details` element with a `phx-mounted` command that
makes the client ignore the `open` attribute when patching, so `open` is only
the initial state. Sections sharing a `group` use the native `name` attribute
and close each other.

`tabs` renders a `role="tablist"` of `role="tab"` buttons with roving
`tabindex` and `role="tabpanel"` regions. Keys match `[A-Za-z0-9_-]+` and are
unique. Without `event` every panel is rendered and a tab's `JS` commands move
`aria-selected`, `tabindex`, and a hidden class, so the browser owns the choice
and keeps it across renders. With `event` a tab pushes the event with
`phx-value-tab` and only the `active` panel is rendered. The `ToriUiTabs` hook
on the tab list moves focus with the arrow keys, Home, and End and selects the
tab it lands on by clicking it.

### 4.8 Conversation

| Helper | Closed values | Other documented inputs |
| --- | --- | --- |
| `chat` | - | `log`, `composer`, `label`, optional `header` |
| `chat_log` | - | `content`, required selector-safe `id`, `label`, `stream`, `jump_label` |
| `chat_message` | roles: `user`, `assistant`, `system`, `tool` | `content`, optional `id`, `name`, `avatar`, `time`, `footer`, `actions`, `streaming` |
| `message_actions` | - | finite `children` iterable, `label`, `copy` and its labels |
| `composer` | - | required selector-safe `id` and `submit_event`, `name`, string `value`, labels, optional `placeholder`, `change_event`, `target`, `stop_event`, `actions`, `hint`, `busy`, `disabled`, `max_rows` from 1 through 40 |
| `suggestions` | - | finite iterable of prompts or `(label, prompt)` pairs, required `event`, optional `target`, `label` |
| `chat_empty` | icon: the bundled set | required `title`, optional `description` and `suggestions` |
| `typing_indicator` | - | `label` |
| `conversation_list` | - | finite `items` iterable of `list_item` rows, `label`, optional `action` |
| `response_branch` | - | `current` and `total` positions, required previous and next events, optional `target`, labels |
| `reasoning` | - | `content`, `summary`, `streaming`, `open`, optional `id` |
| `tool_call` | statuses: `pending`, `running`, `done`, `error` | required `name`, optional `status_label`, `arguments`, `result`, their labels, `open`, `id` |
| `agent_steps` | - | finite `items` iterable, `label` |
| `agent_step` | the statuses | `title`, optional `status_label`, `description`, `id` |
| `sources` | - | finite iterable of `(title, href)` pairs, `label`, optional `id` |
| `citation` | - | `number` from 1 through 9999, optional `href` and `title` |
| `attachment` | icon: the bundled set | required `name`, optional `meta`, `href`, `remove_event`, `remove_label`, `target` |
| `token_usage` | - | non-negative `input_tokens` and `output_tokens`, optional `cost`, labels |
| `artifact_panel` | - | `content`, required `title` and selector-safe `id`, optional `subtitle`, `actions`, `copy` and its labels |

The page owns the conversation and the model call. `chat` is a flex column that
fills its container: an optional header, the log, and the composer.

`chat_log` is a focusable `role="log"` scroller around the message container,
which is a `phx-update="stream"` container when `stream` is set. Its
`ToriUiChatLog` hook keeps the log at the bottom as content grows. Only the
visitor's scrolling releases it; a patch that makes the content taller does not.
While released the hook marks the log with `data-tori-ui-unpinned`, which shows
a button that returns to the latest message.

`chat_message` is an `article`. Its body is the copy source for
`message_actions`, whose copy button targets the closest message. `streaming`
sets `aria-busy` and appends a decorative caret.

`composer` is a `method="post"` form with one labeled `textarea` and the
`ToriUiComposer` hook. The hook submits on Enter, leaves Shift+Enter and IME
composition alone, grows the field to `max_rows`, blocks an empty or busy
submit before the LiveView client sees it, and empties the field after the
client has read it. With `busy` and a `stop_event` the submit button is
replaced by a button that pushes that event.

`reasoning` and `tool_call` are native `details` elements with the same
`phx-mounted` command as `collapsible`, so the browser keeps their open state
while a streaming message is re-rendered around them. Statuses map to an icon,
or a spinner for `running`, and to `status_label` in words. `agent_step` marks
the running step with `aria-current="step"` and names every status for screen
readers. `sources` renders numbered external links with
`rel="noopener noreferrer"` and gives entry *n* the ID `<id>-<n>`; `citation`
is a link to such an entry or plain text. `token_usage` abbreviates counts above
999.

### 4.9 Rich Text

`markdown(source, *, highlight, images)` renders CommonMark with tables and
strikethrough into a `prose` block. It imports `markdown-it-py` when called and
reports the `markdown` extra when the import fails. The source is untrusted:
the parser is created with raw HTML disabled, keeps its link validation that
refuses `javascript:`, `vbscript:`, `file:`, and non-image `data:` targets, and
has the image rule disabled unless `images` is set, so image syntax becomes a
link and nothing is fetched from an address the text chose. Links to absolute
or protocol-relative URLs get `target="_blank"` and
`rel="noopener noreferrer nofollow"`. Fenced and indented code renders through
`code_block`; a fence's language is kept only when it is a short plain
identifier. With `highlight`, Pygments colors known languages through
`tori-ui-hl-`-prefixed token classes that the stylesheet maps to theme colors;
the `highlight` extra is reported when Pygments is missing.

### 4.10 Navigation

| Helper | Closed values | Other documented inputs |
| --- | --- | --- |
| `skip_link` | - | fragment `href`, `label` |
| `navbar` | - | `brand`, optional `items` and `actions`, `label` |
| `nav` | orientations: `vertical`, `horizontal` | finite `items` iterable, required `label` |
| `nav_item` | live: `patch`, `navigate`; icon: the bundled set | `label`, `href`, `replace`, `external`, `current`, optional `badge` |
| `breadcrumbs` | live: `patch`, `navigate` | finite iterable of `(label, href)` pairs, `label` |
| `pagination` | live: `patch`, `navigate` | `page` within `pages`, either an `href` pattern or an `event`, optional `target`, `siblings` from 0 through 5, labels |
| `steps` | - | finite iterable of titles or `(title, description)` pairs, `current`, labels |
| `tab_links` | live: `patch`, `navigate` | finite iterable of `(label, href)` pairs, required `current` and `label` |

Every link follows the link contract of section 4.1. `nav`, `navbar`,
`breadcrumbs`, `pagination`, and `tab_links` render `nav` landmarks named by
their label, and mark the current page with `aria-current="page"`; the page
decides which link that is. The last breadcrumb is always the current page and
never a link. `tab_links` are links, not ARIA tabs.

`pagination` shows the first and last page and `siblings` pages around the
current one, an ellipsis for a longer gap, and the skipped page itself for a
gap of one. With an `href` pattern containing `{page}` it renders links, and a
previous or next step that would leave the range is plain text with
`aria-disabled`. With an `event` it renders buttons that push the event with
`phx-value-page`, disabled at the ends. It takes exactly one of the two.

`steps` marks stages before `current` complete, the current one with
`aria-current="step"`, and names completed stages for screen readers.
`skip_link` is positioned off screen until focused and targets a fragment;
`app_shell` gives its main area the ID `<id>-main` and makes it programmatically
focusable for that purpose.

### 4.11 Overlays

| Helper | Closed values | Other documented inputs |
| --- | --- | --- |
| `open_overlay`, `close_overlay` | - | selector-safe overlay `id`; return a `JS` chain |
| `modal` | sizes: `sm`, `md`, `lg`, `xl` | `content`, required selector-safe `id` and `title`, optional `description`, `footer`, `open`, `dismissible`, `close_event`, `close_label`, `target` |
| `drawer` | sides: `start`, `end` | as `modal`, without `size` |
| `confirm_dialog` | tones: `primary`, `danger` | `message`, required `id`, `title`, and `confirm_event`, labels, optional `target`, `values`, `open`, `cancel_event` |
| `dropdown` | the `button` variants and sizes; alignment: `start`, `end`; icon: the bundled set | trigger `label`, finite `items` iterable, required selector-safe `id` |
| `menu_item` | tones: `neutral`, `danger`; live: `patch`, `navigate`; icon: the bundled set | `label`, either an `event` or an `href`, optional `target`, `values`, `disabled` |
| `popover` | as `dropdown` | trigger `label`, `content`, required `id` and `panel_label` |

`modal`, `drawer`, and `confirm_dialog` render a native `dialog` named by its
title, with the `ToriUiDialog` hook and the `phx-mounted` command that makes the
client keep the `open` attribute. The hook opens the element with `showModal()`,
so the browser contains the focus, makes the rest of the document inert, draws
the dialog in the top layer, and returns the focus when it closes.

`open` is tri-state. Left out, the browser owns the state: `open_overlay(id)`
and `close_overlay(id)` dispatch the `tori-ui:open` and `tori-ui:close` DOM
events that the hook answers, and the dialog's dismiss control closes it with
`close_overlay`. Given as a boolean, the page owns it: the helper renders
`data-tori-ui-open`, the hook follows that attribute on mount and on every
update, and the dismiss control pushes `close_event` so the page can render the
dialog closed.

Every way of closing goes through the dialog's own dismiss control, marked
`data-tori-ui-dismiss`: the hook presses it on Escape and on a click on the
backdrop, so the browser-owned and the page-owned forms need no second code
path. `dismissible=False` renders no dismiss control and marks the dialog so
the hook ignores both. `confirm_dialog` is an `alertdialog` whose cancel button
is the dismiss control; its confirm button pushes `confirm_event` with
`phx-value-*` values, and the hook then closes a browser-owned dialog.

`dropdown` and `popover` render a button with `aria-haspopup`, `aria-expanded`,
and `aria-controls` beside an absolutely positioned panel. `JS` commands toggle
an open class on the wrapper and `aria-expanded` on the button, and
`phx-click-away` closes the panel. The `ToriUiPopup` hook adds what commands
cannot: it moves the focus into the panel when the open class arrives, moves
between `menuitem` elements with the arrow keys, Home, and End, closes on
Escape with the focus back on the button, and closes on a choice and when the
focus leaves. A dropdown's panel has `role="menu"` and its items
`role="menuitem"`; a popover's panel is a non-modal `role="dialog"` named by
`panel_label`. Panels are placed below the button and are not repositioned at
the viewport edge.

### 4.12 Forms

| Helper | Closed values | Other documented inputs |
| --- | --- | --- |
| `form` | method: `post` | `content`, required `id`, optional change/submit events, optional `target` |
| `field` | - | non-empty string `label`, `control`, `control_id`, optional non-empty string help/error, required presentation |
| `field_error` | - | non-empty string `message` and `id` |
| `input` | types: `date`, `datetime-local`, `email`, `month`, `number`, `password`, `search`, `tel`, `text`, `time`, `url`, `week` | label, id, name, scalar string/number value, placeholder, autocomplete, help/error, required/disabled/read-only state, autofocus, minimum/maximum/step, length bounds, debounce or throttle, prefix/suffix, change/blur events, target |
| `textarea` | rows: 1 through 100 | label, id, name, string value, placeholder, help/error, required/disabled/read-only state, length bounds, debounce or throttle, change/blur events, target |
| `select` | - | label, finite `(string value, label)` options, selected value, prompt, help/error, required/disabled state, change/blur events, target |
| `checkbox` | - | label, id, name, string value, checked/required/disabled state, help/error, change/blur events, target |
| `radio_group` | - | label, finite `(string value, label)` options, id, name, selected value, help/error, required/disabled state, `inline`, change event, target |
| `segmented` | - | as `radio_group`, without `inline` |
| `checkbox_group` | - | label, options, id, name, finite iterable of selected values, help/error, required marker, disabled state, `inline`, change event, target |
| `switch` | - | label, id, name, string value, checked/disabled state, help/error, change event, target |
| `multi_select` | size: 2 through 20 | label, options, id, name, selected values, help/error, required/disabled state, change/blur events, target |
| `combobox` | - | label, finite iterable of values or `(value, label)` pairs, id, name, string value, placeholder, help/error, required/disabled state, debounce, change/blur events, target |
| `search` | - | label, id, name, string value, placeholder, disabled state, debounce, change event, target |
| `slider` | - | label, id, name, numeric value within `minimum` and `maximum`, positive `step`, `show_value`, help, disabled state, debounce or throttle, change event, target |
| `hidden` | - | name, scalar string/number value, optional id |
| `fieldset` | - | non-empty `legend`, `content`, optional `description`, `disabled` |
| `form_actions` | alignment: `start`, `end`, `between` | finite `children` iterable |

`form` emits `method="post"`, maps change and submit events to `phx-change` and
`phx-submit`, and can route both to one component through `phx-target`. The POST
default prevents native fallback from putting form values in a URL; the LiveView
route does not thereby become an HTTP form handler, so an application that needs
non-JavaScript submission owns a separate POST endpoint. `input`, `textarea`,
`select`, and `checkbox` may map change and blur events to `phx-change` and
`phx-blur`; control-level `phx-change` requires the control to be inside a form,
as required by the official client.

Each concrete form control renders a complete field with a native label. Help
and error content receive deterministic `<control-id>-help` and
`<control-id>-error` IDs and are referenced by `aria-describedby`; an error also
sets `aria-invalid="true"` and renders through `field_error` with
`role="alert"`. Native `required`, `disabled`, `readonly`, `checked`, and
`selected` attributes retain browser semantics. `minimum`, `maximum`, `step`,
and the length bounds map to the native `min`, `max`, `step`, `minlength`, and
`maxlength` attributes; they help the visitor and do not replace the page's
validation. `debounce` is 0 through 60000 milliseconds or `blur` and maps to
`phx-debounce`; `throttle` maps to `phx-throttle`; a control takes one of them.
`prefix` and `suffix` wrap the input in a group with attached affixes.

`radio_group`, `segmented`, and `checkbox_group` render a `fieldset` whose
`legend` is the label and which carries the help and error description. Radio
groups use `role="radiogroup"` with native radio inputs, so the browser provides
arrow-key selection and enforces `required`; `segmented` only changes the look
and keeps the inputs in the accessibility tree. A checkbox group uses
`role="group"`, and its `required` only marks the label, because the browser
has no rule for a required set. Option controls receive the IDs `<id>-<n>`.
`switch` is a checkbox with `role="switch"`. `multi_select` is a native
`select multiple`, `combobox` a text input with a native `datalist`, `search` an
`input type="search"` with a visually hidden label and a 300 millisecond
default debounce, and `slider` a native range input beside an `output` of the
value the page rendered. The lower-level `field` helper supports a
custom control, but that control's author remains responsible for matching its
ID and ARIA references to the generated help and error IDs and for applying
native `required` and `aria-invalid` state to that control.

Form names are passed through unchanged, so applications may use LiveView's
documented bracket notation for nested mappings and `[]` lists. Phoenix
`phx-change` and `phx-submit` handlers receive the decoded name-shaped mapping
whose leaves are strings; absent unchecked checkboxes remain absent. A
`phx-blur` handler instead receives the official control event value mapping,
normally `{"value": "..."}`. The UI package performs no coercion, domain
validation, changeset modeling, or state management.

## 5. Browser Behavior

Application state stays on the server, in pages and components. Presentation
state that only the browser needs, such as whether a menu is open, where a log
is scrolled, or which theme the visitor chose, stays in the browser. Helpers
reach for browser behavior in this order:

1. native elements and attributes, such as `<details>`, `<dialog>`, and
   `<progress>`;
2. LiveView `JS` commands in `phx-*` bindings, which the official client runs
   and keeps across patches;
3. a Phoenix hook from the bundled script, only where the first two cannot
   express the behavior.

The script is plain JavaScript without a build step. It defines hooks whose
names start with `ToriUi` and adds them to `globalThis.ToriLiveHooks`, the
object the LiveView client passes to the official `LiveSocket`. It registers
them when it loads and again when the document has been parsed, which browsers
do before they run the deferred LiveView client, so an application script that
replaces the object in between does not lose them. Hooks hold only state that
belongs to their element, such as a timer or a scroll position. They do not
store application data, open their own connections, load remote code, or
evaluate strings as code.

The script also applies a theme the visitor stored earlier to
`data-tori-ui-theme` on `<html>` before the body is parsed. Without a stored
choice the document keeps the theme the server rendered.

## 6. Rendering and Safety

Every helper returns a Python 3.14 template string. Its content interpolations
remain subject to `tori-py-liveview` escaping. Form attribute values are
restricted to their documented scalar types, and textarea values are strings;
render trees are not accepted as control values.

The package uses LiveView's `attrs()` helper for generated element attributes and
`classes()` for its fixed class list. `attrs()` omits absent optional values and
renders booleans safely. The public helper rejects event-handler, style, and
`srcdoc` names and executable `data:`, `javascript:`, and `vbscript:` schemes in
URL-bearing attributes. It is not exposed by UI components as an arbitrary
caller-controlled injection point. Template interpolations are not safe in tag
names, attribute names, unquoted attributes, CSS, or JavaScript. `raw()` and
manually constructed template statics remain explicit application trust
boundaries and must not receive untrusted input.

## 7. Assets and Documents

The wheel contains the component rules in `tori_liveview_ui.css` and the script
`tori_liveview_ui.js`. At import time the package assembles its stylesheet
(section 8.3), computes the SHA-256 digest of the stylesheet and of the script,
and publishes them at:

```text
/_tori/liveview-ui/<first-12-hex-digest>.css
/_tori/liveview-ui/<first-12-hex-digest>.js
```

`STYLESHEET_PATH` and `SCRIPT_PATH` are the exact paths for the bundled bytes.
The controller returns those bytes with `text/css; charset=utf-8` or
`text/javascript; charset=utf-8`, an ETag containing the full digest, and
`Cache-Control: public, max-age=31536000, immutable`. Changing a file changes
its path, so long-lived browser and intermediary caching is safe.

`UiLiveView.render_document()` adds independent `data-tori-ui-theme`,
`data-tori-ui-mode`, and `data-tori-ui-skin` attributes to `<html>`, inserts
`stylesheet_link()`, the stylesheets of the application definitions the page
uses, and `script_tag()` into `<head>`, and puts the `tori-ui-document` class on
`<body>` while retaining the normal LiveView document, root, and official
Phoenix browser client. The body class gives the document the theme's paper
background, ink color, and body font and removes the body margin; it is an
explicit class, not an element selector. The script tag has no `defer` or
`async` attribute: it must run before the deferred client reads the hooks, and
before the first paint to apply a stored mode.

All three are selected during initial document rendering; the outer `<html>`
element is outside the normal LiveView diff root, so the server does not change
them from connected page state. A custom `LiveView.render_document()` can call
`stylesheet_link()` and `script_tag()` and set the data attributes itself
instead.

All component selectors use the `tori-ui-` prefix. The stylesheet has no global
element reset; its box-sizing rule is limited to component trees. Root defaults
provide the paper theme in its light palette and the editorial skin for custom
documents that include only the stylesheet. Font stacks use locally available
system fonts only: the package downloads no fonts or other assets, and the
stylesheet contains no `@import` or asset URL.

The stylesheet also provides responsive grid collapse at narrow widths,
`:focus-visible` for every interactive helper, disabled and invalid form
affordances, and `prefers-reduced-motion` transition removal. Every class a
helper emits either has a rule or is listed by the test suite as a structural
name, every rule belongs to a class a helper emits, and keyframe names and
custom properties carry the package prefix.

## 8. Themes, Modes, and Skins

A document's look is three independent selections:

| Attribute | Selects | Values |
| --- | --- | --- |
| `data-tori-ui-theme` | colors: one palette for light and one for dark | the name of a `Theme` |
| `data-tori-ui-mode` | which of the theme's palettes applies | `auto`, `light`, `dark` |
| `data-tori-ui-skin` | spacing, shape, density, typography, shadow and focus geometry | the name of a `Skin` |

The theme framework is how every theme and skin is made, the bundled ones
included. It has no CSS preprocessor, build step, or dependency.

### 8.1 Definitions

`Palette`, `Theme`, and `Skin` are frozen value objects. The fields of
`Palette` and `Skin` are the public token contract: the field `radius_control`
is the custom property `--tori-ui-radius-control`.

- `Palette` holds one palette: `paper`, `panel`, `panel_raised`, `ink`,
  `muted`, `line`, `line_strong`, `accent`, `accent_ink`, `danger`, `info`,
  `success`, `warning`, `shadow_color`, and `scrim`.
- `Theme` holds a name, a `light` and a `dark` palette, and
  `allow_low_contrast`.
- `Skin` holds a name and the spacing scale, radii, control and field
  geometry, region padding, gaps, border widths, the display, body, and code
  font stacks, control and label weight, tracking, and case, shadow geometry,
  focus geometry, disabled opacities, grid minimum, checkbox geometry, and
  hover translation.

Names match `[a-z][a-z0-9-]{0,63}`. Every value is validated against the kind
of its field when the object is built:

| Kind | Accepts |
| --- | --- |
| color | `#rgb`, `#rrggbb`, or `#rrggbbaa` |
| length | `0` or a number with `rem`, `em`, `px`, `%`, `ch`, `vw`, or `vh` |
| box | one to four lengths |
| font stack | a tuple of family names; generic families are emitted bare and the others quoted |
| weight | an integer from 1 to 1000 |
| case | `none`, `uppercase`, `lowercase`, or `capitalize` |
| opacity | a number from 0 to 1 |

No field accepts free CSS text, so a definition cannot add a declaration, a
rule, or a URL to a stylesheet.

`Palette.derive()` and `Skin.derive()` return a copy with some fields changed;
`Skin.derive()` takes the new name first. `Theme.from_seeds()` derives both
palettes from an accent color and an optional neutral color in the OKLCH color
space, at a `standard` or `high` contrast level, and solves each derived
lightness for the contrast rules below.

### 8.2 Contrast

A theme is checked when it is built, for each of its two palettes:

- `ink` and `muted` on `paper`, `panel`, and `panel_raised`, `accent_ink` on
  `accent`, `paper` on `ink`, and `panel` on `danger` reach 4.5:1;
- `accent` and the four tones on `paper` and `panel` reach 3:1 as graphics;
- `accent` and the four tones mixed 80% with `ink`, which is how the
  stylesheet sets text in a tone, reach 4.5:1 on `paper` and `panel`.

A theme that fails raises `ThemeContrastError`, which lists each failing pair
with its ratio. `allow_low_contrast=True` builds the theme anyway.
`Theme.report()` returns every check as a `ContrastCheck`. The translucent
`shadow_color` and `scrim` are not checked.

### 8.3 Generated CSS

`Theme.css()` and `Skin.css()` return the rule for a definition.

A theme is one rule on `[data-tori-ui-theme="<name>"]` that sets each palette
token to `light-dark(<light>, <dark>)`. The mode is `color-scheme` alone:
`light`, `dark`, or `light dark` for `auto`. Because `color-scheme` is
inherited and `light-dark()` is resolved where a token is used, a theme and a
mode compose at any depth of the document. This needs a browser with
`light-dark()`: Chrome 123, Firefox 120, or Safari 17.5.

A skin is one rule on `[data-tori-ui-skin="<name>"]` that sets every skin
token, followed by the two composed tokens, `--tori-ui-radius-surface-inner`
and `--tori-ui-shadow`, so that a skin on an inner element composes them from
its own parts.

The package stylesheet is the generated rules of the bundled definitions
followed by the component rules in `tori_liveview_ui.css`, assembled at import
time. `STYLESHEET_PATH` is the digest of the assembled bytes. Tokens that no
skin changes stay in the component rules: the application shell's sidebar and
aside widths and the stacking order of raised, drawer, overlay, and toast
layers.

### 8.4 Bundled Definitions

`Theme.PAPER` is the default theme; `Theme.SLATE` and `Theme.CONTRAST` are
derived with `Theme.from_seeds()`. `Skin.EDITORIAL` is the default skin, and
`Skin.MINIMAL` and `Skin.ROUNDED` are derived from it. All are in the package
stylesheet and need no registration.

### 8.5 Application Definitions

`LiveViewUiModule.for_root(themes=..., skins=...)` registers application
definitions. Each gets its own stylesheet at:

```text
/_tori/liveview-ui/theme-<name>.<first-12-hex-digest>.css
/_tori/liveview-ui/skin-<name>.<first-12-hex-digest>.css
```

with the same content type, ETag, and immutable cache policy as the package
stylesheet, which they never change. A name may be registered once, and the
bundled names are reserved.

`UiLiveView.ui_theme()` returns a `Theme` and defaults to `Theme.PAPER`;
`ui_skin()` returns a `Skin` and defaults to `Skin.EDITORIAL`; `ui_mode()`
returns `"auto"`, `"light"`, or `"dark"` and defaults to `"auto"`. The document
links the stylesheet of a returned application definition after the package
stylesheet. `ui_extra_definitions()` names further definitions the page uses
through `themed`, so that their stylesheets are linked as well.

`ui_theme()` and `ui_skin()` may instead return a name. A name selects a
bundled definition or one the application styles itself, by defining
`[data-tori-ui-theme="..."]` or `[data-tori-ui-skin="..."]` token overrides in
its own stylesheet loaded after `stylesheet_link()`. Any other value fails
rendering, so a document attribute cannot be injected.

### 8.6 Scoped Looks

`themed` wraps content in an element that carries any of the three attributes
and the `tori-ui-themed` surface class, which applies the paper background, ink
color, and body font of the look in effect inside it. An attribute that is left
out is inherited from the document.

### 8.7 The Visitor's Mode

The bundled script applies a mode the visitor stored earlier to
`data-tori-ui-mode` on `<html>` before the body is parsed, and `mode_toggle`
stores one. Without a stored choice the document keeps the mode the server
rendered. The theme and the skin are the application's choice.

## 9. Non-Goals

This package does not provide:

- domain validation, value coercion, form models, or changesets;
- a client runtime, a client-side state model, or widgets that own application
  state;
- file controls or upload integration until LiveView implements the Phoenix
  upload contract;
- Tailwind, Bootstrap, Node tooling, a CDN, external fonts, or remote script
  code; a separately distributed precompiled skin adapter may be added without
  changing this dependency boundary;
- a CSS preprocessor, free CSS text in a theme or skin definition, a theme
  the visitor picks, or a theme editor;
- a global CSS reset or arbitrary caller-supplied attributes/classes;
- required runtime dependencies beyond ToriPy and LiveView; optional features
  ship as extras, currently `markdown` and `highlight`;
- a model client, a provider adapter, a conversation store, or a page that owns
  a conversation;
- LiveComponent state, page state, event dispatch ownership, or a replacement
  for Phoenix Channels and render-tree semantics.

New component families establish their public contract in section 4 before
they ship, rather than expanding a helper by undocumented attributes or
implicit state.

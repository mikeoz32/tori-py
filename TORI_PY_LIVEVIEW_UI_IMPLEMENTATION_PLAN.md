# ToriPy LiveView UI Implementation Plan

## Status

Foundation slice (LVUI0), initial family acceptance (LVUI1), forms slice
(LVUI2), skinning slice (LVUI3), the component library foundation (LVUI4), and
the layout, content, icon, action, display, feedback, disclosure, chat, and
extended form and navigation families (LVUI5 through LVUI9) are complete.
LVUI10 and LVUI11 finish growing the package into a full component library.

Architecture:
[`TORI_PY_LIVEVIEW_UI_ARCHITECTURE.md`](TORI_PY_LIVEVIEW_UI_ARCHITECTURE.md).

## LVUI0: Foundation - Complete

- [x] Add the independently installable typed `tori-py-liveview-ui`
  distribution with dependencies on Tori Py framework and LiveView.
- [x] Freeze the `tori_py_liveview_ui` facade.
- [x] Implement stateless Template-returning `button`, `badge`, `alert`, `card`,
  `stack`, and `grid` helpers with closed visual options.
- [x] Preserve LiveView template escaping and Phoenix render-tree composition;
  use its `attrs`, `classes`, and `fragment` helpers internally.
- [x] Preserve Phoenix `phx-click` and `phx-target` semantics for buttons without
  adding a client runtime.
- [x] Bundle local prefixed CSS and serve it through
  `LiveViewUiModule.for_root()` at a SHA-256 content-addressed immutable path.
- [x] Add `stylesheet_link()` and `UiLiveView` auto/light/dark document theming.
- [x] Implement theme variables, accessibility focus/disabled behavior,
  responsive grids, and reduced-motion behavior without a global reset, remote
  assets, or external fonts.

## LVUI1: Family Acceptance - Complete

- [x] Run the final full-family test, Ruff, formatter, Ty, build, artifact, and
  strict documentation gates for release.
- [x] Complete independent architecture, accessibility, security, and release
  review across the resolved package family.

## LVUI2: Forms and Validation Presentation - Complete

- [x] Add stateless `form`, `field`, `field_error`, `input`, `textarea`,
  `select`, and `checkbox` Template helpers with closed form-control options.
- [x] Preserve Phoenix `phx-change`, `phx-submit`, `phx-blur`, and `phx-target`
  routing without adding client-side state or behavior.
- [x] Generate native labels, required and disabled states, help/error
  descriptions, `aria-invalid`, and live validation alerts.
- [x] Style form controls within the prefixed local stylesheet with explicit
  focus, invalid, disabled, light/dark, and responsive behavior.
- [x] Exercise server-owned validation and submission through the pinned
  official Phoenix browser client.

## LVUI3: Skinning - Complete

- [x] Keep stable `tori-ui-*` semantic markup and separate color theme selection
  from document-level visual skin selection.
- [x] Add the bundled `editorial`, `minimal`, and `rounded` skins, retaining
  `editorial` as the compatibility default.
- [x] Expand public CSS tokens for spacing, radii, control heights, borders,
  typography, shadows, focus geometry, density, and layout.
- [x] Allow validated application-owned skin names and application stylesheet
  token overrides without mutating the immutable package asset.
- [x] Exercise a non-default skin and post-package token override in the official
  Phoenix browser acceptance test.

## LVUI4: Component Library Foundation - Complete

- [x] Record the library contract: shared helper rules, families, and the
  browser behavior order of native elements, `JS` commands, then hooks.
- [x] Split the helpers into private family modules behind the unchanged flat
  facade.
- [x] Bundle one local script of `ToriUi`-prefixed Phoenix hooks, serve it at a
  SHA-256 content-addressed immutable path, and add `SCRIPT_PATH` and
  `script_tag()`.
- [x] Register the hooks before the deferred LiveView client reads them, also
  when an application script replaces `globalThis.ToriLiveHooks`.
- [x] Apply a stored visitor theme before the first paint.
- [x] Add the component gallery example that later slices extend and exercise
  through the official Phoenix browser client.

## LVUI5: Layout, Content, Icons, and Actions - Complete

- [x] Layout: `row`, `container`, `center`, `divider`, `spacer`, `section`,
  `page_header`, `toolbar`, `split`, `scroll_area`, and `app_shell`.
- [x] Content: `heading`, `text`, `link`, `code`, `code_block`, `kbd`,
  `blockquote`, `prose`, `item_list`, `description_list`, `image`, and `icon`
  with a closed set of bundled inline SVG icons.
- [x] Actions: `icon_button`, `link_button`, `button_group`, `copy_button`, and
  `theme_toggle`; `button` gains icons, event values, a loading state,
  `phx-disable-with`, a native confirmation, and full width.
- [x] Copy text to the clipboard from `copy_button` and `code_block` through a
  `JS` dispatch and one listener in the script.
- [x] Keep the helpers and the stylesheet in agreement on class names through
  the test suite.

## LVUI6: Data Display, Feedback, and Disclosure - Complete

- [x] Display: `table` with page-owned sorting and stream bodies, `table_row`,
  `list_group`, `list_item`, `stat`, `sparkline`, `avatar`, `avatar_group`,
  `tag`, `status_dot`, `timeline`, `timeline_item`, `empty_state`, `progress`,
  `meter`, and `tooltip`.
- [x] Feedback: `spinner`, `skeleton`, `toast`, `toast_region`, `flash_group`,
  `banner`, `connection_status`, and `busy`; `alert` gains actions and
  dismissal by the browser or by the page.
- [x] Disclosure: `collapsible`, `accordion`, and `tabs` that either the
  browser or the page switches.
- [x] Hooks for self-closing toasts and for arrow-key navigation between tabs;
  Escape dismisses an open tooltip.

## LVUI7: Chat and AI - Complete

- [x] Conversation: `chat`, `chat_log`, `chat_message`, `message_actions`,
  `composer`, `suggestions`, `chat_empty`, `typing_indicator`,
  `conversation_list`, and `response_branch`.
- [x] Model output: `reasoning`, `tool_call`, `agent_steps`, `agent_step`,
  `sources`, `citation`, `attachment`, `token_usage`, and `artifact_panel`.
- [x] `markdown` behind the optional `markdown` extra, with raw HTML shown as
  text, link schemes restricted, and images off by default, and code
  highlighting behind the optional `highlight` extra.
- [x] Hooks for following a growing log and for a composer that submits on
  Enter and grows with its text.
- [x] Inline SVG with explicit end tags, so every helper's output is a valid
  LiveView stream item.
- [x] A chat demo in the gallery that streams from a scripted model without an
  API key and batches model output into one render per flush.

## LVUI8: Forms - Complete

- [x] `radio_group`, `checkbox_group`, `switch`, `segmented`, `multi_select`,
  `combobox`, `search`, `slider`, `hidden`, `fieldset`, and `form_actions`.
- [x] `input` and `textarea` gain debounce and throttle, read-only state, and
  value and length bounds; `input` gains a prefix and a suffix, which replace
  the separate `input_group` helper that was planned.

## LVUI9: Navigation - Complete

- [x] `navbar`, `nav`, `nav_item`, `breadcrumbs`, `pagination`, `steps`,
  `tab_links`, and `skip_link`, with live patch and navigate links.
- [x] `app_shell` gives its main area an ID and makes it focusable, as the
  target of the skip link.

## LVUI10: Overlays

- [ ] `modal`, `drawer`, `confirm_dialog`, `dropdown`, `menu_item`, and
  `popover`, with helpers that return the `JS` commands to open and close
  them.
- [ ] Focus containment, Escape, click-away, and focus return.

## LVUI11: Library Acceptance

- [ ] Exercise every interactive family in the gallery through the official
  Phoenix browser client, in the light and dark themes and the bundled skins.
- [ ] Run the full-family test, Ruff, formatter, Ty, build, artifact, and strict
  documentation gates.

## Deferred

- File inputs, drop zones, and upload integration, until LiveView implements
  the Phoenix upload contract.
- Charts beyond `sparkline`, a calendar date picker, a rich text editor,
  drag-and-drop sorting, a carousel, a command palette, a tree view, and a
  virtualized data grid.
- Application form-model or coercion abstractions.
- A state-owning chat page, a provider-neutral model event stream, and a
  one-call application launcher. They belong to a separate package built on
  this one.
- An optional separately distributed precompiled Tailwind skin adapter; Tailwind
  remains outside the core package and runtime dependency graph.
- Arbitrary attribute/class extension APIs and a global design reset.

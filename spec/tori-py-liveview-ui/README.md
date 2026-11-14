# ToriPy LiveView UI Specification

This directory records the executable contract for `tori-py-liveview-ui`. The
architecture is maintained in
[`TORI_PY_LIVEVIEW_UI_ARCHITECTURE.md`](../../TORI_PY_LIVEVIEW_UI_ARCHITECTURE.md).

1. The package is optional, typed, and separately distributed. It depends on
   `tori-py-framework` and `tori-py-liveview`; neither dependency imports it.
2. Its public facade is the flat `tori_py_liveview_ui` namespace:
   `STYLESHEET_PATH`, `SCRIPT_PATH`, `LiveViewUiModule`, `UiLiveView`,
   `stylesheet_link`, `script_tag`, and the helpers of each family. Its
   implementation modules are private.
3. The helpers are stateless and return Python 3.14 `Template` values. Their
   variants, sizes, tones, gaps, alignment, columns, button/input types, and
   textarea row bounds are closed to the documented values; unsupported values
   fail rather than becoming CSS class injection.
4. Helpers preserve LiveView Template escaping and Phoenix render-tree
   composition. Internally generated attributes use `attrs`; callers receive no
   arbitrary attributes or classes parameter.
5. The families are actions (`button`, `icon_button`, `link_button`,
   `button_group`, `copy_button`, `theme_toggle`), layout (`card`, `stack`,
   `grid`, `row`, `container`, `center`, `divider`, `spacer`, `section`,
   `page_header`, `toolbar`, `split`, `scroll_area`, `app_shell`), content
   (`heading`, `text`, `link`, `code`, `code_block`, `kbd`, `blockquote`,
   `prose`, `item_list`, `description_list`, `image`), icons (`icon`), display
   (`badge`, `table`, `table_row`, `list_group`, `list_item`, `stat`,
   `sparkline`, `avatar`, `avatar_group`, `tag`, `status_dot`, `timeline`,
   `timeline_item`, `empty_state`, `progress`, `meter`, `tooltip`, and the
   `TableColumn` value), feedback (`alert`, `banner`, `spinner`, `skeleton`,
   `busy`, `toast`, `toast_region`, `flash_group`, `connection_status`),
   disclosure (`collapsible`, `accordion`, `tabs`), conversation (`chat`,
   `chat_log`, `chat_message`, `message_actions`, `composer`, `suggestions`,
   `chat_empty`, `typing_indicator`, `conversation_list`, `response_branch`,
   `reasoning`, `tool_call`, `agent_steps`, `agent_step`, `sources`,
   `citation`, `attachment`, `token_usage`, `artifact_panel`), rich text
   (`markdown`), and forms (`form`, `fieldset`, `form_actions`, `field`,
   `field_error`, `input`, `textarea`, `select`, `multi_select`, `combobox`,
   `search`, `slider`, `checkbox`, `checkbox_group`, `radio_group`,
   `segmented`, `switch`, `hidden`).
6. `button` maps an optional event and positive safe-integer component target to
   `phx-click` and `phx-target`. A target requires an event. The helper does not
   own event routing or state. Event values map to `phx-value-*` attributes
   with attribute-safe lowercase names and scalar values, and require an event.
   `loading` disables the button and marks it busy, `disable_with` maps to
   `phx-disable-with`, and `confirm` gates the click behind a native dialog
   before the LiveView client sees it.
7. `form` emits `method="post"` and maps optional events to `phx-change` and
   `phx-submit`; controls map optional events to `phx-change` and `phx-blur`.
   Control-level changes require a containing form. An optional positive
   safe-integer `phx-target` requires an event.
8. Concrete controls render native labels and deterministic help/error IDs.
   Errors set `aria-invalid`, participate in `aria-describedby`, and render as
   live alerts. `field` callers own equivalent required, invalid, and ARIA state
   for custom controls.
9. Names preserve bracket/list notation. Form events produce decoded mappings
   with string leaves, blur events produce control value mappings, unchecked
   checkboxes remain absent, and application pages/components own coercion,
   validation, current values, and error state.
10. `LiveViewUiModule.for_root()` materializes one normal controller serving the
    exact bundled CSS and JavaScript bytes. `STYLESHEET_PATH` and `SCRIPT_PATH`
    include the first 12 hexadecimal characters of each file's SHA-256 digest;
    each response has the full-digest ETag and one-year public immutable cache
    policy.
11. `UiLiveView` defaults independently to the `auto` theme and `editorial`
    skin, adds both data attributes to the document HTML element, inserts the
    local `stylesheet_link()` and `script_tag()` into the normal LiveView
    document head, and puts the `tori-ui-document` surface class on the body.
    Theme is closed to `auto`/`light`/`dark`; skin accepts a bounded lowercase
    CSS identifier.
12. The stylesheet bundles `editorial`, `minimal`, and `rounded`. Color theme
    owns palette values; visual skin owns spacing, shape, density, typography,
    shadow/focus geometry, and layout values. The server does not change the
    outer document selection from connected state.
13. CSS selectors are `tori-ui-` prefixed, public `--tori-ui-*` properties are
    application-overridable, component layout is responsive, focus/disabled and
    form-invalid behavior is explicit, and reduced motion disables transitions.
    Application-owned skins remain separate CSS loaded after the immutable
    package stylesheet.
14. Browser behavior uses native elements first, LiveView `JS` commands second,
    and hooks from the bundled script last. The script defines only
    `ToriUi`-prefixed hooks, adds them to `globalThis.ToriLiveHooks` when it
    loads and again when the document has been parsed, and applies a stored
    visitor theme before the first paint. It holds no application state, opens
    no connections, loads no remote code, and evaluates no strings as code.
15. Links are plain, live, or external. Live links carry `data-phx-link` and
    `data-phx-link-state` and need a root-relative path; external links open a
    new tab with `rel="noopener noreferrer"`; executable URL schemes fail.
16. Icons are a closed set of static inline SVG drawings selected by name. An
    unlabeled icon is hidden from assistive technology; an icon-only button
    requires a label.
17. `copy_button` and `code_block` copy in the browser through a `JS` dispatch
    and one script listener, keep the button's accessible name, and announce
    the result. `theme_toggle` applies and stores the visitor's theme in the
    browser. Neither notifies the page.
18. `app_shell` renders the main landmark in a viewport-filling grid. Below
    56rem its sidebar opens over the content through `JS` commands; the open
    state survives server renders and ends on Escape, a scrim click, or a live
    navigation.
19. Every class a helper emits has a rule or is listed as structural, every
    rule belongs to an emitted class, and keyframes and custom properties are
    prefixed.
20. Tables are sorted by the page: sortable headers push an event with the
    column key and report the order through `aria-sort`. A table body may be a
    LiveView stream container whose items are `table_row` results.
21. Alerts, banners, and toasts are dismissed by the browser through a `JS`
    hide command, or by the page through an event. A toast with a duration
    closes itself by pressing its own dismiss button and pauses under the
    pointer or the focus. `flash_group` clears a flash kind through
    `lv:clear-flash`.
22. `busy` marks a region `aria-busy` and makes it inert while loading.
    `connection_status` appears from the classes the LiveView client puts on a
    disconnected root, without script.
23. `collapsible` is a native `details` element whose `open` attribute the
    client leaves alone after the first render. `tabs` follows the tabs
    pattern with arrow-key navigation; the browser switches fully rendered
    panels, or the page switches through an event and renders one panel.
24. `chat_log` follows growing content until the visitor scrolls away, and
    only their scrolling releases it. `composer` submits on Enter, keeps
    Shift+Enter and IME composition, grows to a row limit, refuses an empty or
    busy submit, and empties itself after the client has read the form.
25. A streaming `chat_message` sets `aria-busy`. `reasoning` and `tool_call`
    are native `details` elements whose open state the browser keeps. Every
    helper's output, including inline SVG, is explicitly balanced markup and
    therefore a valid LiveView stream item.
26. `markdown` needs the `markdown` extra and treats its source as untrusted:
    raw HTML is text, executable and local link schemes are not linked, links
    to other sites open without the opener, and images are off unless enabled.
    Code highlighting needs the `highlight` extra and uses prefixed classes
    colored from the theme.
27. Choice groups are fieldsets named by a legend. Radio groups and segmented
    controls are native radios in a `radiogroup`; a checkbox group and a
    multiple select submit a list under a name ending in `[]`. Native bounds,
    read-only state, and `phx-debounce` or `phx-throttle` are closed, validated
    options, and the page remains the authority on validity.
28. The core package has no CDN, Node or Tailwind dependency, external font,
    remote asset, global reset, domain validation/coercion system, arbitrary
    attributes/classes, client runtime, or application-state ownership.
    Optional features ship as extras, and the package contains no model client
    or provider adapter. A future Tailwind skin adapter remains a
    separate precompiled distribution.

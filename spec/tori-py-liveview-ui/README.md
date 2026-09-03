# ToriPy LiveView UI Specification

This directory records the executable foundation contract for
`tori-py-liveview-ui`. The architecture is maintained in
[`TORI_PY_LIVEVIEW_UI_ARCHITECTURE.md`](../../TORI_PY_LIVEVIEW_UI_ARCHITECTURE.md).

1. The package is optional, typed, and separately distributed. It depends on
   `tori-py-framework` and `tori-py-liveview`; neither dependency imports it.
2. Its public facade is limited to `STYLESHEET_PATH`, `LiveViewUiModule`,
   `UiLiveView`, `stylesheet_link`, `button`, `badge`, `alert`, `card`, `stack`,
   `grid`, `form`, `field`, `field_error`, `input`, `textarea`, `select`, and
   `checkbox`.
3. The component helpers are stateless and return Python 3.14 `Template` values.
   Their variants, sizes, tones, gaps, alignment, columns, button/input types,
   and textarea row bounds are closed to the documented values; unsupported
   values fail rather than becoming CSS class injection.
4. Helpers preserve LiveView Template escaping and Phoenix render-tree
   composition. Internally generated button attributes use `attrs`; callers
   receive no arbitrary attributes or classes parameter.
5. `button` maps an optional event and positive safe-integer component target to
   `phx-click` and `phx-target`. A target requires an event. It adds no
   client-side behavior and does not own event routing or state.
6. `form` emits `method="post"` and maps optional events to `phx-change` and
   `phx-submit`; controls map optional events to `phx-change` and `phx-blur`.
   Control-level changes require a containing form. An optional positive
   safe-integer `phx-target` requires an event.
7. Concrete controls render native labels and deterministic help/error IDs.
   Errors set `aria-invalid`, participate in `aria-describedby`, and render as
   live alerts. `field` callers own equivalent required, invalid, and ARIA state
   for custom controls.
8. Names preserve bracket/list notation. Form events produce decoded mappings
   with string leaves, blur events produce control value mappings, unchecked
   checkboxes remain absent, and application pages/components own coercion,
   validation, current values, and error state.
9. `LiveViewUiModule.for_root()` materializes one normal controller serving the
   exact bundled CSS bytes. `STYLESHEET_PATH` includes the first 12 hexadecimal
   characters of their SHA-256 digest; the response has the full-digest ETag and
   one-year public immutable cache policy.
10. `UiLiveView` defaults independently to the `auto` theme and `editorial`
    skin, adds both data attributes to the document HTML element, and inserts
    the local `stylesheet_link()` into the normal LiveView document head. Theme
    is closed to `auto`/`light`/`dark`; skin accepts a bounded lowercase CSS
    identifier.
11. The stylesheet bundles `editorial`, `minimal`, and `rounded`. Color theme
    owns palette values; visual skin owns spacing, shape, density, typography,
    shadow/focus geometry, and layout values. Connected diffs do not dynamically
    change the outer document selection.
12. CSS selectors are `tori-ui-` prefixed, public `--tori-ui-*` properties are
    application-overridable, component layout is responsive, focus/disabled and
    form-invalid behavior is explicit, and reduced motion disables button
    transitions. Application-owned skins remain separate CSS loaded after the
    immutable package stylesheet.
13. The core package has no CDN, Node or Tailwind dependency, external font,
    remote asset, runtime JavaScript, global reset, domain validation/coercion
    system, modal, navigation, arbitrary attributes/classes, widget behavior,
    or component-state ownership. A future Tailwind skin adapter remains a
    separate precompiled distribution.

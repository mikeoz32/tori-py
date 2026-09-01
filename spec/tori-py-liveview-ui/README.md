# ToriPy LiveView UI Specification

This directory records the executable foundation contract for
`tori-py-liveview-ui`. The architecture is maintained in
[`TORI_PY_LIVEVIEW_UI_ARCHITECTURE.md`](../../TORI_PY_LIVEVIEW_UI_ARCHITECTURE.md).

1. The package is optional, typed, and separately distributed. It depends on
   `tori-py-framework` and `tori-py-liveview`; neither dependency imports it.
2. Its public facade is limited to `STYLESHEET_PATH`, `LiveViewUiModule`,
   `UiLiveView`, `stylesheet_link`, `button`, `badge`, `alert`, `card`, `stack`,
   and `grid`.
3. The six helpers are stateless and return Python 3.14 `Template` values. Their
   variants, sizes, tones, gaps, alignment, columns, and button types are closed
   to the documented values; unsupported values fail rather than becoming CSS
   class injection.
4. Helpers preserve LiveView Template escaping and Phoenix render-tree
   composition. Internally generated button attributes use `attrs`; callers
   receive no arbitrary attributes or classes parameter.
5. `button` maps an optional event and positive safe-integer component target to
   `phx-click` and `phx-target`. A target requires an event. It adds no
   client-side behavior and does not own event routing or state.
6. `LiveViewUiModule.for_root()` materializes one normal controller serving the
   exact bundled CSS bytes. `STYLESHEET_PATH` includes the first 12 hexadecimal
   characters of their SHA-256 digest; the response has the full-digest ETag and
   one-year public immutable cache policy.
7. `UiLiveView` defaults to the `auto` theme, validates `auto`/`light`/`dark`,
   adds `data-tori-ui-theme` to the document HTML element, and inserts the local
   `stylesheet_link()` into the normal LiveView document head.
8. CSS selectors are `tori-ui-` prefixed, public `--tori-ui-*` properties are
   application-overridable, component layout is responsive, focus/disabled
   behavior is explicit, and reduced motion disables button transitions.
9. The package has no CDN, Node dependency, external font, remote asset, runtime
   JavaScript, global reset, form system, modal, navigation, arbitrary
   attributes/classes, widget behavior, or component-state ownership.

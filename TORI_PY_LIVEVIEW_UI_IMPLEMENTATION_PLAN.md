# ToriPy LiveView UI Implementation Plan

## Status

Foundation slice (LVUI0) and family acceptance (LVUI1) are complete.

Architecture: [`TORI_PY_LIVEVIEW_UI_ARCHITECTURE.md`](TORI_PY_LIVEVIEW_UI_ARCHITECTURE.md).

## LVUI0: Foundation — Complete

- [x] Add the independently installable typed `tori-py-liveview-ui` distribution
  with dependencies on Tori Py framework and LiveView.
- [x] Freeze the `tori_py_liveview_ui` facade.
- [x] Implement stateless Template-returning `button`, `badge`, `alert`, `card`,
  `stack`, and `grid` helpers with closed visual options.
- [x] Preserve LiveView template escaping/composition and use its `attrs`,
  `classes`, and `fragment` helpers at the appropriate internal boundaries.
- [x] Preserve Opal `data-opal-click` and `data-opal-target` semantics for
  buttons without adding a client runtime.
- [x] Bundle local prefixed CSS and serve it through `LiveViewUiModule.for_root()`
  at a SHA-256 content-addressed immutable path.
- [x] Add `stylesheet_link()` and `UiLiveView` auto/light/dark document theming.
- [x] Implement theme variables, accessibility focus/disabled behavior,
  responsive grids, and reduced-motion behavior without a global reset, remote
  assets, or external fonts.

## LVUI1: Family Acceptance — Complete

- [x] Run the final full-family test, Ruff, formatter, ty, build, artifact, and
  strict documentation gates for release.
- [x] Complete independent architecture, accessibility, security, and release
  review across the resolved package family.

## Deferred

- Form controls and validation presentation.
- Modal, navigation, menu, toast, and upload families.
- Any JavaScript widget behavior or state-owning component abstraction.
- Arbitrary attribute/class extension APIs and a global design reset.

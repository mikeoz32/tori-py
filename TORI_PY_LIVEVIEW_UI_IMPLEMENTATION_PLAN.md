# ToriPy LiveView UI Implementation Plan

## Status

Foundation slice (LVUI0), initial family acceptance (LVUI1), forms slice
(LVUI2), and skinning slice (LVUI3) are complete.

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

## Deferred

- Radio groups, multiple selects, file inputs, upload integration, and
  application form-model or coercion abstractions.
- Modal, navigation, menu, toast, and upload families.
- An optional separately distributed precompiled Tailwind skin adapter; Tailwind
  remains outside the core package and runtime dependency graph.
- Any JavaScript widget behavior or state-owning component abstraction.
- Arbitrary attribute/class extension APIs and a global design reset.

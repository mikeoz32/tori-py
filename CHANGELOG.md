# Changelog

Notable changes to each Tori Py distribution are documented here. Each package
uses independent [Semantic Versioning](https://semver.org/); a version change in
one package does not require the same change in every package.

## [Unreleased]

### Added

- Public package metadata, legal files, security policy, contribution guidance,
  and release documentation.
- Opt-in core `@no_body` route metadata with post-guard actual-stream enforcement
  and compatible trailing route-plan metadata.
- Typed request-lifetime raw HTTP body streaming with direct backpressured ASGI
  receiving, incremental limits, complete-consumption enforcement, and
  provenance-aware disconnect cancellation.
- OpenAPI bound-parameter schema/description refinement plus explicit response
  headers and per-response media types, including header-only 204 responses.
- Native dependency-free HTTP ASGI adapter in `tori_py.asgi` (`AsgiAdapter`,
  `AsgiOptions`, `asgi`, `RequestContext`) alongside the Starlette adapter. It
  serves HTTP scopes only; WebSocket gateways and LiveView need Starlette.
- Custom route parameter resolvers: any object implementing
  `RouteParameterResolver` can bind a handler parameter.
- Explicit singleton `@websocket_gateway` providers with native Starlette
  sockets, marker-only handshake binding, connection-owned request scopes, and
  the full middleware/guard/pipe/interceptor/filter pipeline.
- Separately installable `tori-py-liveview` integration with explicit
  request-scoped pages, signed mounts, checksum-pinned official Phoenix and
  Phoenix LiveView clients, Channels/render-tree interoperability,
  connection-local stateful component CIDs, targeted component events, and
  browser-owned bounded streams, plus serialized connection-local server
  updates through `send_info` and `handle_info`.
- Separately installable `tori-py-liveview-ui` foundation with typed stateless
  display, layout, form, and validation-presentation helpers, a
  content-addressed immutable local stylesheet, and `UiLiveView` document
  theming plus editorial/minimal/rounded skinning for Phoenix LiveView pages.
- LiveView `JS`, an immutable builder for Phoenix client JS commands matching
  `Phoenix.LiveView.JS` and the pinned 1.2.11 client. Chains render as trusted
  `phx-*` values through interpolation, `attrs()`, and `rendered()`, and
  LiveView UI event options accept them.
- LiveView client hooks, pushed events, event replies, and component updates.
  The client bootstrap passes `globalThis.ToriLiveHooks` to the official
  `LiveSocket` as its `hooks` object; pages and components gain `push_event()`
  (`phx:<event>` window events delivered under the render-tree `e` key) and
  `send_update()`, and a mapping returned from `handle_event()` replies to the
  browser event under the `r` key.
- LiveView flash, async work, and join extras. Pages gain `put_flash()`,
  `clear_flash()`, and a read-only `flash` mapping, and components forward
  `put_flash()` and `clear_flash()` to their page; flash follows
  `push_navigate()` as a signed token and `redirect()` through the Phoenix
  `__phoenix_flash__` cookie, and the official `lv:clear-flash` event clears it.
  `start_async()`, `assign_async()`, `cancel_async()`, `handle_async()`, and
  `AsyncResult` run concurrent work and deliver it on the connection task;
  `LiveViewOptions.async_cancel_timeout_seconds` bounds the wait for cancelled
  work. The
  bootstrap passes `globalThis.ToriLiveParams` to the client, connected mounts
  receive `MountContext.connect_params` with `static_changed()`, and a 4xx
  `HttpException` during the connected mount reloads the page.
- LiveView changed-only diffs. After the join, renders send only what the
  official client's cached tree lacks: changed values without their statics,
  only the components that changed, each component template's statics once,
  stream entries only with operations, and the title only when it changes.
  Info and async renders that change nothing push no `diff`.
- LiveView nested components. `LiveComponent.live_component()` renders a nested
  component from a component's `render()`; nested components share the page's
  identity namespace, CIDs, targets, `send_update()`, async work, and
  destruction handshake. A component's root must be a tag in its own template,
  not a nested component or another dynamic value.
- LiveView document keys. `LiveView.document_key()` returns an optional string
  that identifies the document a page renders into. The signed mount token
  carries the digest of the key, and a live navigation to a page with another
  key is answered with a full page load of that page instead of joining the
  document the browser holds. The key is read after `mount()` and
  `handle_params()`; first joins and reconnects are never compared.
- LiveView child LiveViews. `LiveView.live_render()` places a registered page as
  a child view, rendered into its container over HTTP and joined on its own
  channel topic over the same socket, and `LiveViewModule.for_root(embedded=...)`
  registers pages rendered only this way. Child tokens are signed for their
  page, view id, parent mount, params, and session, and a child joins only
  under the mount of a joined parent that rendered it. Each child runs its
  callbacks in its own work scope.
- LiveView UI component library. `tori-py-liveview-ui` grows from 13 helpers to
  families for layout, content and icons, actions, data display, feedback,
  disclosure, forms, navigation, overlays, and chat and AI, all stateless
  Template helpers with closed options. A gallery example shows every helper in
  each theme and skin.
  - The package now also bundles one content-addressed script of
    `ToriUi`-prefixed Phoenix hooks, served at `SCRIPT_PATH` and linked with
    `script_tag()`. Helpers use native elements first, `JS` commands second,
    and a hook only where neither can express a behavior; the browser owns
    presentation state such as an open menu, a scroll position, or a stored
    theme, and the page keeps application state.
  - `UiLiveView` documents load that script, put the `tori-ui-document` surface
    class on `<body>`, which sets the theme's background, text color, and font
    and removes the body margin, and apply a color mode the visitor chose
    with `mode_toggle()` before the first paint.
  - `button` gains icons, event values, a loading state, `phx-disable-with`, a
    native confirmation, and full width; `alert` gains actions and dismissal;
    `input` and `textarea` gain bounds, read-only state, and debounce or
    throttle.
  - The optional `markdown` extra adds `markdown()` on `markdown-it-py`, which
    treats its source as untrusted, and the optional `highlight` extra colors
    its code blocks with Pygments. The required dependencies are unchanged.
- LiveView UI theme framework. Themes and skins are typed definitions:
  `Theme` holds a light and a dark `Palette`, and `Skin` holds the shape
  tokens. The package generates their CSS, validates every value against the
  kind of its token, and checks a theme for WCAG AA contrast when it is
  built, raising `ThemeContrastError` unless `allow_low_contrast=True`.
  - `Theme.from_seeds()` derives both palettes from an accent and an optional
    neutral color; `Palette.derive()` and `Skin.derive()` change some values
    of a definition. `Theme.SLATE` and `Theme.CONTRAST` join `Theme.PAPER`,
    and the bundled skins are `Skin.EDITORIAL`, `Skin.MINIMAL`, and
    `Skin.ROUNDED`.
  - `LiveViewUiModule.for_root(themes=..., skins=...)` serves each application
    definition as its own content-addressed stylesheet, `UiLiveView` links
    those a page returns from `ui_theme()`, `ui_skin()`, and
    `ui_extra_definitions()`, and `stylesheet_link()` accepts definitions.
  - `themed()` gives part of a page its own theme, mode, or skin.
  - `UiLiveView` implements `document_key()` with its look, so a live
    navigation to a page with another theme, mode, skin, or application
    stylesheet loads that page in a new document instead of keeping the old
    look.
  - The color mode is now separate from the theme: `ui_mode()` and
    `data-tori-ui-mode` carry `auto`, `light`, or `dark`, while `ui_theme()`
    and `data-tori-ui-theme` name a theme. A theme sets each color with
    `light-dark()`, which needs Chrome 123, Firefox 120, or Safari 17.5.

### Fixed

- OpenAPI header parameter identities now follow case-insensitive HTTP semantics,
  and excessively nested annotations fail with typed schema diagnostics.
- Settings secrets wrapped in `Optional`, `| None`, or another union, and secrets
  inside optional nested models, are now protected from `--set` and other
  bootstrap overrides.
- LiveView `redirect()` now cleans its target, rejects non-http(s) schemes such
  as `javascript:`, and keeps redirects on the request host unless the host is
  listed in the new `LiveViewOptions.redirect_hosts`. Live navigation targets
  that browsers read as another host, such as `/\evil.example` or
  `///evil.example`, are no longer treated as same-origin.
- Value and factory providers that expose a class with method interceptors now
  fail instead of silently skipping the interceptors.
- LiveView `attrs()`, Template interpolation, and `rendered()` values, and the
  LiveView UI event options built on them, now reject data that would start or
  appear inside a `phx-*` value beginning with `[`, which the Phoenix client runs
  as JS commands.
- Swagger UI now loads its default CDN assets with pinned Subresource Integrity
  hashes. `SwaggerUiOptions` adds `javascript_integrity` and
  `stylesheet_integrity`, which are required for other absolute HTTPS asset URLs.

## [0.1.0] - Unreleased

Coordinated initial beta release train for all 14 distributions. This train
establishes public package boundaries and compatibility ranges; subsequent
releases are versioned independently.

The `tori-py-persistent-streams-rabbitmq` release is provisional and
conditional. Its operational limits, driver and broker requirements, checkpoint
constraints, and remaining deployment gates are documented in its package
README and operations guide.

[Unreleased]: https://github.com/mikeoz32/tori-py/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mikeoz32/tori-py/releases/tag/v0.1.0

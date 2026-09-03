# LiveView UI Showcase

Run the application with:

```text
uv run tori-py run examples.tori_py.liveview.app:create_application
```

Open `http://127.0.0.1:8000/?start=2`. The initial page, two component counters,
and activity stream are rendered over HTTP. Subsequent events travel over
`/_tori/live/websocket` through Phoenix Channels; page events update the page
counter, targeted component events preserve isolated left/right state, and
bounded stream operations prepend or delete activity items without rerendering
retained children.

The page demonstrates stateless `tori-py-liveview-ui` display, layout, and form
helpers. Its counter form uses server-owned validation through `phx-change` and
explicit submission through `phx-submit`; native labels, help text, and error
relationships remain accessible. `UiLiveView` adds the local content-addressed
stylesheet and automatic light/dark theme without a second browser runtime. The
page independently selects the bundled `rounded` visual skin.

The delayed increment starts a background task and wakes the connected page
through `send_info()`/`handle_info()`; the update remains serialized with normal
Phoenix Channel events and renders.

The hard-coded secret is for this local example only. Production deployments
must supply a strong shared secret from configuration.

## Browser E2E

Install Chromium once and run the explicit browser test:

```text
uv run playwright install chromium
uv run pytest examples/tori_py/liveview/browser_e2e.py
```

The test exercises the real vendored official Phoenix and Phoenix LiveView
clients against a local ASGI server. It verifies HTTP rendering, Channels page
and targeted component events, component-state isolation, bounded stream
insertion/deletion, retained DOM identity, title changes, reconnect state, and
browser console errors. It also verifies form change/submission events, live
validation feedback, independent theme/skin attributes, immutable UI stylesheet
link, bundled rounded geometry, an application-owned CSS token override, and the
component class contract. The file is named outside normal pytest discovery so
browser installation remains an explicit local gate rather than an implicit CI
requirement.

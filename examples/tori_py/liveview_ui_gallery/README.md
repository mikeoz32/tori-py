# LiveView UI Gallery

Every `tori-py-liveview-ui` component on one application. Run it with:

```text
uv run tori-py run examples.tori_py.liveview_ui_gallery.app:create_application
```

Open `http://127.0.0.1:8000/`. The sidebar switches between the component
families without reloading the document. The header switches the bundled skins,
which reloads the page because the skin belongs to the document, and holds the
theme toggle, which works in the browser. Both can also be set in the query
string, for example `/?theme=dark&skin=rounded`.

The hard-coded secret is for this local example only. Production deployments
must supply a strong shared secret from configuration.

## Browser E2E

Install Chromium once and run the explicit browser test:

```text
uv run playwright install chromium
uv run pytest examples/tori_py/liveview_ui_gallery/browser_e2e.py
```

The test drives the gallery through the real vendored official Phoenix and
Phoenix LiveView clients and fails on any browser console error.

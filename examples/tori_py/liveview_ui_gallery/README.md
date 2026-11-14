# LiveView UI Gallery

Every `tori-py-liveview-ui` component on one application. Run it with:

```text
uv run tori-py run examples.tori_py.liveview_ui_gallery.app:create_application
```

Open `http://127.0.0.1:8000/`. The links at the top switch between the pages,
the color themes, and the bundled skins; the choice travels in the query string,
for example `/?theme=dark&skin=rounded`.

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

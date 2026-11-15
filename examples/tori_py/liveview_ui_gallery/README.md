# LiveView UI Gallery

Every `tori-py-liveview-ui` component on one application. Run it with:

```text
uv run tori-py run examples.tori_py.liveview_ui_gallery.app:create_application
```

Open `http://127.0.0.1:8000/`. The sidebar switches between the component
families without reloading the document. The header switches the bundled skins,
which reloads the page because the skin belongs to the document, and holds the
mode toggle, which works in the browser. The Themes page shows every theme in
both modes and every skin, with the contrast report of the current theme, and
lets you choose among them. The look can also be set in the query string, for
example `/?theme=slate&mode=dark&skin=rounded`.

The gallery defines a theme and a skin of its own in `looks.py`, the orchid
theme derived from two colors and the compact skin derived from a bundled one,
and registers them with `LiveViewUiModule.for_root()`.

The hard-coded secret is for this local example only. Production deployments
must supply a strong shared secret from configuration.

## Browser scenarios

The gallery is the application under test for the `tori-py-liveview-ui`
pytest-bdd scenarios in `packages/tori-py-liveview-ui/tests/features/`, one
feature file per component family. Install Chromium once and run them:

```text
uv run playwright install chromium
uv run pytest packages/tori-py-liveview-ui/tests/test_browser.py
```

The scenarios drive the gallery through the real vendored official Phoenix and
Phoenix LiveView clients, and a scenario fails on any browser console error.

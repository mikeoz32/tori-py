# LiveView Counter

Run the application with:

```text
uv run tori-py run examples.tori_py.liveview.app:create_application
```

Open `http://127.0.0.1:8000/?start=2`. The initial counter is rendered over
HTTP; subsequent increments travel over `/_tori/live` and update only the
counter's dynamic fragment.

The hard-coded secret is for this local example only. Production deployments
must supply a strong shared secret from configuration.

## Browser E2E

Install Chromium once and run the explicit browser test:

```text
uv run playwright install chromium
uv run pytest examples/tori_py/liveview/browser_e2e.py
```

The test exercises the real vendored Opal client against a local ASGI server.
It verifies HTTP rendering, the WebSocket increment flow, structural DOM
updates, title changes, reconnect state, and browser console errors. The file is
named outside normal pytest discovery so browser installation remains an
explicit local gate rather than an implicit CI requirement.

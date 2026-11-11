# Testing LiveView

Test LiveView pages at three levels. Most behavior belongs in fast unit tests of
the page object; a few HTTP tests prove composition and the first render; a
small browser suite proves the real client works end to end.

| Level | Proves | Tools |
| --- | --- | --- |
| Page unit tests | Event handling, validation, state, rendered HTML | The page class, `MountContext`, `html()` |
| HTTP render tests | Module composition, DI, mount hooks, disconnected HTML | `TestingModule`, `http_client()` |
| Browser tests | Socket join, events, diffs, components, streams, reconnects | A real ASGI server and Playwright |

There is no public test client for the Phoenix Channels protocol. Drive the
connected behavior through the page's callbacks or a real browser rather than by
hand-writing socket frames.

## Page Unit Tests

A page is a plain class. Construct it with fakes, call its callbacks, and render:

```python
import pytest
from starlette.datastructures import QueryParams
from tori_py_liveview import MountContext, html


def mount_context(resource: str, *, connected: bool = False) -> MountContext:
    return MountContext(
        request=None,
        params={},
        resource=resource,
        connected=connected,
        query_params=QueryParams(resource.partition("?")[2]),
    )


@pytest.mark.asyncio
async def test_counter_starts_from_query_and_increments() -> None:
    page = CounterLive()
    await page.mount(mount_context("/counter?start=2"))

    await page.handle_event("increment", {})

    assert page.count == 3
    assert "<output>3</output>" in html(page.render()).to_html()
```

`html()` converts the template returned by `render()` into HTML exactly as the
framework escapes it. Use a real Starlette request in `MountContext` only when the
code under test reads headers or cookies.

Test form handlers with the decoded shape the framework passes:

```python
await page.handle_event("save", {"task": {"title": "  Write docs  "}})
assert page.error is None
```

`live_component()` works only while the framework renders a page, so render
pages that contain components through an HTTP test. `stream_contents()` works
in unit tests and returns the disconnected HTML of the queued items.

## HTTP Render Tests

Compile the production module graph with `TestingModule`, override providers as
needed, and request the page:

```python
import pytest
from tori_py.starlette import StarletteAdapter
from tori_py.testing import TestingModule


@pytest.mark.asyncio
async def test_tasks_page_renders_stored_tasks() -> None:
    builder = TestingModule.create(AppModule)
    builder.override_provider(TaskStore, module=StoreModule).use_value(
        FakeTaskStore(["Write docs"])
    )
    application = await builder.compile(adapter=StarletteAdapter())
    try:
        async with application.http_client() as client:
            response = await client.get("/tasks")
    finally:
        await application.close()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "<li>Write docs</li>" in response.text
    assert "data-phx-session=" in response.text
```

This covers page construction through DI, mount hooks, `mount()` and
`handle_params()` with `connected=False`, components, streams, and the
document. Redirects from mount appear as `302` responses with a `location`
header.

## Browser Tests

Browser tests run the official Phoenix clients against a real server, so they
catch problems no Python-level test can see: missing `id` attributes on stream
items, bindings the client rejects, focus loss, and reconnect behavior.

The LiveView example contains a complete harness in
[`examples/tori_py/liveview/browser_e2e.py`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/liveview/browser_e2e.py).
It starts Uvicorn on a free port in a background thread and drives the page with
`pytest-playwright`:

```python
from playwright.sync_api import Page, expect


def test_counter_increments(page: Page, liveview_url: str) -> None:
    page.goto(f"{liveview_url}/counter?start=2")
    expect(page.locator("[data-phx-session]")).to_have_class("phx-connected")

    page.get_by_role("button", name="+").click()

    expect(page.locator("output")).to_have_text("3")
```

Wait for the `phx-connected` class on the live root before clicking; until
then, the page is the disconnected HTTP render. Collect `console` and
`pageerror` events and assert there are none, since client-side failures do not
reach the server.

Install the browser once and run the example suite explicitly:

```text
uv run playwright install chromium
uv run pytest examples/tori_py/liveview/browser_e2e.py
```

The file name is outside normal pytest discovery so that browser installation
stays an explicit local or CI step.

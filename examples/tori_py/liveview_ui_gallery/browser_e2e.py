from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from playwright.sync_api import Page, expect
from tori_py_liveview_ui import SCRIPT_PATH, STYLESHEET_PATH

from examples.tori_py.liveview_ui_gallery.app import application


@pytest.fixture(scope="module")
def gallery_url() -> Iterator[str]:
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()
    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            lifespan="on",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        pytest.fail("gallery server did not start")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            pytest.fail("gallery server did not stop")


@pytest.fixture
def browser_errors(page: Page) -> Iterator[list[str]]:
    errors: list[str] = []
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield errors
    assert errors == []


def _connected(page: Page) -> None:
    expect(page.locator("[data-phx-session]")).to_have_class("phx-connected")


def test_document_loads_local_assets_and_connects(
    page: Page, gallery_url: str, browser_errors: list[str]
) -> None:
    page.goto(f"{gallery_url}/?skin=rounded")
    _connected(page)

    expect(page.locator(f'head link[href="{STYLESHEET_PATH}"]')).to_have_count(1)
    expect(page.locator(f'head script[src="{SCRIPT_PATH}"]')).to_have_count(1)
    expect(page.locator("html")).to_have_attribute("data-tori-ui-skin", "rounded")
    expect(page.locator("body")).to_have_class("tori-ui-document")
    assert page.evaluate("typeof globalThis.ToriLiveHooks") == "object"
    assert page.evaluate("globalThis.liveSocket.hooks === globalThis.ToriLiveHooks")

    page.get_by_role("button", name="Primary").click()
    expect(page.locator("#clicks")).to_have_text("1")


def test_stored_theme_is_applied_before_the_body_renders(
    page: Page, gallery_url: str, browser_errors: list[str]
) -> None:
    page.goto(f"{gallery_url}/?theme=light")
    expect(page.locator("html")).to_have_attribute("data-tori-ui-theme", "light")

    page.evaluate("localStorage.setItem('tori-ui-theme', 'dark')")
    # The observer sees the attribute the body's first element is parsed with.
    page.add_init_script(
        """
        new MutationObserver((_, observer) => {
          if (document.body) {
            window.__themeAtBody = document.documentElement.dataset.toriUiTheme;
            observer.disconnect();
          }
        }).observe(document, {childList: true, subtree: true});
        """
    )
    page.reload()

    expect(page.locator("html")).to_have_attribute("data-tori-ui-theme", "dark")
    assert page.evaluate("window.__themeAtBody") == "dark"

    page.evaluate("localStorage.setItem('tori-ui-theme', 'sepia')")
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-tori-ui-theme", "light")

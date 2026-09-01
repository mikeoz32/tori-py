from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from playwright.sync_api import Page, expect
from tori_py_liveview_ui import STYLESHEET_PATH

from examples.tori_py.liveview.app import application


@pytest.fixture(scope="module")
def liveview_url() -> Iterator[str]:
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
    thread = threading.Thread(
        target=server.run,
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        pytest.fail("LiveView example server did not start")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            pytest.fail("LiveView example server did not stop")


def test_counter_updates_and_recovers_after_reconnect(
    page: Page, liveview_url: str
) -> None:
    browser_errors: list[str] = []
    websocket_urls: list[str] = []
    page.on(
        "console",
        lambda message: (
            browser_errors.append(message.text) if message.type == "error" else None
        ),
    )
    page.on("pageerror", lambda error: browser_errors.append(str(error)))
    page.on("websocket", lambda websocket: websocket_urls.append(websocket.url))

    page.goto(f"{liveview_url}/?start=2")
    root = page.locator("[data-phx-session]")
    output = page.locator("output[data-page-counter]")
    increment = page.get_by_role("button", name="Increment page")
    left_output = page.locator('output[data-component-id="left"]')
    right_output = page.locator('output[data-component-id="right"]')
    increment_left = page.get_by_role("button", name="Increment Left")
    activity_one = page.locator("#activity-1")
    activity_one.evaluate("element => { window.__toriActivityOne = element; }")

    expect(root).to_have_class("phx-connected")
    expect(page.locator("html")).to_have_attribute("data-tori-ui-theme", "auto")
    expect(page.locator(f'link[href="{STYLESHEET_PATH}"]')).to_have_count(1)
    expect(increment).to_have_class(
        "tori-ui-button tori-ui-button--primary tori-ui-button--md"
    )
    expect(output).to_have_text("2")
    expect(left_output).to_have_text("0")
    expect(right_output).to_have_text("0")
    expect(page).to_have_title("Counter: 2")
    expect(page.locator("#activity-stream > li span")).to_have_text(
        ["Activity 1", "Activity 2"]
    )
    expect(activity_one).to_have_attribute("data-phx-stream", "activity-stream")
    assert page.evaluate("window.liveSocket.version()") == "1.2.11"
    assert any("/_tori/live/websocket?vsn=2.0.0" in url for url in websocket_urls)

    count_input = page.get_by_label("Set page count")
    count_input.fill("5")
    expect(output).to_have_text("5")
    expect(page).to_have_title("Counter: 5")
    count_input.fill("2")
    expect(output).to_have_text("2")

    increment.evaluate("element => element.setAttribute('phx-click', 'missing')")
    increment.click()
    expect(output).to_have_text("2")
    increment.evaluate("element => element.setAttribute('phx-click', 'increment')")
    increment.click()
    expect(output).to_have_text("3")

    prepend = page.get_by_role("button", name="Prepend activity")
    prepend.click()
    prepend.click()
    expect(page.locator("#activity-stream > li span")).to_have_text(
        ["Activity 4", "Activity 3", "Activity 1"]
    )
    expect(page.locator("#activity-2")).to_have_count(0)
    assert activity_one.evaluate("element => element === window.__toriActivityOne")

    page.get_by_role("button", name="Remove Activity 3").click()
    expect(page.locator("#activity-stream > li span")).to_have_text(
        ["Activity 4", "Activity 1"]
    )
    expect(page).to_have_title("Counter: 3")

    increment_left.click()
    expect(left_output).to_have_text("1")
    expect(right_output).to_have_text("0")
    expect(output).to_have_text("3")
    page.get_by_role("button", name="Clear title").click()
    expect(page).to_have_title("")

    root.evaluate(
        "() => window.liveSocket.getSocket().conn.close(4000, 'test reconnect')"
    )
    expect(output).to_have_text("3")
    expect(left_output).to_have_text("0")
    expect(right_output).to_have_text("0")
    expect(root).to_have_class("phx-connected")
    expect(page.locator("#activity-stream > li span")).to_have_text(
        ["Activity 1", "Activity 2"]
    )
    expect(page).to_have_title("Counter: 3")

    increment.click()
    expect(output).to_have_text("4")
    assert browser_errors == []

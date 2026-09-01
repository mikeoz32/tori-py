from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from playwright.sync_api import Page, expect

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
    page.on(
        "console",
        lambda message: (
            browser_errors.append(message.text) if message.type == "error" else None
        ),
    )
    page.on("pageerror", lambda error: browser_errors.append(str(error)))

    page.goto(f"{liveview_url}/?start=2")
    root = page.locator("[data-opal-live-root]")
    output = page.locator("output[data-page-counter]")
    increment = page.get_by_role("button", name="Increment page")
    left_output = page.locator('output[data-component-id="left"]')
    right_output = page.locator('output[data-component-id="right"]')
    increment_left = page.get_by_role("button", name="Increment Left")

    expect(root).to_have_attribute("data-opal-status", "connected")
    expect(output).to_have_text("2")
    expect(left_output).to_have_text("0")
    expect(right_output).to_have_text("0")
    expect(page).to_have_title("Counter: 2")

    increment.click()
    expect(output).to_have_text("3")
    expect(page).to_have_title("Counter: 3")

    increment_left.click()
    expect(left_output).to_have_text("1")
    expect(right_output).to_have_text("0")
    expect(output).to_have_text("3")

    root.evaluate("root => root.__opalLiveView.socket.close(4000, 'test reconnect')")
    expect(output).to_have_text("2")
    expect(left_output).to_have_text("0")
    expect(right_output).to_have_text("0")
    expect(root).to_have_attribute("data-opal-status", "connected")

    increment.click()
    expect(output).to_have_text("3")
    assert browser_errors == []

"""Browser test for the Live Task Board with the official Phoenix clients."""

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from playwright.sync_api import Page, expect

from .app import application
from .live import TITLE_ERROR


@pytest.fixture(scope="module")
def board_url() -> Iterator[str]:
    listener = socket.socket()
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
        pytest.fail("Task board server did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_board_updates_every_open_tab(page: Page, board_url: str) -> None:
    errors: list[str] = []
    other = page.context.new_page()
    for tab in (page, other):
        tab.on(
            "console",
            lambda message: (
                errors.append(message.text) if message.type == "error" else None
            ),
        )
        tab.on("pageerror", lambda error: errors.append(str(error)))
        tab.goto(f"{board_url}/board")
        expect(tab.locator("[data-phx-session]")).to_have_class("phx-connected")
        expect(tab).to_have_title("Task board (0)")

    title = page.get_by_label("Title")
    title.fill("   ")
    expect(page.locator("#task-title-error")).to_have_text(TITLE_ERROR)
    title.fill("Ship the board")
    expect(page.locator("#task-title-error")).to_have_count(0)
    title.press("Enter")

    for tab in (page, other):
        expect(tab.locator("#task-1")).to_contain_text("Ship the board")
        expect(tab).to_have_title("Task board (1)")
    expect(title).to_have_value("")

    response = page.request.post(f"{board_url}/tasks", data={"title": "From the API"})
    assert response.status == 201

    for tab in (page, other):
        expect(tab.locator("#task-2")).to_contain_text("From the API")
        expect(tab.locator("#tasks > li").first).to_have_id("task-2")
        expect(tab).to_have_title("Task board (2)")

    assert errors == []

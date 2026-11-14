from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from playwright.sync_api import BrowserContext, Page, expect
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


@pytest.fixture(autouse=True)
def browser_errors(page: Page) -> Iterator[list[str]]:
    """Fail any test whose page logs a console error or throws."""
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


def _open(page: Page, url: str) -> None:
    page.goto(url)
    expect(page.locator("[data-phx-session]")).to_have_class("phx-connected")


# ---------------------------------------------------------------- Document


def test_document_loads_local_assets_and_connects(page: Page, gallery_url: str) -> None:
    _open(page, f"{gallery_url}/?skin=rounded")

    expect(page.locator(f'head link[href="{STYLESHEET_PATH}"]')).to_have_count(1)
    expect(page.locator(f'head script[src="{SCRIPT_PATH}"]')).to_have_count(1)
    expect(page.locator("html")).to_have_attribute("data-tori-ui-skin", "rounded")
    expect(page.locator("body")).to_have_class("tori-ui-document")
    assert page.evaluate("globalThis.liveSocket.hooks === globalThis.ToriLiveHooks")

    page.get_by_role("button", name="Primary").click()
    expect(page.locator("#clicks")).to_have_text("1")


def test_application_and_package_hooks_both_register(
    page: Page, gallery_url: str
) -> None:
    # The gallery replaces globalThis.ToriLiveHooks from an inline body script,
    # after the package script has run.
    _open(page, f"{gallery_url}/")

    assert page.evaluate("Object.keys(globalThis.ToriLiveHooks).sort()") == [
        "GalleryClock",
        "ToriUiTheme",
    ]
    expect(page.locator("#clock")).not_to_be_empty()
    expect(
        page.locator('#gallery-theme [data-tori-ui-theme-value="auto"]')
    ).to_have_attribute("aria-pressed", "true")


def test_stored_theme_is_applied_before_the_body_renders(
    page: Page, gallery_url: str
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


# ----------------------------------------------------------------- Actions


def test_theme_toggle_applies_stores_and_marks_the_choice(
    page: Page, gallery_url: str
) -> None:
    _open(page, f"{gallery_url}/actions?theme=light")
    header_dark = page.locator('#gallery-theme [data-tori-ui-theme-value="dark"]')
    page_dark = page.locator('#actions-theme [data-tori-ui-theme-value="dark"]')
    page_light = page.locator('#actions-theme [data-tori-ui-theme-value="light"]')
    expect(page_light).to_have_attribute("aria-pressed", "true")

    page_dark.click()

    expect(page.locator("html")).to_have_attribute("data-tori-ui-theme", "dark")
    expect(page_dark).to_have_attribute("aria-pressed", "true")
    expect(page_light).to_have_attribute("aria-pressed", "false")
    # Every toggle on the page follows the one that was used.
    expect(header_dark).to_have_attribute("aria-pressed", "true")
    assert page.evaluate("localStorage.getItem('tori-ui-theme')") == "dark"

    # A server render leaves the browser-owned state alone.
    page.get_by_role("button", name="Add 1", exact=True).click()
    expect(page.locator("#total")).to_have_text("1")
    expect(page_dark).to_have_attribute("aria-pressed", "true")

    # The stored choice wins over the theme the server renders.
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-tori-ui-theme", "dark")
    expect(page_dark).to_have_attribute("aria-pressed", "true")


def test_event_values_and_pressed_state_reach_the_page(
    page: Page, gallery_url: str
) -> None:
    _open(page, f"{gallery_url}/actions")

    page.get_by_role("button", name="Add 10").click()
    page.get_by_role("button", name="Add 1", exact=True).click()
    expect(page.locator("#total")).to_have_text("11")

    favorite = page.get_by_role("button", name="Favorite")
    expect(favorite).to_have_attribute("aria-pressed", "false")
    favorite.click()
    expect(favorite).to_have_attribute("aria-pressed", "true")


def test_confirm_gates_the_click(page: Page, gallery_url: str) -> None:
    _open(page, f"{gallery_url}/actions")
    answers = [False, True]
    messages: list[str] = []

    def answer(dialog) -> None:
        messages.append(dialog.message)
        if answers.pop(0):
            dialog.accept()
        else:
            dialog.dismiss()

    page.on("dialog", answer)
    delete = page.get_by_role("button", name="Delete", exact=True).first

    delete.click()
    page.get_by_role("button", name="Add 1", exact=True).click()
    expect(page.locator("#total")).to_have_text("1")
    expect(page.locator("#deleted")).to_have_text("0")

    delete.click()
    expect(page.locator("#deleted")).to_have_text("1")
    assert messages == ["Delete the record?", "Delete the record?"]


def test_copy_button_copies_text_and_reports(
    page: Page, context: BrowserContext, gallery_url: str
) -> None:
    context.grant_permissions(["clipboard-read", "clipboard-write"])
    _open(page, f"{gallery_url}/actions")
    copy = page.get_by_role("button", name="Copy token")

    copy.click()

    expect(copy).to_have_attribute("data-tori-ui-copied", "")
    expect(copy.locator('[role="status"]')).to_have_text("Copied")
    expect(copy.locator(".tori-ui-copy-button__done")).to_be_visible()
    expect(copy.locator(".tori-ui-copy-button__idle")).to_be_hidden()
    assert page.evaluate("navigator.clipboard.readText()") == "tori-ui-0042"
    # The report clears itself.
    expect(copy).not_to_have_attribute("data-tori-ui-copied", "", timeout=4000)
    expect(copy.locator('[role="status"]')).to_be_empty()


def test_code_block_copies_its_own_code(
    page: Page, context: BrowserContext, gallery_url: str
) -> None:
    context.grant_permissions(["clipboard-read", "clipboard-write"])
    _open(page, f"{gallery_url}/content")
    block = page.locator(".tori-ui-code-block").first

    block.get_by_role("button", name="Copy").click()

    expect(block.locator(".tori-ui-copy-button")).to_have_attribute(
        "data-tori-ui-copied", ""
    )
    copied = page.evaluate("navigator.clipboard.readText()")
    assert copied.startswith('@live_view("/hello")')
    assert copied.rstrip().endswith('return container(heading("Hello", level=1))')


# ------------------------------------------------------------------ Layout


def test_app_shell_shows_the_sidebar_beside_the_content_on_wide_screens(
    page: Page, gallery_url: str
) -> None:
    page.set_viewport_size({"width": 1200, "height": 800})
    _open(page, f"{gallery_url}/")

    expect(page.locator("#gallery-sidebar")).to_be_visible()
    expect(page.locator(".tori-ui-app-shell__menu")).to_be_hidden()
    # The shell fills the viewport and only its main area scrolls.
    assert page.evaluate("document.documentElement.scrollHeight") == 800
    assert (
        page.evaluate(
            "getComputedStyle(document.querySelector('.tori-ui-app-shell__main')).overflowY"
        )
        == "auto"
    )


def test_app_shell_sidebar_opens_over_the_content_on_narrow_screens(
    page: Page, gallery_url: str
) -> None:
    page.set_viewport_size({"width": 480, "height": 800})
    _open(page, f"{gallery_url}/")
    sidebar = page.locator("#gallery-sidebar")
    menu = page.get_by_role("button", name="Menu")
    scrim = page.locator(".tori-ui-app-shell__scrim")
    expect(sidebar).to_be_hidden()
    expect(menu).to_have_attribute("aria-expanded", "false")

    menu.click()
    expect(sidebar).to_be_visible()
    expect(menu).to_have_attribute("aria-expanded", "true")

    # The browser keeps the open state across a server render.
    page.evaluate(
        "[...document.querySelectorAll('button')]"
        ".find((button) => button.textContent === 'Primary').click()"
    )
    expect(page.locator("#clicks")).to_have_text("1")
    expect(sidebar).to_be_visible()
    expect(menu).to_have_attribute("aria-expanded", "true")

    page.keyboard.press("Escape")
    expect(sidebar).to_be_hidden()
    expect(menu).to_have_attribute("aria-expanded", "false")

    menu.click()
    expect(sidebar).to_be_visible()
    scrim.click(position={"x": 440, "y": 400})
    expect(sidebar).to_be_hidden()


def test_live_navigation_keeps_the_document_and_closes_the_open_sidebar(
    page: Page, gallery_url: str
) -> None:
    page.set_viewport_size({"width": 480, "height": 800})
    _open(page, f"{gallery_url}/")
    page.evaluate("window.__sameDocument = true")
    page.get_by_role("button", name="Menu").click()
    sidebar = page.locator("#gallery-sidebar")
    expect(sidebar).to_be_visible()

    sidebar.get_by_role("link", name="Layout").click()

    expect(page).to_have_url(f"{gallery_url}/layout?theme=auto&skin=editorial")
    expect(page.get_by_role("heading", level=1)).to_have_text("Layout")
    assert page.evaluate("window.__sameDocument") is True
    expect(sidebar).to_be_hidden()
    expect(page.get_by_role("button", name="Menu")).to_have_attribute(
        "aria-expanded", "false"
    )

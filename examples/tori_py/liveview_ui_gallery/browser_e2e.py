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

    registered = page.evaluate("Object.keys(globalThis.ToriLiveHooks)")
    assert "GalleryClock" in registered
    assert "ToriUiTheme" in registered
    assert all(
        name.startswith("ToriUi") for name in registered if name != "GalleryClock"
    )
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


# ----------------------------------------------------------------- Display


def test_table_sorting_is_owned_by_the_page(page: Page, gallery_url: str) -> None:
    _open(page, f"{gallery_url}/display")
    customers = page.locator(".tori-ui-table--striped tbody tr td:first-child")
    customer_header = page.get_by_role("columnheader", name="Customer")
    total_header = page.get_by_role("columnheader", name="Total")
    expect(customers).to_have_text(["Ada Lovelace", "Edsger Dijkstra", "Grace Hopper"])
    expect(customer_header).to_have_attribute("aria-sort", "ascending")
    expect(total_header).to_have_attribute("aria-sort", "none")

    customer_header.get_by_role("button").click()
    expect(customers).to_have_text(["Grace Hopper", "Edsger Dijkstra", "Ada Lovelace"])
    expect(customer_header).to_have_attribute("aria-sort", "descending")

    total_header.get_by_role("button").click()
    expect(customers).to_have_text(["Edsger Dijkstra", "Grace Hopper", "Ada Lovelace"])
    expect(total_header).to_have_attribute("aria-sort", "ascending")
    expect(customer_header).to_have_attribute("aria-sort", "none")


def test_list_items_and_tags_push_their_values(page: Page, gallery_url: str) -> None:
    _open(page, f"{gallery_url}/display")
    starred = page.locator("#folder-starred")
    expect(page.locator("#folder-inbox")).to_have_class(
        "tori-ui-list-item tori-ui-list-item--selected"
    )

    starred.get_by_role("button").click()
    expect(starred).to_have_class("tori-ui-list-item tori-ui-list-item--selected")
    expect(starred.get_by_role("button")).to_have_attribute("aria-current", "true")
    expect(page.locator("#folder-inbox")).to_have_class("tori-ui-list-item")

    tags = page.locator(".tori-ui-tag--info .tori-ui-tag__label")
    expect(tags).to_have_text(["python", "liveview", "phoenix"])
    page.get_by_role("button", name="Remove liveview").click()
    expect(tags).to_have_text(["python", "phoenix"])

    page.get_by_role("button", name="Upload more").click()
    expect(page.get_by_role("progressbar", name="Upload")).to_have_attribute(
        "value", "50"
    )


def test_tooltip_opens_on_focus_and_escape_dismisses_it(
    page: Page, gallery_url: str
) -> None:
    _open(page, f"{gallery_url}/display")
    trigger = page.locator(".tori-ui-tooltip")
    bubble = page.get_by_role("tooltip")
    expect(bubble).to_be_hidden()

    trigger.focus()
    expect(bubble).to_be_visible()
    expect(bubble).to_have_text("Application programming interface")

    page.keyboard.press("Escape")
    expect(bubble).to_be_hidden()
    # It opens again once the focus has left and come back.
    page.get_by_role("button", name="Upload more").focus()
    trigger.focus()
    expect(bubble).to_be_visible()


# ---------------------------------------------------------------- Feedback


def test_alerts_are_dismissed_by_the_browser_or_by_the_page(
    page: Page, gallery_url: str
) -> None:
    _open(page, f"{gallery_url}/feedback")
    browser_alert = page.locator(".tori-ui-alert", has_text="Dismissible")
    page_alert = page.locator(".tori-ui-alert", has_text="Page-owned")

    browser_alert.get_by_role("button", name="Dismiss").click()
    expect(browser_alert).to_be_hidden()

    page_alert.get_by_role("button", name="Dismiss").click()
    expect(page_alert).to_have_count(0)
    expect(page.get_by_text("The page-owned alert is gone.")).to_be_visible()
    # The render that removed the second alert kept the first one hidden.
    expect(browser_alert).to_be_hidden()


def test_busy_region_is_inert_while_it_loads(page: Page, gallery_url: str) -> None:
    _open(page, f"{gallery_url}/feedback")
    region = page.locator(".tori-ui-busy")
    expect(region).to_have_attribute("aria-busy", "false")

    page.get_by_role("button", name="Toggle loading").click()
    expect(region).to_have_attribute("aria-busy", "true")
    expect(region.get_by_role("status")).to_have_text("Loading reports")
    assert region.locator(".tori-ui-busy__content").evaluate("el => el.inert")

    page.get_by_role("button", name="Toggle loading").click()
    expect(region).to_have_attribute("aria-busy", "false")
    assert not region.locator(".tori-ui-busy__content").evaluate("el => el.inert")


def test_toast_closes_itself_and_tells_the_page(page: Page, gallery_url: str) -> None:
    _open(page, f"{gallery_url}/feedback")
    opened = page.locator("#open-toasts")

    page.get_by_role("button", name="Notify").click()
    toast = page.locator("#toast-1")
    expect(toast).to_be_visible()
    expect(toast).to_contain_text("Message 1 delivered.")
    expect(opened).to_have_text("1")

    # While the pointer rests on it the countdown is paused.
    toast.hover()
    page.wait_for_timeout(2200)
    expect(toast).to_be_visible()

    page.get_by_role("heading", level=1).hover()
    expect(toast).to_have_count(0, timeout=4000)
    expect(opened).to_have_text("0")


def test_flash_group_shows_and_clears_flash(page: Page, gallery_url: str) -> None:
    _open(page, f"{gallery_url}/feedback")

    page.get_by_role("button", name="Flash error").click()
    error = page.locator("#gallery-flash-error")
    expect(error).to_have_text("A flash of kind error.")
    expect(error).to_have_attribute("role", "alert")

    error.get_by_role("button", name="Dismiss").click()
    expect(error).to_be_hidden()
    # The flash is cleared on the server, so the next render does not bring
    # it back.
    page.get_by_role("button", name="Toggle loading").click()
    expect(page.locator(".tori-ui-busy")).to_have_attribute("aria-busy", "true")
    expect(page.locator("#gallery-flash-error")).to_have_count(0)

    page.get_by_role("button", name="Flash info").click()
    info = page.locator("#gallery-flash-info")
    expect(info).to_have_text("A flash of kind info.")
    # Information closes itself.
    expect(page.locator("#gallery-flash-info")).to_have_count(0, timeout=8000)


def test_connection_status_shows_while_the_client_is_disconnected(
    page: Page, gallery_url: str
) -> None:
    _open(page, f"{gallery_url}/feedback")
    status = page.locator(".tori-ui-connection-status")
    expect(status).to_be_hidden()

    page.evaluate("globalThis.liveSocket.disconnect()")
    expect(status).to_be_visible()
    expect(status).to_have_text("Connection lost. Reconnecting.")

    page.evaluate("globalThis.liveSocket.connect()")
    expect(page.locator("[data-phx-session]")).to_have_class("phx-connected")
    expect(status).to_be_hidden()


# -------------------------------------------------------------- Disclosure


def test_collapsible_state_belongs_to_the_browser(page: Page, gallery_url: str) -> None:
    _open(page, f"{gallery_url}/disclosure")
    shipping = page.locator("#shipping")
    expect(shipping).not_to_have_attribute("open", "")

    shipping.locator("summary").click()
    expect(shipping).to_have_attribute("open", "")
    page.get_by_role("button", name="Render again").click()
    expect(page.locator("#renders")).to_have_text("1")
    expect(shipping).to_have_attribute("open", "")

    # Sections in one group close each other.
    expect(page.locator("#track")).to_have_attribute("open", "")
    page.locator("#pay summary").click()
    expect(page.locator("#pay")).to_have_attribute("open", "")
    expect(page.locator("#track")).not_to_have_attribute("open", "")
    page.get_by_role("button", name="Render again").click()
    expect(page.locator("#renders")).to_have_text("2")
    expect(page.locator("#pay")).to_have_attribute("open", "")
    expect(page.locator("#track")).not_to_have_attribute("open", "")


def test_browser_tabs_switch_without_the_page_and_follow_the_keyboard(
    page: Page, gallery_url: str
) -> None:
    _open(page, f"{gallery_url}/disclosure")
    profile = page.get_by_role("tab", name="Profile")
    security = page.get_by_role("tab", name="Security")
    billing = page.get_by_role("tab", name="Billing")
    expect(profile).to_have_attribute("aria-selected", "true")
    expect(page.locator("#settings-panel-profile")).to_be_visible()
    expect(page.locator("#settings-panel-security")).to_be_hidden()

    security.click()
    expect(security).to_have_attribute("aria-selected", "true")
    expect(security).to_have_attribute("tabindex", "0")
    expect(profile).to_have_attribute("aria-selected", "false")
    expect(profile).to_have_attribute("tabindex", "-1")
    expect(page.locator("#settings-panel-security")).to_be_visible()
    expect(page.locator("#settings-panel-profile")).to_be_hidden()

    page.keyboard.press("ArrowRight")
    expect(billing).to_be_focused()
    expect(billing).to_have_attribute("aria-selected", "true")
    expect(page.locator("#settings-panel-billing")).to_be_visible()
    page.keyboard.press("ArrowRight")
    expect(profile).to_be_focused()
    page.keyboard.press("End")
    expect(billing).to_be_focused()
    page.keyboard.press("Home")
    expect(profile).to_have_attribute("aria-selected", "true")

    # A server render keeps the tab the visitor chose.
    billing.click()
    page.get_by_role("button", name="Render again").click()
    expect(page.locator("#renders")).to_have_text("1")
    expect(billing).to_have_attribute("aria-selected", "true")
    expect(page.locator("#settings-panel-billing")).to_be_visible()
    expect(page.locator("#settings-panel-profile")).to_be_hidden()


def test_page_tabs_render_only_the_panel_the_page_chose(
    page: Page, gallery_url: str
) -> None:
    _open(page, f"{gallery_url}/disclosure")
    weekly = page.get_by_role("tab", name="Weekly")
    panels = page.locator("#reports [role=tabpanel]")
    expect(panels).to_have_count(1)
    expect(panels).to_have_text("Daily: 42 orders.")

    weekly.click()
    expect(weekly).to_have_attribute("aria-selected", "true")
    expect(panels).to_have_count(1)
    expect(panels).to_have_text("Weekly: 310 orders.")
    expect(panels).to_have_attribute("aria-labelledby", "reports-tab-weekly")

    weekly.focus()
    page.keyboard.press("ArrowRight")
    expect(panels).to_have_text("Monthly: 1,280 orders.")

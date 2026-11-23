"""Presentation contracts exercised through the official Phoenix client."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from playwright.sync_api import Page, expect
from tori_py import NestApplication, module
from tori_py.starlette import StarletteAdapter, asgi
from tori_py_liveview import JS, LiveViewModule, LiveViewOptions, fragment, live_view
from tori_py_liveview_ui import (
    LiveViewUiModule,
    Skin,
    Theme,
    UiLiveView,
    artifact_panel,
    badge,
    button,
    card,
    chat_message,
    code_block,
    confirm_dialog,
    markdown,
    message_actions,
    modal,
    open_overlay,
    stack,
    themed,
    toast,
    toast_region,
)

pytestmark = pytest.mark.browser


@live_view("/regressions")
class RegressionLive(UiLiveView):
    def render(self):
        answer = markdown("Answer\n\n```python\nfirst()\n```\n\nEnd.")
        artifact = markdown(
            "Introduction\n\n```python\nfirst()\n```\n\n"
            "Explanation\n\n```python\nsecond()\n```"
        )
        palettes = fragment(
            themed(
                card(
                    fragment(
                        badge(tone, tone=tone)
                        for tone in ("info", "success", "warning", "danger")
                    )
                ),
                theme=theme,
                mode=mode,
                skin=Skin.MINIMAL,
            )
            for theme in (Theme.PAPER, Theme.SLATE, Theme.CONTRAST)
            for mode in ("light", "dark")
        )
        return stack(
            [
                button("Open parent", event=open_overlay("parent")),
                modal(
                    stack(
                        [
                            button("Open confirmation", event=open_overlay("child")),
                            code_block("nested()"),
                            confirm_dialog(
                                "Child body",
                                title="Confirm",
                                id="child",
                                confirm_event=JS(),
                            ),
                        ]
                    ),
                    id="parent",
                    title="Parent",
                ),
                chat_message(answer, id="answer", actions=message_actions([])),
                chat_message(
                    "Displayed text",
                    id="exact",
                    copy_text="Original\n\n```py\nfirst()\n```",
                    actions=message_actions([]),
                ),
                artifact_panel(artifact, id="artifact", title="Artifact"),
                toast_region([toast("Notice", id="notice", duration=600000)]),
                button("Outside"),
                palettes,
            ]
        )


@pytest.fixture(scope="module")
def regression_url() -> Iterator[str]:
    @module(
        imports=[
            LiveViewModule.for_root(
                LiveViewOptions(secret="r" * 32), pages=[RegressionLive]
            ),
            LiveViewUiModule.for_root(),
        ]
    )
    class Root:
        pass

    async def create() -> NestApplication:
        return await NestApplication.create(Root, adapter=StarletteAdapter())

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()
    server = uvicorn.Server(
        uvicorn.Config(
            asgi(create),
            host="127.0.0.1",
            port=port,
            log_level="warning",
            timeout_graceful_shutdown=3,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        assert server.started
        yield f"http://127.0.0.1:{port}/regressions"
    finally:
        server.should_exit = True
        thread.join(timeout=45)
        assert not thread.is_alive()


@pytest.fixture
def regression_page(page: Page, regression_url: str) -> Page:
    page.goto(regression_url)
    expect(page.locator("[data-phx-session]")).to_have_class("phx-connected")
    return page


@pytest.mark.parametrize("action", ["Cancel", "Confirm"])
def test_closing_a_nested_dialog_keeps_its_parent_open(
    regression_page: Page, action: str
) -> None:
    page = regression_page
    page.get_by_role("button", name="Open parent", exact=True).click()
    page.get_by_role("button", name="Open confirmation", exact=True).click()
    expect(page.locator("#child")).to_be_visible()
    page.locator("#child").get_by_role("button", name=action, exact=True).click()
    expect(page.locator("#child")).not_to_be_visible()
    expect(page.locator("#parent")).to_be_visible()


@pytest.mark.parametrize("target", ["answer", "artifact", "exact"])
def test_copy_uses_the_whole_content_without_its_controls(
    regression_page: Page, target: str
) -> None:
    page = regression_page
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    copy = page.locator(
        f"#{target} > .tori-ui-chat-message__main > .tori-ui-message-actions "
        ".tori-ui-copy-button"
        if target != "artifact"
        else "#artifact .tori-ui-artifact__actions .tori-ui-copy-button"
    )
    copy.click()
    expect(copy).to_have_attribute("data-tori-ui-copied", "")
    text = page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n")
    if target == "exact":
        assert text == "Original\n\n```py\nfirst()\n```"
    else:
        assert "first()" in text
        assert "Copy" not in text and "PYTHON" not in text and "python" not in text
        if target == "artifact":
            assert (
                "Introduction" in text and "Explanation" in text and "second()" in text
            )
        else:
            assert "Answer" in text and "End." in text


def test_clipboard_fallback_works_inside_a_modal(regression_page: Page) -> None:
    page = regression_page
    page.evaluate("""() => {
      Object.defineProperty(navigator, 'clipboard', {value: undefined});
      window.copiedSelection = null;
      document.addEventListener('copy', () => {
        window.copiedSelection = document.activeElement.value;
      });
    }""")
    page.get_by_role("button", name="Open parent", exact=True).click()
    copy = page.locator("#parent .tori-ui-code-block .tori-ui-copy-button")
    copy.click()
    expect(copy).to_have_attribute("data-tori-ui-copied", "")
    expect(copy).to_be_focused()
    assert page.evaluate("window.copiedSelection") == "nested()"


def test_toast_waits_until_both_hover_and_focus_leave(regression_page: Page) -> None:
    page = regression_page
    page.clock.install()
    notice = page.locator("#notice")
    dismiss = notice.get_by_role("button", name="Dismiss")
    notice.hover()
    dismiss.focus()
    page.mouse.move(0, 0)
    page.clock.fast_forward(600001)
    expect(notice).to_be_visible()
    notice.hover()
    page.get_by_role("button", name="Outside", exact=True).focus()
    page.clock.fast_forward(600001)
    expect(notice).to_be_visible()
    page.mouse.move(0, 0)
    page.clock.fast_forward(600001)
    expect(notice).not_to_be_visible()


def test_rendered_badge_text_meets_the_palette_contrast_contract(
    regression_page: Page,
) -> None:
    ratios = regression_page.locator(".tori-ui-badge").evaluate_all("""badges => {
      const ctx = document.createElement('canvas').getContext('2d');
      const rgb = color => {
        ctx.fillStyle = color;
        ctx.fillRect(0, 0, 1, 1);
        return [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3).map(c => c/255);
      };
      const luminance = rgb => rgb
        .map(c => c <= .04045 ? c/12.92 : ((c+.055)/1.055)**2.4)
        .reduce((value, channel, index) =>
          value + channel * [.2126, .7152, .0722][index], 0);
      return badges.map(badge => {
        const fg=luminance(rgb(getComputedStyle(badge).color));
        const background = getComputedStyle(badge.closest('.tori-ui-card'));
        const bg=luminance(rgb(background.backgroundColor));
        return (Math.max(fg,bg)+.05)/(Math.min(fg,bg)+.05);
      });
    }""")
    assert len(ratios) == 24
    assert min(ratios) >= 4.5

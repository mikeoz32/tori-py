from __future__ import annotations

import re
import socket
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any, cast
from uuid import uuid4

import pytest
import uvicorn
from playwright.sync_api import Locator, Page, expect
from pytest_bdd import given, parsers, scenarios, then, when
from tori_py_liveview_kit import create_app
from tori_py_liveview_ui import SCRIPT_PATH, STYLESHEET_PATH

from examples.tori_py.liveview_kit.app import (
    AssistantLive,
    ConversationStore,
    ScriptedModel,
)

scenarios("features")

_LIVE_ROOT = "[data-phx-session]"
_CHAT_LOG = "#chat-messages-scroller"

# ------------------------------------------------------------------ Targets
#
# A step names an element by its role and accessible name, by a Playwright
# selector in quotes, or by either inside another one:
#
#     the "Send" button
#     the alert in "#turn-1-assistant"
#     the first ".tori-ui-code-block" in "#turn-1-assistant"

_ROLES = ("alert", "button", "textbox")
_ORDINALS = {"first": 0, "second": 1, "third": 2}
_ROLE = "|".join(sorted(_ROLES, key=len, reverse=True))
_ORDINAL = "|".join(_ORDINALS)
_ITEM = (
    rf'(?:the (?:(?:{_ORDINAL}) )?(?:"[^"]*" )?(?:{_ROLE})\b'
    rf'|(?:the (?:{_ORDINAL}) )?"[^"]*")'
)
_TARGET = rf"(?P<target>{_ITEM}(?: in {_ITEM})*)"
_ITEM_PARTS = re.compile(
    rf'the (?:(?P<ordinal>{_ORDINAL}) )?(?:"(?P<name>[^"]*)" )?(?P<role>{_ROLE})\b'
    rf'|(?:the (?P<nth>{_ORDINAL}) )?"(?P<selector>[^"]*)"'
)
_WITHIN = r"(?: within (?P<seconds>\d+) seconds)?"


def _locate(page: Page, target: str) -> Locator:
    scope: Page | Locator = page
    for item in reversed(list(_ITEM_PARTS.finditer(target))):
        selector = item["selector"]
        if selector is not None:
            found = scope.locator(selector)
            ordinal = item["nth"]
        elif item["name"] is not None:
            found = scope.get_by_role(
                cast(Any, item["role"]), name=item["name"], exact=True
            )
            ordinal = item["ordinal"]
        else:
            found = scope.get_by_role(cast(Any, item["role"]))
            ordinal = item["ordinal"]
        scope = found if ordinal is None else found.nth(_ORDINALS[ordinal])
    assert isinstance(scope, Locator), f"no element named in {target!r}"
    return scope


def _timeout(seconds: str | None) -> float | None:
    return None if seconds is None else int(seconds) * 1000


def _text(text: str) -> str:
    # A step is one line, so it spells a line break as a backslash and an n.
    return text.replace("\\n", "\n")


# ----------------------------------------------------------------- Fixtures


@pytest.fixture(scope="module")
def chat_url() -> Iterator[str]:
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(AssistantLive, providers=(ScriptedModel, ConversationStore)),
            host="127.0.0.1",
            port=port,
            log_level="warning",
            lifespan="on",
            # A browser that drops a socket without a close frame must not
            # keep the server waiting for that connection forever.
            timeout_graceful_shutdown=3,
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
        pytest.fail("chat server did not start")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        # The application may still wait for a dropped page until its own
        # shutdown timeout.
        thread.join(timeout=45)
        if thread.is_alive():
            pytest.fail("chat server did not stop")


@pytest.fixture
def browser_errors(page: Page) -> Iterator[list[str]]:
    """Fail a scenario whose page logs a console error or throws."""
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


@pytest.fixture
def conversation_url(chat_url: str) -> str:
    """A conversation of its own, so scenarios do not see each other's."""
    return f"{chat_url}/?conversation={uuid4().hex}"


def _open(page: Page, url: str) -> None:
    page.goto(url)
    expect(page.locator(_LIVE_ROOT)).to_have_class("phx-connected")


# -------------------------------------------------------------------- Given


@given(parsers.re(r"the viewport is (?P<width>\d+) by (?P<height>\d+)"))
def viewport(page: Page, width: str, height: str) -> None:
    page.set_viewport_size({"width": int(width), "height": int(height)})


@given("I open a new conversation")
def open_conversation(
    page: Page, conversation_url: str, browser_errors: list[str]
) -> None:
    del browser_errors  # Watch the console before the page loads.
    _open(page, conversation_url)


# --------------------------------------------------------------------- When


@when(parsers.re(rf"I click {_TARGET}"))
def click(page: Page, target: str) -> None:
    _locate(page, target).click()


@when(parsers.re(rf'I press "(?P<key>[^"]*)" on {_TARGET}'))
def press_on(page: Page, key: str, target: str) -> None:
    _locate(page, target).press(key)


@when(parsers.re(rf'I fill {_TARGET} with "(?P<text>[^"]*)"'))
def fill(page: Page, target: str, text: str) -> None:
    _locate(page, target).fill(_text(text))


@when(parsers.re(rf'I type "(?P<text>[^"]*)" into {_TARGET}'))
def type_into(page: Page, text: str, target: str) -> None:
    _locate(page, target).press_sequentially(text)


@when("I open the conversation again")
def open_again(page: Page, conversation_url: str) -> None:
    _open(page, conversation_url)


@when("the connection drops and the client rejoins")
def connection_drops(page: Page) -> None:
    root = page.locator(_LIVE_ROOT)
    # The official client reconnects by itself after an abnormal close.
    root.evaluate("() => window.liveSocket.getSocket().conn.close(4000, 'test')")
    expect(root).not_to_have_class("phx-connected")
    expect(root).to_have_class("phx-connected", timeout=15000)


# --------------------------------------------------------------------- Then


def _open_state(locator: Locator, timeout: float | None) -> None:
    expect(locator).to_have_attribute("open", "", timeout=timeout)


_STATES: dict[str, Callable[[Locator, float | None], None]] = {
    "visible": lambda locator, timeout: expect(locator).to_be_visible(timeout=timeout),
    "gone": lambda locator, timeout: expect(locator).to_have_count(0, timeout=timeout),
    "enabled": lambda locator, timeout: expect(locator).to_be_enabled(timeout=timeout),
    "open": _open_state,
}
_STATE = "|".join(sorted(_STATES, key=len, reverse=True))


@then(parsers.re(rf"{_TARGET} is (?P<state>{_STATE}){_WITHIN}"))
def is_in_state(page: Page, target: str, state: str, seconds: str | None) -> None:
    _STATES[state](_locate(page, target), _timeout(seconds))


@then(parsers.re(rf'{_TARGET} shows "(?P<text>[^"]*)"'))
def shows(page: Page, target: str, text: str) -> None:
    expect(_locate(page, target)).to_have_text(_text(text))


@then(parsers.re(rf'{_TARGET} contains "(?P<text>[^"]*)"'))
def contains(page: Page, target: str, text: str) -> None:
    expect(_locate(page, target)).to_contain_text(text)


@then(parsers.re(rf'{_TARGET} does not contain "(?P<text>[^"]*)"'))
def lacks_text(page: Page, target: str, text: str) -> None:
    expect(_locate(page, target)).not_to_contain_text(text)


@then(parsers.re(rf"{_TARGET} appears (?P<count>\d+) times?{_WITHIN}"))
def appears(page: Page, target: str, count: str, seconds: str | None) -> None:
    expect(_locate(page, target)).to_have_count(int(count), timeout=_timeout(seconds))


@then(
    parsers.re(rf'{_TARGET} does not have "(?P<name>[^"]*)" set to "(?P<value>[^"]*)"')
)
def lacks_attribute(page: Page, target: str, name: str, value: str) -> None:
    expect(_locate(page, target)).not_to_have_attribute(name, value)


@then(parsers.re(rf'{_TARGET} has the value "(?P<value>[^"]*)"'))
def has_value(page: Page, target: str, value: str) -> None:
    expect(_locate(page, target)).to_have_value(_text(value))


@then(parsers.re(r'the page title is "(?P<title>[^"]*)"'))
def title_is(page: Page, title: str) -> None:
    expect(page).to_have_title(title)


@then("the document loads the UI stylesheet and script once")
def loads_ui_assets(page: Page) -> None:
    expect(page.locator(f'head link[href="{STYLESHEET_PATH}"]')).to_have_count(1)
    expect(page.locator(f'head script[src="{SCRIPT_PATH}"]')).to_have_count(1)


@then("the chat log is at its end")
def chat_log_at_end(page: Page) -> None:
    assert page.locator(_CHAT_LOG).evaluate(
        "log => log.scrollHeight - log.scrollTop - log.clientHeight < 4"
    )

from __future__ import annotations

import re
import socket
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest
import uvicorn
from playwright.sync_api import BrowserContext, Dialog, Locator, Page, expect
from playwright.sync_api import Error as PlaywrightError
from pytest_bdd import given, parsers, scenarios, then, when
from tori_py_liveview_ui import SCRIPT_PATH, STYLESHEET_PATH

from examples.tori_py.liveview_ui_gallery.app import application
from examples.tori_py.liveview_ui_gallery.looks import SKINS, THEMES
from examples.tori_py.liveview_ui_gallery.shell import SECTIONS

_FEATURES = Path(__file__).parent / "features"

scenarios("features")

_PAGES = [path for path, _ in SECTIONS]
_LIVE_ROOT = "[data-phx-session]"
_CHAT_LOG = "#messages-scroller"

# ------------------------------------------------------------------ Targets
#
# A step names an element by its role and accessible name, by a Playwright
# selector in quotes, or by either inside another one:
#
#     the "Save" button
#     the second listitem in the "Progress" list
#     ".tori-ui-copy-button" in the first ".tori-ui-code-block"

_ROLES = (
    "alertdialog",
    "button",
    "checkbox",
    "columnheader",
    "combobox",
    "dialog",
    "group",
    "link",
    "list",
    "listbox",
    "listitem",
    "menu",
    "menuitem",
    "navigation",
    "progressbar",
    "radio",
    "radiogroup",
    "searchbox",
    "slider",
    "spinbutton",
    "status",
    "switch",
    "tab",
    "table",
    "textbox",
    "tooltip",
)
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
_QUOTED = re.compile(r'"([^"]*)"')


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


def _eventually(
    page: Page, check: Callable[[], bool], problem: Callable[[], str]
) -> None:
    deadline = time.monotonic() + 5
    while not check():
        if time.monotonic() >= deadline:
            raise AssertionError(problem())
        page.wait_for_timeout(50)


# ----------------------------------------------------------------- Fixtures


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
        pytest.fail("gallery server did not start")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        # The application may still wait for a dropped page until its own
        # shutdown timeout.
        thread.join(timeout=45)
        if thread.is_alive():
            pytest.fail("gallery server did not stop")


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
def confirmations() -> list[str]:
    """The messages of the native confirmations a scenario answered."""
    return []


def _open(page: Page, url: str) -> None:
    page.goto(url)
    expect(page.locator(_LIVE_ROOT)).to_have_class("phx-connected")
    # A new document starts without the mark, so a reload is visible later.
    page.evaluate("window.__toriUiSameDocument = true")


def test_audit_examples_name_every_gallery_page() -> None:
    feature = (_FEATURES / "document.feature").read_text(encoding="utf-8")

    rows = re.findall(r"^\s*\|\s*(/\S*)\s*\|\s*$", feature, flags=re.MULTILINE)

    assert rows == _PAGES


# -------------------------------------------------------------------- Given


@given(parsers.re(r"the viewport is (?P<width>\d+) by (?P<height>\d+)"))
def viewport(page: Page, width: str, height: str) -> None:
    page.set_viewport_size({"width": int(width), "height": int(height)})


@given(parsers.re(r"the browser prefers a (?P<scheme>light|dark) color scheme"))
def prefers_color_scheme(page: Page, scheme: str) -> None:
    page.emulate_media(color_scheme=cast(Any, scheme))


@given("the clipboard is available")
def clipboard_available(context: BrowserContext) -> None:
    context.grant_permissions(["clipboard-read", "clipboard-write"])


@given(parsers.re(r'I open the gallery page "(?P<path>[^"]*)"'))
def open_gallery_page(
    page: Page, gallery_url: str, browser_errors: list[str], path: str
) -> None:
    del browser_errors  # Watch the console before the page loads.
    _open(page, f"{gallery_url}{path}")


@given("confirmations will be dismissed and then accepted")
def plan_confirmations(page: Page, confirmations: list[str]) -> None:
    answers = [False, True]

    def answer(dialog: Dialog) -> None:
        confirmations.append(dialog.message)
        if answers.pop(0):
            dialog.accept()
        else:
            dialog.dismiss()

    page.on("dialog", answer)


# --------------------------------------------------------------------- When


@when(parsers.re(rf"I click {_TARGET}"))
def click(page: Page, target: str) -> None:
    _locate(page, target).click()


@when(parsers.re(rf"I click {_TARGET} at (?P<x>\d+), (?P<y>\d+)"))
def click_at(page: Page, target: str, x: str, y: str) -> None:
    _locate(page, target).click(position={"x": int(x), "y": int(y)})


@when(parsers.re(r"I click the page at (?P<x>\d+), (?P<y>\d+)"))
def click_page_at(page: Page, x: str, y: str) -> None:
    page.mouse.click(int(x), int(y))


@when(parsers.re(rf"a script clicks {_TARGET}"))
def script_clicks(page: Page, target: str) -> None:
    _locate(page, target).evaluate("element => element.click()")


@when(parsers.re(r'I press "(?P<key>[^"]*)"'))
def press(page: Page, key: str) -> None:
    page.keyboard.press(key)


@when(parsers.re(rf'I press "(?P<key>[^"]*)" on {_TARGET}'))
def press_on(page: Page, key: str, target: str) -> None:
    _locate(page, target).press(key)


@when(parsers.re(rf"I focus {_TARGET}"))
def focus(page: Page, target: str) -> None:
    _locate(page, target).focus()


@when(parsers.re(rf"I hover {_TARGET}"))
def hover(page: Page, target: str) -> None:
    _locate(page, target).hover()


@when(parsers.re(rf'I fill {_TARGET} with "(?P<text>[^"]*)"'))
def fill(page: Page, target: str, text: str) -> None:
    _locate(page, target).fill(_text(text))


@when(parsers.re(rf'I type "(?P<text>[^"]*)" into {_TARGET}'))
def type_into(page: Page, text: str, target: str) -> None:
    _locate(page, target).press_sequentially(text)


@when(parsers.re(rf"I check {_TARGET}"))
def check(page: Page, target: str) -> None:
    _locate(page, target).check()


@when(parsers.re(rf"I uncheck {_TARGET}"))
def uncheck(page: Page, target: str) -> None:
    _locate(page, target).uncheck()


@when(parsers.re(rf'I select (?P<options>"[^"]*"(?: and "[^"]*")*) in {_TARGET}'))
def select(page: Page, options: str, target: str) -> None:
    _locate(page, target).select_option(_QUOTED.findall(options))


@when(parsers.re(r"(?P<milliseconds>\d+) milliseconds pass"))
def time_passes(page: Page, milliseconds: str) -> None:
    page.wait_for_timeout(int(milliseconds))


@when("I reload the page")
def reload(page: Page) -> None:
    page.reload()


@when("I reload the page watching the mode the body starts with")
def reload_watching_mode(page: Page) -> None:
    # The observer sees the attribute the body's first element is parsed with.
    page.add_init_script(
        """
        new MutationObserver((_, observer) => {
          if (document.body) {
            window.__modeAtBody = document.documentElement.dataset.toriUiMode;
            observer.disconnect();
          }
        }).observe(document, {childList: true, subtree: true});
        """
    )
    page.reload()


@when(parsers.re(r'the browser stores the mode "(?P<mode>[^"]*)"'))
def store_mode(page: Page, mode: str) -> None:
    page.evaluate("mode => localStorage.setItem('tori-ui-mode', mode)", mode)


@when("the client disconnects")
def client_disconnects(page: Page) -> None:
    page.evaluate("globalThis.liveSocket.disconnect()")


@when("the client connects again")
def client_connects(page: Page) -> None:
    page.evaluate("globalThis.liveSocket.connect()")
    expect(page.locator(_LIVE_ROOT)).to_have_class("phx-connected")


@when("I scroll the chat log to its start")
def scroll_chat_log(page: Page) -> None:
    page.locator(_CHAT_LOG).evaluate("log => { log.scrollTop = 0; }")


# ------------------------------------------------------- Then: one element


def _aria(name: str, value: str) -> Callable[[Locator, float | None], None]:
    def check(locator: Locator, timeout: float | None) -> None:
        expect(locator).to_have_attribute(name, value, timeout=timeout)

    return check


def _open_state(locator: Locator, timeout: float | None) -> None:
    expect(locator).to_have_attribute("open", "", timeout=timeout)


def _not_open_state(locator: Locator, timeout: float | None) -> None:
    expect(locator).not_to_have_attribute("open", "", timeout=timeout)


def _modal_state(locator: Locator, timeout: float | None) -> None:
    del timeout
    assert locator.evaluate("element => element.matches(':modal')")


_STATES: dict[str, Callable[[Locator, float | None], None]] = {
    "visible": lambda locator, timeout: expect(locator).to_be_visible(timeout=timeout),
    "hidden": lambda locator, timeout: expect(locator).to_be_hidden(timeout=timeout),
    "gone": lambda locator, timeout: expect(locator).to_have_count(0, timeout=timeout),
    "focused": lambda locator, timeout: expect(locator).to_be_focused(timeout=timeout),
    "enabled": lambda locator, timeout: expect(locator).to_be_enabled(timeout=timeout),
    "disabled": lambda locator, timeout: expect(locator).to_be_disabled(
        timeout=timeout
    ),
    "checked": lambda locator, timeout: expect(locator).to_be_checked(timeout=timeout),
    "not checked": lambda locator, timeout: expect(locator).not_to_be_checked(
        timeout=timeout
    ),
    "empty": lambda locator, timeout: expect(locator).to_be_empty(timeout=timeout),
    "not empty": lambda locator, timeout: expect(locator).not_to_be_empty(
        timeout=timeout
    ),
    "in the viewport": lambda locator, timeout: expect(locator).to_be_in_viewport(
        timeout=timeout
    ),
    "not in the viewport": lambda locator, timeout: expect(
        locator
    ).not_to_be_in_viewport(timeout=timeout),
    "inert": lambda locator, timeout: expect(locator).to_have_js_property(
        "inert", True, timeout=timeout
    ),
    "not inert": lambda locator, timeout: expect(locator).to_have_js_property(
        "inert", False, timeout=timeout
    ),
    "open": _open_state,
    "not open": _not_open_state,
    "modal": _modal_state,
    "selected": _aria("aria-selected", "true"),
    "not selected": _aria("aria-selected", "false"),
    "pressed": _aria("aria-pressed", "true"),
    "not pressed": _aria("aria-pressed", "false"),
    "expanded": _aria("aria-expanded", "true"),
    "collapsed": _aria("aria-expanded", "false"),
}
_STATE = "|".join(sorted(_STATES, key=len, reverse=True))


@then(parsers.re(rf"{_TARGET} is (?P<state>{_STATE}){_WITHIN}"))
def is_in_state(page: Page, target: str, state: str, seconds: str | None) -> None:
    _STATES[state](_locate(page, target), _timeout(seconds))


@then(parsers.re(rf'{_TARGET} shows "(?P<text>[^"]*)"'))
def shows(page: Page, target: str, text: str) -> None:
    expect(_locate(page, target)).to_have_text(_text(text))


@then(parsers.re(rf"{_TARGET} shows:"))
def shows_block(page: Page, target: str, docstring: str) -> None:
    expect(_locate(page, target)).to_have_text(docstring)


@then(parsers.re(rf'{_TARGET} contains "(?P<text>[^"]*)"'))
def contains(page: Page, target: str, text: str) -> None:
    expect(_locate(page, target)).to_contain_text(text)


@then(parsers.re(rf'{_TARGET} show (?P<texts>"[^"]*"(?:, "[^"]*")*)'))
def show_each(page: Page, target: str, texts: str) -> None:
    expect(_locate(page, target)).to_have_text(_QUOTED.findall(texts))


@then(parsers.re(rf"{_TARGET} appears (?P<count>\d+) times?{_WITHIN}"))
def appears(page: Page, target: str, count: str, seconds: str | None) -> None:
    expect(_locate(page, target)).to_have_count(int(count), timeout=_timeout(seconds))


@then(parsers.re(rf'{_TARGET} has "(?P<name>[^"]*)" set to "(?P<value>[^"]*)"'))
def has_attribute(page: Page, target: str, name: str, value: str) -> None:
    expect(_locate(page, target)).to_have_attribute(name, value)


@then(
    parsers.re(
        rf'{_TARGET} does not have "(?P<name>[^"]*)" set to "(?P<value>[^"]*)"'
        rf"{_WITHIN}"
    )
)
def lacks_attribute(
    page: Page, target: str, name: str, value: str, seconds: str | None
) -> None:
    expect(_locate(page, target)).not_to_have_attribute(
        name, value, timeout=_timeout(seconds)
    )


@then(parsers.re(rf'{_TARGET} has class "(?P<classes>[^"]*)"'))
def has_class(page: Page, target: str, classes: str) -> None:
    expect(_locate(page, target)).to_have_class(classes)


@then(parsers.re(rf'{_TARGET} has the value "(?P<value>[^"]*)"'))
def has_value(page: Page, target: str, value: str) -> None:
    expect(_locate(page, target)).to_have_value(_text(value))


@then(
    parsers.re(rf'{_TARGET} has the style "(?P<name>[^"]*)" set to "(?P<value>[^"]*)"')
)
def has_style(page: Page, target: str, name: str, value: str) -> None:
    expect(_locate(page, target)).to_have_css(name, value)


# ------------------------------------------------------ Then: the document


@then(parsers.re(r'the URL is "(?P<path>[^"]*)"'))
def url_is(page: Page, gallery_url: str, path: str) -> None:
    expect(page).to_have_url(f"{gallery_url}{path}")


@then("the document was not reloaded")
def document_not_reloaded(page: Page) -> None:
    # A reload that the server asks for arrives shortly after the page renders.
    page.wait_for_timeout(300)
    assert page.evaluate("window.__toriUiSameDocument") is True


@then("the document was reloaded")
def document_reloaded(page: Page) -> None:
    def reloaded() -> bool:
        try:
            # A new document has not been marked by the step that opened the page.
            return bool(
                page.evaluate(
                    "window.__toriUiSameDocument === undefined"
                    " && document.readyState === 'complete'"
                )
            )
        except PlaywrightError:
            # The page is navigating.
            return False

    _eventually(page, reloaded, lambda: "the document was not loaded again")


@then(parsers.re(r"the document is (?P<height>\d+) pixels tall"))
def document_height(page: Page, height: str) -> None:
    assert page.evaluate("document.documentElement.scrollHeight") == int(height)


@then("the document links the package stylesheet once")
def links_stylesheet(page: Page) -> None:
    expect(page.locator(f'head link[href="{STYLESHEET_PATH}"]')).to_have_count(1)


@then(parsers.re(r"the document links (?P<count>\d+) stylesheets?"))
def links_stylesheets(page: Page, count: str) -> None:
    expect(page.locator('head link[rel="stylesheet"]')).to_have_count(int(count))


@then(
    parsers.re(
        r'the document links the stylesheet of the "(?P<name>[a-z-]+)" '
        r"(?P<kind>theme|skin)"
    )
)
def links_definition(page: Page, name: str, kind: str) -> None:
    definition = THEMES[name] if kind == "theme" else SKINS[name]
    link = f'head link[rel="stylesheet"][href="{definition.stylesheet_path}"]'
    expect(page.locator(link)).to_have_count(1)


@then(
    parsers.re(
        rf'{_TARGET} has the "(?P<token>[a-z_]+)" of the "(?P<name>[a-z-]+)" theme '
        r'in the "(?P<mode>light|dark)" mode as its (?P<part>background|color)'
    )
)
def has_theme_color(
    page: Page, target: str, token: str, name: str, mode: str, part: str
) -> None:
    theme = THEMES[name]
    color = getattr(theme.light if mode == "light" else theme.dark, token)
    red, green, blue = (int(color[index : index + 2], 16) for index in (1, 3, 5))
    expect(_locate(page, target)).to_have_css(
        "background-color" if part == "background" else "color",
        f"rgb({red}, {green}, {blue})",
    )


@then("the document loads the package script once")
def loads_script(page: Page) -> None:
    expect(page.locator(f'head script[src="{SCRIPT_PATH}"]')).to_have_count(1)


@then("the client uses the registered hooks")
def client_uses_hooks(page: Page) -> None:
    assert page.evaluate("globalThis.liveSocket.hooks === globalThis.ToriLiveHooks")


@then(parsers.re(r'the hook "(?P<name>[^"]*)" is registered'))
def hook_registered(page: Page, name: str) -> None:
    assert name in page.evaluate("Object.keys(globalThis.ToriLiveHooks)")


@then(parsers.re(r'the component "(?P<name>[^\"]*)" is registered'))
def component_registered(page: Page, name: str) -> None:
    assert page.evaluate("name => Boolean(customElements.get(name))", name)


@then("the UI does not register named application hooks")
def ui_has_no_named_hooks(page: Page) -> None:
    assert not any(
        name.startswith("ToriUi")
        for name in page.evaluate("Object.keys(globalThis.ToriLiveHooks)")
    )


@then(parsers.re(r'the stored mode is "(?P<mode>[^"]*)"'))
def stored_mode(page: Page, mode: str) -> None:
    assert page.evaluate("localStorage.getItem('tori-ui-mode')") == mode


@then(parsers.re(r'the body started with the mode "(?P<mode>[^"]*)"'))
def body_started_with(page: Page, mode: str) -> None:
    assert page.evaluate("window.__modeAtBody") == mode


@then(parsers.re(r'both confirmations asked "(?P<text>[^"]*)"'))
def confirmations_asked(confirmations: list[str], text: str) -> None:
    assert confirmations == [text, text]


# ----------------------------------------------------- Then: the clipboard


def _clipboard(page: Page) -> str:
    return page.evaluate("navigator.clipboard.readText()")


def _clipboard_eventually(page: Page, check: Callable[[str], bool], what: str) -> None:
    _eventually(
        page,
        lambda: check(_clipboard(page)),
        lambda: f"the clipboard never {what}: {_clipboard(page)!r}",
    )


@then(parsers.re(r'the clipboard holds "(?P<text>[^"]*)"'))
def clipboard_holds(page: Page, text: str) -> None:
    _clipboard_eventually(page, lambda copied: copied == text, f"held {text!r}")


@then(parsers.re(r'the clipboard starts with "(?P<text>[^"]*)"'))
def clipboard_starts_with(page: Page, text: str) -> None:
    _clipboard_eventually(
        page, lambda copied: copied.startswith(text), f"started with {text!r}"
    )


@then("the clipboard starts with:")
def clipboard_starts_with_block(page: Page, docstring: str) -> None:
    _clipboard_eventually(
        page,
        lambda copied: copied.startswith(docstring),
        f"started with {docstring!r}",
    )


@then("the clipboard ends with:")
def clipboard_ends_with_block(page: Page, docstring: str) -> None:
    _clipboard_eventually(
        page,
        lambda copied: copied.rstrip().endswith(docstring),
        f"ended with {docstring!r}",
    )


@then(parsers.re(r'the clipboard does not contain "(?P<text>[^"]*)"'))
def clipboard_lacks(page: Page, text: str) -> None:
    assert text not in _clipboard(page)


# ----------------------------------------------------- Then: focus and log

# Where the focus is while a dialog is open: inside it, on the browser's own
# controls, or on the page behind it.
_FOCUS_AREA = """
(dialog) => {
  const active = document.activeElement;
  if (dialog.contains(active)) return "dialog";
  return active === document.body ? "browser" : "page";
}
"""


@then(parsers.re(rf"the focus is inside {_TARGET}"))
def focus_inside(page: Page, target: str) -> None:
    assert _locate(page, target).evaluate(_FOCUS_AREA) == "dialog"


@then(
    parsers.re(
        rf'pressing "(?P<key>[^"]*)" (?P<count>\d+) times never moves the focus '
        rf"to the page behind {_TARGET}"
    )
)
def focus_never_leaves(page: Page, key: str, count: str, target: str) -> None:
    dialog = _locate(page, target)
    for _ in range(int(count)):
        page.keyboard.press(key)
        assert dialog.evaluate(_FOCUS_AREA) in ("dialog", "browser")


@then("the chat log is at its end")
def chat_log_at_end(page: Page) -> None:
    assert page.locator(_CHAT_LOG).evaluate(
        "log => log.scrollHeight - log.scrollTop - log.clientHeight < 4"
    )


@then("the chat log is at its start")
def chat_log_at_start(page: Page) -> None:
    assert page.locator(_CHAT_LOG).evaluate("log => log.scrollTop") == 0


# ------------------------------------------------------- Then: every page

# What an automatic check can say about a page's markup: IDs are unique,
# every control has an accessible name, every image has alternative text, and
# every reference to another element's ID resolves.
_AUDIT = """
() => {
  const problems = [];
  const ids = new Map();
  for (const element of document.querySelectorAll("[id]")) {
    ids.set(element.id, (ids.get(element.id) ?? 0) + 1);
  }
  for (const [id, count] of ids) {
    if (count > 1) problems.push(`duplicate id ${id}`);
  }
  const label = (element) => {
    const labelledby = (element.getAttribute("aria-labelledby") ?? "")
      .split(/\\s+/)
      .filter(Boolean)
      .map((id) => document.getElementById(id)?.textContent ?? "")
      .join(" ");
    const forLabel = element.id
      ? document.querySelector(`label[for="${CSS.escape(element.id)}"]`)?.textContent
      : "";
    return [
      element.getAttribute("aria-label"),
      labelledby,
      forLabel,
      element.closest("label")?.textContent,
      element.textContent,
      element.getAttribute("title"),
    ].find((text) => text && text.trim() !== "");
  };
  const controls = "button, a[href], input:not([type=hidden]), select, textarea, " +
    "[role=tab], [role=menuitem], [role=switch], summary, dialog, [role=dialog], " +
    "[role=region], [role=group], [role=radiogroup], nav, [role=log], meter, progress";
  for (const element of document.querySelectorAll(controls)) {
    if (!label(element)) {
      problems.push(`unnamed ${element.tagName.toLowerCase()}.${element.className}`);
    }
  }
  for (const image of document.querySelectorAll("img:not([alt])")) {
    problems.push(`image without alt ${image.src}`);
  }
  const references = [
    "aria-labelledby", "aria-describedby", "aria-controls", "for", "list",
  ];
  for (const name of references) {
    for (const element of document.querySelectorAll(`[${name}]`)) {
      for (const id of element.getAttribute(name).split(/\\s+/).filter(Boolean)) {
        if (document.getElementById(id) === null) {
          problems.push(`${name} points at missing #${id}`);
        }
      }
    }
  }
  const headings = [...document.querySelectorAll("h1")].length;
  if (headings > 1) problems.push(`${headings} h1 elements`);
  if (document.querySelectorAll("main").length !== 1) problems.push("not one main");
  return problems;
}
"""


@then("the markup audit finds no problems")
def markup_is_sound(page: Page) -> None:
    assert page.evaluate(_AUDIT) == []


@then(
    parsers.re(
        r'every gallery page fits the viewport in the "(?P<mode>[^"]*)" mode '
        r'with the "(?P<skin>[^"]*)" skin'
    )
)
def every_page_fits(
    page: Page, gallery_url: str, browser_errors: list[str], mode: str, skin: str
) -> None:
    del browser_errors
    for path in _PAGES:
        _open(page, f"{gallery_url}{path}?mode={mode}&skin={skin}")
        expect(page.locator("html")).to_have_attribute("data-tori-ui-mode", mode)
        expect(page.locator("html")).to_have_attribute("data-tori-ui-skin", skin)
        # Nothing spills out of the viewport sideways.
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        ), path


@then("every gallery page keeps its main area within the viewport")
def every_page_is_narrow_enough(
    page: Page, gallery_url: str, browser_errors: list[str]
) -> None:
    del browser_errors
    for path in _PAGES:
        _open(page, f"{gallery_url}{path}")
        overflowing = page.evaluate(
            """
            () => {
              const main = document.querySelector("main");
              return main.scrollWidth - main.clientWidth;
            }
            """
        )
        assert overflowing <= 1, path

from __future__ import annotations

import html as html_module
import json
import re
from collections.abc import Callable
from typing import Any, cast

import pytest
from tori_py_liveview import JS, attrs, html, rendered

# Each expectation follows the argument names the Phoenix LiveView 1.2.11
# client destructures in its exec_* command handlers.
_COMMANDS: list[tuple[Callable[[], JS], list[object]]] = [
    (
        lambda: JS().push(
            "inc",
            value={"id": 1},
            target=3,
            loading="#form",
            page_loading=True,
        ),
        [
            "push",
            {
                "event": "inc",
                "value": {"id": 1},
                "target": 3,
                "loading": "#form",
                "page_loading": True,
            },
        ],
    ),
    (
        lambda: JS().push("save", target="#form"),
        ["push", {"event": "save", "target": "#form"}],
    ),
    (
        lambda: JS().navigate("/items?page=2", replace=True),
        ["navigate", {"href": "/items?page=2", "replace": True}],
    ),
    (lambda: JS().patch("/items"), ["patch", {"href": "/items", "replace": False}]),
    (
        lambda: JS().dispatch("copy", to="#code", detail={"text": "x"}, blocking=True),
        [
            "dispatch",
            {
                "event": "copy",
                "to": "#code",
                "detail": {"text": "x"},
                "bubbles": True,
                "blocking": True,
            },
        ],
    ),
    (
        lambda: JS().show(
            to=("closest", ".row"), transition="fade-in", time=100, display="flex"
        ),
        [
            "show",
            {
                "time": 100,
                "to": {"closest": ".row"},
                "transition": [["fade-in"], [], []],
                "display": "flex",
            },
        ],
    ),
    (
        lambda: JS().hide(to=("inner", ".item"), blocking=False),
        ["hide", {"time": 200, "to": {"inner": ".item"}, "blocking": False}],
    ),
    (
        lambda: JS().toggle(
            to="#menu",
            transition_in=("ease-out duration-200", "opacity-0", "opacity-100"),
            transition_out="fade-out",
        ),
        [
            "toggle",
            {
                "time": 200,
                "to": "#menu",
                "ins": [["ease-out", "duration-200"], ["opacity-0"], ["opacity-100"]],
                "outs": [["fade-out"], [], []],
            },
        ],
    ),
    (
        lambda: JS().add_class("active bold", to="#tab"),
        ["add_class", {"time": 200, "to": "#tab", "names": ["active", "bold"]}],
    ),
    (
        lambda: JS().remove_class(["a", "b c"]),
        ["remove_class", {"time": 200, "names": ["a", "b", "c"]}],
    ),
    (
        lambda: JS().toggle_class("open", transition="fade"),
        [
            "toggle_class",
            {"time": 200, "names": ["open"], "transition": [["fade"], [], []]},
        ],
    ),
    (
        lambda: JS().transition("shake", to="#field"),
        [
            "transition",
            {"time": 200, "to": "#field", "transition": [["shake"], [], []]},
        ],
    ),
    (
        lambda: JS().set_attribute("aria-expanded", "true", to="#menu"),
        ["set_attr", {"attr": ["aria-expanded", "true"], "to": "#menu"}],
    ),
    (lambda: JS().remove_attribute("disabled"), ["remove_attr", {"attr": "disabled"}]),
    (
        lambda: JS().toggle_attribute("aria-expanded", "true", "false"),
        ["toggle_attr", {"attr": ["aria-expanded", "true", "false"]}],
    ),
    (
        lambda: JS().ignore_attributes(["open", "data-*"]),
        ["ignore_attrs", {"attrs": ["open", "data-*"]}],
    ),
    (lambda: JS().focus(to="#name"), ["focus", {"to": "#name"}]),
    (lambda: JS().focus_first(), ["focus_first", {}]),
    (lambda: JS().push_focus(to="#name"), ["push_focus", {"to": "#name"}]),
    (lambda: JS().pop_focus(), ["pop_focus", {}]),
    (
        lambda: JS().exec("phx-remove", to="#modal"),
        ["exec", {"attr": "phx-remove", "to": "#modal"}],
    ),
]


@pytest.mark.parametrize(("build", "expected"), _COMMANDS)
def test_commands_encode_like_phoenix(
    build: Callable[[], JS], expected: list[object]
) -> None:
    assert json.loads(build().encode()) == [expected]


def test_chains_are_immutable_values() -> None:
    base = JS()
    save = base.push("save")
    closed = save.hide(to="#modal")

    assert base.encode() == "[]"
    assert json.loads(closed.encode()) == [
        ["push", {"event": "save"}],
        ["hide", {"time": 200, "to": "#modal"}],
    ]
    assert save == JS().push("save")
    assert hash(save) == hash(JS().push("save"))
    assert save != closed
    assert repr(save) == 'JS([["push",{"event":"save"}]])'


@pytest.mark.parametrize(
    ("build", "error", "message"),
    [
        (lambda: JS().push(""), ValueError, "cannot be empty"),
        (lambda: JS().push(cast(Any, 1)), TypeError, "push event must be a string"),
        (lambda: JS().push("x", value=cast(Any, [1])), TypeError, "must be a mapping"),
        (lambda: JS().push("x", value=cast(Any, {1: "a"})), TypeError, "keys"),
        (lambda: JS().push("x", value={"x": object()}), TypeError, "JSON encodable"),
        (lambda: JS().push("x", value={"x": float("nan")}), TypeError, "JSON"),
        (lambda: JS().push("x", target=0), ValueError, "positive safe integer"),
        (lambda: JS().navigate("//evil.example"), ValueError, "root-relative"),
        (lambda: JS().navigate("/\\evil.example"), ValueError, "root-relative"),
        (lambda: JS().patch("https://evil.example/"), ValueError, "root-relative"),
        (lambda: JS().navigate("javascript:alert(1)"), ValueError, "root-relative"),
        (lambda: JS().navigate("/x", replace=cast(Any, 1)), TypeError, "boolean"),
        (lambda: JS().show(time=-1), ValueError, "non-negative"),
        (lambda: JS().show(time=cast(Any, 1.5)), TypeError, "integer"),
        (lambda: JS().show(to=cast(Any, ("parent", "#x"))), ValueError, "closest"),
        (lambda: JS().show(to=""), ValueError, "cannot be empty"),
        (lambda: JS().hide(blocking=cast(Any, 1)), TypeError, "boolean"),
        (lambda: JS().add_class(""), ValueError, "names cannot be empty"),
        (lambda: JS().add_class(cast(Any, [1])), TypeError, "names must be strings"),
        (lambda: JS().transition(cast(Any, ("a", "b"))), TypeError, "three strings"),
        (lambda: JS().transition(""), ValueError, "transition cannot be empty"),
        (lambda: JS().set_attribute("onclick", "x"), ValueError, "attribute name"),
        (lambda: JS().set_attribute("style", "x"), ValueError, "attribute name"),
        (
            lambda: JS().set_attribute("href", "javascript:alert(1)"),
            ValueError,
            "unsafe URL scheme",
        ),
        (
            lambda: JS().toggle_attribute("phx-click", "save", '[["exec"]]'),
            ValueError,
            "unsafe phx-",
        ),
        (lambda: JS().exec("data-cancel"), ValueError, "phx-\\* command binding"),
    ],
)
def test_commands_validate_arguments(
    build: Callable[[], JS], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        build()


def _attribute(markup: str, name: str) -> str:
    match = re.search(rf'{name}="([^"]*)"', markup)
    assert match is not None
    return html_module.unescape(match.group(1))


def test_commands_render_as_trusted_phoenix_values() -> None:
    # Data inside a command stays inside its JSON string.
    name = (
        'x"}],["set_attr",{"to":"body","attr":["onclick","alert(1)"]}],["push",{"a":"'
    )
    command = JS().push("rename", value={"name": name})
    expected = command.encode()

    assert json.loads(expected) == [
        ["push", {"event": "rename", "value": {"name": name}}]
    ]
    assert _attribute(
        html(t'<b phx-click="{command}">x</b>').to_html(), "phx-click"
    ) == (expected)
    assert _attribute(attrs({"phx-click": command}).value, "phx-click") == expected
    assert (
        _attribute(
            rendered(('<b phx-submit="', '">x</b>'), command).to_html(), "phx-submit"
        )
        == expected
    )


def test_plain_strings_still_cannot_start_phoenix_commands() -> None:
    encoded = JS().push("save").encode()
    with pytest.raises(ValueError, match="unsafe phx-"):
        html(t'<b phx-click="{encoded}">x</b>')
    with pytest.raises(ValueError, match="unsafe phx-"):
        attrs({"phx-click": encoded})

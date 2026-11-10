"""Phoenix LiveView JS commands, built and encoded like ``Phoenix.LiveView.JS``."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Literal

from tori_py_liveview._attributes import (
    phx_command_attribute,
    unsafe_attribute_name,
    unsafe_url,
)
from tori_py_liveview.routing import clean_url

type JSTarget = str | tuple[Literal["closest", "inner"], str]
type JSTransition = str | tuple[str, str, str]

_MAX_SAFE_INTEGER = 2**53 - 1


class JS:
    """An immutable chain of commands the Phoenix client runs for a binding.

    Every method returns a new chain. Interpolate a chain into a ``phx-*``
    attribute or pass it to ``attrs()``. Arguments are JSON encoded, so data in
    them cannot add commands of its own.
    """

    __slots__ = ("_commands",)

    def __init__(self) -> None:
        self._commands: tuple[str, ...] = ()

    def encode(self) -> str:
        """Return the JSON command list the Phoenix client parses."""
        return f"[{','.join(self._commands)}]"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, JS) and other._commands == self._commands

    def __hash__(self) -> int:
        return hash(self._commands)

    def __repr__(self) -> str:
        return f"JS({self.encode()})"

    def push(
        self,
        event: str,
        *,
        value: Mapping[str, object] | None = None,
        target: int | str | None = None,
        loading: str | None = None,
        page_loading: bool = False,
    ) -> JS:
        args: dict[str, object] = {"event": _text("push event", event)}
        if value is not None:
            args["value"] = _mapping("push value", value)
        if target is not None:
            args["target"] = _push_target(target)
        if loading is not None:
            args["loading"] = _text("push loading", loading)
        if _flag("push page_loading", page_loading):
            args["page_loading"] = True
        return self._then("push", args)

    def navigate(self, href: str, *, replace: bool = False) -> JS:
        return self._then(
            "navigate",
            {
                "href": _live_path("navigate", href),
                "replace": _flag("navigate replace", replace),
            },
        )

    def patch(self, href: str, *, replace: bool = False) -> JS:
        return self._then(
            "patch",
            {
                "href": _live_path("patch", href),
                "replace": _flag("patch replace", replace),
            },
        )

    def dispatch(
        self,
        event: str,
        *,
        to: JSTarget | None = None,
        detail: Mapping[str, object] | None = None,
        bubbles: bool = True,
        blocking: bool = False,
    ) -> JS:
        args: dict[str, object] = {"event": _text("dispatch event", event)}
        _set_to(args, "dispatch", to)
        if detail is not None:
            args["detail"] = _mapping("dispatch detail", detail)
        args["bubbles"] = _flag("dispatch bubbles", bubbles)
        if _flag("dispatch blocking", blocking):
            args["blocking"] = True
        return self._then("dispatch", args)

    def show(
        self,
        *,
        to: JSTarget | None = None,
        transition: JSTransition | None = None,
        time: int = 200,
        display: str | None = None,
        blocking: bool = True,
    ) -> JS:
        return self._then(
            "show", _visibility("show", to, transition, time, display, blocking)
        )

    def hide(
        self,
        *,
        to: JSTarget | None = None,
        transition: JSTransition | None = None,
        time: int = 200,
        display: str | None = None,
        blocking: bool = True,
    ) -> JS:
        return self._then(
            "hide", _visibility("hide", to, transition, time, display, blocking)
        )

    def toggle(
        self,
        *,
        to: JSTarget | None = None,
        transition_in: JSTransition | None = None,
        transition_out: JSTransition | None = None,
        time: int = 200,
        display: str | None = None,
        blocking: bool = True,
    ) -> JS:
        args = _animation("toggle", to, time, blocking)
        if transition_in is not None:
            args["ins"] = _transition("toggle", transition_in)
        if transition_out is not None:
            args["outs"] = _transition("toggle", transition_out)
        if display is not None:
            args["display"] = _text("toggle display", display)
        return self._then("toggle", args)

    def add_class(
        self,
        names: str | Iterable[str],
        *,
        to: JSTarget | None = None,
        transition: JSTransition | None = None,
        time: int = 200,
        blocking: bool = True,
    ) -> JS:
        return self._then(
            "add_class",
            _class_change("add_class", names, to, transition, time, blocking),
        )

    def remove_class(
        self,
        names: str | Iterable[str],
        *,
        to: JSTarget | None = None,
        transition: JSTransition | None = None,
        time: int = 200,
        blocking: bool = True,
    ) -> JS:
        return self._then(
            "remove_class",
            _class_change("remove_class", names, to, transition, time, blocking),
        )

    def toggle_class(
        self,
        names: str | Iterable[str],
        *,
        to: JSTarget | None = None,
        transition: JSTransition | None = None,
        time: int = 200,
        blocking: bool = True,
    ) -> JS:
        return self._then(
            "toggle_class",
            _class_change("toggle_class", names, to, transition, time, blocking),
        )

    def transition(
        self,
        transition: JSTransition,
        *,
        to: JSTarget | None = None,
        time: int = 200,
        blocking: bool = True,
    ) -> JS:
        args = _animation("transition", to, time, blocking)
        args["transition"] = _transition("transition", transition)
        return self._then("transition", args)

    def set_attribute(
        self,
        name: str,
        value: str,
        *,
        to: JSTarget | None = None,
    ) -> JS:
        args: dict[str, object] = {"attr": _attribute("set_attribute", name, value)}
        _set_to(args, "set_attribute", to)
        return self._then("set_attr", args)

    def remove_attribute(self, name: str, *, to: JSTarget | None = None) -> JS:
        args: dict[str, object] = {"attr": _attribute("remove_attribute", name)[0]}
        _set_to(args, "remove_attribute", to)
        return self._then("remove_attr", args)

    def toggle_attribute(
        self,
        name: str,
        value: str,
        alternate: str | None = None,
        *,
        to: JSTarget | None = None,
    ) -> JS:
        values = (value,) if alternate is None else (value, alternate)
        args: dict[str, object] = {
            "attr": _attribute("toggle_attribute", name, *values)
        }
        _set_to(args, "toggle_attribute", to)
        return self._then("toggle_attr", args)

    def ignore_attributes(
        self,
        names: str | Iterable[str],
        *,
        to: JSTarget | None = None,
    ) -> JS:
        args: dict[str, object] = {"attrs": _tokens("ignore_attributes", names)}
        _set_to(args, "ignore_attributes", to)
        return self._then("ignore_attrs", args)

    def focus(self, *, to: JSTarget | None = None) -> JS:
        return self._then("focus", _targeted("focus", to))

    def focus_first(self, *, to: JSTarget | None = None) -> JS:
        return self._then("focus_first", _targeted("focus_first", to))

    def push_focus(self, *, to: JSTarget | None = None) -> JS:
        return self._then("push_focus", _targeted("push_focus", to))

    def pop_focus(self) -> JS:
        return self._then("pop_focus", {})

    def exec(self, attribute: str, *, to: JSTarget | None = None) -> JS:
        name = _text("exec attribute", attribute)
        # Only phx-* values are checked for data that would start a command.
        if not phx_command_attribute(name):
            raise ValueError("JS exec attribute must be a phx-* command binding")
        args: dict[str, object] = {"attr": name}
        _set_to(args, "exec", to)
        return self._then("exec", args)

    def _then(self, kind: str, args: Mapping[str, object]) -> JS:
        try:
            command = json.dumps(
                [kind, args],
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as error:
            raise TypeError(f"JS {kind} arguments must be JSON encodable") from error
        chained = object.__new__(JS)
        chained._commands = (*self._commands, command)
        return chained


def _text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"JS {name} must be a string")
    if not value.strip():
        raise ValueError(f"JS {name} cannot be empty")
    return value


def _flag(name: str, value: object) -> bool:
    if type(value) is not bool:
        raise TypeError(f"JS {name} must be a boolean")
    return value


def _mapping(name: str, value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"JS {name} must be a mapping")
    copied: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(f"JS {name} keys must be strings")
        copied[key] = item
    return copied


def _push_target(value: object) -> int | str:
    if type(value) is int:
        if not 0 < value <= _MAX_SAFE_INTEGER:
            raise ValueError("JS push target must be a positive safe integer")
        return value
    return _text("push target", value)


def _live_path(kind: str, href: object) -> str:
    cleaned = clean_url(_text(f"{kind} href", href))
    if not cleaned.startswith("/") or cleaned.startswith("//"):
        raise ValueError(f"JS {kind} href must be a root-relative path")
    return cleaned


def _to(kind: str, value: object) -> str | dict[str, str]:
    if isinstance(value, tuple):
        if len(value) != 2 or value[0] not in ("closest", "inner"):
            raise ValueError(
                f"JS {kind} to must be a selector or a ('closest'|'inner', selector)"
            )
        relation = "closest" if value[0] == "closest" else "inner"
        return {relation: _text(f"{kind} to selector", value[1])}
    return _text(f"{kind} to", value)


def _set_to(args: dict[str, object], kind: str, to: object) -> None:
    if to is not None:
        args["to"] = _to(kind, to)


def _targeted(kind: str, to: object) -> dict[str, object]:
    args: dict[str, object] = {}
    _set_to(args, kind, to)
    return args


def _time(kind: str, value: object) -> int:
    if type(value) is not int:
        raise TypeError(f"JS {kind} time must be an integer")
    if not 0 <= value <= _MAX_SAFE_INTEGER:
        raise ValueError(f"JS {kind} time must be a non-negative safe integer")
    return value


def _animation(
    kind: str, to: object, time: object, blocking: object
) -> dict[str, object]:
    args: dict[str, object] = {"time": _time(kind, time)}
    _set_to(args, kind, to)
    # The client blocks by default and checks for an explicit false.
    if not _flag(f"{kind} blocking", blocking):
        args["blocking"] = False
    return args


def _visibility(
    kind: str,
    to: object,
    transition: object,
    time: object,
    display: object,
    blocking: object,
) -> dict[str, object]:
    args = _animation(kind, to, time, blocking)
    if transition is not None:
        args["transition"] = _transition(kind, transition)
    if display is not None:
        args["display"] = _text(f"{kind} display", display)
    return args


def _class_change(
    kind: str,
    names: object,
    to: object,
    transition: object,
    time: object,
    blocking: object,
) -> dict[str, object]:
    args = _animation(kind, to, time, blocking)
    args["names"] = _tokens(kind, names)
    if transition is not None:
        args["transition"] = _transition(kind, transition)
    return args


def _tokens(kind: str, value: object) -> list[str]:
    if isinstance(value, str):
        tokens = value.split()
    elif isinstance(value, Iterable):
        tokens = []
        for item in value:
            if not isinstance(item, str):
                raise TypeError(f"JS {kind} names must be strings")
            tokens.extend(item.split())
    else:
        raise TypeError(f"JS {kind} names must be a string or strings")
    if not tokens:
        raise ValueError(f"JS {kind} names cannot be empty")
    return tokens


def _transition(kind: str, value: object) -> list[list[str]]:
    if isinstance(value, str):
        stages: tuple[object, ...] = (value, "", "")
    elif isinstance(value, tuple) and len(value) == 3:
        stages = value
    else:
        raise TypeError(f"JS {kind} transition must be a string or three strings")
    if not all(isinstance(stage, str) for stage in stages):
        raise TypeError(f"JS {kind} transition must be a string or three strings")
    encoded = [str(stage).split() for stage in stages]
    if not encoded[0]:
        raise ValueError(f"JS {kind} transition cannot be empty")
    return encoded


def _attribute(kind: str, name: object, *values: object) -> list[str]:
    attribute = _text(f"{kind} attribute", name)
    if unsafe_attribute_name(attribute):
        raise ValueError(f"unsafe HTML attribute name: {attribute!r}")
    normalized = attribute.lower()
    encoded = [attribute]
    for value in values:
        if not isinstance(value, str):
            raise TypeError(f"JS {kind} value must be a string")
        if unsafe_url(normalized, value):
            raise ValueError(f"unsafe URL scheme for HTML attribute: {attribute!r}")
        if value.startswith("[") and phx_command_attribute(normalized):
            raise ValueError(f"unsafe phx-* attribute value: {attribute!r}")
        encoded.append(value)
    return encoded


__all__ = ["JS", "JSTarget", "JSTransition"]

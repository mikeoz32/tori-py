"""Closed vocabularies and argument checks shared by the helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Literal

from tori_py_liveview import JS

type Size = Literal["sm", "md", "lg"]
type Justify = Literal["start", "center", "end", "between"]
type LiveLink = Literal["patch", "navigate"]
type EventValue = str | int | float | bool
type ButtonVariant = Literal["primary", "secondary", "ghost", "danger"]
type ButtonSize = Literal["sm", "md", "lg"]
type ButtonType = Literal["button", "submit", "reset"]
type InputType = Literal[
    "date",
    "datetime-local",
    "email",
    "month",
    "number",
    "password",
    "search",
    "tel",
    "text",
    "time",
    "url",
    "week",
]
type Tone = Literal["neutral", "info", "success", "warning", "danger"]
type Gap = Literal["xs", "sm", "md", "lg", "xl"]
type Alignment = Literal["start", "center", "end", "stretch"]
type Columns = Literal["auto", "1", "2", "3", "4"]

BUTTON_VARIANTS = frozenset({"primary", "secondary", "ghost", "danger"})
BUTTON_SIZES = frozenset({"sm", "md", "lg"})
BUTTON_TYPES = frozenset({"button", "submit", "reset"})
INPUT_TYPES = frozenset(
    {
        "date",
        "datetime-local",
        "email",
        "month",
        "number",
        "password",
        "search",
        "tel",
        "text",
        "time",
        "url",
        "week",
    }
)
TONES = frozenset({"neutral", "info", "success", "warning", "danger"})
GAPS = frozenset({"xs", "sm", "md", "lg", "xl"})
ALIGNMENTS = frozenset({"start", "center", "end", "stretch"})
COLUMNS = frozenset({"auto", "1", "2", "3", "4"})
SIZES = frozenset({"sm", "md", "lg"})
JUSTIFY = frozenset({"start", "center", "end", "between"})
LIVE_LINKS = frozenset({"patch", "navigate"})
MAX_SAFE_INTEGER = 2**53 - 1
_LIVE_LINK_KINDS = {"patch": "patch", "navigate": "redirect"}
_VALUE_NAME = re.compile(r"[a-z][a-z0-9_-]{0,62}")
_SELECTOR_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


def one_of(name: str, value: str, allowed: frozenset[str]) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{name} must be one of: {choices}")
    return value


def optional_text(name: str, value: str | None) -> str | None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{name} must be a string or None")
    return value


def optional_nonempty_text(name: str, value: str | None) -> str | None:
    value = optional_text(name, value)
    if value is not None and not value.strip():
        raise ValueError(f"{name} cannot be empty")
    return value


def required_text(name: str, value: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} cannot be empty")
    return value


def boolean(name: str, value: bool) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a boolean")
    return value


def html_id(name: str, value: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value:
        raise ValueError(f"{name} cannot be empty")
    if any(character.isspace() for character in value):
        raise ValueError(f"{name} cannot contain whitespace")
    return value


def selector_id(name: str, value: str) -> str:
    """Check an ID that a helper also uses inside a CSS selector."""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if _SELECTOR_ID.fullmatch(value) is None:
        raise ValueError(f"{name} must match [A-Za-z][A-Za-z0-9_-]*")
    return value


def event_binding(name: str, value: str | JS | None) -> str | JS | None:
    if value is not None and not isinstance(value, JS):
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string, JS, or None")
        if not value.strip():
            raise ValueError(f"{name} cannot be empty")
    return value


def event_target(name: str, target: int | None, *events: str | JS | None) -> int | None:
    if target is not None:
        if type(target) is not int:
            raise TypeError(f"{name} must be an integer or None")
        if not 0 < target <= MAX_SAFE_INTEGER:
            raise ValueError(f"{name} must be a positive safe integer")
        if not any(event is not None for event in events):
            raise ValueError(f"{name} requires an event")
    return target


def control_description(
    control_id: str,
    help_text: str | None,
    error: str | None,
) -> str | None:
    ids = []
    if help_text is not None:
        ids.append(f"{control_id}-help")
    if error is not None:
        ids.append(f"{control_id}-error")
    return " ".join(ids) or None


def input_value(value: str | int | float | None) -> str | int | float | None:
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, (str, int, float))
    ):
        raise TypeError("input value must be a string, number, or None")
    return value


def bounded_integer(name: str, value: int, minimum: int, maximum: int) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def event_values(
    name: str,
    values: Mapping[str, EventValue] | None,
    *events: str | JS | None,
) -> dict[str, object]:
    """Return the ``phx-value-*`` attributes an event carries to its handler."""
    if values is None:
        return {}
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a mapping or None")
    if not any(event is not None for event in events):
        raise ValueError(f"{name} require an event")
    attributes: dict[str, object] = {}
    for key, value in values.items():
        if not isinstance(key, str) or _VALUE_NAME.fullmatch(key) is None:
            raise ValueError(f"{name} keys must match [a-z][a-z0-9_-]{{0,62}}")
        if isinstance(value, bool):
            value = "true" if value else "false"
        elif not isinstance(value, (str, int, float)):
            raise TypeError(f"{name} must be strings, numbers, or booleans")
        attributes[f"phx-value-{key}"] = value
    return attributes


def link_attributes(
    name: str,
    href: str,
    live: LiveLink | None,
    replace: bool,
    external: bool,
) -> dict[str, object]:
    """Return the attributes of a plain, live, or external link."""
    href = required_text(f"{name} href", href)
    boolean(f"{name} replace", replace)
    boolean(f"{name} external", external)
    if live is None:
        if replace:
            raise ValueError(f"{name} replace requires a live link")
    else:
        one_of(f"{name} live", live, LIVE_LINKS)
        if external:
            raise ValueError(f"{name} cannot be both live and external")
        if not href.startswith("/") or href.startswith("//") or "\\" in href:
            raise ValueError(f"{name} live href must be a root-relative path")
    return {
        "href": href,
        "data-phx-link": None if live is None else _LIVE_LINK_KINDS[live],
        "data-phx-link-state": (
            None if live is None else "replace" if replace else "push"
        ),
        "target": "_blank" if external else None,
        "rel": "noopener noreferrer" if external else None,
    }

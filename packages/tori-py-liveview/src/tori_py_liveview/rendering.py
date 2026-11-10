from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from html import escape
from string.templatelib import Template, convert

from tori_py_liveview._attributes import (
    phx_command_attribute,
    unsafe_attribute_name,
    unsafe_url,
)
from tori_py_liveview.js import JS

# A static ending inside an attribute value, such as ` phx-click="do-`.
_OPEN_ATTRIBUTE_VALUE = re.compile(
    r"""([^\s"'<>/=]+)\s*=\s*(?:"([^"]*)|'([^']*)|([^\s"'<>=`]*))\Z"""
)
_UNQUOTED_VALUE_END = re.compile(r"[\s>]")


@dataclass(frozen=True, slots=True)
class SafeHtml:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("safe HTML must be a string")


def raw(value: str) -> SafeHtml:
    return SafeHtml(value)


@dataclass(frozen=True, slots=True)
class Rendered:
    statics: tuple[str, ...]
    dynamics: tuple[_RenderedDynamic, ...]

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) for value in self.statics):
            raise TypeError("static fragments must be strings")
        if not all(
            isinstance(value, (str, Rendered, _StreamRendered))
            for value in self.dynamics
        ):
            raise TypeError("dynamic fragments must be renderable values")
        if len(self.statics) != len(self.dynamics) + 1:
            raise ValueError("Rendered requires exactly one more static than dynamic")

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.statics, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()

    def to_html(self) -> str:
        return "".join(
            static
            + (
                _dynamic_html(self.dynamics[index])
                if index < len(self.dynamics)
                else ""
            )
            for index, static in enumerate(self.statics)
        )

    def diff(self, previous: Rendered) -> dict[int, _RenderedDynamic] | None:
        if self.fingerprint != previous.fingerprint:
            return None
        return {
            index: value
            for index, value in enumerate(self.dynamics)
            if value != previous.dynamics[index]
        }


@dataclass(frozen=True, slots=True)
class _ComponentRendered(Rendered):
    cid: int


@dataclass(frozen=True, slots=True)
class _StreamInsert:
    item_id: str
    html: str
    at: int
    limit: int | None


@dataclass(frozen=True, slots=True)
class _StreamRendered(SafeHtml):
    ref: str
    inserts: tuple[_StreamInsert, ...]
    delete_ids: tuple[str, ...]
    reset: bool


type _RenderedDynamic = str | Rendered | _StreamRendered


def _dynamic_html(value: _RenderedDynamic) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Rendered):
        return value.to_html()
    return value.value


def _dynamic(value: object) -> _RenderedDynamic:
    if isinstance(value, _StreamRendered):
        return value
    if isinstance(value, SafeHtml):
        return value.value
    if isinstance(value, Rendered):
        return value
    if isinstance(value, Template):
        return html(value)
    if isinstance(value, JS):
        return escape(value.encode(), quote=True)
    return escape(str(value), quote=True)


def html(template: Template) -> Rendered:
    if not isinstance(template, Template):
        raise TypeError("template must be a Template")
    values: list[object] = []
    for interpolation in template.interpolations:
        value = convert(interpolation.value, interpolation.conversion)
        if interpolation.format_spec:
            value = format(value, interpolation.format_spec)
        values.append(value)
    dynamics = tuple(_dynamic(value) for value in values)
    _reject_phx_commands(template.strings, values, dynamics)
    return Rendered(template.strings, dynamics)


def fragment(values: Iterable[object], /) -> Rendered:
    dynamics = tuple(_dynamic(value) for value in values)
    return Rendered(("",) * (len(dynamics) + 1), dynamics)


def classes(*names: str, **conditional: bool) -> str:
    tokens: list[str] = []
    for name in names:
        if not isinstance(name, str):
            raise TypeError("class names must be strings")
        tokens.extend(name.split())
    for name, enabled in conditional.items():
        if type(enabled) is not bool:
            raise TypeError("conditional class flags must be booleans")
        if enabled:
            tokens.extend(name.split())
    return " ".join(tokens)


@dataclass(frozen=True, slots=True)
class _PhxValueSlot:
    """An interpolation inside a phx-* value Phoenix may run as JS commands."""

    name: str
    prefix: str
    continues: bool


@lru_cache(maxsize=1024)
def _phx_value_slots(statics: tuple[str, ...]) -> tuple[_PhxValueSlot | None, ...]:
    """Find each interpolation's phx-* value context once per set of statics."""
    slots: list[_PhxValueSlot | None] = []
    open_value: tuple[str, str] | None = None
    # The last static follows every interpolation and starts none.
    for static in statics[:-1]:
        if open_value is not None:
            name, quote = open_value
            if quote:
                end = static.find(quote)
                end = end + 1 if end >= 0 else -1
            else:
                match = _UNQUOTED_VALUE_END.search(static)
                end = match.start() if match is not None else -1
            if end < 0:
                slots.append(_PhxValueSlot(name, static, True))
                continue
            open_value = None
            static = static[end:]
        match = _OPEN_ATTRIBUTE_VALUE.search(static)
        if match is None or not phx_command_attribute(match.group(1)):
            slots.append(None)
            continue
        name, double, single, bare = match.groups()
        if double is not None:
            quote, prefix = '"', double
        elif single is not None:
            quote, prefix = "'", single
        else:
            quote, prefix = "", bare or ""
        open_value = (name, quote)
        slots.append(_PhxValueSlot(name, prefix, False))
    return tuple(slots)


def _reject_phx_commands(
    statics: Sequence[object],
    values: Sequence[object],
    dynamics: Sequence[_RenderedDynamic],
) -> None:
    """Reject untrusted output that would start or join a phx-* JS command."""
    strings = tuple(static for static in statics if isinstance(static, str))
    if len(strings) != len(statics):
        return
    value = ""
    slots = _phx_value_slots(strings)
    for slot, original, dynamic in zip(slots, values, dynamics, strict=False):
        if slot is None:
            continue
        value = (value if slot.continues else "") + slot.prefix
        text = _dynamic_html(dynamic)
        # Check what is emitted; only raw() and JS may write or extend a command.
        trusted = isinstance(original, SafeHtml | JS)
        if not trusted and (value or text).startswith("["):
            raise ValueError(f"unsafe phx-* attribute value: {slot.name!r}")
        value += text


def attrs(values: Mapping[str, object], /) -> SafeHtml:
    if not isinstance(values, Mapping):
        raise TypeError("attributes must be a mapping")
    encoded: list[str] = []
    for name, value in values.items():
        if not isinstance(name, str):
            raise TypeError("attribute names must be strings")
        if unsafe_attribute_name(name):
            raise ValueError(f"unsafe HTML attribute name: {name!r}")
        normalized = name.lower()
        if value is None or value is False:
            continue
        if value is True:
            encoded.append(f" {name}")
        elif isinstance(value, JS):
            encoded.append(f' {name}="{escape(value.encode(), quote=True)}"')
        else:
            encoded_value = str(value)
            if unsafe_url(normalized, encoded_value):
                raise ValueError(f"unsafe URL scheme for HTML attribute: {name!r}")
            if encoded_value.startswith("[") and phx_command_attribute(normalized):
                raise ValueError(f"unsafe phx-* attribute value: {name!r}")
            encoded.append(f' {name}="{escape(encoded_value, quote=True)}"')
    return SafeHtml("".join(encoded))


def rendered(statics: tuple[str, ...], *values: object) -> Rendered:
    statics = tuple(statics)
    dynamics = tuple(_dynamic(value) for value in values)
    _reject_phx_commands(statics, values, dynamics)
    return Rendered(statics, dynamics)


__all__ = [
    "Rendered",
    "SafeHtml",
    "attrs",
    "classes",
    "fragment",
    "html",
    "raw",
    "rendered",
]

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from html import escape
from string.templatelib import Template, convert

_ATTRIBUTE_NAME = re.compile(r"[A-Za-z_:][A-Za-z0-9:._-]*")
_URL_ATTRIBUTES = frozenset(
    {
        "action",
        "background",
        "cite",
        "formaction",
        "href",
        "longdesc",
        "manifest",
        "ping",
        "poster",
        "profile",
        "src",
        "srcset",
        "usemap",
        "xlink:href",
    }
)
_UNSAFE_URL_SCHEMES = ("data:", "javascript:", "vbscript:")


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
    dynamics: tuple[str, ...]

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) for value in self.statics):
            raise TypeError("static fragments must be strings")
        if not all(isinstance(value, str) for value in self.dynamics):
            raise TypeError("dynamic fragments must be strings")
        if len(self.statics) != len(self.dynamics) + 1:
            raise ValueError("Rendered requires exactly one more static than dynamic")

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.statics, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()

    def to_html(self) -> str:
        return "".join(
            static + (self.dynamics[index] if index < len(self.dynamics) else "")
            for index, static in enumerate(self.statics)
        )

    def diff(self, previous: Rendered) -> dict[int, str] | None:
        if self.fingerprint != previous.fingerprint:
            return None
        return {
            index: value
            for index, value in enumerate(self.dynamics)
            if value != previous.dynamics[index]
        }


def _dynamic(value: object) -> str:
    if isinstance(value, SafeHtml):
        return value.value
    if isinstance(value, Rendered):
        return value.to_html()
    if isinstance(value, Template):
        return html(value).to_html()
    return escape(str(value), quote=True)


def html(template: Template) -> Rendered:
    if not isinstance(template, Template):
        raise TypeError("template must be a Template")
    dynamics: list[str] = []
    for interpolation in template.interpolations:
        value = convert(interpolation.value, interpolation.conversion)
        if interpolation.format_spec:
            value = format(value, interpolation.format_spec)
        dynamics.append(_dynamic(value))
    return Rendered(template.strings, tuple(dynamics))


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


def _unsafe_url_scheme(value: object) -> bool:
    normalized = "".join(
        character for character in str(value).lower() if ord(character) > 0x20
    )
    return normalized.startswith(_UNSAFE_URL_SCHEMES)


def _unsafe_url(name: str, value: object) -> bool:
    if _unsafe_url_scheme(value):
        return True
    if name == "ping":
        candidates = str(value).split()
    elif name == "srcset":
        candidates = (
            candidate for candidate in str(value).split(",") if candidate.strip()
        )
    else:
        return False
    return any(_unsafe_url_scheme(candidate) for candidate in candidates)


def attrs(values: Mapping[str, object], /) -> SafeHtml:
    if not isinstance(values, Mapping):
        raise TypeError("attributes must be a mapping")
    encoded: list[str] = []
    for name, value in values.items():
        if not isinstance(name, str):
            raise TypeError("attribute names must be strings")
        normalized = name.lower()
        if (
            _ATTRIBUTE_NAME.fullmatch(name) is None
            or normalized.startswith("on")
            or normalized in {"srcdoc", "style"}
        ):
            raise ValueError(f"unsafe HTML attribute name: {name!r}")
        if value is None or value is False:
            continue
        if value is True:
            encoded.append(f" {name}")
        else:
            if normalized in _URL_ATTRIBUTES and _unsafe_url(normalized, value):
                raise ValueError(f"unsafe URL scheme for HTML attribute: {name!r}")
            encoded.append(f' {name}="{escape(str(value), quote=True)}"')
    return SafeHtml("".join(encoded))


def rendered(statics: tuple[str, ...], *values: object) -> Rendered:
    return Rendered(tuple(statics), tuple(_dynamic(value) for value in values))


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

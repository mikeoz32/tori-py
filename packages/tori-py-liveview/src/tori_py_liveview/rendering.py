from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from html import escape
from string.templatelib import Template, convert


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


def rendered(statics: tuple[str, ...], *values: object) -> Rendered:
    return Rendered(tuple(statics), tuple(_dynamic(value) for value in values))


__all__ = ["Rendered", "SafeHtml", "fragment", "html", "raw", "rendered"]

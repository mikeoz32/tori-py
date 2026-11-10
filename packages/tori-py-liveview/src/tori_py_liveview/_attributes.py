"""HTML attribute safety rules shared by rendering and JS commands."""

from __future__ import annotations

import re

ATTRIBUTE_NAME = re.compile(r"[A-Za-z_:][A-Za-z0-9:._-]*")
URL_ATTRIBUTES = frozenset(
    {
        "action",
        "background",
        "cite",
        "data",
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
# Phoenix never runs these phx-* values as JS commands.
_PHX_DATA_ATTRIBUTES = frozenset({"phx-target", "phx-key", "phx-disable-with"})


def phx_command_attribute(name: str) -> bool:
    """Whether Phoenix runs a value of this attribute starting with ``[`` as JS."""
    normalized = name.lower()
    return (
        normalized.startswith("phx-")
        and not normalized.startswith("phx-value-")
        and normalized not in _PHX_DATA_ATTRIBUTES
    )


def unsafe_attribute_name(name: str) -> bool:
    normalized = name.lower()
    return (
        ATTRIBUTE_NAME.fullmatch(name) is None
        or normalized.startswith("on")
        or normalized in {"srcdoc", "style"}
    )


def _unsafe_url_scheme(value: str) -> bool:
    normalized = "".join(
        character for character in value.lower() if ord(character) > 0x20
    )
    return normalized.startswith(_UNSAFE_URL_SCHEMES)


def unsafe_url(name: str, value: str) -> bool:
    if name not in URL_ATTRIBUTES:
        return False
    if _unsafe_url_scheme(value):
        return True
    if name == "ping":
        candidates = value.split()
    elif name == "srcset":
        candidates = (candidate for candidate in value.split(",") if candidate.strip())
    else:
        return False
    return any(_unsafe_url_scheme(candidate) for candidate in candidates)

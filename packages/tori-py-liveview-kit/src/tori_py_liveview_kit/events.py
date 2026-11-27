"""What a model produces while it writes a reply.

Python argument types are checked statically. Constructors enforce semantic
constraints such as non-empty names, token ranges, and safe citation URLs.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

_MAX_TOKENS = 10**12


def _nonempty(owner: str, name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{owner} {name} cannot be empty")


def _token_count(name: str, value: int) -> None:
    if not 0 <= value <= _MAX_TOKENS:
        raise ValueError(f"Usage {name} must be from 0 through {_MAX_TOKENS}")


@dataclass(frozen=True, slots=True)
class TextDelta:
    """A piece of the answer, in Markdown."""

    text: str


@dataclass(frozen=True, slots=True)
class ReasoningDelta:
    """A piece of the model's reasoning."""

    text: str


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool the model calls.

    ``arguments`` is shown as preformatted text, so serialize JSON before you
    yield. A second ``ToolCall`` with the same ``id`` replaces the name and the
    arguments of the first.
    """

    id: str
    name: str
    arguments: str = ""

    def __post_init__(self) -> None:
        _nonempty("ToolCall", "id", self.id)
        _nonempty("ToolCall", "name", self.name)


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What the tool call with this ``id`` returned."""

    id: str
    content: str = ""
    is_error: bool = False

    def __post_init__(self) -> None:
        _nonempty("ToolResult", "id", self.id)


@dataclass(frozen=True, slots=True)
class Citation:
    """A source the answer cites.

    A model chooses the address, so it must be an absolute ``http`` or
    ``https`` URL.
    """

    title: str
    url: str

    def __post_init__(self) -> None:
        _nonempty("Citation", "title", self.title)
        try:
            parsed = urlsplit(self.url)
            absolute = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
        except ValueError:
            absolute = False
        if not absolute or any(character.isspace() for character in self.url):
            raise ValueError("Citation url must be an absolute http or https URL")


@dataclass(frozen=True, slots=True)
class Usage:
    """What the reply consumed. The last ``Usage`` of a reply wins."""

    input_tokens: int
    output_tokens: int
    cost: str | None = None

    def __post_init__(self) -> None:
        _token_count("input_tokens", self.input_tokens)
        _token_count("output_tokens", self.output_tokens)
        if self.cost is not None:
            _nonempty("Usage", "cost", self.cost)


@dataclass(frozen=True, slots=True)
class Error:
    """End the reply as failed and show ``message`` to the visitor."""

    message: str

    def __post_init__(self) -> None:
        _nonempty("Error", "message", self.message)


type ChatEvent = (
    TextDelta | ReasoningDelta | ToolCall | ToolResult | Citation | Usage | Error
)

__all__ = [
    "ChatEvent",
    "Citation",
    "Error",
    "ReasoningDelta",
    "TextDelta",
    "ToolCall",
    "ToolResult",
    "Usage",
]

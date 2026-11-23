"""What a model produces while it writes a reply.

An event checks its fields when it is created. A malformed event then fails in
the model task, where the failure becomes an error reply, and never in a page
callback.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

_MAX_TOKENS = 10**12


def _text(owner: str, name: str, value: object) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{owner} {name} must be a string")


def _nonempty(owner: str, name: str, value: object) -> None:
    _text(owner, name, value)
    if not str(value).strip():
        raise ValueError(f"{owner} {name} cannot be empty")


def _token_count(name: str, value: object) -> None:
    if type(value) is not int:
        raise TypeError(f"Usage {name} must be an integer")
    if not 0 <= value <= _MAX_TOKENS:
        raise ValueError(f"Usage {name} must be from 0 through {_MAX_TOKENS}")


@dataclass(frozen=True, slots=True)
class TextDelta:
    """A piece of the answer, in Markdown."""

    text: str

    def __post_init__(self) -> None:
        _text("TextDelta", "text", self.text)


@dataclass(frozen=True, slots=True)
class ReasoningDelta:
    """A piece of the model's reasoning."""

    text: str

    def __post_init__(self) -> None:
        _text("ReasoningDelta", "text", self.text)


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
        _text("ToolCall", "arguments", self.arguments)


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What the tool call with this ``id`` returned."""

    id: str
    content: str = ""
    is_error: bool = False

    def __post_init__(self) -> None:
        _nonempty("ToolResult", "id", self.id)
        _text("ToolResult", "content", self.content)
        if type(self.is_error) is not bool:
            raise TypeError("ToolResult is_error must be a boolean")


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
        _text("Citation", "url", self.url)
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

EVENT_TYPES = (
    TextDelta,
    ReasoningDelta,
    ToolCall,
    ToolResult,
    Citation,
    Usage,
    Error,
)

__all__ = [
    "EVENT_TYPES",
    "ChatEvent",
    "Citation",
    "Error",
    "ReasoningDelta",
    "TextDelta",
    "ToolCall",
    "ToolResult",
    "Usage",
]

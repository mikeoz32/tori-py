"""The messages of a conversation, and how events build a reply."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Literal

from tori_py_liveview_kit.events import (
    ChatEvent,
    Citation,
    Error,
    ReasoningDelta,
    TextDelta,
    ToolCall,
    ToolResult,
    Usage,
)

type ReplyStatus = Literal["streaming", "done", "stopped", "error"]


def _message_id(owner: str, value: str) -> None:
    # The ID is a DOM ID and a LiveView stream item ID.
    if not value:
        raise ValueError(f"{owner} id cannot be empty")
    if any(
        character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F
        for character in value
    ):
        raise ValueError(f"{owner} id cannot contain whitespace or control characters")


@dataclass(frozen=True, slots=True)
class TextPart:
    """A run of answer text, in Markdown."""

    text: str


@dataclass(frozen=True, slots=True)
class ReasoningPart:
    """A run of the model's reasoning."""

    text: str


@dataclass(frozen=True, slots=True)
class ToolPart:
    """A tool call; ``result`` is ``None`` until the tool has answered."""

    id: str
    name: str
    arguments: str = ""
    result: str | None = None
    is_error: bool = False

    def __post_init__(self) -> None:
        for name, value in (("id", self.id), ("name", self.name)):
            if not value.strip():
                raise ValueError(f"ToolPart {name} cannot be empty")


type MessagePart = TextPart | ReasoningPart | ToolPart


@dataclass(frozen=True, slots=True)
class UserMessage:
    """What the visitor wrote."""

    id: str
    text: str

    def __post_init__(self) -> None:
        _message_id("UserMessage", self.id)

    @property
    def role(self) -> Literal["user"]:
        return "user"


@dataclass(frozen=True, slots=True)
class AssistantMessage:
    """A reply, finished or still being written.

    ``parts`` keep the order in which the model produced them. ``error`` is
    the text shown for a reply whose ``status`` is ``error``.
    """

    id: str
    parts: tuple[MessagePart, ...] = ()
    status: ReplyStatus = "done"
    citations: tuple[Citation, ...] = ()
    usage: Usage | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        _message_id("AssistantMessage", self.id)

    @property
    def role(self) -> Literal["assistant"]:
        return "assistant"

    @property
    def text(self) -> str:
        """The answer text, with a blank line between separate text parts."""
        return "\n\n".join(
            part.text for part in self.parts if isinstance(part, TextPart) and part.text
        )


type Message = UserMessage | AssistantMessage


@dataclass(slots=True)
class _ToolSlot:
    index: int
    part: ToolPart


@dataclass(slots=True)
class _TextTail:
    part: TextPart | ReasoningPart
    fragments: list[str]


class _Builder:
    """Collect one batch; deltas are joined once when the batch ends."""

    def __init__(self, reply: AssistantMessage) -> None:
        self._reply = reply
        self._parts: list[MessagePart] = list(reply.parts)
        # Fragments of the last part while this batch extends it.
        self._tail: _TextTail | None = None
        self._tools = {
            part.id: _ToolSlot(index, part)
            for index, part in enumerate(self._parts)
            if isinstance(part, ToolPart)
        }
        self._citations = list(reply.citations)
        self._urls = {citation.url for citation in reply.citations}
        self._usage = reply.usage
        self._error: str | None = None

    def apply(self, event: ChatEvent) -> bool:
        """Apply one event; false once the reply has ended."""
        match event:
            case TextDelta(text=text):
                self._delta(TextPart, text)
            case ReasoningDelta(text=text):
                self._delta(ReasoningPart, text)
            case ToolCall(id=tool_id, name=name, arguments=arguments):
                slot = self._tools.get(tool_id)
                if slot is None:
                    self._append(ToolPart(tool_id, name, arguments))
                else:
                    self._replace_tool(
                        slot, replace(slot.part, name=name, arguments=arguments)
                    )
            case ToolResult(id=tool_id, content=content, is_error=is_error):
                slot = self._tools.get(tool_id)
                if slot is None:
                    self._append(ToolPart(tool_id, "tool", "", content, is_error))
                else:
                    self._replace_tool(
                        slot, replace(slot.part, result=content, is_error=is_error)
                    )
            case Citation(url=url):
                if url not in self._urls:
                    self._urls.add(url)
                    self._citations.append(event)
            case Usage():
                self._usage = event
            case Error(message=message):
                self._error = message
                return False
        return True

    def _delta(self, kind: type[TextPart] | type[ReasoningPart], text: str) -> None:
        if not text:
            return
        last = self._parts[-1] if self._parts else None
        match last:
            case TextPart() | ReasoningPart() if type(last) is kind:
                part = last
            case _:
                part = kind("")
                self._append(part)
        if self._tail is None:
            self._tail = _TextTail(part, [part.text])
        self._tail.fragments.append(text)

    def _replace_tool(self, slot: _ToolSlot, part: ToolPart) -> None:
        self._parts[slot.index] = part
        slot.part = part

    def _append(self, part: MessagePart) -> None:
        self._close()
        if isinstance(part, ToolPart):
            self._tools[part.id] = _ToolSlot(len(self._parts), part)
        self._parts.append(part)

    def _close(self) -> None:
        if self._tail is None:
            return
        self._parts[-1] = replace(self._tail.part, text="".join(self._tail.fragments))
        self._tail = None

    def build(self) -> AssistantMessage:
        self._close()
        return replace(
            self._reply,
            parts=tuple(self._parts),
            citations=tuple(self._citations),
            usage=self._usage,
            status="streaming" if self._error is None else "error",
            error=self._error,
        )


def fold_events(
    reply: AssistantMessage, events: Iterable[ChatEvent]
) -> AssistantMessage:
    """Fold a batch of events into a reply that is still being written.

    A reply that has ended is returned unchanged, and nothing after an
    ``Error`` in the batch is applied.
    """
    if reply.status != "streaming":
        return reply
    builder = _Builder(reply)
    for event in events:
        if not builder.apply(event):
            break
    return builder.build()


__all__ = [
    "AssistantMessage",
    "Message",
    "MessagePart",
    "ReasoningPart",
    "ReplyStatus",
    "TextPart",
    "ToolPart",
    "UserMessage",
    "fold_events",
]

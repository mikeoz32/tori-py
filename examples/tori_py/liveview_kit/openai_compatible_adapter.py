"""Map an OpenAI-compatible Chat Completions stream to LiveView Kit events.

This adapter is an example, not part of `tori-py-liveview-kit`: copy it into
your application and change it. It is for servers that speak the Chat
Completions streaming format, which is how local model servers such as Ollama,
vLLM, and LM Studio are usually reached. It needs the `openai` SDK, which the
kit does not depend on:

    uv add openai

    client = AsyncOpenAI(base_url="http://localhost:11434/v1", api_key="local")

Text becomes `TextDelta`, tool calls become `ToolCall` and `ToolResult`, and
the token counts become one `Usage` when the server reports them. Reasoning is
not part of the format; servers that send it use a `reasoning_content` or
`reasoning` field, which becomes `ReasoningDelta`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field

from openai import AsyncOpenAI, omit
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallParam,
    ChatCompletionToolParam,
)
from tori_py_liveview_kit import (
    AssistantMessage,
    ChatEvent,
    Error,
    Message,
    ReasoningDelta,
    TextDelta,
    ToolCall,
    ToolResult,
    Usage,
)

_LOGGER = logging.getLogger(__name__)

type ToolRunner = Callable[[str, dict[str, object]], Awaitable[str]]


@dataclass(slots=True)
class _Call:
    id: str = ""
    name: str = ""
    arguments: list[str] = field(default_factory=list)
    event_id: str = ""

    def identify(self, used: set[str]) -> str:
        """Keep a reply-wide Kit ID independently of the provider's wire ID."""
        if not self.event_id:
            candidate = self.id or f"call-{len(used)}"
            suffix = len(used)
            while candidate in used:
                suffix += 1
                candidate = f"call-{suffix}"
            self.event_id = candidate
            used.add(candidate)
        return self.event_id


def to_chat_messages(
    messages: Sequence[Message], system: str | None = None
) -> list[ChatCompletionMessageParam]:
    """Return the conversation as text turns, after an optional system turn.

    A reply contributes its text; a reply without text is left out, and
    earlier reasoning and tool calls are not sent back.
    """
    turns: list[ChatCompletionMessageParam] = []
    if system is not None:
        turns.append({"role": "system", "content": system})
    for message in messages:
        if isinstance(message, AssistantMessage):
            if message.text:
                turns.append({"role": "assistant", "content": message.text})
        else:
            turns.append({"role": "user", "content": message.text})
    return turns


async def chat_completion_events(
    client: AsyncOpenAI,
    messages: Sequence[Message],
    *,
    model: str,
    system: str | None = None,
    tools: Iterable[ChatCompletionToolParam] = (),
    run_tool: ToolRunner | None = None,
) -> AsyncIterator[ChatEvent]:
    """Stream one reply to the last message of ``messages``.

    ``run_tool(name, arguments)`` runs one of your tools and returns its
    result as text; it must check its arguments, because the model wrote
    them. The request asks for token counts with ``stream_options``, which a
    server may not support.
    """
    history = to_chat_messages(messages, system)
    declared = list(tools)
    prompt_tokens = completion_tokens = 0
    counted = False
    used_call_ids: set[str] = set()
    while True:
        calls: dict[int, _Call] = {}
        text: list[str] = []
        finish: str | None = None
        stream = await client.chat.completions.create(
            model=model,
            messages=history,
            stream=True,
            stream_options={"include_usage": True},
            tools=declared or omit,
        )
        async with stream:
            async for chunk in stream:
                if chunk.usage is not None:
                    counted = True
                    prompt_tokens += chunk.usage.prompt_tokens
                    completion_tokens += chunk.usage.completion_tokens
                for choice in chunk.choices[:1]:
                    delta = choice.delta
                    # Not in the format; several servers send one of the two.
                    reasoning = getattr(delta, "reasoning_content", None) or getattr(
                        delta, "reasoning", None
                    )
                    if isinstance(reasoning, str) and reasoning:
                        yield ReasoningDelta(reasoning)
                    if delta.content:
                        text.append(delta.content)
                        yield TextDelta(delta.content)
                    for fragment in delta.tool_calls or ():
                        call = calls.setdefault(fragment.index, _Call())
                        call.id = call.id or fragment.id or ""
                        if fragment.function is not None:
                            call.name = call.name or fragment.function.name or ""
                            if fragment.function.arguments:
                                call.arguments.append(fragment.function.arguments)
                        if call.id and call.name:
                            yield ToolCall(
                                call.identify(used_call_ids),
                                call.name,
                                "".join(call.arguments),
                            )
                    if choice.finish_reason is not None:
                        finish = choice.finish_reason

        usage = [Usage(prompt_tokens, completion_tokens)] if counted else []
        if finish == "length":
            # A tool call cut off here has incomplete arguments; do not run it.
            for event in usage:
                yield event
            yield Error("The reply was cut off at the output limit.")
            return
        if finish == "content_filter":
            for event in usage:
                yield event
            yield Error("The model declined to answer this request.")
            return
        if not calls:
            for event in usage:
                yield event
            return
        if run_tool is None:
            for event in usage:
                yield event
            yield Error("The model called a tool that this application does not run.")
            return

        requested = [calls[index] for index in sorted(calls)]
        echoed: list[ChatCompletionMessageToolCallParam] = []
        for call in requested:
            # A server may leave out the ID; the two turns only have to agree.
            call.id = call.id or call.identify(used_call_ids)
            call.name = call.name or "tool"
            echoed.append(
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": "".join(call.arguments),
                    },
                }
            )
        history.append(
            {
                "role": "assistant",
                "content": "".join(text) or None,
                "tool_calls": echoed,
            }
        )
        for call in requested:
            written = "".join(call.arguments)
            event_id = call.identify(used_call_ids)
            yield ToolCall(event_id, call.name, written)
            try:
                arguments = json.loads(written or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError("tool arguments must be a JSON object")
                output = await run_tool(call.name, arguments)
                failed = False
            except Exception:
                # The model and the visitor both read a tool result, so the
                # exception stays in the log.
                _LOGGER.exception("tool %s failed", call.name)
                output = json.dumps({"error": "The tool failed."})
                failed = True
            yield ToolResult(event_id, output, is_error=failed)
            history.append({"role": "tool", "tool_call_id": call.id, "content": output})


__all__ = ["ToolRunner", "chat_completion_events", "to_chat_messages"]

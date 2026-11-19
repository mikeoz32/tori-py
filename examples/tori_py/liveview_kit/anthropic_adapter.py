"""Map the Anthropic Messages stream to LiveView Kit events.

This adapter is an example, not part of `tori-py-liveview-kit`: copy it into
your application and change it. It needs the `anthropic` SDK, which the kit
does not depend on:

    uv add anthropic

The adapter streams one reply. Text becomes `TextDelta`, summarized thinking
becomes `ReasoningDelta`, tool calls become `ToolCall` and `ToolResult`, web
search citations become `Citation`, and the token counts become one `Usage`.
When the model calls one of your tools, the adapter runs `run_tool` and asks
the model to continue, until the model has no more calls.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field

from anthropic import AsyncAnthropic, omit
from anthropic.types.beta import (
    BetaMessageParam,
    BetaToolResultBlockParam,
    BetaToolUnionParam,
)
from tori_py_liveview_kit import (
    AssistantMessage,
    ChatEvent,
    Citation,
    Error,
    Message,
    ReasoningDelta,
    TextDelta,
    ToolCall,
    ToolResult,
    Usage,
)

_LOGGER = logging.getLogger(__name__)
# The API answers a declined request on a fallback model inside the same call.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

type ToolRunner = Callable[[str, dict[str, object]], Awaitable[str]]


@dataclass(slots=True)
class _Call:
    id: str
    name: str
    fragments: list[str] = field(default_factory=list)


def to_api_messages(messages: Sequence[Message]) -> list[BetaMessageParam]:
    """Return the conversation as text turns for the Messages API.

    Only what was said is replayed: a reply contributes its text, and a reply
    without text, such as one that failed before it wrote anything, is left
    out. Earlier reasoning and tool calls are not sent back.
    """
    turns: list[BetaMessageParam] = []
    for message in messages:
        if isinstance(message, AssistantMessage):
            if message.text:
                turns.append({"role": "assistant", "content": message.text})
        else:
            turns.append({"role": "user", "content": message.text})
    return turns


async def anthropic_events(
    client: AsyncAnthropic,
    messages: Sequence[Message],
    *,
    model: str = "claude-opus-5-5",
    system: str | None = None,
    max_tokens: int = 64000,
    tools: Iterable[BetaToolUnionParam] = (),
    run_tool: ToolRunner | None = None,
) -> AsyncIterator[ChatEvent]:
    """Stream one reply to the last message of ``messages``.

    ``tools`` are Messages API tool definitions. ``run_tool(name, arguments)``
    runs one of your own tools and returns its result as text; it must check
    its arguments, because the model wrote them. Tools that Anthropic runs,
    such as web search, need no ``run_tool``.
    """
    history = to_api_messages(messages)
    declared = list(tools)
    input_tokens = output_tokens = 0
    while True:
        calls: dict[int, _Call] = {}
        async with client.beta.messages.stream(
            model=model,
            max_tokens=max_tokens,
            messages=history,
            # Thinking text is empty unless the request asks for a summary.
            thinking={"type": "adaptive", "display": "summarized"},
            betas=[_FALLBACK_BETA],
            fallbacks="default",
            system=omit if system is None else system,
            tools=declared or omit,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use" or block.type == "server_tool_use":
                        calls[event.index] = _Call(block.id, block.name)
                        yield ToolCall(block.id, block.name)
                    elif block.type == "web_search_tool_result":
                        if isinstance(block.content, list):
                            found = "\n".join(result.url for result in block.content)
                            yield ToolResult(block.tool_use_id, found)
                        else:
                            yield ToolResult(
                                block.tool_use_id,
                                block.content.error_code,
                                is_error=True,
                            )
                elif event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        yield TextDelta(delta.text)
                    elif delta.type == "thinking_delta":
                        yield ReasoningDelta(delta.thinking)
                    elif delta.type == "input_json_delta":
                        call = calls.get(event.index)
                        if call is not None:
                            call.fragments.append(delta.partial_json)
                            yield ToolCall(call.id, call.name, "".join(call.fragments))
                    elif delta.type == "citations_delta":
                        cited = delta.citation
                        if cited.type == "web_search_result_location":
                            try:
                                yield Citation(cited.title or cited.url, cited.url)
                            except ValueError:
                                # Not an address the page would link to.
                                pass
            reply = await stream.get_final_message()

        # Deltas contain cumulative snapshots, including updated input counts
        # after a fallback. Count the final snapshot once per API response.
        input_tokens += reply.usage.input_tokens
        output_tokens += reply.usage.output_tokens

        if reply.stop_reason == "pause_turn":
            # A tool Anthropic runs reached its limit; the same turn goes on.
            history.append({"role": "assistant", "content": reply.content})
            continue
        if reply.stop_reason == "refusal":
            yield Usage(input_tokens, output_tokens)
            yield Error("The model declined to answer this request.")
            return
        if reply.stop_reason == "max_tokens":
            # A tool call cut off here has incomplete arguments; do not run it.
            yield Usage(input_tokens, output_tokens)
            yield Error("The reply was cut off at the output limit.")
            return
        requested = [block for block in reply.content if block.type == "tool_use"]
        if not requested:
            break
        if run_tool is None:
            yield Usage(input_tokens, output_tokens)
            yield Error("The model called a tool that this application does not run.")
            return
        results: list[BetaToolResultBlockParam] = []
        for block in requested:
            try:
                output = await run_tool(block.name, block.input)
                failed = False
            except Exception:
                # The model and the visitor both read a tool result, so the
                # exception stays in the log.
                _LOGGER.exception("tool %s failed", block.name)
                output = json.dumps({"error": "The tool failed."})
                failed = True
            yield ToolResult(block.id, output, is_error=failed)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                    "is_error": failed,
                }
            )
        history.append({"role": "assistant", "content": reply.content})
        # Every result of one turn goes back in a single user message.
        history.append({"role": "user", "content": results})
    yield Usage(input_tokens, output_tokens)


__all__ = ["ToolRunner", "anthropic_events", "to_api_messages"]

"""The example Anthropic adapter, fed stream events in their wire format."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("anthropic")

from anthropic import omit  # noqa: E402
from anthropic.types.beta import BetaMessage, BetaRawMessageStreamEvent  # noqa: E402
from pydantic import TypeAdapter  # noqa: E402
from tori_py_liveview_kit import (  # noqa: E402
    AssistantMessage,
    ChatEvent,
    Citation,
    Error,
    ReasoningDelta,
    TextDelta,
    TextPart,
    ToolCall,
    ToolPart,
    ToolResult,
    Usage,
    UserMessage,
)

from examples.tori_py.liveview_kit.anthropic_adapter import (  # noqa: E402
    anthropic_events,
    to_api_messages,
)

_EVENT = TypeAdapter(BetaRawMessageStreamEvent)
_QUESTION = (UserMessage("turn-1-user", "What is the weather in Kyiv?"),)


def _message(
    content: list[dict[str, Any]], stop_reason: str, *, tokens: tuple[int, int]
) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]},
    }


def _start(index: int, block: dict[str, Any]) -> dict[str, Any]:
    return {"type": "content_block_start", "index": index, "content_block": block}


def _delta(index: int, delta: dict[str, Any]) -> dict[str, Any]:
    return {"type": "content_block_delta", "index": index, "delta": delta}


class _Stream:
    """One scripted response: its events, then its final message."""

    def __init__(
        self,
        blocks: list[dict[str, Any]],
        final: list[dict[str, Any]],
        stop_reason: str = "end_turn",
        tokens: tuple[int, int] = (10, 5),
    ) -> None:
        events = [
            {
                "type": "message_start",
                "message": _message([], "end_turn", tokens=(tokens[0], 0)),
            },
            *blocks,
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": tokens[1]},
            },
            {"type": "message_stop"},
        ]
        self._events = [_EVENT.validate_python(event) for event in events]
        self._final = BetaMessage.model_validate(
            _message(final, stop_reason, tokens=tokens)
        )

    async def __aenter__(self) -> _Stream:
        return self

    async def __aexit__(self, *error: object) -> None:
        return None

    async def __aiter__(self):
        for event in self._events:
            yield event

    async def get_final_message(self) -> BetaMessage:
        return self._final


class _Client:
    """Stands in for ``AsyncAnthropic``: hands out the scripted streams."""

    def __init__(self, *streams: _Stream) -> None:
        self._streams = list(streams)
        self.requests: list[dict[str, Any]] = []
        self.beta = self
        self.messages = self

    def stream(self, **request: Any) -> _Stream:
        # The adapter extends one history list, so keep what this call saw.
        self.requests.append({**request, "messages": list(request["messages"])})
        return self._streams.pop(0)


async def _events(client: _Client, **options: Any) -> list[ChatEvent]:
    return [
        event
        async for event in anthropic_events(
            client,  # ty: ignore[invalid-argument-type]
            _QUESTION,
            **options,
        )
    ]


@pytest.mark.asyncio
async def test_usage_counts_the_final_response_snapshot_once() -> None:
    stream = _text_turn(tokens=(10, 5))
    stream._events.insert(
        -2,
        _EVENT.validate_python(
            {
                "type": "message_delta",
                "delta": {"stop_reason": None, "stop_sequence": None},
                "usage": {"output_tokens": 2},
            }
        ),
    )
    # A fallback can update the input count after message_start.
    stream._final.usage.input_tokens = 42
    events = await _events(_Client(stream))
    assert events[-1] == Usage(42, 5)


_TEXT = {"type": "text", "text": "", "citations": None}
_TOOL_USE = {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {}}


def _tool_turn() -> _Stream:
    return _Stream(
        [
            _start(0, _TOOL_USE),
            _delta(0, {"type": "input_json_delta", "partial_json": '{"city":'}),
            _delta(0, {"type": "input_json_delta", "partial_json": ' "Kyiv"}'}),
            {"type": "content_block_stop", "index": 0},
        ],
        [{**_TOOL_USE, "input": {"city": "Kyiv"}}],
        "tool_use",
        tokens=(30, 20),
    )


def _text_turn(text: str = "Sunny.", tokens: tuple[int, int] = (60, 4)) -> _Stream:
    return _Stream(
        [
            _start(0, _TEXT),
            _delta(0, {"type": "text_delta", "text": text}),
            {"type": "content_block_stop", "index": 0},
        ],
        [{**_TEXT, "text": text}],
        tokens=tokens,
    )


@pytest.mark.asyncio
async def test_text_and_summarized_thinking_become_deltas_and_one_usage() -> None:
    thinking = {"type": "thinking", "thinking": "", "signature": ""}
    client = _Client(
        _Stream(
            [
                _start(0, thinking),
                _delta(0, {"type": "thinking_delta", "thinking": "A greeting."}),
                _delta(0, {"type": "signature_delta", "signature": "sig"}),
                {"type": "content_block_stop", "index": 0},
                _start(1, _TEXT),
                _delta(1, {"type": "text_delta", "text": "Hello"}),
                _delta(1, {"type": "text_delta", "text": " there"}),
                {"type": "content_block_stop", "index": 1},
            ],
            [{**_TEXT, "text": "Hello there"}],
            tokens=(12, 7),
        )
    )

    events = await _events(client)

    assert events == [
        ReasoningDelta("A greeting."),
        TextDelta("Hello"),
        TextDelta(" there"),
        Usage(12, 7),
    ]
    (request,) = client.requests
    assert request["model"] == "claude-opus-5-5"
    assert request["messages"] == [
        {"role": "user", "content": "What is the weather in Kyiv?"}
    ]
    assert request["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert request["fallbacks"] == "default"
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    assert request["system"] is omit
    assert request["tools"] is omit


@pytest.mark.asyncio
async def test_a_tool_call_runs_and_the_model_continues() -> None:
    client = _Client(_tool_turn(), _text_turn())
    ran: list[tuple[str, dict[str, object]]] = []

    async def run_tool(name: str, arguments: dict[str, object]) -> str:
        ran.append((name, arguments))
        return "sunny, 21 C"

    tool = {
        "name": "get_weather",
        "description": "Weather",
        "input_schema": {"type": "object"},
    }
    events = await _events(client, system="Be brief.", tools=[tool], run_tool=run_tool)

    assert events == [
        ToolCall("toolu_1", "get_weather"),
        ToolCall("toolu_1", "get_weather", '{"city":'),
        ToolCall("toolu_1", "get_weather", '{"city": "Kyiv"}'),
        ToolResult("toolu_1", "sunny, 21 C"),
        TextDelta("Sunny."),
        Usage(90, 24),
    ]
    assert ran == [("get_weather", {"city": "Kyiv"})]
    first, second = client.requests
    assert first["system"] == "Be brief."
    assert first["tools"] == [tool]
    assert len(first["messages"]) == 1
    # The reply goes back as it came, followed by every result in one turn.
    assistant, results = second["messages"][1:]
    assert assistant["role"] == "assistant"
    assert [block.type for block in assistant["content"]] == ["tool_use"]
    assert results == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_1",
                "content": "sunny, 21 C",
                "is_error": False,
            }
        ],
    }


@pytest.mark.asyncio
async def test_a_failing_tool_is_reported_without_its_exception() -> None:
    client = _Client(_tool_turn(), _text_turn("I could not check."))

    async def run_tool(name: str, arguments: dict[str, object]) -> str:
        raise RuntimeError("key sk-secret rejected")

    events = await _events(client, run_tool=run_tool)

    assert events[3] == ToolResult("toolu_1", '{"error": "The tool failed."}', True)
    assert events[4] == TextDelta("I could not check.")
    assert "sk-secret" not in repr(events)
    assert "sk-secret" not in repr(client.requests)
    assert client.requests[1]["messages"][2]["content"][0]["is_error"] is True


@pytest.mark.asyncio
async def test_a_tool_call_without_a_runner_ends_the_reply() -> None:
    client = _Client(_tool_turn())

    events = await _events(client)

    assert events[-2:] == [
        Usage(30, 20),
        Error("The model called a tool that this application does not run."),
    ]
    assert len(client.requests) == 1


@pytest.mark.parametrize(
    ("stop_reason", "message"),
    [
        ("refusal", "The model declined to answer this request."),
        ("max_tokens", "The reply was cut off at the output limit."),
    ],
)
@pytest.mark.asyncio
async def test_a_reply_that_did_not_finish_ends_with_an_error(
    stop_reason: str, message: str
) -> None:
    client = _Client(
        _Stream(
            [_start(0, _TEXT), _delta(0, {"type": "text_delta", "text": "Part"})],
            [{**_TEXT, "text": "Part"}],
            stop_reason,
            tokens=(8, 3),
        )
    )

    assert await _events(client) == [TextDelta("Part"), Usage(8, 3), Error(message)]


@pytest.mark.asyncio
async def test_a_paused_turn_is_sent_back_and_continues() -> None:
    client = _Client(
        _Stream(
            [
                _start(0, _TEXT),
                _delta(0, {"type": "text_delta", "text": "Searching. "}),
            ],
            [{**_TEXT, "text": "Searching. "}],
            "pause_turn",
            tokens=(10, 2),
        ),
        _text_turn("Found it.", tokens=(15, 3)),
    )

    events = await _events(client)

    assert events == [TextDelta("Searching. "), TextDelta("Found it."), Usage(25, 5)]
    resumed = client.requests[1]["messages"]
    assert [turn["role"] for turn in resumed] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_web_search_becomes_a_tool_call_its_result_and_citations() -> None:
    search = {
        "type": "server_tool_use",
        "id": "srvtoolu_1",
        "name": "web_search",
        "input": {},
    }
    results = {
        "type": "web_search_tool_result",
        "tool_use_id": "srvtoolu_1",
        "content": [
            {
                "type": "web_search_result",
                "title": "Kyiv weather",
                "url": "https://example.com/kyiv",
                "encrypted_content": "x",
                "page_age": None,
            }
        ],
    }
    failed = {
        "type": "web_search_tool_result",
        "tool_use_id": "srvtoolu_2",
        "content": {
            "type": "web_search_tool_result_error",
            "error_code": "max_uses_exceeded",
        },
    }

    def cited(url: str, title: str | None) -> dict[str, Any]:
        return {
            "type": "citations_delta",
            "citation": {
                "type": "web_search_result_location",
                "url": url,
                "title": title,
                "cited_text": "Sunny",
                "encrypted_index": "i",
            },
        }

    client = _Client(
        _Stream(
            [
                _start(0, search),
                _delta(
                    0, {"type": "input_json_delta", "partial_json": '{"query": "kyiv"}'}
                ),
                _start(1, results),
                _start(2, failed),
                _start(3, {**_TEXT, "citations": []}),
                _delta(3, cited("https://example.com/kyiv", "Kyiv weather")),
                _delta(3, cited("https://example.com/untitled", None)),
                _delta(3, cited("ftp://example.com/file", "Not a web address")),
                _delta(3, {"type": "text_delta", "text": "Sunny."}),
            ],
            [{**_TEXT, "text": "Sunny."}],
        )
    )

    assert await _events(client) == [
        ToolCall("srvtoolu_1", "web_search"),
        ToolCall("srvtoolu_1", "web_search", '{"query": "kyiv"}'),
        ToolResult("srvtoolu_1", "https://example.com/kyiv"),
        ToolResult("srvtoolu_2", "max_uses_exceeded", True),
        Citation("Kyiv weather", "https://example.com/kyiv"),
        Citation("https://example.com/untitled", "https://example.com/untitled"),
        TextDelta("Sunny."),
        Usage(10, 5),
    ]


def test_the_conversation_is_replayed_as_text_turns() -> None:
    conversation = (
        UserMessage("turn-1-user", "Hi"),
        AssistantMessage(
            "turn-1-assistant",
            (ToolPart("call-1", "search", "{}", "ok"), TextPart("Hello!")),
        ),
        UserMessage("turn-2-user", "Fail"),
        AssistantMessage(
            "turn-2-assistant", status="error", error="Something went wrong."
        ),
        UserMessage("turn-3-user", "Again"),
    )

    assert to_api_messages(conversation) == [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": "Fail"},
        {"role": "user", "content": "Again"},
    ]

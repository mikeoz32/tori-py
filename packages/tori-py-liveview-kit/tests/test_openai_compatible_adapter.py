"""The example OpenAI-compatible adapter, fed chunks in their wire format."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("openai")

from openai import omit  # noqa: E402
from openai.types.chat import ChatCompletionChunk  # noqa: E402
from tori_py_liveview_kit import (  # noqa: E402
    AssistantMessage,
    ChatEvent,
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
from tori_py_liveview_kit.messages import fold_events  # noqa: E402

from examples.tori_py.liveview_kit.openai_compatible_adapter import (  # noqa: E402
    chat_completion_events,
    to_chat_messages,
)

_QUESTION = (UserMessage("turn-1-user", "What is the weather in Kyiv?"),)


def _chunk(
    delta: dict[str, Any] | None = None,
    *,
    finish: str | None = None,
    usage: tuple[int, int] | None = None,
) -> ChatCompletionChunk:
    choices = (
        []
        if delta is None
        else [{"index": 0, "delta": delta, "finish_reason": finish, "logprobs": None}]
    )
    return ChatCompletionChunk.model_validate(
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "local",
            "choices": choices,
            "usage": None
            if usage is None
            else {
                "prompt_tokens": usage[0],
                "completion_tokens": usage[1],
                "total_tokens": sum(usage),
            },
        }
    )


def _call(index: int, **fields: Any) -> dict[str, Any]:
    function = {key: fields[key] for key in ("name", "arguments") if key in fields}
    fragment: dict[str, Any] = {"index": index, "function": function}
    if "id" in fields:
        fragment.update(id=fields["id"], type="function")
    return {"tool_calls": [fragment]}


class _Stream:
    def __init__(self, chunks: list[ChatCompletionChunk]) -> None:
        self._chunks = chunks
        self.closed = False

    async def __aenter__(self) -> _Stream:
        return self

    async def __aexit__(self, *error: object) -> None:
        self.closed = True

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk


class _Client:
    """Stands in for ``AsyncOpenAI``: hands out the scripted streams."""

    def __init__(self, *responses: list[ChatCompletionChunk]) -> None:
        self.streams = [_Stream(chunks) for chunks in responses]
        self._pending = list(self.streams)
        self.requests: list[dict[str, Any]] = []
        self.chat = self
        self.completions = self

    async def create(self, **request: Any) -> _Stream:
        # The adapter extends one history list, so keep what this call saw.
        self.requests.append({**request, "messages": list(request["messages"])})
        return self._pending.pop(0)


async def _events(client: _Client, **options: Any) -> list[ChatEvent]:
    return [
        event
        async for event in chat_completion_events(
            client,  # ty: ignore[invalid-argument-type]
            _QUESTION,
            model="local",
            **options,
        )
    ]


def _tool_turn() -> list[ChatCompletionChunk]:
    return [
        _chunk({"role": "assistant", "content": None}),
        _chunk(_call(0, id="call_1", name="get_weather", arguments="")),
        _chunk(_call(0, arguments='{"city":')),
        _chunk(_call(0, arguments=' "Kyiv"}'), finish="tool_calls"),
        _chunk(usage=(30, 20)),
    ]


def _text_turn(text: str = "Sunny.") -> list[ChatCompletionChunk]:
    return [_chunk({"content": text}, finish="stop"), _chunk(usage=(60, 4))]


@pytest.mark.asyncio
async def test_text_reasoning_and_usage() -> None:
    client = _Client(
        [
            _chunk({"role": "assistant", "content": ""}),
            _chunk({"reasoning_content": "A greeting."}),
            _chunk({"reasoning": "Keep it short."}),
            _chunk({"content": "Hello"}),
            _chunk({"content": " there"}, finish="stop"),
            _chunk(usage=(12, 7)),
        ]
    )

    events = await _events(client, system="Be brief.")

    assert events == [
        ReasoningDelta("A greeting."),
        ReasoningDelta("Keep it short."),
        TextDelta("Hello"),
        TextDelta(" there"),
        Usage(12, 7),
    ]
    (request,) = client.requests
    assert request["model"] == "local"
    assert request["stream"] is True
    assert request["stream_options"] == {"include_usage": True}
    assert request["tools"] is omit
    assert request["messages"] == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "What is the weather in Kyiv?"},
    ]
    assert client.streams[0].closed


@pytest.mark.asyncio
async def test_a_server_that_reports_no_usage_yields_none() -> None:
    client = _Client([_chunk({"content": "Hi"}, finish="stop")])

    assert await _events(client) == [TextDelta("Hi")]


@pytest.mark.asyncio
async def test_a_tool_call_runs_and_the_model_continues() -> None:
    client = _Client(_tool_turn(), _text_turn())
    ran: list[tuple[str, dict[str, object]]] = []

    async def run_tool(name: str, arguments: dict[str, object]) -> str:
        ran.append((name, arguments))
        return "sunny, 21 C"

    tool = {"type": "function", "function": {"name": "get_weather", "parameters": {}}}
    events = await _events(client, tools=[tool], run_tool=run_tool)

    assert events == [
        ToolCall("call_1", "get_weather"),
        ToolCall("call_1", "get_weather", '{"city":'),
        ToolCall("call_1", "get_weather", '{"city": "Kyiv"}'),
        ToolCall("call_1", "get_weather", '{"city": "Kyiv"}'),
        ToolResult("call_1", "sunny, 21 C"),
        TextDelta("Sunny."),
        Usage(90, 24),
    ]
    assert ran == [("get_weather", {"city": "Kyiv"})]
    first, second = client.requests
    assert first["tools"] == [tool]
    assert second["messages"][1:] == [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"city": "Kyiv"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "sunny, 21 C"},
    ]


@pytest.mark.parametrize("arguments", ['{"city": ', "[1, 2]"])
@pytest.mark.asyncio
async def test_arguments_that_are_not_a_json_object_fail_the_call(
    arguments: str,
) -> None:
    client = _Client(
        [
            _chunk(_call(0, id="call_1", name="get_weather", arguments=arguments)),
            _chunk({}, finish="tool_calls"),
        ],
        _text_turn("I could not check."),
    )
    ran: list[str] = []

    async def run_tool(name: str, arguments: dict[str, object]) -> str:
        ran.append(name)
        return "never"

    events = await _events(client, run_tool=run_tool)

    assert ran == []
    assert ToolResult("call_1", '{"error": "The tool failed."}', True) in events
    # The model hears about the failure and answers.
    assert events[-2:] == [TextDelta("I could not check."), Usage(60, 4)]


@pytest.mark.asyncio
async def test_a_failing_tool_is_reported_without_its_exception() -> None:
    client = _Client(_tool_turn(), _text_turn("I could not check."))

    async def run_tool(name: str, arguments: dict[str, object]) -> str:
        raise RuntimeError("key sk-secret rejected")

    events = await _events(client, run_tool=run_tool)

    assert ToolResult("call_1", '{"error": "The tool failed."}', True) in events
    assert "sk-secret" not in repr(events)
    assert "sk-secret" not in repr(client.requests)


@pytest.mark.asyncio
async def test_a_call_without_an_id_gets_one_both_turns_agree_on() -> None:
    client = _Client(
        [
            _chunk(_call(0, name="get_weather", arguments="{}")),
            _chunk({}, finish="tool_calls"),
        ],
        _text_turn(),
    )

    async def run_tool(name: str, arguments: dict[str, object]) -> str:
        return "ok"

    events = await _events(client, run_tool=run_tool)

    assert events[:2] == [
        ToolCall("call-0", "get_weather", "{}"),
        ToolResult("call-0", "ok"),
    ]
    assistant, result = client.requests[1]["messages"][1:]
    assert assistant["tool_calls"][0]["id"] == "call-0"
    assert result["tool_call_id"] == "call-0"


@pytest.mark.asyncio
async def test_a_tool_call_without_a_runner_ends_the_reply() -> None:
    client = _Client(_tool_turn())

    events = await _events(client)

    assert events[-2:] == [
        Usage(30, 20),
        Error("The model called a tool that this application does not run."),
    ]


@pytest.mark.parametrize(
    ("finish", "message"),
    [
        ("length", "The reply was cut off at the output limit."),
        ("content_filter", "The model declined to answer this request."),
    ],
)
@pytest.mark.asyncio
async def test_a_reply_that_did_not_finish_ends_with_an_error(
    finish: str, message: str
) -> None:
    client = _Client([_chunk({"content": "Part"}, finish=finish), _chunk(usage=(8, 3))])

    assert await _events(client) == [TextDelta("Part"), Usage(8, 3), Error(message)]


def test_the_conversation_is_replayed_as_text_turns() -> None:
    conversation = (
        UserMessage("turn-1-user", "Hi"),
        AssistantMessage("turn-1-assistant", (TextPart("Hello!"),)),
        UserMessage("turn-2-user", "Fail"),
        AssistantMessage("turn-2-assistant", status="error", error="Oops"),
        UserMessage("turn-3-user", "Again"),
    )

    assert to_chat_messages(conversation) == [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": "Fail"},
        {"role": "user", "content": "Again"},
    ]


@pytest.mark.parametrize("provider_id", [None, "reused-id"])
@pytest.mark.asyncio
async def test_tool_calls_of_successive_requests_remain_distinct(
    provider_id: str | None,
) -> None:
    def turn(name: str) -> list[ChatCompletionChunk]:
        fields = {"name": name, "arguments": "{}"}
        if provider_id is not None:
            fields["id"] = provider_id
        return [
            _chunk(_call(0, **fields)),
            _chunk({}, finish="tool_calls"),
        ]

    client = _Client(turn("first"), turn("second"), _text_turn())

    async def run_tool(name: str, arguments: dict[str, object]) -> str:
        return f"{name} result"

    events = await _events(client, run_tool=run_tool)
    reply = fold_events(AssistantMessage("reply", status="streaming"), events)
    parts = [part for part in reply.parts if isinstance(part, ToolPart)]

    assert [(part.name, part.result) for part in parts] == [
        ("first", "first result"),
        ("second", "second result"),
    ]
    assert parts[0].id != parts[1].id
    for request in client.requests[1:]:
        assistant, result = request["messages"][-2:]
        assert assistant["tool_calls"][0]["id"] == result["tool_call_id"]
        if provider_id is not None:
            assert result["tool_call_id"] == provider_id

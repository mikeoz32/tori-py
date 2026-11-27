from __future__ import annotations

import pytest
from tori_py_liveview_kit import (
    AssistantMessage,
    ChatEvent,
    Citation,
    Error,
    ReasoningDelta,
    ReasoningPart,
    ReplyStatus,
    TextDelta,
    TextPart,
    ToolCall,
    ToolPart,
    ToolResult,
    Usage,
    UserMessage,
)
from tori_py_liveview_kit.messages import fold_events


def _reply(*events: ChatEvent) -> AssistantMessage:
    return fold_events(AssistantMessage("turn-1-assistant", status="streaming"), events)


def test_messages_name_their_role() -> None:
    assert UserMessage("turn-1-user", "Hello").role == "user"
    assert AssistantMessage("turn-1-assistant").role == "assistant"


@pytest.mark.parametrize(
    "message_id", ["", "two words", "tab\tid", "line\nid", "a\x00"]
)
def test_message_ids_are_dom_ids(message_id: str) -> None:
    with pytest.raises(ValueError, match="id cannot"):
        UserMessage(message_id, "Hello")
    with pytest.raises(ValueError, match="id cannot"):
        AssistantMessage(message_id)


def test_assistant_message_keeps_immutable_parts_and_citations() -> None:
    message = AssistantMessage(
        "reply",
        (TextPart("Hi"),),
        citations=(Citation("Guide", "https://example.com"),),
    )
    assert message.parts == (TextPart("Hi"),)
    assert message.citations == (Citation("Guide", "https://example.com"),)


def test_tool_part_requires_an_id_and_a_name() -> None:
    with pytest.raises(ValueError, match="ToolPart id cannot be empty"):
        ToolPart("", "search")
    with pytest.raises(ValueError, match="ToolPart name cannot be empty"):
        ToolPart("call-1", "")


def test_consecutive_deltas_merge_into_one_part() -> None:
    reply = _reply(TextDelta("Hel"), TextDelta(""), TextDelta("lo"), TextDelta("!"))

    assert reply.parts == (TextPart("Hello!"),)
    assert reply.text == "Hello!"
    assert reply.status == "streaming"


def test_a_delta_after_another_kind_of_part_opens_a_new_part() -> None:
    reply = _reply(
        ReasoningDelta("Look it "),
        ReasoningDelta("up."),
        ToolCall("call-1", "search", '{"q": "tori"}'),
        TextDelta("First. "),
        ToolCall("call-2", "fetch"),
        ReasoningDelta("Now answer."),
        TextDelta("Second."),
    )

    assert reply.parts == (
        ReasoningPart("Look it up."),
        ToolPart("call-1", "search", '{"q": "tori"}'),
        TextPart("First. "),
        ToolPart("call-2", "fetch"),
        ReasoningPart("Now answer."),
        TextPart("Second."),
    )
    assert reply.text == "First. \n\nSecond."


def test_a_later_batch_extends_the_open_part() -> None:
    first = _reply(TextDelta("One "), TextDelta("two "))
    second = fold_events(first, [TextDelta("three"), ReasoningDelta("hm")])
    third = fold_events(second, [ReasoningDelta("m")])

    assert second.parts == (TextPart("One two three"), ReasoningPart("hm"))
    assert third.parts == (TextPart("One two three"), ReasoningPart("hmm"))
    # The earlier snapshots are values of their own.
    assert first.parts == (TextPart("One two "),)


def test_a_tool_call_with_a_known_id_is_replaced_in_place() -> None:
    reply = _reply(
        ToolCall("call-1", "search", '{"q": "to'),
        TextDelta("Searching."),
        ToolCall("call-1", "search_docs", '{"q": "tori"}'),
    )

    assert reply.parts == (
        ToolPart("call-1", "search_docs", '{"q": "tori"}'),
        TextPart("Searching."),
    )


def test_a_tool_result_completes_the_call_with_its_id() -> None:
    reply = _reply(
        ToolCall("call-1", "search"),
        ToolCall("call-2", "fetch"),
        ToolResult("call-2", "404", is_error=True),
        ToolResult("call-1", '{"matches": 3}'),
    )

    assert reply.parts == (
        ToolPart("call-1", "search", "", '{"matches": 3}'),
        ToolPart("call-2", "fetch", "", "404", True),
    )


def test_a_replaced_tool_call_keeps_its_result() -> None:
    reply = _reply(
        ToolCall("call-1", "search"),
        ToolResult("call-1", "done"),
        ToolCall("call-1", "search", "{}"),
    )

    assert reply.parts == (ToolPart("call-1", "search", "{}", "done"),)


def test_a_result_for_an_unknown_call_is_not_lost() -> None:
    reply = _reply(TextDelta("Hm."), ToolResult("call-9", "late"))

    assert reply.parts == (
        TextPart("Hm."),
        ToolPart("call-9", "tool", "", "late"),
    )


def test_a_result_between_deltas_does_not_split_the_text() -> None:
    reply = _reply(
        ToolCall("call-1", "search"),
        TextDelta("Still "),
        ToolResult("call-1", "ok"),
        TextDelta("writing."),
    )

    assert reply.parts == (
        ToolPart("call-1", "search", "", "ok"),
        TextPart("Still writing."),
    )


def test_citations_are_deduplicated_by_address_and_usage_is_last_wins() -> None:
    guide = Citation("Guide", "https://example.com/guide")
    reply = _reply(
        guide,
        Citation("Guide again", "https://example.com/guide"),
        Citation("Streams", "https://example.com/streams"),
        Usage(100, 1),
        Usage(100, 42, "$0.01"),
    )
    later = fold_events(reply, [Citation("Dup", "https://example.com/streams")])

    assert reply.citations == (
        guide,
        Citation("Streams", "https://example.com/streams"),
    )
    assert later.citations == reply.citations
    assert reply.usage == Usage(100, 42, "$0.01")


def test_an_error_ends_the_reply_and_nothing_after_it_applies() -> None:
    reply = _reply(
        TextDelta("Half an"), Error("The model is overloaded."), TextDelta("x")
    )

    assert reply.status == "error"
    assert reply.error == "The model is overloaded."
    assert reply.parts == (TextPart("Half an"),)
    assert fold_events(reply, [TextDelta(" answer")]) is reply


@pytest.mark.parametrize("status", ["done", "stopped", "error"])
def test_a_reply_that_has_ended_is_returned_unchanged(status: ReplyStatus) -> None:
    reply = AssistantMessage("reply", (TextPart("Done."),), status=status)

    assert fold_events(reply, [TextDelta("more"), Usage(1, 1)]) is reply


def test_an_empty_batch_keeps_the_reply_equal() -> None:
    reply = _reply(TextDelta("Hi"))

    assert fold_events(reply, []) == reply


def test_a_long_reply_folds_in_batches() -> None:
    reply = AssistantMessage("reply", status="streaming")
    for _ in range(50):
        reply = fold_events(reply, [TextDelta("ab")] * 200)

    assert reply.parts == (TextPart("ab" * 10_000),)

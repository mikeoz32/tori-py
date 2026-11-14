from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import pytest
from tori_py_liveview_kit import (
    Citation,
    Error,
    ReasoningDelta,
    TextDelta,
    ToolCall,
    ToolResult,
    Usage,
)


def test_events_are_immutable_values() -> None:
    delta = TextDelta("Hello")

    assert delta == TextDelta("Hello")
    with pytest.raises(FrozenInstanceError):
        delta.text = "changed"  # ty: ignore[invalid-assignment]


def test_deltas_may_be_empty_but_must_be_strings() -> None:
    assert TextDelta("").text == ""
    assert ReasoningDelta("").text == ""

    for event in (TextDelta, ReasoningDelta):
        with pytest.raises(TypeError, match="text must be a string"):
            event(1)  # ty: ignore[invalid-argument-type]


@pytest.mark.parametrize(
    ("arguments", "error", "message"),
    [
        (("", "search"), ValueError, "ToolCall id cannot be empty"),
        (("call-1", " "), ValueError, "ToolCall name cannot be empty"),
        ((1, "search"), TypeError, "ToolCall id must be a string"),
        (("call-1", "search", {"q": 1}), TypeError, "arguments must be a string"),
    ],
)
def test_tool_call_requires_an_id_a_name_and_text_arguments(
    arguments: tuple[Any, ...], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        ToolCall(*arguments)


def test_tool_result_requires_an_id_text_and_a_boolean_flag() -> None:
    assert ToolResult("call-1") == ToolResult("call-1", "", False)

    with pytest.raises(ValueError, match="ToolResult id cannot be empty"):
        ToolResult("")
    with pytest.raises(TypeError, match="content must be a string"):
        ToolResult("call-1", 3)  # ty: ignore[invalid-argument-type]
    with pytest.raises(TypeError, match="is_error must be a boolean"):
        ToolResult("call-1", "", 1)  # ty: ignore[invalid-argument-type]


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "/relative/path",
        "//example.com/path",
        "example.com",
        "http://",
        "https://example.com/a b",
        "https://[broken",
        "",
    ],
)
def test_citation_refuses_everything_but_an_absolute_web_address(url: str) -> None:
    with pytest.raises(ValueError, match="absolute http or https URL"):
        Citation("Guide", url)


def test_citation_accepts_web_addresses_and_requires_a_title() -> None:
    assert Citation("Guide", "https://example.com/guide?x=1#top").url.startswith(
        "https://"
    )
    assert Citation("Guide", "http://localhost:8000/").title == "Guide"

    with pytest.raises(ValueError, match="Citation title cannot be empty"):
        Citation(" ", "https://example.com")


@pytest.mark.parametrize(
    ("arguments", "error", "message"),
    [
        ((-1, 0), ValueError, "input_tokens must be from 0"),
        ((0, 10**12 + 1), ValueError, "output_tokens must be from 0"),
        ((1.5, 0), TypeError, "input_tokens must be an integer"),
        ((True, 0), TypeError, "input_tokens must be an integer"),
        ((0, 0, ""), ValueError, "Usage cost cannot be empty"),
        ((0, 0, 4), TypeError, "Usage cost must be a string"),
    ],
)
def test_usage_bounds_match_what_the_page_can_render(
    arguments: tuple[Any, ...], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        Usage(*arguments)


def test_usage_accepts_counts_and_an_optional_cost() -> None:
    assert Usage(0, 0).cost is None
    assert Usage(1240, 312, "$0.004").cost == "$0.004"


def test_error_requires_a_message() -> None:
    assert Error("The model is overloaded.").message == "The model is overloaded."

    with pytest.raises(ValueError, match="Error message cannot be empty"):
        Error("  ")
    with pytest.raises(TypeError, match="Error message must be a string"):
        Error(None)  # ty: ignore[invalid-argument-type]

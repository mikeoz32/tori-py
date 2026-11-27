from __future__ import annotations

from dataclasses import FrozenInstanceError

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


def test_deltas_may_be_empty() -> None:
    assert TextDelta("").text == ""
    assert ReasoningDelta("").text == ""


@pytest.mark.parametrize(
    ("tool_id", "name", "message"),
    [
        ("", "search", "ToolCall id cannot be empty"),
        ("call-1", " ", "ToolCall name cannot be empty"),
    ],
)
def test_tool_call_requires_a_nonempty_id_and_name(
    tool_id: str, name: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        ToolCall(tool_id, name)


def test_tool_result_requires_a_nonempty_id() -> None:
    assert ToolResult("call-1") == ToolResult("call-1", "", False)

    with pytest.raises(ValueError, match="ToolResult id cannot be empty"):
        ToolResult("")


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
    ("input_tokens", "output_tokens", "cost", "message"),
    [
        (-1, 0, None, "input_tokens must be from 0"),
        (0, 10**12 + 1, None, "output_tokens must be from 0"),
        (0, 0, "", "Usage cost cannot be empty"),
    ],
)
def test_usage_bounds_match_what_the_page_can_render(
    input_tokens: int, output_tokens: int, cost: str | None, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        Usage(input_tokens, output_tokens, cost)


def test_usage_accepts_counts_and_an_optional_cost() -> None:
    assert Usage(0, 0).cost is None
    assert Usage(1240, 312, "$0.004").cost == "$0.004"


def test_error_requires_a_message() -> None:
    assert Error("The model is overloaded.").message == "The model is overloaded."

    with pytest.raises(ValueError, match="Error message cannot be empty"):
        Error("  ")

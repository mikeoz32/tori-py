from __future__ import annotations

import re
from collections.abc import Callable
from html import escape
from string.templatelib import Template
from typing import Any, cast

import pytest
import tori_py_liveview_ui
from tori_py_liveview import JS, LiveView, html
from tori_py_liveview_ui import (
    agent_step,
    agent_steps,
    artifact_panel,
    attachment,
    chat,
    chat_empty,
    chat_log,
    chat_message,
    citation,
    composer,
    conversation,
    conversation_list,
    copy_button,
    icon,
    icon_button,
    message_actions,
    reasoning,
    response_branch,
    sources,
    suggestions,
    token_usage,
    tool_call,
    typing_indicator,
)

ui = tori_py_liveview_ui

_SPINNER = (
    '<span class="tori-ui-spinner tori-ui-spinner--sm" aria-hidden="true"></span>'
)


def _render(template: Template) -> str:
    return html(template).to_html()


def _command(commands: JS) -> str:
    return escape(commands.encode(), quote=True)


def _icon(name: str) -> str:
    return _render(icon(cast(Any, name), size="sm"))


def test_chat_family_is_explicit() -> None:
    assert conversation.__all__ == [
        "agent_step",
        "agent_steps",
        "artifact_panel",
        "attachment",
        "chat",
        "chat_empty",
        "chat_log",
        "chat_message",
        "citation",
        "composer",
        "conversation_list",
        "message_actions",
        "reasoning",
        "response_branch",
        "sources",
        "suggestions",
        "token_usage",
        "tool_call",
        "typing_indicator",
    ]


def test_chat_stacks_a_header_a_log_and_a_composer() -> None:
    assert _render(chat("LOG", "FORM", label="Support", header="HEAD")) == (
        '<section class="tori-ui-chat" aria-label="Support">'
        '<header class="tori-ui-chat__header">HEAD</header>LOG'
        '<div class="tori-ui-chat__composer">FORM</div></section>'
    )
    assert "tori-ui-chat__header" not in _render(chat("LOG", "FORM"))


def test_chat_log_is_a_followed_log_region_around_the_messages() -> None:
    assert _render(chat_log("ITEMS", id="messages", label="Support chat")) == (
        '<div id="messages-scroller" class="tori-ui-chat-log" role="log" '
        'aria-label="Support chat" tabindex="0" phx-hook="ToriUiChatLog">'
        '<div id="messages" class="tori-ui-chat-log__messages">ITEMS</div>'
        '<button type="button" class="tori-ui-chat-log__jump" '
        'aria-label="Jump to the latest message" '
        f'title="Jump to the latest message">{_icon("arrow-down")}</button></div>'
    )
    streamed = _render(chat_log("ITEMS", id="messages", stream=True))
    assert (
        '<div id="messages" class="tori-ui-chat-log__messages" phx-update="stream">'
    ) in streamed


def test_chat_message_renders_its_role_and_optional_parts() -> None:
    assert _render(chat_message("Hi <there>", role="user", id="m1")) == (
        '<article id="m1" class="tori-ui-chat-message tori-ui-chat-message--user">'
        '<div class="tori-ui-chat-message__main">'
        '<div class="tori-ui-chat-message__body" data-tori-ui-copy-source>'
        "Hi &lt;there&gt;</div></div></article>"
    )
    full = _render(
        chat_message(
            "Answer",
            name="Assistant",
            avatar="AV",
            time="12:04",
            footer="FOOT",
            actions="ACTIONS",
        )
    )
    assert full == (
        '<article class="tori-ui-chat-message tori-ui-chat-message--assistant">'
        '<div class="tori-ui-chat-message__avatar">AV</div>'
        '<div class="tori-ui-chat-message__main">'
        '<header class="tori-ui-chat-message__meta">'
        '<span class="tori-ui-chat-message__name">Assistant</span>'
        '<span class="tori-ui-chat-message__time">12:04</span></header>'
        '<div class="tori-ui-chat-message__body" data-tori-ui-copy-source>Answer</div>'
        '<div class="tori-ui-chat-message__footer">FOOT</div>ACTIONS</div></article>'
    )


def test_streaming_message_is_busy_and_shows_a_caret() -> None:
    result = _render(chat_message("Wri", streaming=True))

    assert 'aria-busy="true"' in result
    assert (
        'Wri<span class="tori-ui-chat-message__caret" aria-hidden="true"></span></div>'
    ) in result
    assert "aria-busy" not in _render(chat_message("Written"))


def test_message_actions_start_with_a_copy_of_the_message() -> None:
    copy = _render(copy_button(to=("closest", ".tori-ui-chat-message")))
    retry = icon_button("refresh", label="Retry", size="sm")

    assert _render(message_actions([retry])) == (
        '<div class="tori-ui-message-actions" role="group" '
        f'aria-label="Message actions">{copy}{_render(retry)}</div>'
    )
    assert "tori-ui-copy-button" not in _render(message_actions([], copy=False))


def test_composer_is_a_hooked_form_with_a_send_button() -> None:
    assert _render(
        composer(id="composer", submit_event="send", placeholder="Ask anything")
    ) == (
        '<form id="composer" method="post" class="tori-ui-composer" '
        'phx-submit="send" phx-hook="ToriUiComposer">'
        '<label class="tori-ui-visually-hidden" for="composer-input">Message</label>'
        '<textarea id="composer-input" name="message" '
        'class="tori-ui-composer__input" rows="1" placeholder="Ask anything" '
        'data-tori-ui-max-rows="8"></textarea>'
        '<div class="tori-ui-composer__bar">'
        '<div class="tori-ui-composer__actions"></div>'
        '<button type="submit" class="tori-ui-composer__send" aria-label="Send" '
        f'title="Send">{_icon("send")}</button></div></form>'
    )


def test_busy_composer_offers_to_stop_and_does_not_submit() -> None:
    result = _render(
        composer(
            id="composer",
            submit_event="send",
            change_event="draft",
            target=3,
            value="half <typed>",
            busy=True,
            stop_event="stop",
            actions="MODEL",
            hint="Enter sends",
            max_rows=4,
        )
    )

    assert (
        'phx-submit="send" phx-change="draft" phx-target="3" '
        'phx-hook="ToriUiComposer" data-tori-ui-busy="true"'
    ) in result
    assert 'data-tori-ui-max-rows="4">half &lt;typed&gt;</textarea>' in result
    assert '<div class="tori-ui-composer__actions">MODEL</div>' in result
    assert (
        '<button type="button" class="tori-ui-composer__send '
        'tori-ui-composer__send--stop" aria-label="Stop" title="Stop" '
        f'phx-click="stop" phx-target="3">{_icon("stop")}</button>'
    ) in result
    assert '<p class="tori-ui-composer__hint">Enter sends</p>' in result
    assert 'type="submit"' not in result
    # Without a stop event the send button stays, disabled.
    waiting = _render(composer(id="c", submit_event="send", busy=True))
    assert 'aria-label="Send" title="Send" disabled' in waiting


def test_suggestions_push_their_prompt() -> None:
    assert _render(
        suggestions([("Summarize", "Summarize <this>."), "Explain"], event="pick")
    ) == (
        '<div class="tori-ui-suggestions" role="group" aria-label="Suggestions">'
        '<button type="button" class="tori-ui-suggestions__item" phx-click="pick" '
        'phx-value-prompt="Summarize &lt;this&gt;.">Summarize</button>'
        '<button type="button" class="tori-ui-suggestions__item" phx-click="pick" '
        'phx-value-prompt="Explain">Explain</button></div>'
    )


def test_chat_empty_and_typing_indicator() -> None:
    assert _render(chat_empty("Ask away", description="No key needed", icon=None)) == (
        '<div class="tori-ui-chat-empty"><p class="tori-ui-chat-empty__title">'
        'Ask away</p><p class="tori-ui-chat-empty__description">No key needed</p>'
        "</div>"
    )
    welcome = _render(chat_empty("Ask away", suggestions="PROMPTS"))
    assert _render(icon("sparkles", size="lg")) in welcome
    assert welcome.endswith("PROMPTS</div>")
    assert _render(typing_indicator(label="Thinking")) == (
        '<span class="tori-ui-typing" role="status">'
        + '<span class="tori-ui-typing__dot" aria-hidden="true"></span>' * 3
        + '<span class="tori-ui-visually-hidden">Thinking</span></span>'
    )


def test_conversation_list_is_navigation_around_a_list_group() -> None:
    assert _render(conversation_list(["A"], label="Chats", action="NEW")) == (
        '<nav class="tori-ui-conversation-list" aria-label="Chats">'
        '<div class="tori-ui-conversation-list__action">NEW</div>'
        '<ul class="tori-ui-list-group">A</ul></nav>'
    )


def test_response_branch_disables_the_step_at_each_end() -> None:
    first = _render(
        response_branch(current=1, total=3, previous_event="prev", next_event="next")
    )
    assert first == (
        '<span class="tori-ui-response-branch">'
        '<button type="button" class="tori-ui-response-branch__step" '
        f'aria-label="Previous response" disabled phx-click="prev">'
        f"{_icon('chevron-left')}</button>"
        '<span class="tori-ui-response-branch__count">1 / 3</span>'
        '<button type="button" class="tori-ui-response-branch__step" '
        f'aria-label="Next response" phx-click="next">{_icon("chevron-right")}'
        "</button></span>"
    )
    last = _render(
        response_branch(current=3, total=3, previous_event="prev", next_event="next")
    )
    assert last.count("disabled") == 1
    assert 'aria-label="Next response" disabled' in last


def test_reasoning_folds_away_and_keeps_the_visitors_choice() -> None:
    keep = _command(JS().ignore_attributes(["open"]))

    assert _render(reasoning("Because.", summary="Thought for 3s", id="r1")) == (
        f'<details id="r1" class="tori-ui-reasoning" phx-mounted="{keep}">'
        f'<summary class="tori-ui-reasoning__summary">{_icon("lightbulb")}'
        '<span class="tori-ui-reasoning__label">Thought for 3s</span>'
        f"{_icon('chevron-down')}</summary>"
        '<div class="tori-ui-reasoning__content">Because.</div></details>'
    )
    live = _render(reasoning("Hmm", summary="Thinking", streaming=True, open=True))
    assert live.startswith('<details class="tori-ui-reasoning" open phx-mounted="')
    assert f'<summary class="tori-ui-reasoning__summary">{_SPINNER}' in live


def test_tool_call_shows_status_arguments_and_result() -> None:
    result = _render(
        tool_call(
            "search_docs",
            status_label="Done",
            arguments='{"q": "<x>"}',
            result="3 matches",
            id="t1",
        )
    )

    assert result.startswith(
        '<details id="t1" class="tori-ui-tool-call tori-ui-tool-call--done" '
        'phx-mounted="'
    )
    assert (
        f'<summary class="tori-ui-tool-call__summary">{_icon("tool")}'
        '<code class="tori-ui-tool-call__name">search_docs</code>'
        f'<span class="tori-ui-tool-call__status">{_icon("check-circle")}Done</span>'
    ) in result
    assert (
        '<div class="tori-ui-tool-call__content">'
        '<p class="tori-ui-tool-call__label">Arguments</p>'
        '<pre class="tori-ui-tool-call__data" tabindex="0">'
        "{&quot;q&quot;: &quot;&lt;x&gt;&quot;}</pre>"
        '<p class="tori-ui-tool-call__label">Result</p>'
        '<pre class="tori-ui-tool-call__data" tabindex="0">3 matches</pre></div>'
    ) in result
    running = _render(tool_call("run", status="running"))
    assert f'<span class="tori-ui-tool-call__status">{_SPINNER}running</span>' in (
        running
    )
    assert '<div class="tori-ui-tool-call__content"></div>' in running
    assert _icon("x-circle") in _render(tool_call("deploy", status="error"))


def test_agent_steps_name_each_status_for_screen_readers() -> None:
    steps = agent_steps(
        [
            agent_step("Read", status="done", status_label="Done", id="s1"),
            agent_step("Write", status="running", description="Two files"),
            agent_step("Test"),
        ],
        label="Plan",
    )

    assert _render(steps) == (
        '<ol class="tori-ui-agent-steps" aria-label="Plan">'
        '<li id="s1" class="tori-ui-agent-steps__step '
        'tori-ui-agent-steps__step--done">'
        f'<span class="tori-ui-agent-steps__status">{_icon("check-circle")}'
        '<span class="tori-ui-visually-hidden">Done: </span></span>'
        '<div class="tori-ui-agent-steps__body">'
        '<p class="tori-ui-agent-steps__title">Read</p></div></li>'
        '<li class="tori-ui-agent-steps__step tori-ui-agent-steps__step--running" '
        f'aria-current="step"><span class="tori-ui-agent-steps__status">{_SPINNER}'
        '<span class="tori-ui-visually-hidden">running: </span></span>'
        '<div class="tori-ui-agent-steps__body">'
        '<p class="tori-ui-agent-steps__title">Write</p>'
        '<div class="tori-ui-agent-steps__description">Two files</div></div></li>'
        '<li class="tori-ui-agent-steps__step tori-ui-agent-steps__step--pending">'
        f'<span class="tori-ui-agent-steps__status">{_icon("circle")}'
        '<span class="tori-ui-visually-hidden">pending: </span></span>'
        '<div class="tori-ui-agent-steps__body">'
        '<p class="tori-ui-agent-steps__title">Test</p></div></li></ol>'
    )


def test_sources_are_numbered_external_links_a_citation_can_target() -> None:
    assert _render(sources([("Guide", "https://example.com/a")], id="refs")) == (
        '<aside class="tori-ui-sources" aria-label="Sources">'
        '<p class="tori-ui-sources__label">Sources</p>'
        '<ol class="tori-ui-sources__list">'
        '<li id="refs-1" class="tori-ui-sources__item">'
        '<a class="tori-ui-sources__link" href="https://example.com/a" '
        'target="_blank" rel="noopener noreferrer">Guide</a></li></ol></aside>'
    )
    assert _render(citation(1, href="#refs-1", title="Guide")) == (
        '<a class="tori-ui-citation" href="#refs-1" title="Guide">1</a>'
    )
    assert _render(citation(2)) == '<span class="tori-ui-citation">2</span>'
    with pytest.raises(ValueError, match="unsafe URL scheme"):
        sources([("Bad", "javascript:alert(1)")])


def test_attachment_can_link_and_be_removed() -> None:
    assert _render(attachment("report.pdf", meta="24 kB")) == (
        f'<span class="tori-ui-attachment">{_icon("file")}'
        '<span class="tori-ui-attachment__name">report.pdf</span>'
        '<span class="tori-ui-attachment__meta">24 kB</span></span>'
    )
    removable = _render(
        attachment(
            "cat.png",
            icon="image",
            href="/files/cat.png",
            remove_event="detach",
            remove_label="Remove cat.png",
        )
    )
    assert '<a class="tori-ui-attachment__name" href="/files/cat.png">cat.png</a>' in (
        removable
    )
    assert (
        '<button type="button" class="tori-ui-attachment__remove" '
        'aria-label="Remove cat.png" phx-click="detach" phx-value-name="cat.png">'
    ) in removable


@pytest.mark.parametrize(
    ("count", "shown"),
    [(0, "0"), (999, "999"), (1000, "1k"), (1240, "1.2k"), (2_500_000, "2.5M")],
)
def test_token_usage_shortens_large_counts(count: int, shown: str) -> None:
    result = _render(token_usage(input_tokens=count, output_tokens=7, cost="$0.01"))

    assert f"</svg>{shown}</span>" in result
    assert 'role="img" aria-label="Input tokens"' in result
    assert 'role="img" aria-label="Output tokens"' in result
    assert '<span class="tori-ui-token-usage__cost">$0.01</span>' in result


def test_artifact_panel_names_itself_and_copies_its_content() -> None:
    copy = _render(copy_button(to="#artifact-content"))

    assert _render(
        artifact_panel("BODY", title="hello.py", id="artifact", subtitle="Program")
    ) == (
        '<section id="artifact" class="tori-ui-artifact" '
        'aria-labelledby="artifact-title">'
        '<header class="tori-ui-artifact__header">'
        '<div class="tori-ui-artifact__heading">'
        '<h2 id="artifact-title" class="tori-ui-artifact__title">hello.py</h2>'
        '<p class="tori-ui-artifact__subtitle">Program</p></div>'
        f'<div class="tori-ui-artifact__actions">{copy}</div></header>'
        '<div id="artifact-content" class="tori-ui-artifact__content">BODY</div>'
        "</section>"
    )


def test_a_full_assistant_message_is_a_valid_stream_item() -> None:
    class Page(LiveView):
        def render(self) -> str:
            return ""

    message = chat_message(
        t"{reasoning('why', id='m1-why')}{tool_call('search', arguments='{}')}",
        id="m1",
        name="Assistant",
        footer=sources([("Guide", "https://example.com")]),
        actions=message_actions([icon_button("refresh", label="Retry")]),
    )

    # Raises when the item is not one balanced root element with this ID.
    Page().stream_insert("messages", "m1", message)


@pytest.mark.parametrize(
    ("call", "error", "message"),
    [
        (lambda: ui.chat("a", "b", label=""), ValueError, "chat label cannot be"),
        (lambda: ui.chat_log("x", id="a b"), ValueError, "chat log id must match"),
        (
            lambda: ui.composer(id="c", submit_event=""),
            ValueError,
            "composer submit event cannot be empty",
        ),
        (
            lambda: ui.composer(id="c", submit_event="s", max_rows=0),
            ValueError,
            "composer maximum rows must be between",
        ),
        (
            lambda: ui.composer(id="c.x", submit_event="s"),
            ValueError,
            "composer id must match",
        ),
        (
            lambda: ui.suggestions([""], event="e"),
            ValueError,
            "suggestions label text cannot be empty",
        ),
        (
            lambda: ui.response_branch(
                current=4, total=3, previous_event="p", next_event="n"
            ),
            ValueError,
            "response branch current must be between 1 and 3",
        ),
        (
            lambda: ui.response_branch(
                current=1, total=0, previous_event="p", next_event="n"
            ),
            ValueError,
            "response branch total must be between",
        ),
        (
            lambda: ui.reasoning("x", summary=""),
            ValueError,
            "reasoning summary cannot be empty",
        ),
        (lambda: ui.tool_call(""), ValueError, "tool call name cannot be empty"),
        (lambda: ui.citation(0), ValueError, "citation number must be between"),
        (
            lambda: ui.attachment("a.txt", target=1),
            ValueError,
            "attachment target requires an event",
        ),
        (
            lambda: ui.token_usage(input_tokens=-1, output_tokens=0),
            ValueError,
            "token usage input tokens must be between",
        ),
        (
            lambda: ui.artifact_panel("x", title="t", id="a b"),
            ValueError,
            "artifact panel id must match",
        ),
    ],
)
def test_chat_helpers_reject_values_outside_their_contract(
    call: Callable[[], Any], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=re.escape(message)):
        call()

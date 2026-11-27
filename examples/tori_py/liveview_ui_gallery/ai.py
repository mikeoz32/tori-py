"""Gallery page for the parts of a conversation and of a model's output."""

from __future__ import annotations

from string.templatelib import Template

from tori_py_liveview import UnknownEventError, live_view
from tori_py_liveview_ui import (
    agent_step,
    agent_steps,
    artifact_panel,
    attachment,
    avatar,
    button,
    chat_message,
    citation,
    code_block,
    conversation_list,
    grid,
    icon_button,
    list_item,
    markdown,
    message_actions,
    reasoning,
    response_branch,
    row,
    sources,
    stack,
    suggestions,
    text,
    token_usage,
    tool_call,
    typing_indicator,
)

from examples.tori_py.liveview_ui_gallery.shell import GalleryPage, demo

_VARIANTS = [
    "Streams keep rendered items in the browser.",
    "A stream sends inserts and deletes instead of the whole list.",
    "Use a stream when the list is long or grows without bound.",
]
_MARKDOWN = """A model answers in **Markdown**, with `code`, lists, and tables.

- Raw HTML such as <b>this</b> stays text.
- A [link](https://example.com) opens in a new tab.

| Helper | Role |
| --- | --- |
| `reasoning` | Folds the thinking away |
| `tool_call` | Shows a call and its result |
"""


@live_view("/ai")
class AiLive(GalleryPage):
    heading = "AI"
    summary = "Messages, reasoning, tool calls, sources, and other model output."
    path = "/ai"

    def __init__(self) -> None:
        super().__init__()
        self.variant = 0
        self.picked = "none"
        self.files = ["report.pdf", "notes.md"]

    async def handle_event(self, event: str, value: object) -> None:
        match event, value:
            case "previous", _:
                self.variant = max(self.variant - 1, 0)
            case "next", _:
                self.variant = min(self.variant + 1, len(_VARIANTS) - 1)
            case "pick", {"prompt": str(prompt)}:
                self.picked = prompt
            case "detach", {"name": str(name)}:
                self.files = [file for file in self.files if file != name]
            case _:
                raise UnknownEventError(event)

    def render(self) -> Template:
        answer = (
            t"{_VARIANTS[self.variant]}{citation(1, href='#refs-1', title='Streams')}"
        )
        branch = response_branch(
            current=self.variant + 1,
            total=len(_VARIANTS),
            previous_event="previous",
            next_event="next",
        )
        messages = stack(
            [
                chat_message("How do streams work?", role="user", id="message-user"),
                chat_message(
                    answer,
                    id="message-assistant",
                    name="Assistant",
                    time="12:04",
                    avatar=avatar("Tori Assistant", size="sm"),
                    footer=stack(
                        [
                            sources(
                                [
                                    ("Streams guide", "https://example.com/streams"),
                                    ("Phoenix streams", "https://example.com/phoenix"),
                                ],
                                id="refs",
                            ),
                            token_usage(
                                input_tokens=1240, output_tokens=312, cost="$0.004"
                            ),
                        ],
                        gap="sm",
                        align="start",
                    ),
                    actions=message_actions(
                        [
                            icon_button("refresh", label="Retry", size="sm"),
                            icon_button("thumbs-up", label="Good", size="sm"),
                            branch,
                        ]
                    ),
                ),
                chat_message(
                    "Still writing",
                    id="message-streaming",
                    name="Assistant",
                    streaming=True,
                ),
                chat_message(typing_indicator(), id="message-typing"),
                chat_message(
                    "The conversation was renamed.", role="system", id="message-system"
                ),
            ],
            gap="lg",
        )
        thinking = stack(
            [
                reasoning(
                    text("The visitor wants a short answer.", size="sm", muted=True),
                    summary="Thought for 3 seconds",
                    id="reasoning-done",
                ),
                reasoning(
                    text("Comparing two approaches", size="sm", muted=True),
                    summary="Thinking",
                    streaming=True,
                    open=True,
                    id="reasoning-live",
                ),
            ]
        )
        tools = stack(
            [
                tool_call(
                    "search_docs",
                    status_label="Done",
                    arguments='{"query": "streams"}',
                    result='{"matches": 3}',
                    id="tool-done",
                    open=True,
                ),
                tool_call(
                    "run_tests",
                    status="running",
                    status_label="Running",
                    arguments='{"path": "tests/"}',
                    id="tool-running",
                ),
                tool_call(
                    "deploy", status="error", status_label="Failed", id="tool-error"
                ),
            ]
        )
        plan = agent_steps(
            [
                agent_step("Read the issue", status="done", status_label="Done"),
                agent_step(
                    "Write the fix",
                    status="running",
                    status_label="Running",
                    description="Editing two files.",
                ),
                agent_step("Run the tests", status_label="Pending"),
                agent_step(
                    "Open a pull request", status="error", status_label="Failed"
                ),
            ]
        )
        prompts = stack(
            [
                suggestions(
                    [("Summarize", "Summarize this page."), "Explain streams"],
                    event="pick",
                ),
                text(t'Picked: <output id="picked">{self.picked}</output>', size="sm"),
            ]
        )
        files = row(
            (
                attachment(
                    name,
                    meta="24 kB",
                    remove_event="detach",
                    remove_label=f"Remove {name}",
                )
                for name in self.files
            ),
            gap="sm",
        )
        conversations = conversation_list(
            [
                list_item("Streams", description="Today", selected=True, href="/ai"),
                list_item("Deploy checklist", description="Yesterday", href="/ai"),
            ],
            action=button("New chat", icon="plus", size="sm", variant="secondary"),
        )
        artifact = artifact_panel(
            code_block("print('hello')", language="python", copy=False),
            title="hello.py",
            subtitle="Generated program",
            id="artifact",
        )
        return self.page(
            grid(
                [
                    demo("Messages", messages),
                    demo("Markdown", markdown(_MARKDOWN)),
                    demo("Reasoning", thinking),
                    demo("Tool calls", tools),
                    demo("Agent steps", plan),
                    demo("Suggestions", prompts),
                    demo("Attachments", files),
                    demo("Conversation list", conversations),
                    demo("Artifact", artifact),
                ],
                columns="2",
                gap="lg",
            )
        )

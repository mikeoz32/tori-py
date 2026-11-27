"""Helpers for conversations and for what a language model produces."""

from __future__ import annotations

from collections.abc import Iterable
from string.templatelib import Template
from typing import Literal

from tori_py_liveview import JS, attrs, classes, fragment, raw

from tori_py_liveview_ui._shared import (
    bounded_integer,
    event_binding,
    event_target,
    html_id,
    optional_nonempty_text,
    required_text,
    selector_id,
)
from tori_py_liveview_ui.actions import copy_button
from tori_py_liveview_ui.icons import IconName
from tori_py_liveview_ui.icons import icon as render_icon

type MessageRole = Literal["user", "assistant", "system", "tool"]
type StepStatus = Literal["pending", "running", "done", "error"]

_STATUS_ICONS: dict[str, IconName] = {
    "pending": "circle",
    "done": "check-circle",
    "error": "x-circle",
}
# The visitor's open or closed choice outlives the server's renders.
_KEEP_OPEN = JS().ignore_attributes(["open"])
_SPINNER = raw(
    '<span class="tori-ui-spinner tori-ui-spinner--sm" aria-hidden="true"></span>'
)


def _status_icon(status: str) -> object:
    if status == "running":
        return _SPINNER
    return render_icon(_STATUS_ICONS[status], size="sm")


def chat(
    log: object,
    composer: object,
    *,
    label: str = "Chat",
    header: object | None = None,
) -> Template:
    """Stack a header, a ``chat_log()``, and a ``composer()`` in one column.

    The column fills the height of its container, the log takes the free
    space and scrolls, and the composer stays at the bottom.
    """
    label = required_text("chat label", label)
    header_markup = (
        t'<header class="tori-ui-chat__header">{header}</header>'
        if header is not None
        else raw("")
    )
    return (
        t'<section class="tori-ui-chat" aria-label="{label}">{header_markup}{log}'
        t'<div class="tori-ui-chat__composer">{composer}</div></section>'
    )


def chat_log(
    content: object,
    *,
    id: str,
    label: str = "Conversation",
    stream: bool = False,
    jump_label: str = "Jump to the latest message",
) -> Template:
    """Render the scrolling list of messages.

    The log follows new content while the visitor is at the bottom and stops
    following once they scroll up; a button then jumps back to the latest
    message. With ``stream=True`` the messages are a LiveView stream:
    ``content`` is ``self.stream_contents(id)`` and every item is a
    ``chat_message()`` whose ``id`` is the stream item ID.
    """
    id = selector_id("chat log id", id)
    label = required_text("chat log label", label)
    jump_label = required_text("chat log jump label", jump_label)
    scroller = attrs(
        {
            "id": f"{id}-scroller",
            "class": "tori-ui-chat-log",
            "role": "log",
            "aria-label": label,
            "tabindex": "0",
            "phx-hook": "ToriUiChatLog",
        }
    )
    messages = attrs(
        {
            "id": id,
            "class": "tori-ui-chat-log__messages",
            "phx-update": "stream" if stream else None,
        }
    )
    jump = attrs(
        {
            "type": "button",
            "class": "tori-ui-chat-log__jump",
            "aria-label": jump_label,
            "title": jump_label,
        }
    )
    return (
        t"<div{scroller}><div{messages}>{content}</div>"
        t"<button{jump}>{render_icon('arrow-down', size='sm')}</button></div>"
    )


def chat_message(
    content: object,
    *,
    role: MessageRole = "assistant",
    id: str | None = None,
    name: str | None = None,
    avatar: object | None = None,
    time: object | None = None,
    streaming: bool = False,
    footer: object | None = None,
    actions: object | None = None,
    copy_text: str | None = None,
) -> Template:
    """Render one message of a conversation.

    ``streaming`` marks a message that is still being written: it shows a
    caret, and screen readers wait for the message to finish before they read
    it. ``footer`` holds what belongs to the answer, such as ``sources()`` or
    ``token_usage()``, and ``actions`` a ``message_actions()`` row.
    ``copy_text`` optionally supplies the exact text for the copy action,
    independently of the rendered reasoning, controls, or status messages.
    """
    if id is not None:
        id = html_id("chat message id", id)
    name = optional_nonempty_text("chat message name", name)
    attributes = attrs(
        {
            "id": id,
            "class": classes("tori-ui-chat-message", f"tori-ui-chat-message--{role}"),
            "aria-busy": "true" if streaming else None,
        }
    )
    avatar_markup = (
        t'<div class="tori-ui-chat-message__avatar">{avatar}</div>'
        if avatar is not None
        else raw("")
    )
    name_markup = (
        t'<span class="tori-ui-chat-message__name">{name}</span>'
        if name is not None
        else raw("")
    )
    time_markup = (
        t'<span class="tori-ui-chat-message__time">{time}</span>'
        if time is not None
        else raw("")
    )
    meta_markup = (
        t'<header class="tori-ui-chat-message__meta">{name_markup}{time_markup}'
        t"</header>"
        if name is not None or time is not None
        else raw("")
    )
    caret = (
        t'<span class="tori-ui-chat-message__caret" aria-hidden="true"></span>'
        if streaming
        else raw("")
    )
    footer_markup = (
        t'<div class="tori-ui-chat-message__footer">{footer}</div>'
        if footer is not None
        else raw("")
    )
    actions_markup = actions if actions is not None else raw("")
    body = attrs(
        {
            "class": "tori-ui-chat-message__body",
            "data-tori-ui-copy-source": True,
            "data-tori-ui-copy-text": copy_text,
        }
    )
    return (
        t"<article{attributes}>{avatar_markup}"
        t'<div class="tori-ui-chat-message__main">{meta_markup}'
        t"<div{body}>"
        t"{content}{caret}</div>{footer_markup}{actions_markup}</div></article>"
    )


def message_actions(
    children: Iterable[object],
    *,
    label: str = "Message actions",
    copy: bool = True,
    copy_label: str = "Copy",
    copied_label: str = "Copied",
) -> Template:
    """Render the row of small controls under a message.

    With ``copy`` the row starts with a button that copies the message text.
    Add ``icon_button()`` controls for retry, feedback, and the like.
    """
    label = required_text("message actions label", label)
    copy_markup = (
        copy_button(
            to=("closest", ".tori-ui-chat-message"),
            label=copy_label,
            copied_label=copied_label,
        )
        if copy
        else raw("")
    )
    return (
        t'<div class="tori-ui-message-actions" role="group" aria-label="{label}">'
        t"{copy_markup}{fragment(children)}</div>"
    )


def composer(
    *,
    id: str,
    submit_event: str | JS,
    name: str = "message",
    value: str = "",
    label: str = "Message",
    placeholder: str | None = None,
    change_event: str | JS | None = None,
    target: int | None = None,
    submit_label: str = "Send",
    busy: bool = False,
    stop_event: str | JS | None = None,
    stop_label: str = "Stop",
    disabled: bool = False,
    max_rows: int = 8,
    actions: object | None = None,
    hint: object | None = None,
) -> Template:
    """Render the form a visitor writes a message in.

    Enter sends the message and Shift+Enter starts a new line; the field
    grows with its text up to ``max_rows`` and empties once the message is
    sent. While ``busy`` the form does not submit, and with ``stop_event`` the
    send button becomes a stop button. ``actions`` holds extra controls, such
    as a model select, and ``hint`` a line under the field.
    """
    id = selector_id("composer id", id)
    submit_event = event_binding("composer submit event", submit_event)
    name = required_text("composer name", name)
    label = required_text("composer label", label)
    placeholder = optional_nonempty_text("composer placeholder", placeholder)
    change_event = event_binding("composer change event", change_event)
    target = event_target("composer target", target, submit_event)
    submit_label = required_text("composer submit label", submit_label)
    stop_event = event_binding("composer stop event", stop_event)
    stop_label = required_text("composer stop label", stop_label)
    bounded_integer("composer maximum rows", max_rows, 1, 40)
    input_id = f"{id}-input"
    form = attrs(
        {
            "id": id,
            "method": "post",
            "class": "tori-ui-composer",
            "phx-submit": submit_event,
            "phx-change": change_event,
            "phx-target": target,
            "phx-hook": "ToriUiComposer",
            "data-tori-ui-busy": "true" if busy else None,
        }
    )
    field = attrs(
        {
            "id": input_id,
            "name": name,
            "class": "tori-ui-composer__input",
            "rows": 1,
            "placeholder": placeholder,
            "disabled": disabled,
            "data-tori-ui-max-rows": max_rows,
        }
    )
    if busy and stop_event is not None:
        stop = attrs(
            {
                "type": "button",
                "class": "tori-ui-composer__send tori-ui-composer__send--stop",
                "aria-label": stop_label,
                "title": stop_label,
                "phx-click": stop_event,
                "phx-target": target,
            }
        )
        control = t"<button{stop}>{render_icon('stop', size='sm')}</button>"
    else:
        send = attrs(
            {
                "type": "submit",
                "class": "tori-ui-composer__send",
                "aria-label": submit_label,
                "title": submit_label,
                "disabled": disabled or busy,
            }
        )
        control = t"<button{send}>{render_icon('send', size='sm')}</button>"
    actions_markup = actions if actions is not None else raw("")
    hint_markup = (
        t'<p class="tori-ui-composer__hint">{hint}</p>' if hint is not None else raw("")
    )
    return (
        t'<form{form}><label class="tori-ui-visually-hidden" for="{input_id}">'
        t"{label}</label><textarea{field}>{value}</textarea>"
        t'<div class="tori-ui-composer__bar">'
        t'<div class="tori-ui-composer__actions">{actions_markup}</div>{control}'
        t"</div>{hint_markup}</form>"
    )


def suggestions(
    items: Iterable[str | tuple[str, str]],
    *,
    event: str | JS,
    target: int | None = None,
    label: str = "Suggestions",
) -> Template:
    """Offer prompts the visitor can send with one click.

    An item is a prompt, or a ``(label, prompt)`` pair when the button should
    say something shorter. The click pushes ``event`` with the prompt as
    ``prompt``.
    """
    event = event_binding("suggestions event", event)
    target = event_target("suggestions target", target, event)
    label = required_text("suggestions label", label)
    buttons: list[Template] = []
    for item in items:
        if isinstance(item, tuple):
            text, prompt = item
        else:
            text = prompt = item
        text = required_text("suggestions label text", text)
        prompt = required_text("suggestions prompt", prompt)
        button = attrs(
            {
                "type": "button",
                "class": "tori-ui-suggestions__item",
                "phx-click": event,
                "phx-target": target,
                "phx-value-prompt": prompt,
            }
        )
        buttons.append(t"<button{button}>{text}</button>")
    return (
        t'<div class="tori-ui-suggestions" role="group" aria-label="{label}">'
        t"{fragment(buttons)}</div>"
    )


def chat_empty(
    title: str,
    *,
    description: object | None = None,
    icon: IconName | None = "sparkles",
    suggestions: object | None = None,
) -> Template:
    """Welcome the visitor to a conversation that has no messages yet."""
    title = required_text("chat empty title", title)
    glyph: object = raw("")
    if icon is not None:
        drawing = render_icon(icon, size="lg")
        glyph = t'<div class="tori-ui-chat-empty__icon">{drawing}</div>'
    description_markup = (
        t'<p class="tori-ui-chat-empty__description">{description}</p>'
        if description is not None
        else raw("")
    )
    suggestions_markup = suggestions if suggestions is not None else raw("")
    return (
        t'<div class="tori-ui-chat-empty">{glyph}'
        t'<p class="tori-ui-chat-empty__title">{title}</p>{description_markup}'
        t"{suggestions_markup}</div>"
    )


def typing_indicator(*, label: str = "Writing a reply") -> Template:
    """Show that a reply is on its way before its first words arrive."""
    label = required_text("typing indicator label", label)
    return (
        t'<span class="tori-ui-typing" role="status">'
        t'<span class="tori-ui-typing__dot" aria-hidden="true"></span>'
        t'<span class="tori-ui-typing__dot" aria-hidden="true"></span>'
        t'<span class="tori-ui-typing__dot" aria-hidden="true"></span>'
        t'<span class="tori-ui-visually-hidden">{label}</span></span>'
    )


def conversation_list(
    items: Iterable[object],
    *,
    label: str = "Conversations",
    action: object | None = None,
) -> Template:
    """List earlier conversations as navigation.

    Build the rows with ``list_item()``, marking the open one ``selected``.
    ``action`` is a control above the list, such as a new-conversation button.
    """
    label = required_text("conversation list label", label)
    action_markup = (
        t'<div class="tori-ui-conversation-list__action">{action}</div>'
        if action is not None
        else raw("")
    )
    return (
        t'<nav class="tori-ui-conversation-list" aria-label="{label}">'
        t'{action_markup}<ul class="tori-ui-list-group">{fragment(items)}</ul></nav>'
    )


def response_branch(
    *,
    current: int,
    total: int,
    previous_event: str | JS,
    next_event: str | JS,
    target: int | None = None,
    previous_label: str = "Previous response",
    next_label: str = "Next response",
) -> Template:
    """Step through the alternative responses to one message."""
    bounded_integer("response branch total", total, 1, 9999)
    bounded_integer("response branch current", current, 1, total)
    previous_event = event_binding("response branch previous event", previous_event)
    next_event = event_binding("response branch next event", next_event)
    target = event_target("response branch target", target, previous_event)
    previous = attrs(
        {
            "type": "button",
            "class": "tori-ui-response-branch__step",
            "aria-label": required_text(
                "response branch previous label", previous_label
            ),
            "disabled": current == 1,
            "phx-click": previous_event,
            "phx-target": target,
        }
    )
    following = attrs(
        {
            "type": "button",
            "class": "tori-ui-response-branch__step",
            "aria-label": required_text("response branch next label", next_label),
            "disabled": current == total,
            "phx-click": next_event,
            "phx-target": target,
        }
    )
    return (
        t'<span class="tori-ui-response-branch"><button{previous}>'
        t"{render_icon('chevron-left', size='sm')}</button>"
        t'<span class="tori-ui-response-branch__count">{current} / {total}</span>'
        t"<button{following}>{render_icon('chevron-right', size='sm')}</button></span>"
    )


def reasoning(
    content: object,
    *,
    summary: str = "Reasoning",
    streaming: bool = False,
    open: bool = False,
    id: str | None = None,
) -> Template:
    """Fold a model's reasoning away under a one-line summary.

    ``streaming`` shows a spinner while the reasoning is still arriving.
    ``open`` is only the state the block starts in; afterwards the browser
    owns it.
    """
    summary = required_text("reasoning summary", summary)
    if id is not None:
        id = html_id("reasoning id", id)
    attributes = attrs(
        {
            "id": id,
            "class": "tori-ui-reasoning",
            "open": open,
            "phx-mounted": _KEEP_OPEN,
        }
    )
    glyph = _SPINNER if streaming else render_icon("lightbulb", size="sm")
    return (
        t'<details{attributes}><summary class="tori-ui-reasoning__summary">{glyph}'
        t'<span class="tori-ui-reasoning__label">{summary}</span>'
        t"{render_icon('chevron-down', size='sm')}</summary>"
        t'<div class="tori-ui-reasoning__content">{content}</div></details>'
    )


def tool_call(
    name: str,
    *,
    status: StepStatus = "done",
    status_label: str | None = None,
    arguments: object | None = None,
    result: object | None = None,
    arguments_label: str = "Arguments",
    result_label: str = "Result",
    open: bool = False,
    id: str | None = None,
) -> Template:
    """Show a tool the model called, with its arguments and its result.

    ``status_label`` is the status in words; without one the status name is
    used. Strings in ``arguments`` and ``result`` are shown as preformatted
    text, so pass JSON already serialized.
    """
    name = required_text("tool call name", name)
    status_label = optional_nonempty_text("tool call status label", status_label)
    if id is not None:
        id = html_id("tool call id", id)
    attributes = attrs(
        {
            "id": id,
            "class": classes("tori-ui-tool-call", f"tori-ui-tool-call--{status}"),
            "open": open,
            "phx-mounted": _KEEP_OPEN,
        }
    )
    parts: list[Template] = []
    for part_label, value in (
        (required_text("tool call arguments label", arguments_label), arguments),
        (required_text("tool call result label", result_label), result),
    ):
        if value is not None:
            parts.append(
                t'<p class="tori-ui-tool-call__label">{part_label}</p>'
                t'<pre class="tori-ui-tool-call__data" tabindex="0">{value}</pre>'
            )
    state = status if status_label is None else status_label
    return (
        t'<details{attributes}><summary class="tori-ui-tool-call__summary">'
        t"{render_icon('tool', size='sm')}"
        t'<code class="tori-ui-tool-call__name">{name}</code>'
        t'<span class="tori-ui-tool-call__status">{_status_icon(status)}{state}</span>'
        t"{render_icon('chevron-down', size='sm')}</summary>"
        t'<div class="tori-ui-tool-call__content">{fragment(parts)}</div></details>'
    )


def agent_steps(items: Iterable[object], *, label: str = "Steps") -> Template:
    """Render ``agent_step()`` entries as the ordered plan of an agent."""
    label = required_text("agent steps label", label)
    return (
        t'<ol class="tori-ui-agent-steps" aria-label="{label}">{fragment(items)}</ol>'
    )


def agent_step(
    title: object,
    *,
    status: StepStatus = "pending",
    status_label: str | None = None,
    description: object | None = None,
    id: str | None = None,
) -> Template:
    """Render one step of ``agent_steps()`` with its status."""
    status_label = optional_nonempty_text("agent step status label", status_label)
    if id is not None:
        id = html_id("agent step id", id)
    attributes = attrs(
        {
            "id": id,
            "class": classes(
                "tori-ui-agent-steps__step", f"tori-ui-agent-steps__step--{status}"
            ),
            "aria-current": "step" if status == "running" else None,
        }
    )
    state = status if status_label is None else status_label
    description_markup = (
        t'<div class="tori-ui-agent-steps__description">{description}</div>'
        if description is not None
        else raw("")
    )
    return (
        t'<li{attributes}><span class="tori-ui-agent-steps__status">'
        t'{_status_icon(status)}<span class="tori-ui-visually-hidden">{state}: </span>'
        t'</span><div class="tori-ui-agent-steps__body">'
        t'<p class="tori-ui-agent-steps__title">{title}</p>{description_markup}'
        t"</div></li>"
    )


def sources(
    items: Iterable[tuple[str, str]],
    *,
    label: str = "Sources",
    id: str | None = None,
) -> Template:
    """List the sources an answer cites as numbered external links.

    An item is a ``(title, href)`` pair. With an ``id`` each entry gets the ID
    ``<id>-<number>``, which a ``citation()`` can link to.
    """
    label = required_text("sources label", label)
    if id is not None:
        id = html_id("sources id", id)
    entries: list[Template] = []
    for number, item in enumerate(items, start=1):
        title = required_text("sources title", item[0])
        link = attrs(
            {
                "class": "tori-ui-sources__link",
                "href": required_text("sources href", item[1]),
                "target": "_blank",
                "rel": "noopener noreferrer",
            }
        )
        entry = attrs(
            {
                "id": None if id is None else f"{id}-{number}",
                "class": "tori-ui-sources__item",
            }
        )
        entries.append(t"<li{entry}><a{link}>{title}</a></li>")
    return (
        t'<aside class="tori-ui-sources" aria-label="{label}">'
        t'<p class="tori-ui-sources__label">{label}</p>'
        t'<ol class="tori-ui-sources__list">{fragment(entries)}</ol></aside>'
    )


def citation(
    number: int,
    *,
    href: str | None = None,
    title: str | None = None,
) -> Template:
    """Render an inline reference to a numbered source.

    ``href`` is usually the fragment of a ``sources()`` entry, such as
    ``#sources-1``; without it the citation is plain text.
    """
    bounded_integer("citation number", number, 1, 9999)
    title = optional_nonempty_text("citation title", title)
    if href is None:
        attributes = attrs({"class": "tori-ui-citation", "title": title})
        return t"<span{attributes}>{number}</span>"
    attributes = attrs(
        {
            "class": "tori-ui-citation",
            "href": required_text("citation href", href),
            "title": title,
        }
    )
    return t"<a{attributes}>{number}</a>"


def attachment(
    name: str,
    *,
    meta: str | None = None,
    icon: IconName = "file",
    href: str | None = None,
    remove_event: str | JS | None = None,
    remove_label: str = "Remove",
    target: int | None = None,
) -> Template:
    """Render a file that belongs to a message.

    ``meta`` is a short note such as the size. With ``href`` the name links to
    the file, and with ``remove_event`` the chip ends in a remove button whose
    click carries the name as ``name``.
    """
    name = required_text("attachment name", name)
    meta = optional_nonempty_text("attachment meta", meta)
    remove_event = event_binding("attachment remove event", remove_event)
    remove_label = required_text("attachment remove label", remove_label)
    target = event_target("attachment target", target, remove_event)
    label: object
    if href is None:
        label = t'<span class="tori-ui-attachment__name">{name}</span>'
    else:
        link = attrs(
            {
                "class": "tori-ui-attachment__name",
                "href": required_text("attachment href", href),
            }
        )
        label = t"<a{link}>{name}</a>"
    meta_markup = (
        t'<span class="tori-ui-attachment__meta">{meta}</span>'
        if meta is not None
        else raw("")
    )
    remove: object = raw("")
    if remove_event is not None:
        button = attrs(
            {
                "type": "button",
                "class": "tori-ui-attachment__remove",
                "aria-label": remove_label,
                "phx-click": remove_event,
                "phx-target": target,
                "phx-value-name": name,
            }
        )
        remove = t"<button{button}>{render_icon('x', size='sm')}</button>"
    return (
        t'<span class="tori-ui-attachment">{render_icon(icon, size="sm")}{label}'
        t"{meta_markup}{remove}</span>"
    )


def _compact(count: int) -> str:
    if count < 1000:
        return str(count)
    if count < 1_000_000:
        return f"{count / 1000:.1f}".rstrip("0").rstrip(".") + "k"
    return f"{count / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"


def token_usage(
    *,
    input_tokens: int,
    output_tokens: int,
    cost: str | None = None,
    input_label: str = "Input tokens",
    output_label: str = "Output tokens",
) -> Template:
    """Summarize what a response consumed in one quiet line."""
    bounded_integer("token usage input tokens", input_tokens, 0, 10**12)
    bounded_integer("token usage output tokens", output_tokens, 0, 10**12)
    cost = optional_nonempty_text("token usage cost", cost)
    input_label = required_text("token usage input label", input_label)
    output_label = required_text("token usage output label", output_label)
    cost_markup = (
        t'<span class="tori-ui-token-usage__cost">{cost}</span>'
        if cost is not None
        else raw("")
    )
    return (
        t'<span class="tori-ui-token-usage">'
        t'<span class="tori-ui-token-usage__count" title="{input_label}">'
        t"{render_icon('arrow-up', size='sm', label=input_label)}"
        t"{_compact(input_tokens)}</span>"
        t'<span class="tori-ui-token-usage__count" title="{output_label}">'
        t"{render_icon('arrow-down', size='sm', label=output_label)}"
        t"{_compact(output_tokens)}</span>{cost_markup}</span>"
    )


def artifact_panel(
    content: object,
    *,
    title: str,
    id: str,
    subtitle: str | None = None,
    actions: object | None = None,
    copy: bool = True,
    copy_label: str = "Copy",
    copied_label: str = "Copied",
) -> Template:
    """Frame something a model produced, such as a document or a program.

    The panel names itself from ``title`` and, with ``copy``, offers to copy
    its content.
    """
    title = required_text("artifact panel title", title)
    id = selector_id("artifact panel id", id)
    subtitle = optional_nonempty_text("artifact panel subtitle", subtitle)
    subtitle_markup = (
        t'<p class="tori-ui-artifact__subtitle">{subtitle}</p>'
        if subtitle is not None
        else raw("")
    )
    copy_markup = (
        copy_button(to=f"#{id}-content", label=copy_label, copied_label=copied_label)
        if copy
        else raw("")
    )
    actions_markup = actions if actions is not None else raw("")
    return (
        t'<section id="{id}" class="tori-ui-artifact" aria-labelledby="{id}-title">'
        t'<header class="tori-ui-artifact__header">'
        t'<div class="tori-ui-artifact__heading">'
        t'<h2 id="{id}-title" class="tori-ui-artifact__title">{title}</h2>'
        t'{subtitle_markup}</div><div class="tori-ui-artifact__actions">'
        t"{actions_markup}{copy_markup}</div></header>"
        t'<div id="{id}-content" class="tori-ui-artifact__content" '
        t"data-tori-ui-copy-source>{content}</div>"
        t"</section>"
    )


__all__ = [
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

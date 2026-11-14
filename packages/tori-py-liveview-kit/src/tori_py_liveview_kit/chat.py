"""A chat page that owns its conversation."""

from __future__ import annotations

import logging
from abc import abstractmethod
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import partial
from importlib.util import find_spec
from string.templatelib import Template
from typing import Literal

from tori_py_liveview import AsyncResult, MountContext, Rendered
from tori_py_liveview_ui import (
    UiLiveView,
    alert,
    app_shell,
    avatar,
    chat,
    chat_empty,
    chat_log,
    chat_message,
    composer,
    connection_status,
    markdown,
    message_actions,
    reasoning,
    row,
    sources,
    spacer,
    stack,
    text,
    theme_toggle,
    token_usage,
    tool_call,
    typing_indicator,
)
from tori_py_liveview_ui import suggestions as suggestion_buttons

from tori_py_liveview_kit._runtime import FLUSH, REPLY, ReplyRuntime
from tori_py_liveview_kit.events import ChatEvent
from tori_py_liveview_kit.messages import (
    AssistantMessage,
    Message,
    ReasoningPart,
    ReplyStatus,
    TextPart,
    ToolPart,
    UserMessage,
    fold_events,
)

_LOGGER = logging.getLogger(__name__)
_LOG = "chat-messages"
_STATE = "_tori_kit_chat"
# Code in a reply is colored when the optional highlighter is installed.
_HIGHLIGHT = find_spec("pygments") is not None


@dataclass(slots=True)
class _Chat:
    runtime: ReplyRuntime
    messages: list[Message] = field(default_factory=list)
    # The reply being written; it joins ``messages`` when it ends.
    reply: AssistantMessage | None = None
    ids: set[str] = field(default_factory=set)
    turn: int = 0


class ChatLiveView(UiLiveView):
    """A page that turns ``respond()`` into a conversation.

    A subclass implements ``respond()`` as an async generator of events. The
    page keeps the history, streams the reply, and stops it on request and
    when the connection ends. Its state is created on first use, so a
    subclass constructor does not need to call ``super().__init__()``.

    The text below is what a visitor reads or hears; override it to translate
    the page.
    """

    assistant_name: str = "Assistant"
    chat_label: str = "Chat"
    log_label: str = "Conversation"
    welcome: str = "How can I help?"
    welcome_description: str | None = None
    suggestions: Sequence[str | tuple[str, str]] = ()
    suggestions_label: str = "Suggestions"
    placeholder: str | None = None
    composer_label: str = "Message"
    composer_hint: str | None = None
    send_label: str = "Send"
    stop_label: str = "Stop"
    typing_label: str = "Writing a reply"
    reasoning_label: str = "Reasoning"
    thinking_label: str = "Thinking"
    tool_running_label: str = "Running"
    tool_done_label: str = "Done"
    tool_failed_label: str = "Failed"
    tool_unfinished_label: str = "Not finished"
    tool_arguments_label: str = "Arguments"
    tool_result_label: str = "Result"
    sources_label: str = "Sources"
    input_tokens_label: str = "Input tokens"
    output_tokens_label: str = "Output tokens"
    actions_label: str = "Message actions"
    copy_label: str = "Copy"
    copied_label: str = "Copied"
    theme_label: str = "Color theme"
    connection_lost_text: str = "Connection lost. Reconnecting."
    empty_reply_text: str = "The reply is empty."
    stopped_text: str = "Stopped."
    error_text: str = "Something went wrong."

    #: The least time between two renders of a reply that is being written.
    flush_interval: float = 0.05

    @abstractmethod
    def respond(self, messages: Sequence[Message]) -> AsyncIterator[str | ChatEvent]:
        """Yield what the model produces for the visitor's last message.

        Write it as an async generator. ``messages`` is the conversation
        through the visitor's new message. A yielded string is a
        ``TextDelta``. The generator runs in its own task: it reports through
        the events it yields and must not change what the page renders.
        """

    async def initial_messages(self, context: MountContext) -> Sequence[Message]:
        """Return the conversation this mount starts with.

        It runs for the disconnected render and again for every connected
        mount, so a stored conversation survives a reconnect.
        """
        del context
        return ()

    async def reply_finished(self, message: AssistantMessage) -> None:
        """Called once for every reply that ends, however it ended.

        A reply that a disconnect cut off arrives as ``stopped``. An exception
        raised here is logged and does not end the connection.
        """
        del message

    @property
    def messages(self) -> tuple[Message, ...]:
        """The conversation, without the reply that is being written."""
        return tuple(self._chat().messages)

    @property
    def busy(self) -> bool:
        """Whether a reply is being written."""
        return self._chat().runtime.active

    def title(self) -> str | None:
        return self.assistant_name

    async def mount(self, context: MountContext) -> None:
        await super().mount(context)
        state = self._chat()
        for message in await self.initial_messages(context):
            if not isinstance(message, UserMessage | AssistantMessage):
                raise TypeError(
                    "initial_messages must return UserMessage and "
                    "AssistantMessage values"
                )
            if message.id in state.ids:
                raise ValueError(
                    f"initial_messages returned the message id {message.id!r} twice"
                )
            if isinstance(message, AssistantMessage) and message.status == "streaming":
                # Nothing is writing a restored reply any more.
                message = replace(message, status="stopped")
            state.ids.add(message.id)
            state.messages.append(message)
            self._show(message)

    async def handle_event(
        self, event: str, value: object
    ) -> Mapping[str, object] | None:
        match event, value:
            case "chat:send", {"message": str(prompt)}:
                self._send(prompt)
            case "chat:suggest", {"prompt": str(prompt)}:
                self._send(prompt)
            case "chat:stop", _:
                await self._stop()
            case _:
                return await super().handle_event(event, value)
        return None

    async def handle_info(self, name: str, value: object) -> None:
        if name != FLUSH:
            await super().handle_info(name, value)
            return
        # An exception here would close the connection.
        try:
            events = self._chat().runtime.take(value)
            if events:
                self._fold(events)
        except Exception:
            self._abort()

    async def handle_async(self, name: str, result: AsyncResult[object]) -> None:
        if name != REPLY:
            await super().handle_async(name, result)
            return
        try:
            completion = self._chat().runtime.complete(result)
            if completion is None:
                return
            self._fold(completion.events, show=False)
            if completion.error is not None:
                await self._finish("error", self.error_text)
            elif completion.cancelled:
                await self._finish("stopped")
            else:
                await self._finish("done")
        except Exception:
            self._abort()

    async def disconnect(self) -> None:
        # LiveView has cancelled the model task before it calls this.
        try:
            self._fold(self._chat().runtime.abandon(), show=False)
            await self._finish("stopped", show=False)
        except Exception:
            _LOGGER.exception(
                "LiveView Kit cleanup failed: page=%s", type(self).__qualname__
            )
        await super().disconnect()

    def render(self) -> Rendered | Template | str:
        header = row(
            [
                t"<strong>{self.assistant_name}</strong>",
                spacer(),
                theme_toggle(id="chat-theme", label=self.theme_label),
            ],
            gap="sm",
            wrap=False,
        )
        status = connection_status(message=self.connection_lost_text)
        return app_shell(t"{self.chat_panel()}{status}", id="chat-app", header=header)

    def chat_panel(self) -> Template:
        """Render the conversation and its composer.

        Place it in a layout of your own by overriding ``render()``. It must
        be part of every render: a stream that leaves the page loses its
        messages.
        """
        state = self._chat()
        if state.messages or state.reply is not None:
            log: object = chat_log(
                self.stream_contents(_LOG), id=_LOG, label=self.log_label, stream=True
            )
        else:
            log = chat_empty(
                self.welcome,
                description=self.welcome_description,
                suggestions=(
                    suggestion_buttons(
                        self.suggestions,
                        event="chat:suggest",
                        label=self.suggestions_label,
                    )
                    if self.suggestions
                    else None
                ),
            )
        form = composer(
            id="chat-composer",
            submit_event="chat:send",
            label=self.composer_label,
            placeholder=self.placeholder,
            submit_label=self.send_label,
            busy=state.runtime.active,
            stop_event="chat:stop",
            stop_label=self.stop_label,
            hint=self.composer_hint,
        )
        return chat(log, form, label=self.chat_label)

    def render_user_message(self, message: UserMessage) -> Rendered | Template | str:
        """Render a visitor's message as one element whose ID is ``message.id``."""
        return chat_message(message.text, role="user", id=message.id)

    def render_assistant_message(
        self, message: AssistantMessage
    ) -> Rendered | Template | str:
        """Render a reply as one element whose ID is ``message.id``."""
        streaming = message.status == "streaming"
        last = message.parts[-1] if message.parts else None
        body: list[object] = []
        for index, part in enumerate(message.parts):
            match part:
                case ReasoningPart(text=content):
                    thinking = streaming and part is last
                    body.append(
                        reasoning(
                            text(content, size="sm", muted=True),
                            summary=(
                                self.thinking_label
                                if thinking
                                else self.reasoning_label
                            ),
                            streaming=thinking,
                            id=f"{message.id}-reasoning-{index}",
                        )
                    )
                case ToolPart():
                    body.append(
                        self._tool(part, f"{message.id}-tool-{index}", streaming)
                    )
                case TextPart(text=content):
                    body.append(markdown(content, highlight=_HIGHLIGHT))
        waiting = last is None or (
            isinstance(last, ToolPart) and last.result is not None
        )
        if streaming and waiting:
            body.append(typing_indicator(label=self.typing_label))
        elif message.status == "stopped":
            body.append(text(self.stopped_text, size="sm", muted=True))
        elif message.status == "error":
            body.append(alert(message.error or self.error_text, tone="danger"))
        elif not message.parts:
            body.append(text(self.empty_reply_text, size="sm", muted=True))
        footer: list[object] = []
        if not streaming and message.citations:
            footer.append(
                sources(
                    [(citation.title, citation.url) for citation in message.citations],
                    label=self.sources_label,
                    id=f"{message.id}-sources",
                )
            )
        if not streaming and message.usage is not None:
            footer.append(
                token_usage(
                    input_tokens=message.usage.input_tokens,
                    output_tokens=message.usage.output_tokens,
                    cost=message.usage.cost,
                    input_label=self.input_tokens_label,
                    output_label=self.output_tokens_label,
                )
            )
        actions = (
            message_actions(
                [],
                label=self.actions_label,
                copy_label=self.copy_label,
                copied_label=self.copied_label,
            )
            if not streaming and message.text
            else None
        )
        return chat_message(
            stack(body, gap="sm"),
            id=message.id,
            name=self.assistant_name,
            avatar=avatar(self.assistant_name, size="sm"),
            streaming=streaming and isinstance(last, TextPart),
            footer=stack(footer, gap="sm", align="start") if footer else None,
            actions=actions,
        )

    def _tool(self, part: ToolPart, element_id: str, streaming: bool) -> Template:
        if part.result is None and streaming:
            return self._tool_call(part, element_id, "running", self.tool_running_label)
        if part.result is None:
            return self._tool_call(
                part, element_id, "pending", self.tool_unfinished_label
            )
        if part.is_error:
            return self._tool_call(part, element_id, "error", self.tool_failed_label)
        return self._tool_call(part, element_id, "done", self.tool_done_label)

    def _tool_call(
        self,
        part: ToolPart,
        element_id: str,
        status: Literal["pending", "running", "done", "error"],
        label: str,
    ) -> Template:
        return tool_call(
            part.name,
            status=status,
            status_label=label,
            arguments=part.arguments or None,
            result=part.result,
            arguments_label=self.tool_arguments_label,
            result_label=self.tool_result_label,
            id=element_id,
        )

    def _chat(self) -> _Chat:
        state = self.__dict__.get(_STATE)
        if state is None:
            state = _Chat(ReplyRuntime(self, flush_interval=self.flush_interval))
            self.__dict__[_STATE] = state
        return state

    def _send(self, prompt: str) -> None:
        prompt = prompt.strip()
        state = self._chat()
        if not prompt or state.runtime.active:
            return
        while True:
            state.turn += 1
            user_id = f"turn-{state.turn}-user"
            reply_id = f"turn-{state.turn}-assistant"
            if user_id not in state.ids and reply_id not in state.ids:
                break
        state.ids.update((user_id, reply_id))
        user = UserMessage(user_id, prompt)
        state.messages.append(user)
        self._show(user)
        self._begin(reply_id)

    def _begin(self, reply_id: str) -> None:
        state = self._chat()
        history = tuple(state.messages)
        state.reply = AssistantMessage(reply_id, status="streaming")
        self._show(state.reply)
        state.runtime.start(partial(self.respond, history))

    async def _stop(self) -> None:
        state = self._chat()
        if not state.runtime.active:
            return
        # Keep what the model wrote before the visitor stopped it.
        self._fold(state.runtime.stop(), show=False)
        await self._finish("stopped")

    def _fold(self, events: list[ChatEvent], *, show: bool = True) -> None:
        state = self._chat()
        if state.reply is None or not events:
            return
        state.reply = fold_events(state.reply, events)
        if show:
            self._show(state.reply)

    async def _finish(
        self, status: ReplyStatus, error: str | None = None, *, show: bool = True
    ) -> None:
        state = self._chat()
        reply = state.reply
        if reply is None:
            return
        state.reply = None
        if reply.status == "streaming":
            reply = replace(reply, status=status, error=error)
        state.messages.append(reply)
        if show:
            self._show(reply)
        try:
            await self.reply_finished(reply)
        except Exception:
            _LOGGER.exception(
                "LiveView Kit reply_finished failed: page=%s",
                type(self).__qualname__,
            )

    def _show(self, message: Message) -> None:
        """Insert a message into the stream, or update it in place."""
        try:
            if isinstance(message, UserMessage):
                item = self.render_user_message(message)
            else:
                item = self.render_assistant_message(message)
            self.stream_insert(_LOG, message.id, item)
        except Exception:
            _LOGGER.exception(
                "LiveView Kit could not render a message: page=%s message=%s",
                type(self).__qualname__,
                message.id,
            )
            self.stream_insert(_LOG, message.id, self._unrendered(message))

    def _unrendered(self, message: Message) -> Template:
        return chat_message(
            alert(self.error_text, tone="danger"), role=message.role, id=message.id
        )

    def _abort(self) -> None:
        """End the reply after a failure inside one of this page's callbacks."""
        _LOGGER.exception(
            "LiveView Kit callback failed: page=%s", type(self).__qualname__
        )
        try:
            state = self._chat()
            state.runtime.stop()
            reply, state.reply = state.reply, None
            if reply is not None:
                failed = replace(reply, status="error", error=self.error_text)
                state.messages.append(failed)
                self.stream_insert(_LOG, failed.id, self._unrendered(failed))
        except Exception:
            _LOGGER.exception(
                "LiveView Kit could not end a failed reply: page=%s",
                type(self).__qualname__,
            )


__all__ = ["ChatLiveView"]

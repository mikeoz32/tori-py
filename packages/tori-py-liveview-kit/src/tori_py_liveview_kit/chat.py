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
    button,
    chat,
    chat_empty,
    chat_log,
    chat_message,
    composer,
    connection_status,
    icon_button,
    markdown,
    message_actions,
    mode_toggle,
    reasoning,
    row,
    sources,
    spacer,
    stack,
    text,
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
    MessagePart,
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


@dataclass(frozen=True, slots=True)
class _ReplyView:
    message: AssistantMessage
    can_retry: bool

    @property
    def streaming(self) -> bool:
        return self.message.status == "streaming"

    @property
    def last(self) -> MessagePart | None:
        return self.message.parts[-1] if self.message.parts else None


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
    mode_label: str = "Color theme"
    connection_lost_text: str = "Connection lost. Reconnecting."
    empty_reply_text: str = "The reply is empty."
    stopped_text: str = "Stopped."
    error_text: str = "Something went wrong."
    retry_label: str = "Try again"

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

    def describe_error(self, error: BaseException) -> str:
        """Return what a visitor reads when ``respond()`` raised ``error``.

        The default says nothing about the error, because an exception's text
        may hold a credential or an internal address. The exception itself is
        logged.
        """
        del error
        return self.error_text

    def can_retry(self, message: Message) -> bool:
        """Whether ``message`` is a stopped or failed reply that can be retried.

        Only the last message of an idle conversation can.
        """
        state = self._chat()
        return (
            not state.runtime.active
            and bool(state.messages)
            and state.messages[-1].id == message.id
            and isinstance(message, AssistantMessage)
            and message.status in ("stopped", "error")
        )

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
            if message.id in state.ids:
                raise ValueError(
                    f"initial_messages returned the message id {message.id!r} twice"
                )
            if isinstance(message, AssistantMessage) and message.status == "streaming":
                # Nothing is writing a restored reply any more.
                message = replace(message, status="stopped")
            state.ids.add(message.id)
            state.messages.append(message)
        # Retry eligibility depends on the complete restored conversation.
        for message in state.messages:
            self._upsert_message(message)

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
            case "chat:retry", {"message_id": message_id}:
                self._retry(message_id)
            case "chat:retry", _:
                self._retry()
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
                self._apply_reply_events(events)
        except Exception:
            await self._abort_reply()

    async def handle_async(self, name: str, result: AsyncResult[object]) -> None:
        if name != REPLY:
            await super().handle_async(name, result)
            return
        try:
            completion = self._chat().runtime.complete(result)
            if completion is None:
                return
            self._apply_reply_events(completion.events, show=False)
            if completion.error is not None:
                await self._finish_reply("error", self._describe(completion.error))
            elif completion.cancelled:
                await self._finish_reply("stopped")
            else:
                await self._finish_reply("done")
        except Exception:
            await self._abort_reply()

    async def disconnect(self) -> None:
        # LiveView has cancelled the model task before it calls this.
        try:
            self._apply_reply_events(self._chat().runtime.abandon(), show=False)
        except Exception:
            await self._abort_reply(show=False)
        else:
            await self._finish_reply("stopped", show=False)
        await super().disconnect()

    def render(self) -> Rendered | Template | str:
        header = row(
            [
                t"<strong>{self.assistant_name}</strong>",
                spacer(),
                mode_toggle(id="chat-theme", label=self.mode_label),
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
        view = _ReplyView(message, can_retry=self.can_retry(message))
        return chat_message(
            stack(
                [*self._render_reply_parts(view), *self._render_reply_status(view)],
                gap="sm",
            ),
            id=message.id,
            name=self.assistant_name,
            avatar=avatar(self.assistant_name, size="sm"),
            streaming=view.streaming and isinstance(view.last, TextPart),
            footer=self._render_reply_footer(message),
            actions=self._render_reply_actions(view),
            copy_text=message.text if not view.streaming else None,
        )

    def _render_reply_parts(self, view: _ReplyView) -> list[object]:
        message = view.message
        body: list[object] = []
        for index, part in enumerate(message.parts):
            match part:
                case ReasoningPart(text=content):
                    thinking = view.streaming and part is view.last
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
                        self._tool(part, f"{message.id}-tool-{index}", view.streaming)
                    )
                case TextPart(text=content):
                    body.append(markdown(content, highlight=_HIGHLIGHT))
        return body

    def _render_reply_status(self, view: _ReplyView) -> list[object]:
        message, last = view.message, view.last
        waiting = last is None or (
            isinstance(last, ToolPart) and last.result is not None
        )
        if view.streaming and waiting:
            return [typing_indicator(label=self.typing_label)]
        if message.status == "stopped":
            return [text(self.stopped_text, size="sm", muted=True)]
        if message.status == "error":
            return [
                alert(
                    message.error or self.error_text,
                    tone="danger",
                    actions=(
                        button(
                            self.retry_label,
                            variant="secondary",
                            size="sm",
                            icon="refresh",
                            event="chat:retry",
                            values={"message_id": message.id},
                        )
                        if view.can_retry
                        else None
                    ),
                )
            ]
        if not message.parts and not view.streaming:
            return [text(self.empty_reply_text, size="sm", muted=True)]
        return []

    def _render_reply_footer(self, message: AssistantMessage) -> Template | None:
        if message.status == "streaming":
            return None
        footer: list[object] = []
        if message.citations:
            footer.append(
                sources(
                    [(citation.title, citation.url) for citation in message.citations],
                    label=self.sources_label,
                    id=f"{message.id}-sources",
                )
            )
        if message.usage is not None:
            footer.append(
                token_usage(
                    input_tokens=message.usage.input_tokens,
                    output_tokens=message.usage.output_tokens,
                    cost=message.usage.cost,
                    input_label=self.input_tokens_label,
                    output_label=self.output_tokens_label,
                )
            )
        return stack(footer, gap="sm", align="start") if footer else None

    def _render_reply_actions(self, view: _ReplyView) -> Template | None:
        message = view.message
        # A failed reply offers retry in its alert; a stopped one, here.
        retry = (
            [
                icon_button(
                    "refresh",
                    label=self.retry_label,
                    size="sm",
                    event="chat:retry",
                    values={"message_id": message.id},
                )
            ]
            if message.status == "stopped" and view.can_retry
            else []
        )
        return (
            message_actions(
                retry,
                label=self.actions_label,
                copy=bool(message.text),
                copy_label=self.copy_label,
                copied_label=self.copied_label,
            )
            if not view.streaming and (message.text or retry)
            else None
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
        previous = state.messages[-1] if state.messages else None
        user = UserMessage(user_id, prompt)
        state.messages.append(user)
        self._upsert_message(user)
        if isinstance(previous, AssistantMessage) and previous.status != "done":
            # It is no longer the last message, so it stops offering retry.
            self._upsert_message(previous)
        self._begin(reply_id)

    def _retry(self, message_id: object = None) -> None:
        state = self._chat()
        if not state.messages or not self.can_retry(state.messages[-1]):
            return
        if message_id is not None and message_id != state.messages[-1].id:
            return
        # The new attempt takes the place of the reply, under the same ID.
        self._begin(state.messages.pop().id)

    def _begin(self, reply_id: str) -> None:
        state = self._chat()
        history = tuple(state.messages)
        state.reply = AssistantMessage(reply_id, status="streaming")
        self._upsert_message(state.reply)
        state.runtime.start(partial(self.respond, history))

    async def _stop(self) -> None:
        state = self._chat()
        if not state.runtime.active:
            return
        # Keep what the model wrote before the visitor stopped it.
        try:
            self._apply_reply_events(state.runtime.stop(), show=False)
        except Exception:
            await self._abort_reply()
        else:
            await self._finish_reply("stopped")

    def _apply_reply_events(
        self, events: list[ChatEvent], *, show: bool = True
    ) -> None:
        state = self._chat()
        if state.reply is None or not events:
            return
        state.reply = fold_events(state.reply, events)
        if show:
            self._upsert_message(state.reply)

    async def _finish_reply(
        self, status: ReplyStatus, error: str | None = None, *, show: bool = True
    ) -> AssistantMessage | None:
        state = self._chat()
        reply = state.reply
        if reply is None:
            return None
        state.reply = None
        if reply.status == "streaming":
            reply = replace(reply, status=status, error=error)
        state.messages.append(reply)
        try:
            if show:
                self._upsert_message(reply)
        finally:
            # Persistence observes the terminal state even if stream insertion fails.
            try:
                await self.reply_finished(reply)
            except Exception:
                _LOGGER.exception(
                    "LiveView Kit reply_finished failed: page=%s",
                    type(self).__qualname__,
                )
        return reply

    def _describe(self, error: BaseException) -> str:
        try:
            described = self.describe_error(error)
            return described if described.strip() else self.error_text
        except Exception:
            _LOGGER.exception(
                "LiveView Kit describe_error failed: page=%s", type(self).__qualname__
            )
            return self.error_text

    def _upsert_message(self, message: Message) -> None:
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

    async def _abort_reply(self, *, show: bool = True) -> None:
        """End the reply after a failure inside one of this page's callbacks."""
        _LOGGER.exception(
            "LiveView Kit callback failed: page=%s", type(self).__qualname__
        )
        try:
            state = self._chat()
            state.runtime.stop()
            failed = await self._finish_reply("error", self.error_text, show=False)
            if show and failed is not None:
                self.stream_insert(_LOG, failed.id, self._unrendered(failed))
        except Exception:
            _LOGGER.exception(
                "LiveView Kit could not end a failed reply: page=%s",
                type(self).__qualname__,
            )


__all__ = ["ChatLiveView"]

"""Server-rendered task board backed by the CQRS buses."""

from string.templatelib import Template

from tori_py_cqrs_core import CommandBus, QueryBus
from tori_py_liveview import MountContext, UnknownEventError, live_view
from tori_py_liveview_ui import (
    UiLiveView,
    alert,
    badge,
    button,
    card,
    form,
    input,
    stack,
)

from .feed import TaskBoardFeed
from .messages import CreateTask, ListTasks
from .models import CreateTaskBody, Task, TaskTitleInvalid

TASKS = "tasks"
VISIBLE_TASKS = 50
TITLE_ERROR = "After trimming, the task title must contain 1-120 characters."


@live_view("/board")
class TaskBoardLive(UiLiveView):
    def __init__(
        self,
        commands: CommandBus,
        queries: QueryBus,
        feed: TaskBoardFeed,
    ) -> None:
        self._commands = commands
        self._queries = queries
        self._feed = feed
        self._subscribed = False
        self.draft = ""
        self.error: str | None = None
        self.task_count = 0
        self.last_task_id = 0

    async def mount(self, context: MountContext) -> None:
        self.stream_reset(TASKS)
        await self._show_new_tasks()
        if context.connected:
            self._feed.subscribe(self)
            self._subscribed = True

    async def handle_event(self, event: str, value: object) -> None:
        match event, value:
            case "validate", {"task": {"title": str(title)}}:
                self.draft = title
                self.error = None if _valid_title(title) else TITLE_ERROR
            case "create", {"task": {"title": str(title)}}:
                self.draft = title
                try:
                    await self._commands.execute(CreateTask(CreateTaskBody(title)))
                except TaskTitleInvalid:
                    self.error = TITLE_ERROR
                    return
                self.draft = ""
                self.error = None
                await self._show_new_tasks()
            case _:
                raise UnknownEventError(event)

    async def handle_info(self, name: str, value: object) -> None:
        if name != "tasks_changed":
            await super().handle_info(name, value)
            return
        await self._show_new_tasks()

    async def disconnect(self) -> None:
        if self._subscribed:
            self._feed.unsubscribe(self)
            self._subscribed = False

    def title(self) -> str:
        return f"Task board ({self.task_count})"

    def render(self) -> Template:
        title_input = input(
            "Title",
            id="task-title",
            name="task[title]",
            value=self.draft,
            placeholder="What needs doing?",
            error=self.error,
            required=True,
        )
        create_form = form(
            stack(
                [title_input, button("Add task", button_type="submit")],
                gap="sm",
                align="start",
            ),
            id="task-form",
            change_event="validate",
            submit_event="create",
        )
        empty = alert("No tasks yet.") if self.task_count == 0 else ""
        tasks = self.stream_contents(TASKS)
        board = card(
            t'{empty}<ol id="{TASKS}" phx-update="stream">{tasks}</ol>',
            eyebrow="Live",
            title="Newest tasks",
            footer=badge(f"{self.task_count} total", tone="info"),
        )
        return t"<main>{stack([create_form, board], gap='lg')}</main>"

    async def _show_new_tasks(self) -> None:
        tasks = await self._queries.execute(ListTasks())
        for task in tasks:
            if task.id > self.last_task_id:
                self.stream_insert(
                    TASKS,
                    f"task-{task.id}",
                    _task_item(task),
                    at=0,
                    limit=VISIBLE_TASKS,
                )
                self.last_task_id = task.id
        self.task_count = len(tasks)


def _valid_title(title: str) -> bool:
    return 1 <= len(title.strip()) <= 120


def _task_item(task: Task) -> Template:
    return t'<li id="task-{task.id}"><strong>#{task.id}</strong> {task.title}</li>'

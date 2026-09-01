"""Local CQRS facade used by the command RPC controller."""

from tori_py_cqrs_core import CommandBus

from ..contracts import Task
from .messages import CreateTask, RenameTask


class TaskApplicationService:
    def __init__(self, commands: CommandBus) -> None:
        self._commands = commands

    async def create(self, title: str) -> Task:
        return await self._commands.execute(CreateTask(title))

    async def rename(self, task_id: int, title: str) -> Task:
        return await self._commands.execute(RenameTask(task_id, title))


__all__ = ["TaskApplicationService"]

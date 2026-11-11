"""Wake connected task boards when the task list changes."""

from typing import Protocol

from tori_py_cqrs import event_handler

from .messages import TaskCreated


class BoardSubscriber(Protocol):
    def send_info(self, name: str, value: object = None) -> bool: ...


class TaskBoardFeed:
    def __init__(self) -> None:
        self._subscribers: set[BoardSubscriber] = set()

    def subscribe(self, subscriber: BoardSubscriber) -> None:
        self._subscribers.add(subscriber)

    def unsubscribe(self, subscriber: BoardSubscriber) -> None:
        self._subscribers.discard(subscriber)

    def tasks_changed(self) -> None:
        for subscriber in tuple(self._subscribers):
            subscriber.send_info("tasks_changed")


@event_handler(TaskCreated)
class AnnounceTaskCreated:
    def __init__(self, feed: TaskBoardFeed) -> None:
        self._feed = feed

    async def handle(self, event: TaskCreated) -> None:
        del event
        self._feed.tasks_changed()

"""Commands whose persistence outcome the event store could not confirm."""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UnknownOutcome:
    task_id: int
    cause: BaseException


class ReconciliationLog:
    """Keep each unknown outcome until someone checks the store for it."""

    def __init__(self) -> None:
        self.entries: list[UnknownOutcome] = []

    def record(self, task_id: int, cause: BaseException) -> None:
        self.entries.append(UnknownOutcome(task_id, cause))
        logger.warning("task %s: event store outcome unknown: %s", task_id, cause)

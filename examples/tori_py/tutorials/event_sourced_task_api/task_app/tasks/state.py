"""Command-service state that is not part of the aggregate model."""


class TaskIdSequence:
    """Process-local integer allocator used only after title validation."""

    def __init__(self) -> None:
        self._next_id = 1

    def next(self) -> int:
        task_id = self._next_id
        self._next_id += 1
        return task_id


__all__ = ["TaskIdSequence"]

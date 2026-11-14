"""Task API contracts and application errors."""

import msgspec


class Task(msgspec.Struct, frozen=True):
    id: int
    title: str


class CreateTaskBody(msgspec.Struct, forbid_unknown_fields=True):
    title: str


class RenameTaskBody(msgspec.Struct, forbid_unknown_fields=True):
    title: str


class TaskTitleInvalid(Exception):
    """Raised when a normalized task title is outside the accepted length."""


class TaskNotFound(Exception):
    """Raised when a task ID has no event stream."""


class InvalidIfMatch(Exception):
    """Raised when If-Match is not an ETag returned by this API."""


class TaskVersionMismatch(Exception):
    """Raised when the task changed after the client read it."""

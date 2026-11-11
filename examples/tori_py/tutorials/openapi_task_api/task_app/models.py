"""Task API contracts and application errors."""

from typing import Annotated

import msgspec


class Task(msgspec.Struct, frozen=True):
    id: int
    title: str


class CreateTaskBody(msgspec.Struct, forbid_unknown_fields=True):
    title: Annotated[
        str,
        msgspec.Meta(description="Trimmed before storage; 1-120 characters remain."),
    ]


class ParameterError(msgspec.Struct, frozen=True):
    parameter: str
    source: str
    message: str


class Problem(msgspec.Struct, frozen=True):
    """An RFC 9457 Problem Details error response."""

    type: str
    title: str
    status: int
    detail: str
    instance: str
    errors: ParameterError | msgspec.UnsetType = msgspec.UNSET


class TaskTitleInvalid(Exception):
    """Raised when a normalized task title is outside the accepted length."""


class TaskNotFound(Exception):
    """Raised when a task ID is absent from the repository."""

"""Immutable Unit of Work persistence outcomes."""

from dataclasses import dataclass

from tori_py_cqrs_event_sourcing_core.events import CommitResult


@dataclass(frozen=True, slots=True)
class ConfirmedCommit:
    """A validated storage commit result."""

    result: CommitResult


@dataclass(frozen=True, slots=True)
class ConfirmedNonCommit:
    """A confirmed non-commit, optionally caused by an earlier failure."""

    cause: BaseException | None = None


@dataclass(frozen=True, slots=True)
class IndeterminateCommit:
    """A commit whose durable result cannot be proven."""

    cause: BaseException


type UnitOfWorkOutcome = ConfirmedCommit | ConfirmedNonCommit | IndeterminateCommit


__all__ = [
    "ConfirmedCommit",
    "ConfirmedNonCommit",
    "IndeterminateCommit",
    "UnitOfWorkOutcome",
]

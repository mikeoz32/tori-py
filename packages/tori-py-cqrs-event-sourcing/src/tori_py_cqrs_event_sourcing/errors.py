"""Public integration-specific failures."""

import asyncio
from enum import StrEnum

from tori_py_cqrs_event_sourcing_core import (
    CommitResult,
    ConfirmedNonCommit,
    IndeterminateCommit,
    UnitOfWorkOutcome,
)


class CqrsEventSourcingError(Exception):
    """Base class for ToriPy CQRS event-sourcing failures."""


class CqrsEventSourcingConfigurationError(CqrsEventSourcingError):
    """Raised for invalid integration declarations or composition."""


class CommandTransactionUnavailableError(CqrsEventSourcingError):
    """Raised when repository use is outside its owning command body."""


class CommandSynchronizationStateError(CqrsEventSourcingError):
    """Raised when synchronization registration is unavailable."""


class CommandFinalizationPhase(StrEnum):
    """The command lifecycle region in which finalization failed."""

    HANDLER_ROLLBACK = "handler_rollback"
    HANDLER_FINALIZATION = "handler_finalization"
    COMMIT = "commit"
    SYNCHRONIZATION = "synchronization"
    SCOPE_CLEANUP = "scope_cleanup"
    UOW_CLEANUP = "uow_cleanup"


class ConfirmedCommandFinalizationError(CqrsEventSourcingError):
    """A confirmed commit followed by synchronization or cleanup failure."""

    def __init__(
        self,
        *,
        commit_result: CommitResult,
        handler_result: object | None,
        phase: CommandFinalizationPhase,
        primary_error: BaseException,
        secondary_errors: tuple[BaseException, ...] = (),
    ) -> None:
        self.commit_result = commit_result
        self.handler_result = handler_result
        self.phase = phase
        self.primary_error = primary_error
        self.secondary_errors = secondary_errors
        super().__init__(f"confirmed command commit failed during {phase.value}")
        self.__cause__ = primary_error


class ConfirmedNonCommitFinalizationError(CqrsEventSourcingError):
    """A confirmed non-commit with an additional finalization failure."""

    def __init__(
        self,
        *,
        outcome: ConfirmedNonCommit,
        phase: CommandFinalizationPhase,
        primary_error: BaseException,
        secondary_errors: tuple[BaseException, ...] = (),
    ) -> None:
        self.outcome = outcome
        self.phase = phase
        self.primary_error = primary_error
        self.secondary_errors = secondary_errors
        super().__init__(f"confirmed command non-commit failed during {phase.value}")
        self.__cause__ = primary_error


class IndeterminateCommandFinalizationError(CqrsEventSourcingError):
    """An indeterminate commit with an additional finalization failure."""

    def __init__(
        self,
        *,
        outcome: IndeterminateCommit,
        phase: CommandFinalizationPhase,
        primary_error: BaseException,
        secondary_errors: tuple[BaseException, ...] = (),
    ) -> None:
        self.outcome = outcome
        self.phase = phase
        self.primary_error = primary_error
        self.secondary_errors = secondary_errors
        super().__init__(f"indeterminate command failed during {phase.value}")
        self.__cause__ = primary_error


class CommandCancellationError(asyncio.CancelledError):
    """Cancellation retaining the exact persistence outcome."""

    def __init__(
        self,
        *,
        outcome: UnitOfWorkOutcome,
        cancellation: asyncio.CancelledError,
        phase: CommandFinalizationPhase,
        secondary_errors: tuple[BaseException, ...] = (),
    ) -> None:
        self.outcome = outcome
        self.cancellation = cancellation
        self.phase = phase
        self.secondary_errors = secondary_errors
        super().__init__(f"command cancelled during {phase.value}")


__all__ = [
    "CommandCancellationError",
    "CommandFinalizationPhase",
    "CommandSynchronizationStateError",
    "CommandTransactionUnavailableError",
    "ConfirmedCommandFinalizationError",
    "ConfirmedNonCommitFinalizationError",
    "CqrsEventSourcingConfigurationError",
    "CqrsEventSourcingError",
    "IndeterminateCommandFinalizationError",
]

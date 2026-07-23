"""Errors raised by the Nestpy CQRS integration."""

import asyncio

from cqrs_core import CqrsError


class NestpyCqrsError(CqrsError):
    """Base error for integration-specific failures."""


class CqrsConfigurationError(NestpyCqrsError):
    """Raised when explicit Nestpy CQRS configuration is invalid."""


class CqrsLifecycleError(NestpyCqrsError):
    """Raised when coordinated CQRS startup or shutdown fails."""


class CqrsPipelineStateError(NestpyCqrsError):
    """Raised when CQRS invocation pipeline state is used incorrectly."""


class CqrsHandlerExitError(NestpyCqrsError):
    """Retain a handler failure and every terminal-callback failure."""

    def __init__(
        self,
        body_error: BaseException | None,
        callback_errors: tuple[BaseException, ...],
    ) -> None:
        self.body_error = body_error
        self.callback_errors = callback_errors
        super().__init__("CQRS handler terminal finalization failed")
        self.__cause__ = body_error or callback_errors[0]


class CqrsHandlerExitCancellationError(asyncio.CancelledError):
    """Preserve cancellation raised by a handler or terminal callback."""

    def __init__(
        self,
        cancellation: asyncio.CancelledError,
        secondary_errors: tuple[BaseException, ...],
    ) -> None:
        self.cancellation = cancellation
        self.secondary_errors = secondary_errors
        super().__init__("CQRS handler terminal finalization was cancelled")


__all__ = [
    "CqrsConfigurationError",
    "CqrsHandlerExitCancellationError",
    "CqrsHandlerExitError",
    "CqrsLifecycleError",
    "CqrsPipelineStateError",
    "NestpyCqrsError",
]

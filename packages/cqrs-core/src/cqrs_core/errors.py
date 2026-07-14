"""Typed exceptions shared by core protocols and implementations."""

from uuid import UUID


class CqrsError(Exception):
    """Base class for errors raised by the CQRS core."""


class CqrsValidationError(CqrsError):
    """Raised when a core contract receives invalid data."""


class EnvelopeValidationError(CqrsValidationError):
    """Raised when an envelope or delivery metadata is invalid."""


class TransportLifecycleError(CqrsError):
    """Base class for transport lifecycle failures."""


class TransportNotStartedError(TransportLifecycleError):
    """Raised when work is submitted before transport startup."""


class TransportStoppedError(TransportLifecycleError):
    """Raised when work is submitted after transport shutdown."""


class QueueCapacityError(CqrsError):
    """Raised when a bounded transport queue cannot accept work in time."""

    def __init__(self, *, timeout: float | None = None) -> None:
        self.timeout = timeout
        detail = " before the timeout" if timeout is not None else ""
        super().__init__(f"transport queue did not have capacity{detail}")


class RequestTimeoutError(CqrsError):
    """Raised when a request caller stops waiting for a reply."""

    def __init__(
        self,
        *,
        message_id: UUID,
        correlation_id: UUID,
        timeout: float | None = None,
    ) -> None:
        self.message_id = message_id
        self.correlation_id = correlation_id
        self.timeout = timeout
        detail = f" after {timeout} seconds" if timeout is not None else ""
        super().__init__(
            f"request {message_id} with correlation {correlation_id} timed out{detail}"
        )


class InvalidLifecycleTransitionError(TransportLifecycleError):
    """Raised when a transport lifecycle operation is not valid in its state."""

    def __init__(self, *, operation: str, state: str) -> None:
        self.operation = operation
        self.state = state
        super().__init__(f"cannot {operation} while transport is in {state} state")


class DuplicateHandlerError(CqrsValidationError):
    """Base class for duplicate handler registrations."""

    def __init__(self, *, message_type: str) -> None:
        self.message_type = message_type
        super().__init__(f"multiple handlers registered for {message_type}")


class DuplicateCommandHandlerError(DuplicateHandlerError):
    """Raised when a command has more than one handler."""


class DuplicateQueryHandlerError(DuplicateHandlerError):
    """Raised when a query has more than one handler."""


class MissingHandlerError(CqrsError):
    """Raised when a message has no required handler."""

    def __init__(self, *, message_type: str) -> None:
        self.message_type = message_type
        super().__init__(f"no handler registered for {message_type}")


class InvalidHandlerRegistrationError(CqrsValidationError):
    """Raised when a handler registration does not satisfy its contract."""


class InvalidReplyCorrelationError(CqrsError):
    """Raised when a reply does not match its request correlation ID."""

    def __init__(self, *, expected: UUID, actual: UUID) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"reply correlation {actual} does not match expected {expected}"
        )

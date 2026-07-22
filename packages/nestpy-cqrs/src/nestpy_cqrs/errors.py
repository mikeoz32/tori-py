"""Errors raised by the Nestpy CQRS integration."""

from cqrs_core import CqrsError


class NestpyCqrsError(CqrsError):
    """Base error for integration-specific failures."""


class CqrsConfigurationError(NestpyCqrsError):
    """Raised when explicit Nestpy CQRS configuration is invalid."""


class CqrsLifecycleError(NestpyCqrsError):
    """Raised when coordinated CQRS startup or shutdown fails."""


__all__ = ["CqrsConfigurationError", "CqrsLifecycleError", "NestpyCqrsError"]

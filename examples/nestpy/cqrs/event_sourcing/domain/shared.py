"""Shared community domain values and failures."""

from enum import StrEnum


class DomainError(Exception):
    """Base class for expected community domain failures."""


class DomainValidationError(DomainError):
    """Raised when a requested state transition is invalid."""


class AccessDeniedError(DomainError):
    """Raised when an explicit actor cannot perform an operation."""


class DomainNotFoundError(DomainError):
    """Raised when a projected domain object is missing."""


class Visibility(StrEnum):
    PUBLIC = "public"
    MEMBERS = "members"
    PRIVATE = "private"


class GroupAccess(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


def require_text(value: str, *, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise DomainValidationError(
            f"{field} must contain 1-{maximum} non-whitespace characters"
        )
    return normalized


__all__ = [
    "AccessDeniedError",
    "DomainError",
    "DomainNotFoundError",
    "DomainValidationError",
    "GroupAccess",
    "Visibility",
    "require_text",
]

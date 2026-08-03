"""Stable package errors for the Nestpy microservices integration."""

from __future__ import annotations


class MicroservicesError(Exception):
    """Base error for failures owned by the microservices integration."""

    diagnostic_code = "microservices.error"


class OptionalDependencyError(MicroservicesError):
    """Raised when an optional transport dependency is used without its extra."""

    diagnostic_code = "microservices.optional_dependency"

    def __init__(self, dependency: str, extra: str) -> None:
        self.dependency = dependency
        self.extra = extra
        super().__init__(
            f"{dependency!r} is required for this feature; install the "
            f"'nestpy-microservices[{extra}]' extra"
        )


class IdentityValidationError(MicroservicesError, ValueError):
    """Raised when a published service or message identity is invalid."""

    diagnostic_code = "microservices.identity_validation"


class WireValidationError(MicroservicesError, ValueError):
    """Raised when a transport-neutral wire value violates its contract."""

    diagnostic_code = "microservices.wire_validation"


class WireEncodingError(WireValidationError):
    """Raised when a value cannot be encoded under the wire contract."""

    diagnostic_code = "microservices.wire_encoding"


class WireDecodingError(WireValidationError):
    """Raised when bytes do not contain a valid wire envelope."""

    diagnostic_code = "microservices.wire_decoding"


class WireSizeLimitError(WireValidationError):
    """Raised before decoding when a wire value exceeds configured limits."""

    diagnostic_code = "microservices.wire_size_limit"


class WireDeadlineError(WireValidationError):
    """Raised when an envelope deadline violates the RPC contract."""

    diagnostic_code = "microservices.wire_deadline"


class HandlerCompilationError(MicroservicesError, ValueError):
    """Raised when message handler metadata or signatures are invalid."""

    diagnostic_code = "microservices.handler_compilation"


__all__ = [
    "HandlerCompilationError",
    "IdentityValidationError",
    "MicroservicesError",
    "OptionalDependencyError",
    "WireDeadlineError",
    "WireDecodingError",
    "WireEncodingError",
    "WireSizeLimitError",
    "WireValidationError",
]

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


__all__ = ["MicroservicesError", "OptionalDependencyError"]

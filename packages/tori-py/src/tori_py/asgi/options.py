"""Configuration owned by the native ASGI application adapter."""

from dataclasses import dataclass

from tori_py.core.errors import BootstrapError


@dataclass(frozen=True, slots=True)
class AsgiOptions:
    """Transport-specific native ASGI request limits."""

    body_size_limit: int = 1024 * 1024

    def __post_init__(self) -> None:
        if type(self.body_size_limit) is not int:
            raise BootstrapError(
                "body_size_limit must be an integer",
                code="application.invalid_options",
            )
        if self.body_size_limit < 0:
            raise BootstrapError(
                "body_size_limit cannot be negative",
                code="application.invalid_options",
            )


__all__ = ["AsgiOptions"]

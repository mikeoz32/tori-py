"""Driver-neutral application and Starlette option declarations."""

from dataclasses import dataclass

from nestpy.core.errors import BootstrapError
from nestpy.core.metadata import validate_pipeline_binding
from nestpy.core.protocols import ExceptionFilter, Guard, Interceptor, Pipe
from nestpy.core.providers import Token


def _non_negative(name: str, value: object) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise BootstrapError(
            f"{name} must be a number",
            code="application.invalid_options",
        )
    if value < 0:
        raise BootstrapError(
            f"{name} cannot be negative",
            code="application.invalid_options",
        )


@dataclass(frozen=True, slots=True)
class ApplicationOptions:
    """Application lifecycle timing options."""

    shutdown_timeout: float = 30.0
    cancellation_grace: float = 1.0
    cleanup_reserve: float = 5.0

    def __post_init__(self) -> None:
        _non_negative("shutdown_timeout", self.shutdown_timeout)
        _non_negative("cancellation_grace", self.cancellation_grace)
        _non_negative("cleanup_reserve", self.cleanup_reserve)
        if self.cancellation_grace + self.cleanup_reserve > self.shutdown_timeout:
            raise BootstrapError(
                "cancellation grace plus cleanup reserve exceeds shutdown timeout",
                code="application.invalid_options",
            )


@dataclass(frozen=True, slots=True)
class StarletteOptions:
    """Starlette-driver limits and pipeline provider tokens."""

    body_size_limit: int = 1024 * 1024
    middleware: tuple[Token, ...] = ()
    guards: tuple[Token | Guard, ...] = ()
    pipes: tuple[Token | Pipe, ...] = ()
    interceptors: tuple[Token | Interceptor, ...] = ()
    filters: tuple[Token | ExceptionFilter, ...] = ()

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
        for field_name in (
            "middleware",
            "guards",
            "pipes",
            "interceptors",
            "filters",
        ):
            values = tuple(getattr(self, field_name))
            try:
                values = tuple(
                    validate_pipeline_binding(field_name, binding) for binding in values
                )
            except BootstrapError as error:
                raise BootstrapError(
                    f"{field_name} contains an invalid registration",
                    code=error.diagnostic_code,
                ) from error
            object.__setattr__(self, field_name, values)


__all__ = ["ApplicationOptions", "StarletteOptions"]

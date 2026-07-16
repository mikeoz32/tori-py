"""Bootstrap context used while factories and dynamic modules materialize."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import MappingProxyType

from nestpy.core.errors import BootstrapError


@dataclass(frozen=True, slots=True)
class BootstrapContext:
    """Immutable non-secret bootstrap overrides."""

    overrides: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        normalized: list[tuple[str, str]] = []
        for path, value in self.overrides:
            if not isinstance(path, str) or not path:
                raise BootstrapError(
                    "bootstrap override path cannot be empty",
                    code="settings.source_error",
                )
            if not isinstance(value, str):
                raise BootstrapError(
                    "bootstrap override values must remain textual",
                    code="settings.source_error",
                )
            normalized.append((path, value))
        object.__setattr__(self, "overrides", tuple(normalized))

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> BootstrapContext:
        return cls(tuple(values.items()))

    def as_mapping(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self.overrides))


_CURRENT_CONTEXT: ContextVar[BootstrapContext | None] = ContextVar(
    "nestpy_bootstrap_context",
    default=None,
)


def current_bootstrap_context() -> BootstrapContext:
    """Return the current context or an empty external-hosting context."""

    return _CURRENT_CONTEXT.get() or BootstrapContext()


@contextmanager
def use_bootstrap_context(context: BootstrapContext) -> Iterator[None]:
    """Set and reliably reset bootstrap context across factory awaits."""

    token = _CURRENT_CONTEXT.set(context)
    try:
        yield
    finally:
        _CURRENT_CONTEXT.reset(token)


__all__ = [
    "BootstrapContext",
    "current_bootstrap_context",
    "use_bootstrap_context",
]

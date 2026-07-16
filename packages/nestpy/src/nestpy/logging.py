"""Structured logging and driver-neutral correlation context."""

from __future__ import annotations

import contextvars
import logging as std_logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

from nestpy.core.modules import DeferredModule, ModuleSpec
from nestpy.core.protocols import Logger
from nestpy.core.providers import FactoryProvider

_RESERVED_FIELDS = frozenset(
    {
        "application",
        "module",
        "provider",
        "route",
        "scope",
        "request_id",
        "resource_state",
    }
)
_correlation: contextvars.ContextVar[Mapping[str, object] | None] = (
    contextvars.ContextVar(
        "nestpy_log_correlation",
        default=None,
    )
)


@dataclass(frozen=True, slots=True)
class LogContext:
    """Immutable framework fields carried by the current execution context."""

    fields: Mapping[str, object]


def current_log_context() -> LogContext:
    return LogContext(dict(_correlation.get() or {}))


@contextmanager
def use_log_context(**fields: object) -> Iterator[LogContext]:
    """Temporarily add correlation fields and reset them on exit."""

    previous = dict(_correlation.get() or {})
    merged = {**previous, **fields}
    token = _correlation.set(merged)
    try:
        yield LogContext(dict(merged))
    finally:
        _correlation.reset(token)


class PythonLogger:
    """Logger implementation that emits reserved fields through ``extra``."""

    def __init__(
        self,
        logger: std_logging.Logger | None = None,
        fields: Mapping[str, object] | None = None,
    ) -> None:
        self._logger = logger or std_logging.getLogger("nestpy")
        self._fields = dict(fields or {})

    def bind(self, **fields: object) -> PythonLogger:
        accepted = {
            key: value for key, value in fields.items() if key not in _RESERVED_FIELDS
        }
        return PythonLogger(self._logger, {**self._fields, **accepted})

    def debug(self, message: str, **fields: object) -> None:
        self._write(std_logging.DEBUG, message, fields)

    def info(self, message: str, **fields: object) -> None:
        self._write(std_logging.INFO, message, fields)

    def warning(self, message: str, **fields: object) -> None:
        self._write(std_logging.WARNING, message, fields)

    def error(self, message: str, **fields: object) -> None:
        self._write(std_logging.ERROR, message, fields)

    def _write(
        self,
        level: int,
        message: str,
        fields: Mapping[str, object],
    ) -> None:
        context = dict(_correlation.get() or {})
        accepted = {
            key: value for key, value in fields.items() if key not in _RESERVED_FIELDS
        }
        merged = {**context, **self._fields, **accepted}
        self._logger.log(level, message, extra={"nestpy": merged})


class LoggingModule:
    """Opt-in global module exposing the default :class:`Logger`."""

    @classmethod
    def for_root(
        cls,
        *,
        application: str = "nestpy",
        logger_name: str = "nestpy",
        level: int = std_logging.INFO,
        global_: bool = True,
    ) -> DeferredModule:
        def materialize() -> ModuleSpec:
            logger = std_logging.getLogger(logger_name)
            logger.setLevel(level)
            return ModuleSpec(
                providers=[
                    FactoryProvider(
                        Logger,
                        lambda: PythonLogger(logger, {"application": application}),
                    )
                ],
                exports=[Logger],
                global_=global_,
            )

        return DeferredModule(cls, "default", materialize)


__all__ = [
    "LogContext",
    "LoggingModule",
    "PythonLogger",
    "current_log_context",
    "use_log_context",
]

"""Driver-neutral protocols shared by later Nestpy phases."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from nestpy.core.providers import Token


@runtime_checkable
class ScopedResolver(Protocol):
    """Resolve a token in the current application or request scope."""

    async def resolve(self, token: Token) -> object:
        """Resolve one provider token."""


@runtime_checkable
class ExecutionContext(Protocol):
    """Driver-neutral context visible to pipeline components."""

    @property
    def application_id(self) -> str:
        """Return the application identifier."""

    @property
    def module_id(self) -> str | None:
        """Return the owning module identifier."""

    @property
    def route_id(self) -> str | None:
        """Return the route identifier when one matched."""

    @property
    def request_id(self) -> str | None:
        """Return the request correlation identifier."""

    @property
    def resolver(self) -> ScopedResolver:
        """Return the invalidatable scoped resolver."""

    @property
    def metadata(self) -> Mapping[str, object]:
        """Return immutable framework metadata."""

    @property
    def execution_kind(self) -> str:
        """Return a driver-neutral execution kind such as ``http``."""


@runtime_checkable
class Middleware(Protocol):
    async def handle(
        self,
        context: ExecutionContext,
        next: Callable[[], Awaitable[PipelineResult]],
    ) -> PipelineResult:
        """Execute middleware around the one-shot next callback."""


@runtime_checkable
class Guard(Protocol):
    async def can_activate(self, context: ExecutionContext) -> bool:
        """Return whether execution may continue."""


@runtime_checkable
class Pipe(Protocol):
    async def transform(
        self,
        value: object,
        metadata: ArgumentMetadata,
    ) -> object:
        """Transform one extracted argument."""


@runtime_checkable
class Interceptor(Protocol):
    async def intercept(
        self,
        context: ExecutionContext,
        next: Callable[[], Awaitable[PipelineResult]],
    ) -> PipelineResult:
        """Execute around the one-shot next callback."""


@runtime_checkable
class ExceptionFilter(Protocol):
    async def catch(
        self,
        error: Exception,
        context: ExecutionContext,
    ) -> PipelineResult:
        """Return a replacement result or re-raise the error."""


@runtime_checkable
class Logger(Protocol):
    def bind(self, **fields: object) -> Logger:
        """Return a logger with structured fields attached."""

    def debug(self, message: str, **fields: object) -> None:
        """Write a debug record."""

    def info(self, message: str, **fields: object) -> None:
        """Write an info record."""

    def warning(self, message: str, **fields: object) -> None:
        """Write a warning record."""

    def error(self, message: str, **fields: object) -> None:
        """Write an error record."""


@runtime_checkable
class Codec(Protocol):
    def decode(
        self,
        value: object,
        target: type[object],
        *,
        path: str = "",
    ) -> object:
        """Decode one value into a declared target type."""

    def encode(self, value: object) -> object:
        """Encode one value into a serializable representation."""


@runtime_checkable
class SettingsDecoder(Protocol):
    def decode(
        self,
        values: Mapping[str, object],
        model: type[object],
        *,
        codec: Codec,
    ) -> object:
        """Decode merged settings values into a model instance."""


@dataclass(frozen=True, slots=True)
class ArgumentMetadata:
    """Metadata passed to one argument pipe."""

    parameter_name: str
    binding_kind: str
    source_name: str | None
    annotation: object
    route_id: str
    module_id: str


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """A driver-neutral value or opaque explicit driver response."""

    value: object
    is_response: bool = False

    @classmethod
    def from_value(cls, value: object) -> PipelineResult:
        return cls(value=value)

    @classmethod
    def from_response(cls, response: object) -> PipelineResult:
        return cls(value=response, is_response=True)


__all__ = [
    "ArgumentMetadata",
    "Codec",
    "ExceptionFilter",
    "ExecutionContext",
    "Guard",
    "Interceptor",
    "Logger",
    "Middleware",
    "Pipe",
    "PipelineResult",
    "ScopedResolver",
    "SettingsDecoder",
]

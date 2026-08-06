"""Driver-neutral protocols shared by later Nestpy phases."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from nestpy.core.providers import Token

if TYPE_CHECKING:
    from nestpy.core.compiler import CompiledGraph, ModuleId, ProviderRef
    from nestpy.core.discovery import ModuleView, ProviderView
    from nestpy.core.reflection import MetadataDecorator, MetadataKey


@runtime_checkable
class ScopedResolver(Protocol):
    """Resolve a token in the current application or request scope."""

    async def resolve(self, token: Token) -> object:
        """Resolve one provider token."""


@runtime_checkable
class QualifiedScopedResolver(ScopedResolver, Protocol):
    """Optional exact-reference resolution capability."""

    async def resolve_ref(self, ref: ProviderRef) -> object:
        """Resolve one exact provider reference visible from this module."""


@runtime_checkable
class GraphValidator(Protocol):
    """Validate a complete graph before singleton or resource startup."""

    def validate_graph(self, graph: CompiledGraph) -> None:
        """Raise when the compiled application violates an extension invariant."""


@runtime_checkable
class WorkScopeFactory(Protocol):
    """Open application-tracked DI work scopes from one module identity."""

    @property
    def application_id(self) -> str:
        """Return the driver-neutral application identifier."""

    @property
    def module_id(self) -> ModuleId:
        """Return the module identity used for provider visibility."""

    def open(self) -> AbstractAsyncContextManager[ScopedResolver]:
        """Return a fresh work scope for one asynchronous invocation."""

    async def run[T](
        self,
        operation: Callable[[ScopedResolver], Awaitable[T]],
    ) -> T:
        """Execute one scoped operation without inherited execution context."""

    async def run_in[T](
        self,
        module_id: ModuleId,
        operation: Callable[[ScopedResolver], Awaitable[T]],
    ) -> T:
        """Execute one scoped operation from an exact compiled module identity."""


@runtime_checkable
class ModulesContainer(Protocol):
    """Read-only application view over every compiled module."""

    def __len__(self) -> int: ...

    def __iter__(self) -> Iterator[ModuleId]: ...

    def __getitem__(self, module_id: ModuleId) -> ModuleView: ...

    def values(self) -> tuple[ModuleView, ...]: ...

    def provider(self, module_id: ModuleId, token: Token) -> ProviderView | None:
        """Return the exact visible declaration and its canonical provider."""


@runtime_checkable
class DiscoveryService(Protocol):
    """Enumerate compiled providers and controllers without constructing them."""

    def get_providers[T](
        self,
        *,
        include: Iterable[type[object]] | None = None,
        metadata: MetadataKey[T] | MetadataDecorator[T] | None = None,
    ) -> tuple[ProviderView, ...]: ...

    def get_controllers[T](
        self,
        *,
        include: Iterable[type[object]] | None = None,
        metadata: MetadataKey[T] | MetadataDecorator[T] | None = None,
    ) -> tuple[ProviderView, ...]: ...

    def get_metadata_by_decorator[T](
        self,
        decorator: MetadataDecorator[T],
        provider: ProviderView,
    ) -> T | None: ...


@runtime_checkable
class ShutdownContext(Protocol):
    """Expose the remaining graceful quiescence budget."""

    def remaining(self) -> float | None:
        """Return remaining seconds, or None when shutdown is unbounded."""


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
    "DiscoveryService",
    "ExceptionFilter",
    "ExecutionContext",
    "GraphValidator",
    "Guard",
    "Interceptor",
    "Logger",
    "Middleware",
    "ModulesContainer",
    "Pipe",
    "PipelineResult",
    "ScopedResolver",
    "SettingsDecoder",
    "ShutdownContext",
    "WorkScopeFactory",
]

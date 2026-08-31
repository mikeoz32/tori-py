"""Framework-neutral ToriPy errors and diagnostic values."""

import asyncio
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

type DiagnosticCode = str


class Diagnostic:
    """A stable machine-readable diagnostic without framework object reprs."""

    __slots__ = ("code", "message", "details")

    def __init__(
        self,
        code: DiagnosticCode,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = MappingProxyType(dict(details or {}))

    def __repr__(self) -> str:
        return (
            f"Diagnostic(code={self.code!r}, message={self.message!r}, "
            f"details={dict(self.details)!r})"
        )


class ToriPyError(Exception):
    """Base class for public ToriPy failures."""

    code: DiagnosticCode = "tori_py.error"

    def __init__(
        self,
        message: str,
        *,
        code: DiagnosticCode | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic = Diagnostic(code or self.code, message, details)

    @property
    def diagnostic_code(self) -> DiagnosticCode:
        return self.diagnostic.code


class BootstrapError(ToriPyError):
    """Raised when application declarations cannot be bootstrapped."""

    code = "bootstrap.error"


class ResolutionError(ToriPyError):
    """Raised when a provider cannot be resolved."""

    code = "provider.resolution_error"


class ScopeError(ToriPyError):
    """Raised for invalid scope declarations or use."""

    code = "provider.scope_error"


class ScopeClosedError(ScopeError):
    """Raised when a closed scope is used."""

    code = "scope.closed"


class ResourceError(ToriPyError):
    """Raised when resource acquisition or cleanup fails."""

    code = "resource.error"


class ScopeFinalizationError(ResourceError):
    """Retain an ordinary scope failure and every cleanup failure."""

    code = "resource.cleanup_error"

    def __init__(
        self,
        body_error: BaseException | None,
        cleanup_errors: tuple[BaseException, ...],
    ) -> None:
        if not cleanup_errors:
            raise ValueError("scope finalization requires cleanup errors")
        super().__init__(
            "scope resource cleanup failed",
            details={"cleanup_error_count": len(cleanup_errors)},
        )
        self.body_error = body_error
        self.cleanup_errors = cleanup_errors


class ScopeCancellationError(asyncio.CancelledError):
    """Preserve cancellation while retaining scope cleanup failures."""

    def __init__(
        self,
        cancellation: asyncio.CancelledError,
        cleanup_errors: tuple[BaseException, ...],
    ) -> None:
        super().__init__("scope resource cleanup failed during cancellation")
        self.cancellation = cancellation
        self.body_error = cancellation
        self.cleanup_errors = cleanup_errors


class LifecycleError(ToriPyError):
    """Raised when an application lifecycle hook fails."""

    code = "lifecycle.error"


class ApplicationStateError(ToriPyError):
    """Raised when an application state transition is invalid."""

    code = "application.invalid_state"


class SettingsError(ToriPyError):
    """Raised by settings loading and decoding."""

    code = "settings.error"


class PipelineStateError(ToriPyError):
    """Raised when pipeline execution violates its state contract."""

    code = "pipeline.invalid_state"


DIAGNOSTIC_CODES: Final[frozenset[DiagnosticCode]] = frozenset(
    {
        "module.cycle",
        "module.dynamic_conflict",
        "module.static_dynamic_conflict",
        "module.materialization_error",
        "module.invalid_constructor",
        "module.invalid_export",
        "provider.duplicate",
        "provider.invalid_declaration",
        "provider.invalid_signature",
        "provider.unresolved",
        "provider.ambiguous",
        "provider.cycle",
        "provider.alias_cycle",
        "provider.scope_violation",
        "provider.reserved_token",
        "reflection.invalid_metadata",
        "reflection.duplicate_metadata",
        "discovery.invalid_filter",
        "controller.invalid_declaration",
        "controller.invalid_signature",
        "route.invalid_signature",
        "route.duplicate",
        "route.invalid_binding",
        "route.duplicate_pipeline_decorator",
        "gateway.invalid_declaration",
        "gateway.invalid_signature",
        "gateway.invalid_binding",
        "gateway.duplicate_metadata",
        "gateway.duplicate",
        "settings.source_error",
        "settings.decode_error",
        "testing.builder_sealed",
        "testing.invalid_module",
        "testing.invalid_override",
        "testing.private_provider",
        "testing.httpx_unavailable",
        "resource.acquire_error",
        "resource.cleanup_error",
        "resource.lingering_worker",
        "resource.lingering_resource",
        "lifecycle.startup_error",
        "lifecycle.shutdown_timeout",
        "lifecycle.lingering_task",
        "application.invalid_state",
    }
)

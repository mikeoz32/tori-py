"""Framework-neutral Nestpy errors and diagnostic values."""

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


class NestpyError(Exception):
    """Base class for public Nestpy failures."""

    code: DiagnosticCode = "nestpy.error"

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


class BootstrapError(NestpyError):
    """Raised when application declarations cannot be bootstrapped."""

    code = "bootstrap.error"


class ResolutionError(NestpyError):
    """Raised when a provider cannot be resolved."""

    code = "provider.resolution_error"


class ScopeError(NestpyError):
    """Raised for invalid scope declarations or use."""

    code = "provider.scope_error"


class ScopeClosedError(ScopeError):
    """Raised when a closed scope is used."""

    code = "scope.closed"


class ResourceError(NestpyError):
    """Raised when resource acquisition or cleanup fails."""

    code = "resource.error"


class LifecycleError(NestpyError):
    """Raised when an application lifecycle hook fails."""

    code = "lifecycle.error"


class ApplicationStateError(NestpyError):
    """Raised when an application state transition is invalid."""

    code = "application.invalid_state"


class SettingsError(NestpyError):
    """Raised by settings loading and decoding."""

    code = "settings.error"


class PipelineStateError(NestpyError):
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

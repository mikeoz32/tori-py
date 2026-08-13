"""Public OpenAPI integration failures."""

from tori_py import ToriPyError


class OpenApiError(ToriPyError):
    """Base class for ToriPy OpenAPI integration failures."""

    code = "openapi.error"


class OpenApiConfigurationError(OpenApiError):
    """Raised when OpenAPI package configuration is invalid."""

    code = "openapi.configuration_error"


class OpenApiMetadataError(OpenApiError):
    """Raised when documentation metadata is invalid or ambiguous."""

    code = "openapi.metadata_error"


class OpenApiSchemaError(OpenApiError):
    """Raised when an annotation cannot produce an OpenAPI schema."""

    code = "openapi.schema_error"


__all__ = [
    "OpenApiConfigurationError",
    "OpenApiError",
    "OpenApiMetadataError",
    "OpenApiSchemaError",
]

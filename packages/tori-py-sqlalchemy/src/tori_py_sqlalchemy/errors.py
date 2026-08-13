"""Public integration-specific failures."""

from tori_py import ToriPyError


class SqlAlchemyIntegrationError(ToriPyError):
    """Base class for ToriPy SQLAlchemy integration failures."""

    code = "sqlalchemy.integration_error"


class SqlAlchemyConfigurationError(SqlAlchemyIntegrationError):
    """Raised for invalid SQLAlchemy module configuration."""

    code = "sqlalchemy.configuration_error"


class TransactionContextError(SqlAlchemyIntegrationError):
    """Raised when an entity operation has no usable transaction context."""

    code = "sqlalchemy.transaction_context_error"


__all__ = [
    "SqlAlchemyConfigurationError",
    "SqlAlchemyIntegrationError",
    "TransactionContextError",
]

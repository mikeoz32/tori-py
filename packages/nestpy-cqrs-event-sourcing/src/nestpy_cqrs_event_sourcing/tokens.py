"""Deterministic public tokens for keyed event-sourcing roots."""

from nestpy import Token

from nestpy_cqrs_event_sourcing.errors import CqrsEventSourcingConfigurationError


def _keyed(kind: str, key: str) -> Token:
    if not isinstance(key, str) or not key or key == "static":
        raise CqrsEventSourcingConfigurationError(
            "event-sourcing key must be non-empty and not 'static'"
        )
    return f"nestpy_cqrs_event_sourcing:{key}:{kind}"


def get_event_store_token(*, key: str = "default") -> Token:
    """Return the qualified EventStore token for one root."""

    return _keyed("event_store", key)


def get_schema_registry_token(*, key: str = "default") -> Token:
    """Return the qualified schema-registry token for one root."""

    return _keyed("schema_registry", key)


def get_command_synchronization_token(*, key: str = "default") -> Token:
    """Return the qualified command-synchronization token for one root."""

    return _keyed("command_synchronization", key)


def get_transaction_interceptor_token(*, key: str = "default") -> Token:
    """Return the qualified CQRS transaction-interceptor token for one root."""

    return _keyed("transaction_interceptor", key)


def _transaction_accessor_token(key: str) -> Token:
    return _keyed("private_transaction_accessor", key)


def _transaction_coordinator_token(key: str) -> Token:
    return _keyed("private_transaction_coordinator", key)


def _synchronization_state_token(key: str) -> Token:
    return _keyed("private_synchronization_state", key)


__all__ = [
    "get_command_synchronization_token",
    "get_event_store_token",
    "get_schema_registry_token",
    "get_transaction_interceptor_token",
]

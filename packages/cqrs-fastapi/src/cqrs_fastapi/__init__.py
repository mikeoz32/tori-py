"""FastAPI integration for cqrs-core."""

from cqrs_fastapi.adapter import (
    FastAPIAdapter,
    FastAPIConfigurationError,
    get_command_bus,
    get_event_bus,
    get_query_bus,
)
from cqrs_fastapi.provider import FastAPIHandlerProvider

__all__ = [
    "FastAPIAdapter",
    "FastAPIConfigurationError",
    "FastAPIHandlerProvider",
    "get_command_bus",
    "get_event_bus",
    "get_query_bus",
]

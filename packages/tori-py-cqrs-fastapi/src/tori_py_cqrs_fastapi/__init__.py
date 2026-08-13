"""FastAPI integration for tori-py-cqrs-core."""

from tori_py_cqrs_fastapi.adapter import (
    FastAPIAdapter,
    FastAPIConfigurationError,
    get_command_bus,
    get_event_bus,
    get_query_bus,
)
from tori_py_cqrs_fastapi.provider import FastAPIHandlerProvider

__all__ = [
    "FastAPIAdapter",
    "FastAPIConfigurationError",
    "FastAPIHandlerProvider",
    "get_command_bus",
    "get_event_bus",
    "get_query_bus",
]

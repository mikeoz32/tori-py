"""Nestpy integration for cqrs-core."""

from nestpy_cqrs.bindings import (
    CqrsHandlerBinding,
    command_handler,
    event_handler,
    query_handler,
)
from nestpy_cqrs.errors import (
    CqrsConfigurationError,
    CqrsLifecycleError,
    NestpyCqrsError,
)
from nestpy_cqrs.module import CqrsModule
from nestpy_cqrs.options import CqrsModuleOptions, TransportFactory

__all__ = [
    "CqrsConfigurationError",
    "CqrsHandlerBinding",
    "CqrsLifecycleError",
    "CqrsModule",
    "CqrsModuleOptions",
    "NestpyCqrsError",
    "TransportFactory",
    "command_handler",
    "event_handler",
    "query_handler",
]

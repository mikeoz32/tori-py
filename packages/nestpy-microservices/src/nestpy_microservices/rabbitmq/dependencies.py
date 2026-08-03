"""Optional RabbitMQ dependency loading."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

from nestpy_microservices.errors import OptionalDependencyError


def require_aio_pika() -> ModuleType:
    """Load and return ``aio_pika`` when the RabbitMQ extra is installed."""

    try:
        return import_module("aio_pika")
    except ModuleNotFoundError as error:
        if error.name != "aio_pika":
            raise
        raise OptionalDependencyError("aio-pika", "rabbitmq") from error


__all__ = ["require_aio_pika"]

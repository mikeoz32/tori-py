"""Deferred keyed RabbitMQ root and transport references."""

from __future__ import annotations

from dataclasses import dataclass

from nestpy import DeferredModule, FactoryProvider, ModuleSpec, ValueProvider

from nestpy_microservices.rabbitmq.connection import RabbitMqConnectionManager
from nestpy_microservices.rabbitmq.options import RabbitMqOptions


@dataclass(frozen=True, slots=True)
class RabbitMqRoot:
    key: str
    options: RabbitMqOptions


@dataclass(frozen=True, slots=True)
class RabbitMqTransport:
    """Reference one configured RabbitMQ root by its Nestpy key."""

    key: str = "default"

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key:
            raise ValueError("RabbitMqTransport key must be non-empty")


class RabbitMqModule:
    @classmethod
    def for_root(
        cls, options: RabbitMqOptions, *, key: str = "default"
    ) -> DeferredModule:
        if not isinstance(options, RabbitMqOptions):
            raise TypeError("options must be RabbitMqOptions")
        root = RabbitMqRoot(key, options)

        def create_manager(configured: RabbitMqRoot) -> RabbitMqConnectionManager:
            return RabbitMqConnectionManager(configured.options)

        def materialize() -> ModuleSpec:
            return ModuleSpec(
                providers=(
                    ValueProvider(rabbitmq_root_token(key), root),
                    ValueProvider(RabbitMqRoot, root),
                    FactoryProvider(RabbitMqConnectionManager, create_manager),
                ),
                exports=(rabbitmq_root_token(key),),
            )

        return DeferredModule(cls, key, materialize)


def rabbitmq_root_token(key: str) -> str:
    if not isinstance(key, str) or not key:
        raise ValueError("RabbitMQ root key must be non-empty")
    return f"nestpy.rabbitmq.root.{key}"


__all__ = [
    "RabbitMqModule",
    "RabbitMqRoot",
    "RabbitMqTransport",
    "rabbitmq_root_token",
]

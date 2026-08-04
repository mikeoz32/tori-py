"""Deferred keyed RabbitMQ root and transport references."""

from __future__ import annotations

from dataclasses import dataclass

from nestpy import DeferredModule, FactoryProvider, ModuleSpec, ValueProvider

from nestpy_microservices.rabbitmq.client import RabbitMqClientTransport
from nestpy_microservices.rabbitmq.connection import RabbitMqConnectionManager
from nestpy_microservices.rabbitmq.options import RabbitMqOptions
from nestpy_microservices.rabbitmq.server import RabbitMqServerTransport


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


class RabbitMqServerTransportFactory:
    """Create server transports from the module-owned connection manager."""

    def __init__(self, manager: RabbitMqConnectionManager, root: RabbitMqRoot) -> None:
        self.manager = manager
        self.key = root.key

    def create(self, identity, options):
        return RabbitMqServerTransport(
            self.manager,
            identity,
            prefetch=options.max_inflight_deliveries,
        )


class RabbitMqClientTransportFactory:
    """Create one client transport from the module-owned connection manager."""

    def __init__(self, manager: RabbitMqConnectionManager, root: RabbitMqRoot) -> None:
        self.manager = manager
        self.key = root.key

    def create(self):
        return RabbitMqClientTransport(self.manager)


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
            def create_server_factory(
                manager: RabbitMqConnectionManager,
                configured: RabbitMqRoot,
            ) -> RabbitMqServerTransportFactory:
                return RabbitMqServerTransportFactory(manager, configured)

            def create_client_factory(
                manager: RabbitMqConnectionManager,
                configured: RabbitMqRoot,
            ) -> RabbitMqClientTransportFactory:
                return RabbitMqClientTransportFactory(manager, configured)

            return ModuleSpec(
                providers=(
                    ValueProvider(rabbitmq_root_token(key), root),
                    ValueProvider(RabbitMqRoot, root),
                    FactoryProvider(RabbitMqConnectionManager, create_manager),
                    FactoryProvider(
                        RabbitMqServerTransportFactory, create_server_factory
                    ),
                    FactoryProvider(
                        RabbitMqClientTransportFactory, create_client_factory
                    ),
                ),
                exports=(
                    rabbitmq_root_token(key),
                    RabbitMqConnectionManager,
                    RabbitMqServerTransportFactory,
                    RabbitMqClientTransportFactory,
                ),
            )

        return DeferredModule(cls, key, materialize)


def rabbitmq_root_token(key: str) -> str:
    if not isinstance(key, str) or not key:
        raise ValueError("RabbitMQ root key must be non-empty")
    return f"nestpy.rabbitmq.root.{key}"


__all__ = [
    "RabbitMqModule",
    "RabbitMqClientTransportFactory",
    "RabbitMqRoot",
    "RabbitMqServerTransportFactory",
    "RabbitMqTransport",
    "rabbitmq_root_token",
]

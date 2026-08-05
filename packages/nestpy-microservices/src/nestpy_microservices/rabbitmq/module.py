"""Deferred keyed RabbitMQ root and transport references."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from nestpy import DeferredModule, FactoryProvider, Inject, ModuleSpec, ValueProvider

from nestpy_microservices.rabbitmq.client import RabbitMqClientTransport
from nestpy_microservices.rabbitmq.connection import RabbitMqConnectionManager
from nestpy_microservices.rabbitmq.options import RabbitMqOptions
from nestpy_microservices.rabbitmq.server import RabbitMqServerTransport


@dataclass(frozen=True, slots=True)
class RabbitMqRoot:
    key: str
    options: RabbitMqOptions

    def __post_init__(self) -> None:
        _validate_key(self.key)


@dataclass(frozen=True, slots=True)
class RabbitMqTransport:
    """Reference one configured RabbitMQ root by its Nestpy key."""

    key: str = "default"

    def __post_init__(self) -> None:
        _validate_key(self.key)

    @property
    def server_factory_token(self) -> str:
        return rabbitmq_server_factory_token(self.key)

    @property
    def client_factory_token(self) -> str:
        return rabbitmq_client_factory_token(self.key)


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
            retry_delay_ms=self.manager.options.retry_delay_ms,
            max_delivery_attempts=self.manager.options.max_delivery_attempts,
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
        root_token = rabbitmq_root_token(key)
        manager_token = rabbitmq_manager_token(key)
        server_factory_token = rabbitmq_server_factory_token(key)
        client_factory_token = rabbitmq_client_factory_token(key)

        def create_manager(configured: RabbitMqRoot) -> RabbitMqConnectionManager:
            return RabbitMqConnectionManager(configured.options)

        create_manager.__annotations__["configured"] = Annotated[
            RabbitMqRoot, Inject(root_token)
        ]

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

            create_server_factory.__annotations__["manager"] = Annotated[
                RabbitMqConnectionManager, Inject(manager_token)
            ]
            create_server_factory.__annotations__["configured"] = Annotated[
                RabbitMqRoot, Inject(root_token)
            ]
            create_client_factory.__annotations__["manager"] = Annotated[
                RabbitMqConnectionManager, Inject(manager_token)
            ]
            create_client_factory.__annotations__["configured"] = Annotated[
                RabbitMqRoot, Inject(root_token)
            ]

            return ModuleSpec(
                providers=(
                    ValueProvider(root_token, root),
                    FactoryProvider(manager_token, create_manager),
                    FactoryProvider(server_factory_token, create_server_factory),
                    FactoryProvider(client_factory_token, create_client_factory),
                ),
                exports=(
                    root_token,
                    manager_token,
                    server_factory_token,
                    client_factory_token,
                ),
            )

        return DeferredModule(cls, key, materialize)


def rabbitmq_root_token(key: str) -> str:
    _validate_key(key)
    return f"nestpy.rabbitmq.root.{key}"


def rabbitmq_manager_token(key: str = "default") -> str:
    _validate_key(key)
    return f"nestpy.rabbitmq.manager.{key}"


def rabbitmq_server_factory_token(key: str = "default") -> str:
    _validate_key(key)
    return f"nestpy.rabbitmq.server_factory.{key}"


def rabbitmq_client_factory_token(key: str = "default") -> str:
    _validate_key(key)
    return f"nestpy.rabbitmq.client_factory.{key}"


def _validate_key(key: str) -> None:
    if not isinstance(key, str) or not key:
        raise ValueError("RabbitMQ root key must be non-empty")


__all__ = [
    "RabbitMqModule",
    "RabbitMqClientTransportFactory",
    "RabbitMqRoot",
    "RabbitMqServerTransportFactory",
    "RabbitMqTransport",
    "rabbitmq_client_factory_token",
    "rabbitmq_manager_token",
    "rabbitmq_root_token",
    "rabbitmq_server_factory_token",
]

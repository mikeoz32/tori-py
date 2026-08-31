"""Keyed in-memory transport module used by the executable system test."""

from __future__ import annotations

from dataclasses import dataclass

from tori_py import DeferredModule, ModuleSpec, ValueProvider
from tori_py_microservices import (
    InMemoryBroker,
    InMemoryClientTransport,
    InMemoryServerTransport,
    KeyedTransportFactoryReference,
    MicroservicesOptions,
    ServiceIdentity,
)


@dataclass(frozen=True, slots=True)
class InMemoryServerFactory:
    broker: InMemoryBroker

    def create(
        self,
        identity: ServiceIdentity,
        options: MicroservicesOptions,
    ) -> InMemoryServerTransport:
        return InMemoryServerTransport(
            self.broker,
            identity,
            prefetch=options.max_inflight_deliveries,
        )


@dataclass(frozen=True, slots=True)
class InMemoryClientFactory:
    broker: InMemoryBroker

    def create(self) -> InMemoryClientTransport:
        return InMemoryClientTransport(self.broker)


class InMemoryTransportModule:
    """Provide in-memory factories under any public keyed transport reference."""

    @classmethod
    def for_root(
        cls,
        broker: InMemoryBroker,
        reference: KeyedTransportFactoryReference,
    ) -> DeferredModule:
        if not isinstance(broker, InMemoryBroker):
            raise TypeError("broker must be an InMemoryBroker")
        if not isinstance(reference, KeyedTransportFactoryReference):
            raise TypeError("reference must be a keyed transport factory reference")
        server_factory = InMemoryServerFactory(broker)
        client_factory = InMemoryClientFactory(broker)

        def materialize() -> ModuleSpec:
            return ModuleSpec(
                providers=(
                    ValueProvider(reference.server_factory_token, server_factory),
                    ValueProvider(reference.client_factory_token, client_factory),
                ),
                exports=(
                    reference.server_factory_token,
                    reference.client_factory_token,
                ),
            )

        return DeferredModule(cls, reference.key, materialize)


__all__ = [
    "InMemoryClientFactory",
    "InMemoryServerFactory",
    "InMemoryTransportModule",
]

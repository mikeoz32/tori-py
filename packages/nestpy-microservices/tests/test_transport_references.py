from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import nestpy_microservices.clients as clients_module
import nestpy_microservices.module as server_module
import pytest
from nestpy import DeferredModule, ModuleSpec, ValueProvider
from nestpy.testing import TestingModule

from nestpy_microservices import (
    ClientsModule,
    InMemoryBroker,
    InMemoryClientTransport,
    KeyedTransportFactoryReference,
    MicroservicesModule,
    ServiceCluster,
    ServiceIdentity,
    ServiceRuntime,
)

SERVICE = ServiceIdentity("tests", "keyed-adapter", 1)


@dataclass(frozen=True, slots=True)
class FakeTransportReference:
    key: str

    @property
    def server_factory_token(self) -> str:
        return f"tests.fake.server.{self.key}"

    @property
    def client_factory_token(self) -> str:
        return f"tests.fake.client.{self.key}"


@dataclass(slots=True)
class FakeServerFactory:
    broker: InMemoryBroker

    def create(self, identity, options):
        del options
        from nestpy_microservices import InMemoryServerTransport

        return InMemoryServerTransport(self.broker, identity)


@dataclass(slots=True)
class FakeClientFactory:
    broker: InMemoryBroker

    def create(self):
        return InMemoryClientTransport(self.broker)


class FakeAdapterModule:
    @classmethod
    def for_root(
        cls, broker: InMemoryBroker, reference: FakeTransportReference
    ) -> DeferredModule:
        server_factory = FakeServerFactory(broker)
        client_factory = FakeClientFactory(broker)

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


def test_generic_composition_modules_contain_no_adapter_specific_names() -> None:
    forbidden = "rabbit" + "mq"
    for module in (server_module, clients_module):
        source = Path(module.__file__).read_text(encoding="utf-8").lower()
        assert forbidden not in source


@pytest.mark.asyncio
async def test_fake_non_rabbit_keyed_adapter_composes_without_generic_changes() -> None:
    broker = InMemoryBroker()
    reference = FakeTransportReference("custom")
    assert isinstance(reference, KeyedTransportFactoryReference)

    server_application = await TestingModule.create(
        MicroservicesModule.for_root(
            SERVICE,
            transport=reference,
            imports=(FakeAdapterModule.for_root(broker, reference),),
        )
    ).compile()
    runtime = cast(ServiceRuntime, await server_application.resolve(ServiceRuntime))
    assert isinstance(runtime._transport_factory, FakeServerFactory)

    client_application = await TestingModule.create(
        ClientsModule.register_cluster(
            reference,
            imports=(FakeAdapterModule.for_root(broker, reference),),
        )
    ).compile()
    cluster = cast(ServiceCluster, await client_application.resolve(ServiceCluster))
    assert isinstance(cluster.transport, InMemoryClientTransport)

    await client_application.close()
    await server_application.close()
    await broker.close()

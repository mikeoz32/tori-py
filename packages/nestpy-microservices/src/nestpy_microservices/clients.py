"""Nestpy keyed provider registration for one shared service cluster client."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

from nestpy import (
    DeferredModule,
    FactoryProvider,
    ModuleImport,
    ModuleSpec,
    ValueProvider,
)

from nestpy_microservices.cluster import ServiceCluster, ServiceClusterOptions
from nestpy_microservices.errors import TransportStateError
from nestpy_microservices.transport import ClientTransport


@dataclass(frozen=True, slots=True)
class ClientClusterRoot:
    """External transport and immutable options captured by a client root."""

    transport: object
    options: ServiceClusterOptions


class ClientsModule:
    """Dynamic module factory for a keyed singleton :class:`ServiceCluster`."""

    @classmethod
    def register_cluster(
        cls,
        transport: object,
        *,
        options: ServiceClusterOptions | None = None,
        imports: Iterable[ModuleImport] = (),
        key: str = "default",
    ) -> DeferredModule:
        is_rabbitmq = _is_rabbitmq_transport(transport)
        if not is_rabbitmq and not isinstance(transport, ClientTransport):
            raise TypeError("transport must implement ClientTransport")
        selected_options = ServiceClusterOptions() if options is None else options
        if not isinstance(selected_options, ServiceClusterOptions):
            raise TypeError("options must be ServiceClusterOptions")
        root = ClientClusterRoot(transport, selected_options)
        captured_imports = tuple(imports)

        if is_rabbitmq:
            from nestpy_microservices.rabbitmq.module import (
                RabbitMqClientTransportFactory,
            )

            def create_cluster(
                configured: ClientClusterRoot,
                rabbit_factory: RabbitMqClientTransportFactory,
            ) -> ServiceCluster:
                if getattr(configured.transport, "key", None) != rabbit_factory.key:
                    raise TransportStateError(
                        "RabbitMQ transport key does not match the imported root"
                    )
                return ServiceCluster(
                    rabbit_factory.create(),
                    options=configured.options,
                    manage_transport=True,
                )

            create_cluster.__annotations__["rabbit_factory"] = (
                RabbitMqClientTransportFactory
            )
        else:

            def create_cluster(configured: ClientClusterRoot) -> ServiceCluster:
                return ServiceCluster(
                    cast(ClientTransport, configured.transport),
                    options=configured.options,
                )

        def materialize() -> ModuleSpec:
            return ModuleSpec(
                imports=captured_imports,
                providers=(
                    ValueProvider(ClientClusterRoot, root),
                    FactoryProvider(ServiceCluster, create_cluster),
                ),
                exports=(ServiceCluster,),
            )

        return DeferredModule(cls, key, materialize)


def _is_rabbitmq_transport(transport: object) -> bool:
    from nestpy_microservices.rabbitmq.module import RabbitMqTransport

    return isinstance(transport, RabbitMqTransport)


__all__ = ["ClientClusterRoot", "ClientsModule"]

"""Nestpy keyed provider registration for one shared service cluster client."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from nestpy import (
    DeferredModule,
    FactoryProvider,
    ModuleImport,
    ModuleSpec,
    ValueProvider,
)

from nestpy_microservices.cluster import ServiceCluster, ServiceClusterOptions
from nestpy_microservices.transport import ClientTransport


@dataclass(frozen=True, slots=True)
class ClientClusterRoot:
    """External transport and immutable options captured by a client root."""

    transport: ClientTransport
    options: ServiceClusterOptions


class ClientsModule:
    """Dynamic module factory for a keyed singleton :class:`ServiceCluster`."""

    @classmethod
    def register_cluster(
        cls,
        transport: ClientTransport,
        *,
        options: ServiceClusterOptions | None = None,
        imports: Iterable[ModuleImport] = (),
        key: str = "default",
    ) -> DeferredModule:
        if not isinstance(transport, ClientTransport):
            raise TypeError("transport must implement ClientTransport")
        selected_options = ServiceClusterOptions() if options is None else options
        if not isinstance(selected_options, ServiceClusterOptions):
            raise TypeError("options must be ServiceClusterOptions")
        root = ClientClusterRoot(transport, selected_options)
        captured_imports = tuple(imports)

        def create_cluster(configured: ClientClusterRoot) -> ServiceCluster:
            return ServiceCluster(configured.transport, options=configured.options)

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


__all__ = ["ClientClusterRoot", "ClientsModule"]

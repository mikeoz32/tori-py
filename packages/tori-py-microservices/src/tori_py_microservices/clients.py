"""ToriPy keyed provider registration for one shared service cluster client."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated, cast

from tori_py import (
    AliasProvider,
    DeferredModule,
    FactoryProvider,
    Inject,
    ModuleImport,
    ModuleSpec,
    ValueProvider,
)

from tori_py_microservices.cluster import ServiceCluster, ServiceClusterOptions
from tori_py_microservices.contracts import create_service_proxy
from tori_py_microservices.errors import TransportStateError
from tori_py_microservices.transport import (
    ClientTransport,
    ClientTransportFactory,
    KeyedTransportFactoryReference,
)


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
        contracts: Iterable[type[object]] = (),
        key: str = "default",
    ) -> DeferredModule:
        cluster_token = cls.get_cluster_token(key)
        is_reference = isinstance(transport, KeyedTransportFactoryReference)
        if not is_reference and not isinstance(transport, ClientTransport):
            raise TypeError("transport must implement ClientTransport")
        selected_options = ServiceClusterOptions() if options is None else options
        if not isinstance(selected_options, ServiceClusterOptions):
            raise TypeError("options must be ServiceClusterOptions")
        root = ClientClusterRoot(transport, selected_options)
        captured_imports = tuple(imports)
        captured_contracts = tuple(contracts)
        if len(set(captured_contracts)) != len(captured_contracts):
            raise ValueError("client contracts must be unique")
        if not all(isinstance(contract, type) for contract in captured_contracts):
            raise TypeError("client contracts must be classes")

        if is_reference:
            reference = transport

            def create_cluster(
                configured: ClientClusterRoot,
                referenced_factory: object,
            ) -> ServiceCluster:
                if not isinstance(referenced_factory, ClientTransportFactory):
                    raise TransportStateError(
                        "referenced provider does not implement ClientTransportFactory"
                    )
                return ServiceCluster(
                    referenced_factory.create(),
                    options=configured.options,
                    manage_transport=True,
                )

            create_cluster.__annotations__["referenced_factory"] = Annotated[
                object,
                Inject(reference.client_factory_token),
            ]
        else:

            def create_cluster(configured: ClientClusterRoot) -> ServiceCluster:
                return ServiceCluster(
                    cast(ClientTransport, configured.transport),
                    options=configured.options,
                )

        def materialize() -> ModuleSpec:
            contract_providers: list[FactoryProvider] = []
            for contract in captured_contracts:

                def create_proxy(
                    cluster: ServiceCluster,
                    *,
                    contract=contract,
                ) -> object:
                    return create_service_proxy(contract, cluster)

                create_proxy.__annotations__["cluster"] = Annotated[
                    ServiceCluster,
                    Inject(cluster_token),
                ]
                contract_providers.append(FactoryProvider(contract, create_proxy))
            return ModuleSpec(
                imports=captured_imports,
                providers=(
                    ValueProvider(ClientClusterRoot, root),
                    FactoryProvider(cluster_token, create_cluster),
                    *contract_providers,
                    *(
                        (AliasProvider(ServiceCluster, cluster_token),)
                        if key == "default"
                        else ()
                    ),
                ),
                exports=(
                    cluster_token,
                    *captured_contracts,
                    *((ServiceCluster,) if key == "default" else ()),
                ),
            )

        return DeferredModule(cls, key, materialize)

    @staticmethod
    def get_cluster_token(key: str = "default") -> str:
        """Return the deterministic injection token for one keyed cluster."""

        if not isinstance(key, str) or not key or key == "static":
            raise ValueError("cluster key must be non-empty and not 'static'")
        return f"tori_py.microservices.cluster.{key}"


__all__ = ["ClientClusterRoot", "ClientsModule"]

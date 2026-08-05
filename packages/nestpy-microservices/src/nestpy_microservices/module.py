"""Deferred Nestpy module descriptor for one service root."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated, cast

from nestpy import (
    CompiledGraph,
    DeferredModule,
    DiscoveryService,
    FactoryProvider,
    Inject,
    ModuleImport,
    ModulesContainer,
    ModuleSpec,
    ValueProvider,
    WorkScopeFactory,
)

from nestpy_microservices.errors import TransportStateError
from nestpy_microservices.events import EventDispatcher
from nestpy_microservices.identities import ServiceIdentity
from nestpy_microservices.options import MicroservicesOptions
from nestpy_microservices.runtime import ServiceRuntime
from nestpy_microservices.transport import (
    ClientTransportFactory,
    KeyedTransportFactoryReference,
    ServerTransportFactory,
)


@dataclass(frozen=True, slots=True)
class MicroservicesRoot:
    """Validated service-root configuration captured by module materialization."""

    identity: ServiceIdentity
    transport: object
    options: MicroservicesOptions


class MicroservicesModule:
    """Dynamic module descriptor that performs no startup work."""

    @classmethod
    def for_root(
        cls,
        identity: ServiceIdentity,
        *,
        transport: object,
        options: MicroservicesOptions | None = None,
        imports: Iterable[ModuleImport] = (),
        key: str = "default",
    ) -> DeferredModule:
        if not isinstance(identity, ServiceIdentity):
            raise TypeError("identity must be a ServiceIdentity")
        is_reference = isinstance(transport, KeyedTransportFactoryReference)
        if not is_reference and not isinstance(transport, ServerTransportFactory):
            raise TypeError("transport must provide create(identity, options)")
        selected_options = options or MicroservicesOptions()
        captured_imports = tuple(imports)
        root = MicroservicesRoot(identity, transport, selected_options)

        if is_reference:
            reference = transport

            def create_runtime(
                configured: MicroservicesRoot,
                discovery: DiscoveryService,
                modules: ModulesContainer,
                work_scopes: WorkScopeFactory,
                referenced_factory: object,
            ) -> ServiceRuntime:
                if not isinstance(referenced_factory, ServerTransportFactory):
                    raise TransportStateError(
                        "referenced provider does not implement ServerTransportFactory"
                    )
                return ServiceRuntime(
                    configured.identity,
                    transport_factory=referenced_factory,
                    discovery=discovery,
                    modules=modules,
                    work_scopes=work_scopes,
                    options=configured.options,
                )

            create_runtime.__annotations__["referenced_factory"] = Annotated[
                object,
                Inject(reference.server_factory_token),
            ]

            def create_event_dispatcher(
                configured: MicroservicesRoot,
                referenced_client_factory: object,
            ) -> EventDispatcher:
                if not isinstance(referenced_client_factory, ClientTransportFactory):
                    raise TransportStateError(
                        "referenced provider does not implement ClientTransportFactory"
                    )
                return EventDispatcher(
                    configured.identity,
                    referenced_client_factory,
                    options=configured.options,
                )

            create_event_dispatcher.__annotations__["referenced_client_factory"] = (
                Annotated[
                    object,
                    Inject(reference.client_factory_token),
                ]
            )
        else:

            def create_runtime(
                configured: MicroservicesRoot,
                discovery: DiscoveryService,
                modules: ModulesContainer,
                work_scopes: WorkScopeFactory,
            ) -> ServiceRuntime:
                return ServiceRuntime(
                    configured.identity,
                    transport_factory=cast(
                        ServerTransportFactory, configured.transport
                    ),
                    discovery=discovery,
                    modules=modules,
                    work_scopes=work_scopes,
                    options=configured.options,
                )

        def materialize() -> ModuleSpec:
            providers = [
                ValueProvider(MicroservicesRoot, root),
                FactoryProvider(ServiceRuntime, create_runtime),
            ]
            if is_reference:
                providers.append(
                    FactoryProvider(EventDispatcher, create_event_dispatcher)
                )
            return ModuleSpec(
                imports=captured_imports,
                providers=providers,
                exports=(EventDispatcher,) if is_reference else (),
            )

        return DeferredModule(cls, key, materialize)

    def validate_graph(self, graph: CompiledGraph) -> None:
        roots = sum(
            provider.key.token is MicroservicesRoot
            for module_plan in graph.modules
            for provider in module_plan.providers
        )
        if roots > 1:
            raise TransportStateError(
                "an application may configure at most one MicroservicesModule root"
            )


__all__ = ["MicroservicesModule", "MicroservicesRoot"]

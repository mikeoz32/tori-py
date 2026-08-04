"""Deferred Nestpy module descriptor for one service root."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from nestpy import (
    DeferredModule,
    DiscoveryService,
    FactoryProvider,
    ModuleImport,
    ModulesContainer,
    ModuleSpec,
    ValueProvider,
    WorkScopeFactory,
)

from nestpy_microservices.identities import ServiceIdentity
from nestpy_microservices.options import MicroservicesOptions
from nestpy_microservices.runtime import ServerTransportFactory, ServiceRuntime
from nestpy_microservices.transport import DeliveryDispatcher


@dataclass(frozen=True, slots=True)
class MicroservicesRoot:
    """Validated service-root configuration captured by module materialization."""

    identity: ServiceIdentity
    transport: ServerTransportFactory
    options: MicroservicesOptions
    dispatcher: DeliveryDispatcher | None = None


class MicroservicesModule:
    """Dynamic module descriptor that performs no startup work."""

    @classmethod
    def for_root(
        cls,
        identity: ServiceIdentity,
        *,
        transport: ServerTransportFactory,
        options: MicroservicesOptions | None = None,
        imports: Iterable[ModuleImport] = (),
        key: str = "default",
        dispatcher: DeliveryDispatcher | None = None,
    ) -> DeferredModule:
        if not isinstance(identity, ServiceIdentity):
            raise TypeError("identity must be a ServiceIdentity")
        if not callable(getattr(transport, "create", None)):
            raise TypeError("transport must provide create(identity, options)")
        selected_options = options or MicroservicesOptions()
        captured_imports = tuple(imports)
        root = MicroservicesRoot(identity, transport, selected_options, dispatcher)

        def create_runtime(
            configured: MicroservicesRoot,
            discovery: DiscoveryService,
            modules: ModulesContainer,
            work_scopes: WorkScopeFactory,
        ) -> ServiceRuntime:
            return ServiceRuntime(
                configured.identity,
                transport_factory=configured.transport,
                discovery=discovery,
                modules=modules,
                work_scopes=work_scopes,
                options=configured.options,
                dispatcher=configured.dispatcher,
            )

        def materialize() -> ModuleSpec:
            return ModuleSpec(
                imports=captured_imports,
                providers=(
                    ValueProvider(MicroservicesRoot, root),
                    FactoryProvider(ServiceRuntime, create_runtime),
                ),
            )

        return DeferredModule(cls, key, materialize)


__all__ = ["MicroservicesModule", "MicroservicesRoot"]

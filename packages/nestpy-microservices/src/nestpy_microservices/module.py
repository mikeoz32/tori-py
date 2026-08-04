"""Deferred Nestpy module descriptor for one service root."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

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

from nestpy_microservices.errors import TransportStateError
from nestpy_microservices.identities import ServiceIdentity
from nestpy_microservices.options import MicroservicesOptions
from nestpy_microservices.runtime import ServerTransportFactory, ServiceRuntime
from nestpy_microservices.transport import DeliveryDispatcher


@dataclass(frozen=True, slots=True)
class MicroservicesRoot:
    """Validated service-root configuration captured by module materialization."""

    identity: ServiceIdentity
    transport: object
    options: MicroservicesOptions
    dispatcher: DeliveryDispatcher | None = None


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
        dispatcher: DeliveryDispatcher | None = None,
    ) -> DeferredModule:
        if not isinstance(identity, ServiceIdentity):
            raise TypeError("identity must be a ServiceIdentity")
        is_rabbitmq = _is_rabbitmq_transport(transport)
        if not is_rabbitmq and not callable(getattr(transport, "create", None)):
            raise TypeError("transport must provide create(identity, options)")
        selected_options = options or MicroservicesOptions()
        captured_imports = tuple(imports)
        root = MicroservicesRoot(identity, transport, selected_options, dispatcher)

        if is_rabbitmq:
            from nestpy_microservices.rabbitmq.module import (
                RabbitMqServerTransportFactory,
            )

            def create_runtime(
                configured: MicroservicesRoot,
                discovery: DiscoveryService,
                modules: ModulesContainer,
                work_scopes: WorkScopeFactory,
                rabbit_factory: RabbitMqServerTransportFactory,
            ) -> ServiceRuntime:
                if getattr(configured.transport, "key", None) != rabbit_factory.key:
                    raise TransportStateError(
                        "RabbitMQ transport key does not match the imported root"
                    )
                return ServiceRuntime(
                    configured.identity,
                    transport_factory=rabbit_factory,
                    discovery=discovery,
                    modules=modules,
                    work_scopes=work_scopes,
                    options=configured.options,
                    dispatcher=configured.dispatcher,
                )

            create_runtime.__annotations__["rabbit_factory"] = (
                RabbitMqServerTransportFactory
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


def _is_rabbitmq_transport(transport: object) -> bool:
    from nestpy_microservices.rabbitmq.module import RabbitMqTransport

    return isinstance(transport, RabbitMqTransport)


__all__ = ["MicroservicesModule", "MicroservicesRoot"]

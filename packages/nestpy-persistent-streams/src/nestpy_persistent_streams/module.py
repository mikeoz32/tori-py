"""Always-global persistent stream root composition."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from nestpy import (
    AliasProvider,
    CompiledGraph,
    DeferredModule,
    DiscoveryService,
    FactoryProvider,
    ModuleImport,
    ModuleProvider,
    ModulesContainer,
    ModuleSpec,
    Token,
    ValueProvider,
    WorkScopeFactory,
)

from nestpy_persistent_streams.contracts import (
    StreamAdapterFactory,
    StreamPublisher,
)
from nestpy_persistent_streams.errors import StreamConfigurationError
from nestpy_persistent_streams.options import (
    PersistentStreamsOptions,
    PersistentStreamsRuntimeOptions,
    PublisherRegistration,
    StreamBinding,
    validate_stream_inventory,
)
from nestpy_persistent_streams.publishers import (
    BoundStreamPublisher,
    ProtocolStreamPublisher,
    stream_publisher_token,
)
from nestpy_persistent_streams.runtime import StreamRuntime


class _PersistentStreamsRootMarker:
    pass


@dataclass(frozen=True, slots=True)
class _PublisherInventory:
    registrations: tuple[PublisherRegistration, ...]


def _runtime_factory(
    options: PersistentStreamsOptions,
    discovery: DiscoveryService,
    modules: ModulesContainer,
    work_scopes: WorkScopeFactory,
    adapter_factory: StreamAdapterFactory,
    publisher_inventory: _PublisherInventory,
) -> StreamRuntime:
    return StreamRuntime(
        options,
        adapter_factory,
        discovery,
        modules,
        work_scopes,
        publisher_inventory.registrations,
    )


class PersistentStreamsModule:
    """Configure the one always-global persistent stream application root."""

    @classmethod
    def for_root(
        cls,
        options: PersistentStreamsOptions,
        *,
        imports: Iterable[ModuleImport] = (),
    ) -> DeferredModule:
        if not isinstance(options, PersistentStreamsOptions):
            raise TypeError("options must be PersistentStreamsOptions")
        return cls._descriptor(
            option_providers=(ValueProvider(PersistentStreamsOptions, options),),
            imports=imports,
            bindings=options.bindings,
            publishers=options.publishers,
        )

    @classmethod
    def for_root_async(
        cls,
        *,
        use_factory: Callable[..., object],
        bindings: Iterable[StreamBinding],
        publishers: Iterable[PublisherRegistration] = (),
        imports: Iterable[ModuleImport] = (),
    ) -> DeferredModule:
        if not callable(use_factory):
            raise TypeError("use_factory must be callable")
        static_bindings, static_publishers = validate_stream_inventory(
            bindings, publishers
        )

        def create_options(
            runtime: PersistentStreamsRuntimeOptions,
        ) -> PersistentStreamsOptions:
            return PersistentStreamsOptions(static_bindings, static_publishers, runtime)

        return cls._descriptor(
            option_providers=(
                FactoryProvider(PersistentStreamsRuntimeOptions, use_factory),
                FactoryProvider(PersistentStreamsOptions, create_options),
            ),
            imports=imports,
            bindings=static_bindings,
            publishers=static_publishers,
        )

    @classmethod
    def _descriptor(
        cls,
        *,
        option_providers: tuple[ModuleProvider, ...],
        bindings: tuple[StreamBinding, ...],
        publishers: tuple[PublisherRegistration, ...],
        imports: Iterable[ModuleImport] = (),
    ) -> DeferredModule:
        imported = tuple(imports)
        declared_publishers = publishers
        if any(
            not isinstance(value, PublisherRegistration)
            for value in declared_publishers
        ):
            raise StreamConfigurationError(
                "publishers must contain PublisherRegistration values"
            )

        def create_runtime(
            options: PersistentStreamsOptions,
            discovery: DiscoveryService,
            modules: ModulesContainer,
            work_scopes: WorkScopeFactory,
            adapter_factory: StreamAdapterFactory,
            publisher_inventory: _PublisherInventory,
        ) -> StreamRuntime:
            return _runtime_factory(
                options,
                discovery,
                modules,
                work_scopes,
                adapter_factory,
                publisher_inventory,
            )

        def materialize() -> ModuleSpec:
            providers: list[ModuleProvider] = [
                ValueProvider(_PersistentStreamsRootMarker, object()),
                ValueProvider(
                    _PublisherInventory,
                    _PublisherInventory(declared_publishers),
                ),
                *option_providers,
                FactoryProvider(StreamRuntime, create_runtime),
                AliasProvider(StreamPublisher, StreamRuntime),
            ]
            exports: list[Token] = [StreamPublisher, StreamRuntime]
            aliases = bindings
            registrations = declared_publishers
            named: dict[str, str] = {
                binding.alias: binding.alias for binding in aliases
            }
            for registration in registrations:
                if registration.name is not None:
                    if registration.name in named:
                        raise StreamConfigurationError(
                            "publisher token collides with a binding alias"
                        )
                    named[registration.name] = registration.stream
            for name, stream in named.items():
                token = stream_publisher_token(name)
                providers.append(FactoryProvider(token, _bound_factory(stream)))
                exports.append(token)
            for registration in registrations:
                if registration.protocol is None:
                    continue
                providers.append(
                    FactoryProvider(
                        registration.protocol,
                        _protocol_factory(registration),
                    )
                )
                exports.append(registration.protocol)
            return ModuleSpec(
                imports=imported,
                providers=providers,
                exports=exports,
                global_=True,
            )

        return DeferredModule(cls, "root", materialize)

    def validate_graph(self, graph: CompiledGraph) -> None:
        roots = sum(
            provider.key.token is _PersistentStreamsRootMarker
            for module in graph.modules
            for provider in module.providers
        )
        if roots > 1:
            raise StreamConfigurationError(
                "an application may configure only one PersistentStreamsModule root"
            )


def _bound_factory(stream: str) -> Callable[..., BoundStreamPublisher]:
    def create(runtime: StreamRuntime) -> BoundStreamPublisher:
        binding = next(
            (value for value in runtime.options.bindings if value.alias == stream),
            None,
        )
        if binding is None:
            raise StreamConfigurationError(
                f"publisher references unknown stream {stream!r}"
            )
        return BoundStreamPublisher(runtime, stream)

    return create


def _protocol_factory(
    registration: PublisherRegistration,
) -> Callable[..., ProtocolStreamPublisher]:
    def create(runtime: StreamRuntime) -> ProtocolStreamPublisher:
        binding = next(
            (
                value
                for value in runtime.options.bindings
                if value.alias == registration.stream
            ),
            None,
        )
        if binding is None or registration.protocol is None:
            raise StreamConfigurationError("invalid Protocol publisher registration")
        return ProtocolStreamPublisher(
            registration.protocol,
            BoundStreamPublisher(runtime, binding.alias),
            binding.payload_type,
        )

    return create


__all__ = ["PersistentStreamsModule"]

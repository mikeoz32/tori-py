"""Keyed root and feature dynamic modules."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Any

from cqrs_event_sourcing import (
    EventSchemaRegistry,
    EventSourcedRepository,
    EventStore,
)
from nestpy import (
    AliasProvider,
    ClassProvider,
    DeferredModule,
    FactoryProvider,
    Inject,
    ModuleImport,
    ModuleSpec,
    ProviderDeclaration,
    Scope,
    Token,
    ValueProvider,
)

from nestpy_cqrs_event_sourcing.decorators import _repository_metadata
from nestpy_cqrs_event_sourcing.errors import CqrsEventSourcingConfigurationError
from nestpy_cqrs_event_sourcing.options import CqrsEventSourcingOptions
from nestpy_cqrs_event_sourcing.runtime import (
    _CommandSynchronizationState,
    _CommandTransactionCoordinator,
    _TransactionAccessor,
    _TransactionInterceptor,
)
from nestpy_cqrs_event_sourcing.tokens import (
    _synchronization_state_token,
    _transaction_accessor_token,
    _transaction_coordinator_token,
    get_command_synchronization_token,
    get_event_store_token,
    get_schema_registry_token,
    get_transaction_interceptor_token,
)


class CqrsEventSourcingModule:
    """Compose keyed event-sourcing roots and explicit repository features."""

    @classmethod
    def for_root(
        cls,
        options: CqrsEventSourcingOptions,
        *,
        imports: Iterable[ModuleImport] = (),
        key: str = "default",
    ) -> DeferredModule:
        if not isinstance(options, CqrsEventSourcingOptions):
            raise CqrsEventSourcingConfigurationError(
                "options must be CqrsEventSourcingOptions"
            )
        store_token = get_event_store_token(key=key)
        schema_token = get_schema_registry_token(key=key)
        synchronization_token = get_command_synchronization_token(key=key)
        interceptor_token = get_transaction_interceptor_token(key=key)
        accessor_token = _transaction_accessor_token(key)
        coordinator_token = _transaction_coordinator_token(key)
        synchronization_state_token = _synchronization_state_token(key)
        try:
            imported = tuple(imports)
        except TypeError as error:
            raise CqrsEventSourcingConfigurationError(
                "imports must be iterable"
            ) from error

        coordinator_factory = _coordinator_factory(
            options,
            store_token=store_token,
            synchronization_token=synchronization_state_token,
            accessor_token=accessor_token,
        )
        interceptor_factory = _interceptor_factory(
            coordinator_token=coordinator_token,
            completion_key=f"nestpy_cqrs_event_sourcing:{key}",
        )

        def materialize() -> ModuleSpec:
            if not options.schemas.is_frozen:
                raise CqrsEventSourcingConfigurationError(
                    "event schema registry must be frozen before compilation"
                )
            providers: list[ProviderDeclaration] = []
            if options.store == store_token:
                pass
            elif options.store is EventStore:
                providers.append(AliasProvider(store_token, EventStore))
            else:
                providers.extend(
                    (
                        AliasProvider(EventStore, options.store),
                        AliasProvider(store_token, EventStore),
                    )
                )
            providers.extend(
                (
                    ValueProvider(schema_token, options.schemas),
                    ClassProvider(
                        accessor_token,
                        _TransactionAccessor,
                        scope=Scope.REQUEST,
                    ),
                    ClassProvider(
                        synchronization_state_token,
                        _CommandSynchronizationState,
                        scope=Scope.REQUEST,
                    ),
                    AliasProvider(
                        synchronization_token,
                        synchronization_state_token,
                    ),
                    FactoryProvider(
                        coordinator_token,
                        coordinator_factory,
                        scope=Scope.REQUEST,
                    ),
                    FactoryProvider(
                        interceptor_token,
                        interceptor_factory,
                        scope=Scope.REQUEST,
                    ),
                )
            )
            exports: list[Token] = [
                store_token,
                schema_token,
                synchronization_token,
                interceptor_token,
                accessor_token,
            ]
            return ModuleSpec(
                imports=imported,
                providers=providers,
                exports=exports,
                global_=True,
            )

        return DeferredModule(cls, key, materialize)

    @classmethod
    def for_feature(
        cls,
        repositories: Iterable[type[EventSourcedRepository[Any, Any]]],
        *,
        root_key: str = "default",
        key: str | None = None,
    ) -> DeferredModule:
        try:
            declared = tuple(repositories)
        except TypeError as error:
            raise CqrsEventSourcingConfigurationError(
                "repositories must be iterable"
            ) from error
        if len(set(declared)) != len(declared):
            raise CqrsEventSourcingConfigurationError(
                "feature repositories must not contain duplicates"
            )
        declarations = []
        for repository in declared:
            if not isinstance(repository, type) or not issubclass(
                repository, EventSourcedRepository
            ):
                raise CqrsEventSourcingConfigurationError(
                    "features require EventSourcedRepository subclasses"
                )
            declarations.append(_repository_metadata(repository))

        accessor_token = _transaction_accessor_token(root_key)
        schema_token = get_schema_registry_token(key=root_key)
        providers = tuple(
            FactoryProvider(
                repository,
                _repository_factory(
                    repository,
                    declaration,
                    accessor_token=accessor_token,
                    schema_token=schema_token,
                ),
                scope=Scope.REQUEST,
            )
            for repository, declaration in zip(declared, declarations, strict=True)
        )

        if key is not None and (not isinstance(key, str) or not key):
            raise CqrsEventSourcingConfigurationError(
                "feature key must be a non-empty string or None"
            )
        feature_identity = f"{root_key}:{key or 'default'}"
        feature_module = type(
            "_CqrsEventSourcingFeatureModule",
            (),
            {"__module__": __name__},
        )

        def materialize() -> ModuleSpec:
            return ModuleSpec(
                providers=providers,
                exports=declared,
            )

        return DeferredModule(
            feature_module,
            feature_identity,
            materialize,
        )


def _coordinator_factory(
    options: CqrsEventSourcingOptions,
    *,
    store_token: Token,
    synchronization_token: Token,
    accessor_token: Token,
):
    def create(store, synchronization, accessor):
        return _CommandTransactionCoordinator(
            store,
            synchronization,
            accessor,
            options.unit_of_work_factory,
        )

    create.__annotations__ = {
        "store": Annotated[EventStore, Inject(store_token)],
        "synchronization": Annotated[
            _CommandSynchronizationState,
            Inject(synchronization_token),
        ],
        "accessor": Annotated[_TransactionAccessor, Inject(accessor_token)],
    }
    return create


def _interceptor_factory(*, coordinator_token: Token, completion_key: str):
    def create(coordinator):
        return _TransactionInterceptor(coordinator, completion_key)

    create.__annotations__ = {
        "coordinator": Annotated[
            _CommandTransactionCoordinator,
            Inject(coordinator_token),
        ]
    }
    return create


def _repository_factory(
    repository: type[EventSourcedRepository[Any, Any]],
    declaration,
    *,
    accessor_token: Token,
    schema_token: Token,
):
    def create(accessor, schemas):
        return repository(
            accessor.current(),
            category=declaration.category,
            aggregate_factory=declaration.aggregate_factory,
            aggregate_type=declaration.aggregate_type,
            id_encoder=declaration.id_encoder,
            schemas=schemas,
            page_size=declaration.page_size,
            operation_lease=accessor.require,
        )

    create.__annotations__ = {
        "accessor": Annotated[_TransactionAccessor, Inject(accessor_token)],
        "schemas": Annotated[EventSchemaRegistry, Inject(schema_token)],
    }
    return create


__all__ = ["CqrsEventSourcingModule"]

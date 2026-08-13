"""Dynamic ToriPy CQRS module composition."""

from collections.abc import Iterable

from tori_py import (
    AliasProvider,
    ClassProvider,
    DeferredModule,
    FactoryProvider,
    ModuleId,
    ModuleImport,
    ModuleSpec,
    ValueProvider,
)
from tori_py_cqrs_core import CommandBus, CqrsBuses, EventBus, QueryBus

from tori_py_cqrs.bindings import CqrsHandlerBinding
from tori_py_cqrs.errors import CqrsConfigurationError
from tori_py_cqrs.options import CqrsModuleOptions
from tori_py_cqrs.provider import (
    ToriPyHandlerProvider,
    _binding_plan,
    _BindingPlan,
    _explicit_bindings,
    _ExplicitBindings,
)
from tori_py_cqrs.runtime import (
    _buses,
    _command_bus,
    _CqrsRuntime,
    _create_runtime,
    _event_bus,
    _query_bus,
)


class CqrsModule:
    """Compose one discovered CQRS graph as a keyed ToriPy dynamic module."""

    @classmethod
    def for_root(
        cls,
        *,
        handlers: Iterable[CqrsHandlerBinding] = (),
        imports: Iterable[ModuleImport] = (),
        options: CqrsModuleOptions | None = None,
        key: str = "default",
        global_: bool = False,
    ) -> DeferredModule:
        try:
            bindings = tuple(handlers)
        except TypeError as error:
            raise CqrsConfigurationError("handlers must be iterable") from error
        if any(not isinstance(binding, CqrsHandlerBinding) for binding in bindings):
            raise CqrsConfigurationError(
                "handlers must contain only CqrsHandlerBinding values"
            )
        if options is not None and not isinstance(options, CqrsModuleOptions):
            raise CqrsConfigurationError("options must be a CqrsModuleOptions")
        selected_options = CqrsModuleOptions() if options is None else options
        explicit = _explicit_bindings(ModuleId(cls, key), key, bindings)
        imported = tuple(imports)

        def materialize() -> ModuleSpec:
            aliases = tuple(
                AliasProvider(entry.alias, entry.binding.token)
                for entry in explicit.entries
            )
            return ModuleSpec(
                imports=imported,
                providers=(
                    *aliases,
                    ValueProvider(CqrsModuleOptions, selected_options),
                    ValueProvider(_ExplicitBindings, explicit),
                    FactoryProvider(_BindingPlan, _binding_plan),
                    ClassProvider(ToriPyHandlerProvider),
                    FactoryProvider(_CqrsRuntime, _create_runtime),
                    FactoryProvider(CqrsBuses, _buses),
                    FactoryProvider(CommandBus, _command_bus),
                    FactoryProvider(QueryBus, _query_bus),
                    FactoryProvider(EventBus, _event_bus),
                ),
                exports=(CqrsBuses, CommandBus, QueryBus, EventBus),
                global_=global_,
            )

        return DeferredModule(cls, key, materialize)


__all__ = ["CqrsModule"]

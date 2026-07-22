"""Read-only views over one application's compiled providers."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from types import MappingProxyType

from nestpy.core.compiler import CompiledGraph, ModuleId, ProviderRef
from nestpy.core.errors import BootstrapError, ScopeError
from nestpy.core.providers import (
    ClassProvider,
    FactoryProvider,
    ProviderDeclaration,
    Scope,
    Token,
    ValueProvider,
)
from nestpy.core.reflection import MetadataDecorator, MetadataKey, Reflector


@dataclass(frozen=True, slots=True)
class ProviderView:
    """Immutable exact identity and canonical runtime provider snapshot."""

    ref: ProviderRef
    canonical: ProviderRef
    token: Token
    declaration: ProviderDeclaration
    scope: Scope
    implementation: type[object] | None
    instance: object | None
    instance_created: bool


@dataclass(frozen=True, slots=True)
class ModuleView:
    """Immutable provider/controller view for one compiled module identity."""

    module_id: ModuleId
    module: type[object]
    providers: tuple[ProviderView, ...]
    controllers: tuple[ProviderView, ...]


class RuntimeModulesContainer:
    """Application-owned implementation of the public ModulesContainer protocol."""

    def __init__(
        self,
        graph: CompiledGraph,
        instance_for: Callable[[ProviderRef], tuple[bool, object | None]],
    ) -> None:
        self._graph = graph
        self._instance_for = instance_for
        self._module_ids = frozenset(plan.module_id for plan in graph.modules)

    def __len__(self) -> int:
        return len(self._graph.modules)

    def __iter__(self) -> Iterator[ModuleId]:
        return iter(plan.module_id for plan in self._graph.modules)

    def __getitem__(self, module_id: ModuleId) -> ModuleView:
        try:
            return self._views()[module_id]
        except KeyError as error:
            raise ScopeError("unknown compiled module identity") from error

    def values(self) -> tuple[ModuleView, ...]:
        views = self._views()
        return tuple(views[plan.module_id] for plan in self._graph.modules)

    def provider(self, module_id: ModuleId, token: Token) -> ProviderView | None:
        if module_id not in self._module_ids:
            raise ScopeError("unknown compiled module identity")
        ref = self._graph.visibility.get((module_id, token))
        if ref is None:
            return None
        return self._provider_view(ref)

    def _views(self):
        provider_views: dict[ModuleId, list[ProviderView]] = {
            plan.module_id: [] for plan in self._graph.modules
        }
        controller_views: dict[ModuleId, list[ProviderView]] = {
            plan.module_id: [] for plan in self._graph.modules
        }
        controllers = {
            (plan.module_id, controller)
            for plan in self._graph.modules
            for controller in plan.spec.controllers
        }
        for ref in self._graph.provider_order:
            plan = self._graph.providers[ref]
            if ref != plan.canonical:
                continue
            view = self._provider_view(ref)
            destination = (
                controller_views
                if (ref.module_id, ref.token) in controllers
                else provider_views
            )
            destination[ref.module_id].append(view)
        return MappingProxyType(
            {
                plan.module_id: ModuleView(
                    module_id=plan.module_id,
                    module=plan.module,
                    providers=tuple(provider_views[plan.module_id]),
                    controllers=tuple(controller_views[plan.module_id]),
                )
                for plan in self._graph.modules
            }
        )

    def _provider_view(self, ref: ProviderRef) -> ProviderView:
        plan = self._graph.providers[ref]
        canonical_plan = self._graph.providers[plan.canonical]
        instance_created, instance = self._instance_for(plan.canonical)
        return ProviderView(
            ref=ref,
            canonical=plan.canonical,
            token=ref.token,
            declaration=plan.declaration,
            scope=canonical_plan.scope,
            implementation=_implementation(
                canonical_plan.declaration,
                instance,
                instance_created,
            ),
            instance=instance,
            instance_created=instance_created,
        )


class RuntimeDiscoveryService:
    """Application-owned implementation of generic provider discovery."""

    def __init__(
        self,
        modules: RuntimeModulesContainer,
        reflector: Reflector,
    ) -> None:
        self._modules = modules
        self._reflector = reflector

    def get_providers[T](
        self,
        *,
        include: Iterable[type[object]] | None = None,
        metadata: MetadataKey[T] | MetadataDecorator[T] | None = None,
    ) -> tuple[ProviderView, ...]:
        return self._discover("providers", include=include, metadata=metadata)

    def get_controllers[T](
        self,
        *,
        include: Iterable[type[object]] | None = None,
        metadata: MetadataKey[T] | MetadataDecorator[T] | None = None,
    ) -> tuple[ProviderView, ...]:
        return self._discover("controllers", include=include, metadata=metadata)

    def _discover[T](
        self,
        collection: str,
        *,
        include: Iterable[type[object]] | None,
        metadata: MetadataKey[T] | MetadataDecorator[T] | None,
    ) -> tuple[ProviderView, ...]:
        selected = _include(include)
        discovered: list[ProviderView] = []
        for module in self._modules.values():
            if selected is not None and module.module not in selected:
                continue
            views = (
                module.providers if collection == "providers" else module.controllers
            )
            for view in views:
                if metadata is not None:
                    if not any(
                        self._reflector.has(metadata, target)
                        for target in _metadata_targets(view)
                    ):
                        continue
                discovered.append(view)
        return tuple(discovered)

    def get_metadata_by_decorator[T](
        self,
        decorator: MetadataDecorator[T],
        provider: ProviderView,
    ) -> T | None:
        """Read decorator metadata from a discovered provider target."""

        for target in _metadata_targets(provider):
            if self._reflector.has(decorator, target):
                return self._reflector.get(decorator, target)
        return None


def _implementation(
    declaration: ProviderDeclaration,
    instance: object | None,
    instance_created: bool,
) -> type[object] | None:
    if isinstance(declaration, ClassProvider):
        return declaration.use_class
    if isinstance(declaration, ValueProvider):
        return type(declaration.value)
    if isinstance(declaration, FactoryProvider) and instance_created:
        return type(instance)
    return None


def _metadata_targets(provider: ProviderView) -> tuple[object, ...]:
    targets: list[object] = []
    if provider.implementation is not None:
        targets.append(provider.implementation)
    if provider.instance_created and provider.instance is not None:
        targets.append(provider.instance)
    return tuple(targets)


def _include(
    include: Iterable[type[object]] | None,
) -> frozenset[type[object]] | None:
    if include is None:
        return None
    try:
        selected = tuple(include)
    except TypeError as error:
        raise BootstrapError(
            "discovery include must be iterable",
            code="discovery.invalid_filter",
        ) from error
    if any(not isinstance(module, type) for module in selected):
        raise BootstrapError(
            "discovery include must contain module classes",
            code="discovery.invalid_filter",
        )
    return frozenset(selected)


__all__ = ["ModuleView", "ProviderView"]

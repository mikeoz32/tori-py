"""Immutable module and provider graph compilation for Nestpy N1."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Annotated, cast, get_args, get_origin, get_type_hints

from nestpy.core.errors import BootstrapError, SettingsError
from nestpy.core.modules import (
    DeferredModule,
    ModuleImport,
    ModuleSpec,
    get_module_metadata,
)
from nestpy.core.protocols import DiscoveryService, ModulesContainer, WorkScopeFactory
from nestpy.core.providers import (
    AliasProvider,
    ClassProvider,
    Inject,
    ProviderDeclaration,
    Scope,
    Token,
    ValueProvider,
)
from nestpy.core.reflection import Reflector

_INTRINSIC_DEPENDENCIES = (
    WorkScopeFactory,
    ModulesContainer,
    DiscoveryService,
    Reflector,
)


@dataclass(frozen=True, slots=True)
class ModuleId:
    """Qualified static or dynamic module identity."""

    module: type[object]
    key: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderRef:
    """A provider token qualified by its owning module."""

    module_id: ModuleId
    token: Token


ProviderKey = ProviderRef


@dataclass(frozen=True, slots=True)
class DependencyPlan:
    """One precompiled constructor or factory parameter."""

    parameter_name: str
    token: Token | None
    annotation: object
    has_default: bool
    provider_ref: ProviderRef | None = None


@dataclass(frozen=True, slots=True)
class ProviderPlan:
    """Immutable provider declaration and its compiled dependencies."""

    key: ProviderKey
    declaration: ProviderDeclaration
    dependencies: tuple[DependencyPlan, ...]
    scope: Scope
    canonical: ProviderRef


@dataclass(frozen=True, slots=True)
class ModulePlan:
    """Immutable module shape and local provider plans."""

    module_id: ModuleId
    module: type[object]
    spec: ModuleSpec
    imports: tuple[ModuleId, ...]
    providers: tuple[ProviderPlan, ...]

    @property
    def exports(self) -> tuple[Token, ...]:
        return tuple(self.spec.exports)

    @property
    def global_(self) -> bool:
        return self.spec.global_


@dataclass(frozen=True, slots=True)
class GraphShape:
    """Frozen module graph shape in dependency-first order."""

    root: ModuleId
    modules: tuple[ModulePlan, ...]


@dataclass(frozen=True, slots=True)
class CompiledGraph:
    """Complete immutable N1 output consumed by later runtime phases."""

    shape: GraphShape
    providers: Mapping[ProviderRef, ProviderPlan]
    visibility: Mapping[tuple[ModuleId, Token], ProviderRef]
    provider_order: tuple[ProviderRef, ...]

    @property
    def root(self) -> ModuleId:
        return self.shape.root

    @property
    def modules(self) -> tuple[ModulePlan, ...]:
        return self.shape.modules


@dataclass(slots=True)
class _ModuleNode:
    module_id: ModuleId
    module: type[object]
    spec: ModuleSpec
    imports: list[ModuleId]


class _Compiler:
    def __init__(
        self,
        *,
        import_resolver: Callable[[ModuleImport], ModuleImport] | None = None,
        spec_transformer: Callable[[ModuleId, ModuleSpec], ModuleSpec] | None = None,
        fallback_provider_collector: (
            Callable[[ModuleId, ModuleSpec, bool], Iterable[ProviderDeclaration]] | None
        ) = None,
    ) -> None:
        self.nodes: dict[ModuleId, _ModuleNode] = {}
        self.states: dict[ModuleId, str] = {}
        self.order: list[ModuleId] = []
        self.static_ids: dict[type[object], ModuleId] = {}
        self.dynamic_ids: dict[tuple[type[object], str], DeferredModule] = {}
        self.descriptor_ids: dict[int, ModuleId] = {}
        self.import_resolver = import_resolver
        self.spec_transformer = spec_transformer
        self.fallback_provider_collector = fallback_provider_collector

    async def compile(
        self,
        root: type[object] | DeferredModule,
    ) -> CompiledGraph:
        root_id = await self._ensure_import(root)
        await self._visit(root_id, ())
        return self._finish(root_id)

    async def _ensure_import(self, imported: ModuleImport) -> ModuleId:
        if self.import_resolver is not None:
            imported = self.import_resolver(imported)
        if isinstance(imported, DeferredModule):
            return await self._ensure_dynamic(imported)
        if isinstance(imported, type):
            return self._ensure_static(imported)
        raise BootstrapError(
            "module import must be a module class or deferred descriptor",
            code="module.invalid_declaration",
        )

    def _ensure_static(self, module: type[object]) -> ModuleId:
        if module in self.static_ids:
            return self.static_ids[module]
        if any(identity[0] is module for identity in self.dynamic_ids):
            raise self._error(
                "module.static_dynamic_conflict",
                f"static module {module.__qualname__} conflicts with a dynamic module",
            )
        _validate_module_constructor(module)
        module_id = ModuleId(module)
        self.static_ids[module] = module_id
        metadata = get_module_metadata(module)
        spec = metadata if metadata is not None else ModuleSpec()
        if self.spec_transformer is not None:
            spec = self.spec_transformer(module_id, spec)
        self.nodes[module_id] = _ModuleNode(module_id, module, spec, [])
        return module_id

    async def _ensure_dynamic(self, descriptor: DeferredModule) -> ModuleId:
        descriptor_id = id(descriptor)
        existing_descriptor = self.dynamic_ids.get((descriptor.module, descriptor.key))
        if existing_descriptor is not None and existing_descriptor is not descriptor:
            raise self._error(
                "module.dynamic_conflict",
                "different deferred descriptors use the same module identity",
                {
                    "module": descriptor.module.__qualname__,
                    "key": descriptor.key,
                },
            )
        if descriptor_id in self.descriptor_ids:
            return self.descriptor_ids[descriptor_id]
        if descriptor.module in self.static_ids:
            raise self._error(
                "module.static_dynamic_conflict",
                "dynamic module conflicts with static form",
            )

        identity = (descriptor.module, descriptor.key)
        self.dynamic_ids[identity] = descriptor
        module_id = ModuleId(descriptor.module, descriptor.key)
        self.descriptor_ids[descriptor_id] = module_id
        _validate_module_constructor(descriptor.module)
        try:
            result = descriptor.factory()
            if inspect.isawaitable(result):
                result = await result
        except SettingsError:
            raise
        except Exception as error:
            raise self._error(
                "module.materialization_error",
                "failed to materialize dynamic module",
            ) from error
        if not isinstance(result, ModuleSpec):
            raise self._error(
                "module.materialization_error",
                "dynamic module materializer must return ModuleSpec",
                {"module": descriptor.module.__qualname__, "key": descriptor.key},
            )
        if self.spec_transformer is not None:
            result = self.spec_transformer(module_id, result)
        self.nodes[module_id] = _ModuleNode(
            module_id,
            descriptor.module,
            result,
            [],
        )
        return module_id

    async def _visit(
        self,
        module_id: ModuleId,
        stack: tuple[ModuleId, ...],
    ) -> None:
        state = self.states.get(module_id)
        if state == "done":
            return
        if state == "visiting":
            cycle = stack + (module_id,)
            raise self._error(
                "module.cycle",
                "cyclic module import detected",
                {"path": tuple(_module_label(item) for item in cycle)},
            )
        self.states[module_id] = "visiting"
        node = self.nodes[module_id]
        next_stack = stack + (module_id,)
        for imported in node.spec.imports:
            child_id = await self._ensure_import(imported)
            node.imports.append(child_id)
            await self._visit(child_id, next_stack)
        self.states[module_id] = "done"
        self.order.append(module_id)

    def _finish(self, root_id: ModuleId) -> CompiledGraph:
        local_refs: dict[ModuleId, dict[Token, ProviderRef]] = {}
        module_plans: dict[ModuleId, ModulePlan] = {}

        for module_id in self.order:
            node = self.nodes[module_id]
            declaration_list = list(node.spec.providers)
            for controller in node.spec.controllers:
                existing = next(
                    (
                        provider
                        for provider in declaration_list
                        if provider.token is controller
                    ),
                    None,
                )
                if existing is not None:
                    if (
                        getattr(existing, "scope", Scope.SINGLETON)
                        is not Scope.SINGLETON
                    ):
                        raise self._error(
                            "controller.invalid_declaration",
                            "controllers must be singleton providers",
                            {"controller": controller.__qualname__},
                        )
                    raise self._error(
                        "provider.duplicate",
                        f"duplicate provider token {controller.__qualname__}",
                    )
                declaration_list.append(ClassProvider(controller, controller))

            refs: dict[Token, ProviderRef] = {}
            plans: list[ProviderPlan] = []
            for declaration in declaration_list:
                token = declaration.token
                _validate_provider_token(token)
                if token in refs:
                    raise self._error(
                        "provider.duplicate",
                        f"duplicate provider token {_token_label(token)}",
                        {"module": _module_label(module_id)},
                    )
                ref = ProviderRef(module_id, token)
                refs[token] = ref
                declaration_dependencies = _compile_dependencies(declaration)
                plans.append(
                    ProviderPlan(
                        key=ref,
                        declaration=declaration,
                        dependencies=declaration_dependencies,
                        scope=(
                            declaration.scope
                            if not isinstance(declaration, AliasProvider)
                            else Scope.SINGLETON
                        ),
                        canonical=ref,
                    )
                )
            local_refs[module_id] = refs
            module_plans[module_id] = ModulePlan(
                module_id=module_id,
                module=node.module,
                spec=node.spec,
                imports=tuple(node.imports),
                providers=tuple(plans),
            )

        if self.fallback_provider_collector is not None:
            for module_id in self.order:
                node = self.nodes[module_id]
                for declaration in self.fallback_provider_collector(
                    module_id,
                    node.spec,
                    module_id == root_id,
                ):
                    token = declaration.token
                    _validate_provider_token(token)
                    if _has_visible_provider(
                        module_id,
                        token,
                        local_refs,
                        module_plans,
                        self.order,
                    ):
                        continue
                    ref = ProviderRef(module_id, token)
                    plan = ProviderPlan(
                        key=ref,
                        declaration=declaration,
                        dependencies=_compile_dependencies(declaration),
                        scope=(
                            declaration.scope
                            if not isinstance(declaration, AliasProvider)
                            else Scope.SINGLETON
                        ),
                        canonical=ref,
                    )
                    local_refs[module_id][token] = ref
                    module_plans[module_id] = replace(
                        module_plans[module_id],
                        providers=module_plans[module_id].providers + (plan,),
                    )
        visibility = self._compile_visibility(local_refs, module_plans)

        provider_map: dict[ProviderRef, ProviderPlan] = {}
        for module_plan in module_plans.values():
            for provider_plan in module_plan.providers:
                provider_map[provider_plan.key] = provider_plan
        canonical_cache: dict[ProviderRef, ProviderRef] = {}
        for ref in tuple(provider_map):
            canonical_cache[ref] = _canonical_provider(
                ref,
                provider_map,
                visibility,
                canonical_cache,
                (),
            )

        for ref, plan in tuple(provider_map.items()):
            compiled_dependencies = tuple(
                replace(
                    dependency,
                    provider_ref=(
                        None
                        if dependency.token is None
                        or dependency.token in _INTRINSIC_DEPENDENCIES
                        else canonical_cache[
                            _visible_ref(
                                ref.module_id,
                                dependency.token,
                                visibility,
                                local_refs,
                                module_plans,
                                self.order,
                            )
                        ]
                    ),
                )
                for dependency in plan.dependencies
            )
            canonical = canonical_cache[ref]
            canonical_plan = provider_map[canonical]
            provider_map[ref] = replace(
                plan,
                dependencies=compiled_dependencies,
                scope=canonical_plan.scope,
                canonical=canonical,
            )

        edges = _provider_edges(provider_map, visibility, self.order)
        _validate_provider_cycles(edges, provider_map)
        _validate_scope_paths(edges, provider_map)
        provider_order = _provider_order(edges, provider_map, self.order, module_plans)
        final_modules = tuple(
            replace(
                module_plans[module_id],
                providers=tuple(
                    provider_map[provider.key]
                    for provider in module_plans[module_id].providers
                ),
            )
            for module_id in self.order
        )
        return CompiledGraph(
            shape=GraphShape(root_id, final_modules),
            providers=MappingProxyType(provider_map),
            visibility=MappingProxyType(visibility),
            provider_order=provider_order,
        )

    def _compile_visibility(
        self,
        local_refs: Mapping[ModuleId, Mapping[Token, ProviderRef]],
        module_plans: Mapping[ModuleId, ModulePlan],
    ) -> dict[tuple[ModuleId, Token], ProviderRef]:
        visibility: dict[tuple[ModuleId, Token], ProviderRef] = {}
        for module_id in self.order:
            self._validate_exports(module_id, local_refs, module_plans)
            for token in _visible_tokens(
                module_id, local_refs, module_plans, self.order
            ):
                visibility[(module_id, token)] = _resolve_visible(
                    module_id,
                    token,
                    local_refs,
                    module_plans,
                    self.order,
                )
        return visibility

    def _validate_exports(
        self,
        module_id: ModuleId,
        local_refs: Mapping[ModuleId, Mapping[Token, ProviderRef]],
        module_plans: Mapping[ModuleId, ModulePlan],
    ) -> None:
        plan = module_plans[module_id]
        for token in plan.exports:
            if token in local_refs[module_id]:
                continue
            candidates = _direct_export_candidates(module_id, token, module_plans)
            if not candidates:
                raise self._error(
                    "module.invalid_export",
                    f"module cannot export unresolved token {_token_label(token)}",
                    {"module": _module_label(module_id)},
                )
            if len(candidates) > 1:
                raise self._error(
                    "provider.ambiguous",
                    f"ambiguous exported token {_token_label(token)}",
                    {"module": _module_label(module_id)},
                )

    @staticmethod
    def _error(
        code: str,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> BootstrapError:
        return BootstrapError(message, code=code, details=details)


async def compile_graph(
    root: type[object] | DeferredModule,
    *,
    import_resolver: Callable[[ModuleImport], ModuleImport] | None = None,
    spec_transformer: Callable[[ModuleId, ModuleSpec], ModuleSpec] | None = None,
    fallback_provider_collector: (
        Callable[[ModuleId, ModuleSpec, bool], Iterable[ProviderDeclaration]] | None
    ) = None,
) -> CompiledGraph:
    """Compile a root module and all imported modules without instantiation."""

    return await _Compiler(
        import_resolver=import_resolver,
        spec_transformer=spec_transformer,
        fallback_provider_collector=fallback_provider_collector,
    ).compile(root)


def _validate_module_constructor(module: type[object]) -> None:
    try:
        parameters = inspect.signature(module).parameters.values()
    except (TypeError, ValueError) as error:
        raise BootstrapError(
            f"cannot inspect module constructor {module.__qualname__}",
            code="module.invalid_constructor",
        ) from error
    for parameter in parameters:
        if parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            continue
        if parameter.default is inspect.Parameter.empty:
            raise BootstrapError(
                f"module {module.__qualname__} has required constructor arguments",
                code="module.invalid_constructor",
            )


def _compile_dependencies(
    declaration: ProviderDeclaration,
) -> tuple[DependencyPlan, ...]:
    if isinstance(declaration, ValueProvider | AliasProvider):
        return ()
    if isinstance(declaration, ClassProvider):
        class_target = cast(type[object], declaration.use_class)
        target: Callable[..., object] = cast(Callable[..., object], class_target)
        signature_target = class_target.__init__
    else:
        target = declaration.factory
        signature_target = declaration.factory
    try:
        parameters = tuple(inspect.signature(target).parameters.values())
        hints = get_type_hints(signature_target, include_extras=True)
    except (NameError, TypeError, ValueError) as error:
        raise BootstrapError(
            "provider annotations could not be compiled",
            code="provider.invalid_signature",
        ) from error
    plans: list[DependencyPlan] = []
    for parameter in parameters:
        if parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            raise BootstrapError(
                f"variadic provider parameter {parameter.name} is not injectable",
                code="provider.invalid_signature",
            )
        annotation = hints.get(parameter.name, parameter.annotation)
        token, explicit = _annotation_token(annotation)
        has_default = parameter.default is not inspect.Parameter.empty
        if token is None and not has_default:
            raise BootstrapError(
                f"required provider parameter {parameter.name} is unannotated",
                code="provider.invalid_signature",
            )
        if has_default and not explicit:
            token = None
        plans.append(
            DependencyPlan(
                parameter_name=parameter.name,
                token=token,
                annotation=annotation,
                has_default=has_default,
            )
        )
    return tuple(plans)


def _validate_provider_token(token: Token) -> None:
    if token in _INTRINSIC_DEPENDENCIES:
        name = getattr(token, "__name__", "framework dependency")
        raise BootstrapError(
            f"{name} is a reserved framework dependency",
            code="provider.reserved_token",
        )


def _annotation_token(annotation: object) -> tuple[Token | None, bool]:
    explicit = False
    if annotation is inspect.Parameter.empty:
        return None, explicit
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        annotation = args[0]
        markers = [metadata for metadata in args[1:] if isinstance(metadata, Inject)]
        if len(markers) > 1:
            raise BootstrapError(
                "multiple Inject markers are invalid",
                code="provider.invalid_signature",
            )
        if markers:
            explicit = True
            return markers[0].token, explicit
    return (annotation if isinstance(annotation, type) else None), explicit


def _direct_export_candidates(
    module_id: ModuleId,
    token: Token,
    module_plans: Mapping[ModuleId, ModulePlan],
) -> tuple[ProviderRef, ...]:
    candidates: list[ProviderRef] = []
    seen: set[ModuleId] = set()

    for imported in module_plans[module_id].imports:
        if imported in seen:
            continue
        seen.add(imported)
        candidates.extend(
            _module_export_candidates(imported, token, module_plans, (module_id,))
        )
    return tuple(dict.fromkeys(candidates))


def _module_export_candidates(
    module_id: ModuleId,
    token: Token,
    module_plans: Mapping[ModuleId, ModulePlan],
    path: tuple[ModuleId, ...],
) -> tuple[ProviderRef, ...]:
    if module_id in path:
        return ()
    module_plan = module_plans[module_id]
    if token not in module_plan.exports:
        return ()
    local = tuple(
        provider.key
        for provider in module_plan.providers
        if provider.key.token == token
    )
    if local:
        return local
    candidates: list[ProviderRef] = []
    for imported in module_plan.imports:
        candidates.extend(
            _module_export_candidates(
                imported, token, module_plans, path + (module_id,)
            )
        )
    return tuple(dict.fromkeys(candidates))


def _visible_tokens(
    module_id: ModuleId,
    local_refs: Mapping[ModuleId, Mapping[Token, ProviderRef]],
    module_plans: Mapping[ModuleId, ModulePlan],
    order: Iterable[ModuleId],
) -> tuple[Token, ...]:
    tokens: list[Token] = list(local_refs[module_id])
    tokens.extend(
        token
        for imported in module_plans[module_id].imports
        for token in module_plans[imported].exports
    )
    tokens.extend(
        token
        for global_id in order
        if module_plans[global_id].global_
        for token in module_plans[global_id].exports
    )
    return tuple(dict.fromkeys(tokens))


def _resolve_visible(
    module_id: ModuleId,
    token: Token,
    local_refs: Mapping[ModuleId, Mapping[Token, ProviderRef]],
    module_plans: Mapping[ModuleId, ModulePlan],
    order: Iterable[ModuleId],
) -> ProviderRef:
    local = local_refs[module_id].get(token)
    if local is not None:
        return local
    direct = _direct_export_candidates(module_id, token, module_plans)
    if len(direct) > 1:
        raise BootstrapError(
            f"ambiguous direct provider token {_token_label(token)}",
            code="provider.ambiguous",
        )
    if direct:
        return direct[0]
    global_candidates = tuple(
        provider
        for global_id in order
        if module_plans[global_id].global_
        for provider in _module_export_candidates(global_id, token, module_plans, ())
    )
    if len(global_candidates) > 1:
        raise BootstrapError(
            f"ambiguous global provider token {_token_label(token)}",
            code="provider.ambiguous",
        )
    if global_candidates:
        return global_candidates[0]
    raise BootstrapError(
        f"unresolved provider token {_token_label(token)}",
        code="provider.unresolved",
    )


def _has_visible_provider(
    module_id: ModuleId,
    token: Token,
    local_refs: Mapping[ModuleId, Mapping[Token, ProviderRef]],
    module_plans: Mapping[ModuleId, ModulePlan],
    order: Iterable[ModuleId],
) -> bool:
    try:
        _resolve_visible(module_id, token, local_refs, module_plans, order)
    except BootstrapError as error:
        if error.diagnostic_code == "provider.unresolved":
            return False
        raise
    return True


def _visible_ref(
    module_id: ModuleId,
    token: Token,
    visibility: Mapping[tuple[ModuleId, Token], ProviderRef],
    local_refs: Mapping[ModuleId, Mapping[Token, ProviderRef]],
    module_plans: Mapping[ModuleId, ModulePlan],
    order: Iterable[ModuleId],
) -> ProviderRef:
    existing = visibility.get((module_id, token))
    if existing is not None:
        return existing
    return _resolve_visible(module_id, token, local_refs, module_plans, order)


def _canonical_provider(
    ref: ProviderRef,
    provider_map: Mapping[ProviderRef, ProviderPlan],
    visibility: Mapping[tuple[ModuleId, Token], ProviderRef],
    cache: dict[ProviderRef, ProviderRef],
    stack: tuple[ProviderRef, ...],
) -> ProviderRef:
    cached = cache.get(ref)
    if cached is not None:
        return cached
    declaration = provider_map[ref].declaration
    if not isinstance(declaration, AliasProvider):
        cache[ref] = ref
        return ref
    target = visibility.get((ref.module_id, declaration.target))
    if target is None:
        raise BootstrapError(
            f"unresolved alias target {_token_label(declaration.target)}",
            code="provider.unresolved",
        )
    if ref in stack or target in stack:
        cycle = stack + (ref, target)
        raise BootstrapError(
            "provider alias cycle detected",
            code="provider.alias_cycle",
            details={"path": tuple(_provider_label(item) for item in cycle)},
        )
    canonical = _canonical_provider(
        target, provider_map, visibility, cache, stack + (ref,)
    )
    cache[ref] = canonical
    return canonical


def _provider_edges(
    provider_map: Mapping[ProviderRef, ProviderPlan],
    visibility: Mapping[tuple[ModuleId, Token], ProviderRef],
    order: Iterable[ModuleId],
) -> dict[ProviderRef, tuple[ProviderRef, ...]]:
    del order
    edges: dict[ProviderRef, tuple[ProviderRef, ...]] = {}
    for ref, plan in provider_map.items():
        if isinstance(plan.declaration, AliasProvider):
            target = visibility[(ref.module_id, plan.declaration.target)]
            edges[ref] = (provider_map[target].canonical,)
        else:
            edges[ref] = tuple(
                dependency.provider_ref
                for dependency in plan.dependencies
                if dependency.provider_ref is not None
            )
    return edges


def _validate_provider_cycles(
    edges: Mapping[ProviderRef, tuple[ProviderRef, ...]],
    provider_map: Mapping[ProviderRef, ProviderPlan],
) -> None:
    states: dict[ProviderRef, str] = {}
    stack: list[ProviderRef] = []

    def visit(ref: ProviderRef) -> None:
        state = states.get(ref)
        if state == "done":
            return
        if state == "visiting":
            start = stack.index(ref)
            cycle = tuple(stack[start:] + [ref])
            has_alias = any(
                isinstance(provider_map[item].declaration, AliasProvider)
                for item in cycle
            )
            raise BootstrapError(
                "provider dependency cycle detected",
                code="provider.alias_cycle" if has_alias else "provider.cycle",
                details={"path": tuple(_provider_label(item) for item in cycle)},
            )
        states[ref] = "visiting"
        stack.append(ref)
        for dependency in edges.get(ref, ()):
            visit(dependency)
        stack.pop()
        states[ref] = "done"

    for ref in edges:
        visit(ref)


def _validate_scope_paths(
    edges: Mapping[ProviderRef, tuple[ProviderRef, ...]],
    provider_map: Mapping[ProviderRef, ProviderPlan],
) -> None:
    for root, plan in provider_map.items():
        if plan.scope is not Scope.SINGLETON:
            continue

        def visit(ref: ProviderRef, path: tuple[ProviderRef, ...]) -> None:
            for dependency in edges.get(ref, ()):
                next_path = path + (dependency,)
                if provider_map[dependency].scope is Scope.REQUEST:
                    raise BootstrapError(
                        "singleton provider reaches request-scoped provider",
                        code="provider.scope_violation",
                        details={
                            "path": tuple(_provider_label(item) for item in next_path),
                            "scopes": tuple(
                                provider_map[item].scope.value for item in next_path
                            ),
                        },
                    )
                visit(dependency, next_path)

        visit(root, (root,))


def _provider_order(
    edges: Mapping[ProviderRef, tuple[ProviderRef, ...]],
    provider_map: Mapping[ProviderRef, ProviderPlan],
    module_order: Iterable[ModuleId],
    module_plans: Mapping[ModuleId, ModulePlan],
) -> tuple[ProviderRef, ...]:
    result: list[ProviderRef] = []
    visited: set[ProviderRef] = set()

    def visit(ref: ProviderRef) -> None:
        if ref in visited:
            return
        visited.add(ref)
        for dependency in edges.get(ref, ()):
            visit(dependency)
        result.append(ref)

    for module_id in module_order:
        for provider in module_plans[module_id].providers:
            visit(provider.key)
    return tuple(result)


def _module_label(module_id: ModuleId) -> str:
    suffix = "" if module_id.key is None else f":{module_id.key}"
    return f"{module_id.module.__qualname__}{suffix}"


def _token_label(token: Token) -> str:
    return token.__qualname__ if isinstance(token, type) else token


def _provider_label(ref: ProviderRef) -> str:
    return f"{_module_label(ref.module_id)}::{_token_label(ref.token)}"


__all__ = [
    "CompiledGraph",
    "DependencyPlan",
    "GraphShape",
    "ModuleId",
    "ModulePlan",
    "ProviderKey",
    "ProviderPlan",
    "ProviderRef",
    "compile_graph",
]

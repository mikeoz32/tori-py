"""Pre-compilation graph overrides backed by the production kernel."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

from nestpy.application import (
    ApplicationAdapter,
    NestApplication,
    _create_application,
)
from nestpy.core.compiler import CompiledGraph, ModuleId
from nestpy.core.errors import BootstrapError
from nestpy.core.modules import DeferredModule, ModuleImport, ModuleSpec
from nestpy.core.options import ApplicationOptions, PipelineOptions
from nestpy.core.providers import (
    AliasProvider,
    ClassProvider,
    FactoryProvider,
    ProviderDeclaration,
    Token,
    ValueProvider,
)

if TYPE_CHECKING:
    import httpx


@dataclass(frozen=True, slots=True)
class _ModuleSelector:
    module: type[object]
    key: str | None = None


@dataclass(frozen=True, slots=True)
class _ProviderOverride:
    token: Token
    selector: _ModuleSelector | None
    declaration: ProviderDeclaration


class ProviderOverride:
    """Fluent declaration builder returned by ``TestingModule.override_provider``."""

    def __init__(
        self,
        owner: TestingModule,
        token: Token,
        selector: _ModuleSelector | None,
    ) -> None:
        self._owner = owner
        self._token = token
        self._selector = selector

    def use_value(self, value: object) -> TestingModule:
        return self._owner._add_provider_override(
            _ProviderOverride(
                self._token, self._selector, ValueProvider(self._token, value)
            )
        )

    def use_class(self, use_class: type[object]) -> TestingModule:
        return self._owner._add_provider_override(
            _ProviderOverride(
                self._token,
                self._selector,
                ClassProvider(self._token, use_class),
            )
        )

    def use_factory(
        self,
        factory: Callable[..., object],
    ) -> TestingModule:
        return self._owner._add_provider_override(
            _ProviderOverride(
                self._token,
                self._selector,
                FactoryProvider(self._token, factory),
            )
        )

    def use_alias(self, target: Token) -> TestingModule:
        return self._owner._add_provider_override(
            _ProviderOverride(
                self._token,
                self._selector,
                AliasProvider(self._token, target),
            )
        )


class TestingModule:
    """Mutable test builder that seals before compiling a normal application."""

    __test__ = False

    def __init__(self, root: type[object] | DeferredModule) -> None:
        self.root = root
        self._module_overrides: dict[object, ModuleImport] = {}
        self._provider_overrides: list[_ProviderOverride] = []
        self._sealed = False

    @classmethod
    def create(cls, root: type[object] | DeferredModule) -> TestingModule:
        return cls(root)

    def replace_module(
        self,
        target: DeferredModule | tuple[type[object], str],
        replacement: ModuleImport,
    ) -> TestingModule:
        self._check_open()
        self._module_overrides[_module_key(target)] = replacement
        return self

    def override_provider(
        self,
        token: Token,
        *,
        module: type[object] | DeferredModule | tuple[type[object], str],
    ) -> ProviderOverride:
        self._check_open()
        return ProviderOverride(self, token, _selector(module))

    def override_global(self, token: Token) -> ProviderOverride:
        self._check_open()
        return ProviderOverride(self, token, None)

    async def compile(
        self,
        *,
        options: ApplicationOptions | None = None,
        pipeline: PipelineOptions | None = None,
        adapter: ApplicationAdapter | None = None,
    ) -> TestingApplication:
        self._check_open()
        self._sealed = True
        application = await _create_application(
            self.root,
            options=options,
            pipeline=pipeline,
            adapter=adapter,
            import_resolver=self._resolve_import,
            spec_transformer=self._transform_spec,
            graph_validator=self._validate_override_targets,
        )
        await application.start()
        return TestingApplication(application)

    def _add_provider_override(
        self,
        override: _ProviderOverride,
    ) -> TestingModule:
        self._check_open()
        self._provider_overrides.append(override)
        return self

    def _resolve_import(self, imported: ModuleImport) -> ModuleImport:
        replacement = self._module_overrides.get(_module_key(imported))
        return imported if replacement is None else replacement

    def _transform_spec(self, module_id: ModuleId, spec: ModuleSpec) -> ModuleSpec:
        overrides = []
        for override in self._provider_overrides:
            if override.selector is None:
                if spec.global_ and override.token in spec.exports:
                    overrides.append(override)
            elif _matches(override.selector, module_id):
                overrides.append(override)
        if not overrides:
            return spec
        providers = list(cast(tuple[ProviderDeclaration, ...], spec.providers))
        exports = set(spec.exports)
        for override in overrides:
            if override.token not in exports:
                raise BootstrapError(
                    "private providers cannot be overridden",
                    code="testing.private_provider",
                    details={"token": repr(override.token)},
                )
            for index, provider in enumerate(providers):
                if provider.token == override.token:
                    providers[index] = override.declaration
                    break
            else:
                providers.append(override.declaration)
        return replace(spec, providers=providers)

    def _validate_override_targets(self, graph: CompiledGraph) -> None:
        for override in self._provider_overrides:
            if override.selector is None:
                matched = any(
                    module.global_ and override.token in module.exports
                    for module in graph.modules
                )
            else:
                matched = any(
                    _matches(override.selector, module.module_id)
                    for module in graph.modules
                )
            if not matched:
                raise BootstrapError(
                    "testing override target is not present in the compiled graph",
                    code="testing.invalid_override",
                    details={"token": repr(override.token)},
                )

    def _check_open(self) -> None:
        if self._sealed:
            raise BootstrapError(
                "testing module builder is sealed",
                code="testing.builder_sealed",
            )


class TestingApplication:
    """Testing facade over one production-equivalent NestApplication."""

    def __init__(self, application: NestApplication) -> None:
        self.application = application
        self.graph = application.graph

    def get_adapter[T: ApplicationAdapter](self, adapter_type: type[T]) -> T:
        return self.application.get_adapter(adapter_type)

    def http_client(
        self,
        *,
        base_url: str = "http://testserver",
        raise_app_exceptions: bool = False,
        client_address: tuple[str, int] = ("testclient", 50000),
    ) -> AbstractAsyncContextManager[httpx.AsyncClient]:
        """Return an HTTPX client context for the started Starlette adapter."""

        from nestpy.testing.http import http_client

        return http_client(
            self,
            base_url=base_url,
            raise_app_exceptions=raise_app_exceptions,
            client_address=client_address,
        )

    async def resolve(
        self,
        token: Token,
        module: ModuleId | type[object] | tuple[type[object], str] | None = None,
    ) -> object:
        module_id = (
            self.graph.root if module is None else _module_id(self.graph, module)
        )
        return await self.application._kernel.resolver(module_id).resolve(token)

    async def close(self) -> None:
        await self.application.shutdown()


def _module_key(
    value: DeferredModule | tuple[type[object], str] | ModuleImport,
) -> object:
    if isinstance(value, DeferredModule):
        return (value.module, value.key)
    return value


def _selector(
    value: type[object] | DeferredModule | tuple[type[object], str] | None,
) -> _ModuleSelector | None:
    if value is None:
        return None
    if isinstance(value, DeferredModule):
        return _ModuleSelector(value.module, value.key)
    if isinstance(value, tuple):
        return _ModuleSelector(value[0], value[1])
    return _ModuleSelector(value)


def _matches(selector: _ModuleSelector | None, module_id: ModuleId) -> bool:
    return selector is None or (
        selector.module is module_id.module and selector.key == module_id.key
    )


def _module_id(
    graph: CompiledGraph,
    value: ModuleId | type[object] | tuple[type[object], str],
) -> ModuleId:
    if isinstance(value, ModuleId):
        return value
    for module in graph.modules:
        if isinstance(value, tuple):
            if module.module is value[0] and module.module_id.key == value[1]:
                return module.module_id
        elif module.module is value:
            return module.module_id
    raise BootstrapError(
        "module is not present in the testing graph",
        code="testing.invalid_module",
    )


__all__ = ["ProviderOverride", "TestingApplication", "TestingModule"]

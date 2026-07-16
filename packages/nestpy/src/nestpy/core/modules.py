"""Static and deferred module declarations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from nestpy.core.errors import BootstrapError
from nestpy.core.providers import (
    AliasProvider,
    ClassProvider,
    FactoryProvider,
    ProviderDeclaration,
    Token,
    ValueProvider,
    validate_token,
)


def _as_tuple[T](values: Iterable[T]) -> tuple[T, ...]:
    return tuple(values)


@dataclass(frozen=True, slots=True)
class DeferredModule:
    """A deferred dynamic module descriptor, not a materialized module."""

    module: type[object]
    key: str
    factory: ModuleFactory

    def __post_init__(self) -> None:
        if not isinstance(self.module, type):
            raise BootstrapError(
                "deferred module module must be a class",
                code="module.invalid_declaration",
            )
        if not isinstance(self.key, str) or not self.key or self.key == "static":
            raise BootstrapError(
                "dynamic module key must be non-empty and not 'static'",
                code="module.invalid_declaration",
            )
        if not callable(self.factory):
            raise BootstrapError(
                "deferred module factory must be callable",
                code="module.invalid_declaration",
            )


type ModuleImport = type[object] | DeferredModule


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    """Immutable materialized module shape used by later compilation phases."""

    imports: Iterable[ModuleImport] = ()
    providers: Iterable[ProviderDeclaration] = ()
    controllers: Iterable[type[object]] = ()
    exports: Iterable[Token] = ()
    global_: bool = False

    def __post_init__(self) -> None:
        imports = _as_tuple(self.imports)
        providers = _as_tuple(self.providers)
        controllers = _as_tuple(self.controllers)
        exports = _as_tuple(self.exports)
        for imported in imports:
            if not isinstance(imported, type) and not isinstance(
                imported, DeferredModule
            ):
                raise BootstrapError(
                    "module imports must be classes or deferred descriptors",
                    code="module.invalid_declaration",
                )
        for provider in providers:
            if not isinstance(
                provider,
                (ValueProvider, ClassProvider, FactoryProvider, AliasProvider),
            ):
                raise BootstrapError(
                    "module providers must be explicit provider declarations",
                    code="provider.invalid_declaration",
                )
        for controller in controllers:
            if not isinstance(controller, type):
                raise BootstrapError(
                    "module controllers must be classes",
                    code="controller.invalid_declaration",
                )
        exports = tuple(validate_token(token) for token in exports)
        if not isinstance(self.global_, bool):
            raise BootstrapError(
                "module global_ must be boolean",
                code="module.invalid_declaration",
            )
        object.__setattr__(self, "imports", imports)
        object.__setattr__(self, "providers", providers)
        object.__setattr__(self, "controllers", controllers)
        object.__setattr__(self, "exports", exports)


type ModuleFactory = Callable[[], ModuleSpec | Awaitable[ModuleSpec]]


@dataclass(frozen=True, slots=True)
class ModuleMetadata(ModuleSpec):
    """Metadata attached directly to a static module class."""


def module(
    *,
    imports: Iterable[ModuleImport] = (),
    providers: Iterable[ProviderDeclaration] = (),
    controllers: Iterable[type[object]] = (),
    exports: Iterable[Token] = (),
    global_: bool = False,
) -> Callable[[type[object]], type[object]]:
    """Attach immutable module metadata without registering the class globally."""

    metadata = ModuleMetadata(
        imports=tuple(imports),
        providers=tuple(providers),
        controllers=tuple(controllers),
        exports=tuple(exports),
        global_=global_,
    )

    def decorate(target: type[object]) -> type[object]:
        if "__nestpy_module_metadata__" in target.__dict__:
            raise BootstrapError(
                "module metadata is already declared on this target",
                code="module.duplicate_metadata",
            )
        type.__setattr__(target, "__nestpy_module_metadata__", metadata)
        return target

    return decorate


def get_module_metadata(target: type[object]) -> ModuleMetadata | None:
    """Read directly declared module metadata without inheriting it."""

    metadata = target.__dict__.get("__nestpy_module_metadata__")
    return metadata if isinstance(metadata, ModuleMetadata) else None


__all__ = [
    "DeferredModule",
    "ModuleFactory",
    "ModuleImport",
    "ModuleMetadata",
    "ModuleSpec",
    "get_module_metadata",
    "module",
]

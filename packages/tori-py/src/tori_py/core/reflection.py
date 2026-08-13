"""Typed Python-native metadata declarations and lookup."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from tori_py.core.errors import BootstrapError

_METADATA_ATTRIBUTE = "__tori_py_reflection_metadata__"
_MISSING = object()


@dataclass(frozen=True, slots=True)
class MetadataKey[T]:
    """Unique typed identity used to attach and retrieve metadata."""

    name: str
    _identity: object = field(default_factory=object, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise BootstrapError(
                "metadata key name must be a non-empty string",
                code="reflection.invalid_metadata",
            )


@dataclass(frozen=True, slots=True)
class MetadataDecorator[T]:
    """Typed decorator factory associated with one metadata key."""

    key: MetadataKey[T]

    @property
    def KEY(self) -> MetadataKey[T]:  # noqa: N802 - mirrors Nest's decorator API
        """Return the decorator's lookup key."""

        return self.key

    def __call__[TargetT](self, value: T) -> Callable[[TargetT], TargetT]:
        return metadata(self.key, value)


def metadata[T, TargetT](
    key: MetadataKey[T] | MetadataDecorator[T],
    value: T,
) -> Callable[[TargetT], TargetT]:
    """Attach one directly declared metadata value to a class or function."""

    selected_key = _key(key)

    def decorate(target: TargetT) -> TargetT:
        if not isinstance(target, type) and not inspect.isfunction(target):
            raise BootstrapError(
                "metadata target must be a class or function",
                code="reflection.invalid_metadata",
            )
        existing = target.__dict__.get(_METADATA_ATTRIBUTE)
        if existing is None:
            values: dict[MetadataKey[object], object] = {}
        elif isinstance(existing, Mapping):
            values = dict(existing)
        else:
            raise BootstrapError(
                "metadata storage on target is invalid",
                code="reflection.invalid_metadata",
            )
        if selected_key in values:
            raise BootstrapError(
                f"metadata {selected_key.name} is already declared on target",
                code="reflection.duplicate_metadata",
            )
        values[selected_key] = value
        setattr(target, _METADATA_ATTRIBUTE, MappingProxyType(values))
        return target

    return decorate


class Reflector:
    """Read typed metadata without a process-global registry."""

    @staticmethod
    def create_decorator[T](name: str) -> MetadataDecorator[T]:
        """Create one uniquely keyed typed metadata decorator."""

        return MetadataDecorator(MetadataKey(name))

    def get_own[T](
        self,
        key: MetadataKey[T] | MetadataDecorator[T],
        target: object,
    ) -> T | None:
        """Return metadata declared directly on the target's class or function."""

        value = self._own_value(key, target)
        return None if value is _MISSING else cast(T, value)

    def has_own[T](
        self,
        key: MetadataKey[T] | MetadataDecorator[T],
        target: object,
    ) -> bool:
        """Return whether metadata is declared directly on the target."""

        return self._own_value(key, target) is not _MISSING

    def get[T](
        self,
        key: MetadataKey[T] | MetadataDecorator[T],
        target: object,
    ) -> T | None:
        """Return direct metadata or the nearest class-inherited value."""

        owner = _owner(target)
        if not isinstance(owner, type):
            return self.get_own(key, owner)
        for candidate in owner.__mro__:
            value = self._own_value(key, candidate)
            if value is not _MISSING:
                return cast(T, value)
        return None

    def has[T](
        self,
        key: MetadataKey[T] | MetadataDecorator[T],
        target: object,
    ) -> bool:
        """Return whether direct or inherited metadata exists for a target."""

        owner = _owner(target)
        if not isinstance(owner, type):
            return self.has_own(key, owner)
        return any(self.has_own(key, candidate) for candidate in owner.__mro__)

    def get_all_and_override[T](
        self,
        key: MetadataKey[T] | MetadataDecorator[T],
        targets: Iterable[object],
    ) -> T | None:
        """Return the first available metadata value from ordered targets."""

        for target in targets:
            if self.has(key, target):
                return self.get(key, target)
        return None

    @staticmethod
    def _own_value[T](
        key: MetadataKey[T] | MetadataDecorator[T],
        target: object,
    ) -> object:
        selected_key = _key(key)
        owner = _owner(target)
        values = owner.__dict__.get(_METADATA_ATTRIBUTE)
        if not isinstance(values, Mapping):
            return _MISSING
        return values.get(selected_key, _MISSING)


def _key[T](
    key: MetadataKey[T] | MetadataDecorator[T],
) -> MetadataKey[T]:
    if isinstance(key, MetadataDecorator):
        return key.key
    if isinstance(key, MetadataKey):
        return key
    raise BootstrapError(
        "metadata lookup requires a MetadataKey or MetadataDecorator",
        code="reflection.invalid_metadata",
    )


def _owner(target: object) -> type[object] | Callable[..., object]:
    if isinstance(target, type) or inspect.isfunction(target):
        return target
    if inspect.ismethod(target):
        return target.__func__
    return type(target)


__all__ = ["MetadataDecorator", "MetadataKey", "Reflector", "metadata"]

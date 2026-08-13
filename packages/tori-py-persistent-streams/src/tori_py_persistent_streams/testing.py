"""Deterministic configured in-memory adapter for tests and examples."""

from __future__ import annotations

from dataclasses import dataclass

from tori_py import DeferredModule, ModuleSpec, ValueProvider
from tori_py_persistent_streams_core import (
    InMemoryPersistentLog,
    PersistentStreamAdapter,
)

from tori_py_persistent_streams.contracts import StreamAdapterFactory


@dataclass(slots=True)
class InMemoryStreamAdapterFactory:
    """Create or expose one in-memory persistent log."""

    log: PersistentStreamAdapter | None = None
    created: int = 0

    def create(self, bindings: tuple[object, ...]) -> PersistentStreamAdapter:
        del bindings
        self.created += 1
        if self.log is None:
            self.log = InMemoryPersistentLog()
        return self.log


class InMemoryPersistentStreamsModule:
    """Configure an in-memory adapter module for normal ToriPy imports."""

    @classmethod
    def for_root(
        cls,
        factory: InMemoryStreamAdapterFactory | None = None,
    ) -> DeferredModule:
        selected = factory or InMemoryStreamAdapterFactory()

        def materialize() -> ModuleSpec:
            return ModuleSpec(
                providers=[ValueProvider(StreamAdapterFactory, selected)],
                exports=[StreamAdapterFactory],
            )

        return DeferredModule(cls, "default", materialize)


__all__ = [
    "InMemoryPersistentStreamsModule",
    "InMemoryStreamAdapterFactory",
]

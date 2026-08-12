"""Deterministic configured in-memory adapter for tests and examples."""

from __future__ import annotations

from dataclasses import dataclass

from nestpy import DeferredModule, ModuleSpec, ValueProvider
from persistent_streams import InMemoryPersistentLog, PersistentStreamAdapter

from nestpy_persistent_streams.contracts import StreamAdapterFactory


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
    """Configure an in-memory adapter module for normal Nestpy imports."""

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

"""Deterministic configured in-memory adapter for tests and examples."""

from __future__ import annotations

from dataclasses import dataclass

from nestpy import DeferredModule, ModuleSpec, ValueProvider
from persistent_streams import InMemoryPersistentLog, PersistentStreamAdapter

from nestpy_persistent_streams.contracts import ConfiguredStreamAdapter

IN_MEMORY_STREAM_ADAPTER_FACTORY = (
    "nestpy-persistent-streams:testing:in-memory-adapter-factory"
)


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
    """Materialize a configured in-memory adapter reference."""

    @classmethod
    def for_root(
        cls,
        factory: InMemoryStreamAdapterFactory | None = None,
    ) -> ConfiguredStreamAdapter:
        selected = factory or InMemoryStreamAdapterFactory()

        def materialize() -> ModuleSpec:
            return ModuleSpec(
                providers=[ValueProvider(IN_MEMORY_STREAM_ADAPTER_FACTORY, selected)],
                exports=[IN_MEMORY_STREAM_ADAPTER_FACTORY],
            )

        descriptor = DeferredModule(cls, "default", materialize)
        return ConfiguredStreamAdapter(
            descriptor,
            IN_MEMORY_STREAM_ADAPTER_FACTORY,
            "in-memory",
        )


__all__ = [
    "IN_MEMORY_STREAM_ADAPTER_FACTORY",
    "InMemoryPersistentStreamsModule",
    "InMemoryStreamAdapterFactory",
]

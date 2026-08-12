from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from nestpy import (
    DeferredModule,
    FactoryProvider,
    ModuleImport,
    ModuleSpec,
    ValueProvider,
)
from nestpy_persistent_streams import StreamAdapterFactory
from persistent_streams import PersistentStreamAdapter

from persistent_streams_rabbitmq.log import RabbitMqPersistentLog
from persistent_streams_rabbitmq.options import RabbitMqPersistentStreamsOptions

_RABBITMQ_OPTIONS = "persistent-streams-rabbitmq:options"


@dataclass(frozen=True, slots=True)
class RabbitMqStreamAdapterFactory:
    options: RabbitMqPersistentStreamsOptions

    def __post_init__(self) -> None:
        if not isinstance(self.options, RabbitMqPersistentStreamsOptions):
            raise TypeError("options must be RabbitMqPersistentStreamsOptions")

    def create(self, bindings: tuple[object, ...]) -> PersistentStreamAdapter:
        del bindings
        return RabbitMqPersistentLog(self.options)


class RabbitMqPersistentStreamsModule:
    @classmethod
    def for_root(cls, options: RabbitMqPersistentStreamsOptions) -> DeferredModule:
        if not isinstance(options, RabbitMqPersistentStreamsOptions):
            raise TypeError("options must be RabbitMqPersistentStreamsOptions")

        def materialize() -> ModuleSpec:
            factory = RabbitMqStreamAdapterFactory(options)
            return ModuleSpec(
                providers=[
                    ValueProvider(_RABBITMQ_OPTIONS, options),
                    ValueProvider(StreamAdapterFactory, factory),
                ],
                exports=[StreamAdapterFactory],
            )

        return DeferredModule(cls, "root", materialize)

    @classmethod
    def for_root_async(
        cls,
        *,
        use_factory: Callable[..., object],
        imports: Iterable[ModuleImport] = (),
    ) -> DeferredModule:
        if not callable(use_factory):
            raise TypeError("use_factory must be callable")

        def create_factory(
            options: RabbitMqPersistentStreamsOptions,
        ) -> RabbitMqStreamAdapterFactory:
            if not isinstance(options, RabbitMqPersistentStreamsOptions):
                raise TypeError(
                    "RabbitMQ options factory must return "
                    "RabbitMqPersistentStreamsOptions"
                )
            return RabbitMqStreamAdapterFactory(options)

        def materialize() -> ModuleSpec:
            return ModuleSpec(
                imports=tuple(imports),
                providers=[
                    FactoryProvider(RabbitMqPersistentStreamsOptions, use_factory),
                    FactoryProvider(StreamAdapterFactory, create_factory),
                ],
                exports=[StreamAdapterFactory],
            )

        return DeferredModule(cls, "root-async", materialize)


__all__ = [
    "RabbitMqPersistentStreamsModule",
    "RabbitMqStreamAdapterFactory",
]

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

from persistent_streams import (
    IncompatibleStreamError,
    ResourceLimitError,
    StreamDefinition,
    UnknownStreamError,
    ValidationError,
)
from rstream import Producer, RouteType, SuperStreamCreationOption, SuperStreamProducer
from rstream.exceptions import StreamDoesNotExist

from persistent_streams_rabbitmq._shared import best_effort_close
from persistent_streams_rabbitmq.errors import TopologyConflictError
from persistent_streams_rabbitmq.options import (
    DeclarationMode,
    RabbitMqPersistentStreamsOptions,
    SaslMechanism,
)


@dataclass(frozen=True, slots=True)
class TopologyPreflight:
    kind: str
    physical_streams: tuple[str, ...]
    binding_keys: tuple[str, ...]
    unverified_facts: tuple[str, ...] = (
        "effective-retention",
        "replication",
        "leader-placement",
        "broker-policy",
        "permissions",
    )


class TopologyMixin:
    options: RabbitMqPersistentStreamsOptions
    _definitions: dict[str, StreamDefinition]
    _topology: dict[str, TopologyPreflight]
    _declaration_lock: asyncio.Lock

    @property
    def topology_preflight(self) -> Mapping[str, TopologyPreflight]:
        return dict(self._topology)

    async def declare_stream(self, definition: StreamDefinition) -> None:
        self._require_open()
        if not isinstance(definition, StreamDefinition):
            raise TypeError("definition must be StreamDefinition")
        async with self._declaration_lock:
            current = self._definitions.get(definition.name)
            if current is not None:
                if current.compatibility_key != definition.compatibility_key:
                    raise IncompatibleStreamError(definition.name)
                return
            physical_count = sum(
                existing.partition_count for existing in self._definitions.values()
            )
            if physical_count + definition.partition_count > self.options.max_streams:
                raise ResourceLimitError("physical stream resource limit reached")
            if definition.partition_count == 1:
                preflight = await self._declare_regular(definition)
            else:
                preflight = await self._declare_super(definition)
            self._definitions[definition.name] = definition
            self._topology[definition.name] = preflight

    async def _declare_regular(self, definition: StreamDefinition) -> TopologyPreflight:
        producer = Producer(**self.options.connection.driver_kwargs())
        try:
            await self._within(producer.start())
            exists = await self._within(producer.stream_exists(definition.name))
            if not exists:
                super_partitions = await self._inspect_super_partitions(definition.name)
                if super_partitions is not None:
                    raise TopologyConflictError(
                        "Super Stream exists where a regular stream is required"
                    )
            if (
                not exists
                and self.options.declaration is DeclarationMode.REQUIRE_EXISTING
            ):
                raise UnknownStreamError(definition.name)
            if not exists:
                await self._within(
                    producer.create_stream(
                        definition.name,
                        arguments=dict(self.options.declaration_arguments),
                        exists_ok=True,
                    )
                )
                if await self._inspect_super_partitions(definition.name) is not None:
                    raise TopologyConflictError(
                        "Super Stream exists where a regular stream is required"
                    )
        finally:
            await best_effort_close(producer)
        return TopologyPreflight("regular", (definition.name,), ())

    async def _declare_super(self, definition: StreamDefinition) -> TopologyPreflight:
        binding_keys = tuple(str(index) for index in range(definition.partition_count))
        physical = tuple(f"{definition.name}-{key}" for key in binding_keys)
        inspector = Producer(**self.options.connection.driver_kwargs())
        try:
            await self._within(inspector.start())
            regular_exists = await self._within(
                inspector.stream_exists(definition.name)
            )
        finally:
            await best_effort_close(inspector)
        if regular_exists:
            raise TopologyConflictError(
                "regular stream exists where Super Stream is required"
            )
        actual = await self._inspect_super_partitions(definition.name)
        if actual is None:
            if self.options.declaration is DeclarationMode.REQUIRE_EXISTING:
                raise UnknownStreamError(definition.name)
            await self._create_super(definition.name, binding_keys)
            actual = await self._inspect_super_partitions(definition.name)
        if tuple(actual or ()) != physical:
            raise TopologyConflictError("Super Stream partition topology conflicts")
        routes = await self._inspect_routes(definition.name, binding_keys)
        if routes != physical:
            raise TopologyConflictError("Super Stream binding topology conflicts")
        return TopologyPreflight("super", physical, binding_keys)

    async def _create_super(self, name: str, keys: tuple[str, ...]) -> None:
        owner = self._new_super_owner(
            name,
            creation=SuperStreamCreationOption(
                n_partitions=0,
                binding_keys=list(keys),
                arguments=dict(self.options.declaration_arguments),
            ),
        )
        try:
            await self._within(owner.start())
        finally:
            await best_effort_close(owner)

    async def _inspect_super_partitions(self, name: str) -> tuple[str, ...] | None:
        owner = self._new_super_owner(name)
        try:
            await self._within(owner.start())
            return tuple(await self._within(owner.super_stream_metadata.partitions()))
        except StreamDoesNotExist:
            return None
        except ValueError as error:
            if str(error) != (
                "the number of partitions of the stream is <= to 0, the "
                "superstream doesn't probably exist"
            ):
                raise
            return None
        finally:
            await best_effort_close(owner)

    async def _inspect_routes(
        self, name: str, keys: tuple[str, ...]
    ) -> tuple[str, ...]:
        routes: list[str] = []
        for key in keys:
            owner = self._new_super_owner(name)
            try:
                await self._within(owner.start())
                selected = await self._within(owner.super_stream_metadata.routes(key))
                if len(selected) != 1:
                    raise TopologyConflictError(
                        "binding key does not select one partition"
                    )
                routes.append(selected[0])
            finally:
                await best_effort_close(owner)
        return tuple(routes)

    def _new_super_owner(
        self, name: str, creation: SuperStreamCreationOption | None = None
    ) -> SuperStreamProducer:
        async def route(message: object) -> str:
            del message
            return "0"

        if self.options.connection.sasl_mechanism is not SaslMechanism.PLAIN:
            raise ValidationError(
                "rstream 1.0.1 SuperStreamProducer supports only PLAIN SASL"
            )
        kwargs = self.options.connection.driver_kwargs()
        kwargs.pop("sasl_configuration_mechanism")
        return SuperStreamProducer(
            **kwargs,
            super_stream=name,
            super_stream_creation_option=creation,
            routing_extractor=route,
            routing=RouteType.Key,
        )

    def _require_open(self) -> None:
        raise NotImplementedError

    async def _within(self, operation):
        raise NotImplementedError


__all__ = ["TopologyMixin", "TopologyPreflight"]

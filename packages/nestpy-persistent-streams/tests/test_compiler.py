from __future__ import annotations

from typing import Annotated, Protocol, cast
from uuid import UUID

import pytest
from nestpy import ModuleId, ModulesContainer, ProviderRef, controller
from nestpy_persistent_streams import (
    StreamContext,
    StreamHandlerCompilationError,
    StreamPayload,
    StreamRecordContext,
    compile_controller_stream_handlers,
    stream_handler,
    stream_publish,
)
from nestpy_persistent_streams.compiler import validate_publisher_protocol
from nestpy_persistent_streams.errors import StreamConfigurationError
from persistent_streams import PublishReceipt


class Modules:
    def provider(self, module_id, token):
        del module_id, token
        return None


def test_compiles_direct_typed_handler() -> None:
    @controller()
    class Projection:
        @stream_handler(stream="events", consumer_group="projection-v1")
        async def apply(
            self,
            payload: Annotated[str, StreamPayload()],
            context: Annotated[StreamContext, StreamRecordContext()],
        ) -> None:
            del payload, context

    owner = ModuleId(Projection)
    plans = compile_controller_stream_handlers(
        owner, Projection, cast(ModulesContainer, Modules())
    )

    assert len(plans) == 1
    assert plans[0].module_id == owner
    assert plans[0].controller_ref == ProviderRef(owner, Projection)
    assert plans[0].payload_type is str


def test_inherited_handler_is_not_discovered() -> None:
    class Parent:
        @stream_handler(stream="events", consumer_group="projection-v1")
        async def apply(self, payload: Annotated[str, StreamPayload()]) -> None:
            del payload

    @controller()
    class Child(Parent):
        pass

    assert (
        compile_controller_stream_handlers(
            ModuleId(Child), Child, cast(ModulesContainer, Modules())
        )
        == ()
    )


def test_invalid_handler_signatures_fail_compilation() -> None:
    @controller()
    class MissingPayload:
        @stream_handler(stream="events", consumer_group="projection-v1")
        async def apply(self) -> None:
            pass

    with pytest.raises(StreamHandlerCompilationError, match="exactly one"):
        compile_controller_stream_handlers(
            ModuleId(MissingPayload),
            MissingPayload,
            cast(ModulesContainer, Modules()),
        )

    @controller()
    class Synchronous:
        @stream_handler(stream="events", consumer_group="projection-v2")
        def apply(self, payload: Annotated[str, StreamPayload()]) -> None:
            del payload

    with pytest.raises(StreamHandlerCompilationError, match="must be async"):
        compile_controller_stream_handlers(
            ModuleId(Synchronous),
            Synchronous,
            cast(ModulesContainer, Modules()),
        )


def test_undecorated_direct_publisher_protocol_method_is_rejected() -> None:
    class Publisher(Protocol):
        async def publish(self, payload: str) -> None: ...

    with pytest.raises(StreamConfigurationError, match="requires @stream_publish"):
        validate_publisher_protocol(Publisher, str)


def test_publisher_protocol_payload_default_is_rejected() -> None:
    class Publisher(Protocol):
        @stream_publish(payload=str)
        async def publish(
            self,
            payload: str = "default",
            *,
            record_id: UUID | None = None,
        ) -> PublishReceipt: ...

    with pytest.raises(StreamConfigurationError, match="payload cannot have a default"):
        validate_publisher_protocol(Publisher, str)

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Annotated, cast

import pytest
from nestpy import (
    DiscoveryService,
    Inject,
    ModuleId,
    ModulesContainer,
    ProviderRef,
    Token,
    use_guard,
)

from nestpy_microservices import (
    Context,
    EventDispatchMode,
    EventHandlerPlan,
    HandlerCompilationError,
    Header,
    Headers,
    Payload,
    RpcContext,
    RpcHandlerPlan,
    ServiceIdentity,
    compile_controller_message_handlers,
    compile_discovered_service_handlers,
    compile_service_handler_registry,
    event_handler,
    rpc,
)

SERVICE = ServiceIdentity("kinker", "members", 1)
MODULE_ID = ModuleId(object)


class MessageController:
    @rpc("resolve-profile", schema_version=2)
    @use_guard("audit-guard")
    async def resolve(
        self,
        payload: Annotated[dict[str, object], Payload()],
        context: Annotated[RpcContext, Context()],
        headers: Annotated[dict[str, object], Headers()],
        trace: Annotated[str, Header("trace")],
        repository: Annotated[object, Inject("repository")],
    ) -> dict[str, object]:
        return {
            "payload": payload,
            "context": context,
            "headers": headers,
            "trace": trace,
            "repository": repository,
        }

    @event_handler(
        SERVICE,
        "profile-created",
        schema_version=1,
        mode=EventDispatchMode.SERVICE_POOL,
        subscription="notify-profile",
    )
    async def created(self, payload: Annotated[dict[str, object], Payload()]) -> None:
        return None

    async def ordinary(self, value: object) -> object:
        return value


class InheritedMessageController(MessageController):
    pass


def test_controller_compiler_uses_direct_metadata_and_preserves_order() -> None:
    plans = compile_controller_message_handlers(MODULE_ID, MessageController)

    assert [plan.method_name for plan in plans] == ["resolve", "created"]
    rpc_plan, event_plan = plans
    assert isinstance(rpc_plan, RpcHandlerPlan)
    assert isinstance(event_plan, EventHandlerPlan)
    assert rpc_plan.method == "resolve-profile"
    assert rpc_plan.schema_version == 2
    assert [parameter.kind for parameter in rpc_plan.parameters] == [
        "payload",
        "context",
        "headers",
        "header",
        "inject",
    ]
    assert rpc_plan.parameters[3].source == "trace"
    assert rpc_plan.parameters[4].token == "repository"
    assert rpc_plan.method_pipeline.guards == ("audit-guard",)
    assert event_plan.subscription == "notify-profile"
    assert event_plan.metadata.reliable is True

    assert (
        compile_controller_message_handlers(MODULE_ID, InheritedMessageController) == ()
    )


def test_graph_aware_compilation_qualifies_injections_and_pipeline_tokens() -> None:
    class FakeModules:
        def provider(self, module_id: ModuleId, token: Token):
            return SimpleNamespace(ref=ProviderRef(module_id, token))

    plans = compile_controller_message_handlers(
        MODULE_ID,
        MessageController,
        modules=cast(ModulesContainer, FakeModules()),
    )
    rpc_plan = plans[0]
    assert isinstance(rpc_plan, RpcHandlerPlan)
    assert rpc_plan.parameters[4].provider_ref == ProviderRef(MODULE_ID, "repository")
    assert rpc_plan.method_pipeline.qualified_provider_refs == (
        ("guards", ProviderRef(MODULE_ID, "audit-guard")),
    )


def test_registry_rejects_duplicate_rpc_and_event_identities() -> None:
    class DuplicateRpc:
        @rpc("resolve-profile", schema_version=2)
        async def other(self, payload: Annotated[object, Payload()]) -> object:
            return payload

    with pytest.raises(HandlerCompilationError):
        compile_service_handler_registry(
            ((MODULE_ID, MessageController), (ModuleId(str), DuplicateRpc))
        )

    class DuplicateEvent:
        @event_handler(
            SERVICE,
            "profile-created",
            schema_version=1,
            mode=EventDispatchMode.SERVICE_POOL,
            subscription="notify-profile",
        )
        async def other(self, payload: Annotated[object, Payload()]) -> None:
            return None

    with pytest.raises(HandlerCompilationError):
        compile_service_handler_registry(
            ((MODULE_ID, MessageController), (ModuleId(str), DuplicateEvent))
        )


def test_registry_stores_immutable_exact_indexes_once() -> None:
    class VersionOne:
        @rpc("resolve-profile", schema_version=1)
        async def resolve(self, payload: Annotated[object, Payload()]) -> object:
            return payload

    registry = compile_service_handler_registry(
        ((MODULE_ID, MessageController), (ModuleId(str), VersionOne))
    )

    assert registry.rpc_by_target is registry.rpc_by_target
    assert registry.event_by_subscription is registry.event_by_subscription
    assert registry.rpc_by_target[("resolve-profile", 1)].schema_version == 1
    assert registry.rpc_by_target[("resolve-profile", 2)].schema_version == 2
    with pytest.raises(TypeError):
        mutable_view = cast(
            dict[tuple[str, int], RpcHandlerPlan], registry.rpc_by_target
        )
        mutable_view[("resolve-profile", 3)] = registry.rpc_handlers[0]


def test_broadcast_default_and_reliable_modes_are_explicit() -> None:
    @event_handler(
        SERVICE,
        "cache-invalidated",
        schema_version=1,
        mode=EventDispatchMode.BROADCAST,
        subscription="profile-cache",
    )
    async def ephemeral(
        payload: Annotated[object, Payload()],
    ) -> None:
        return None

    @event_handler(
        SERVICE,
        "cache-invalidated",
        schema_version=1,
        mode=EventDispatchMode.BROADCAST,
        subscription="profile-cache-reliable",
        reliable=True,
    )
    async def reliable(
        payload: Annotated[object, Payload()],
    ) -> None:
        return None

    BroadcastController = type(
        "BroadcastController",
        (),
        {"ephemeral": ephemeral, "reliable": reliable},
    )

    plans = compile_controller_message_handlers(MODULE_ID, BroadcastController)
    ephemeral_plan, reliable_plan = plans
    assert isinstance(ephemeral_plan, EventHandlerPlan)
    assert isinstance(reliable_plan, EventHandlerPlan)
    assert [
        ephemeral_plan.metadata.reliable,
        reliable_plan.metadata.reliable,
    ] == [False, True]

    with pytest.raises(HandlerCompilationError):
        event_handler(
            SERVICE,
            "cache-invalidated",
            schema_version=1,
            mode=EventDispatchMode.SINGLETON,
            subscription="global-cache",
            reliable=False,
        )


@pytest.mark.parametrize(
    "controller",
    [
        type(
            "SyncController",
            (),
            {
                "handle": rpc("sync")(lambda self, payload: payload),
            },
        ),
        type(
            "UnannotatedController",
            (),
            {
                "handle": rpc("unannotated")(lambda self, payload: payload),
            },
        ),
    ],
)
def test_invalid_rpc_handlers_fail_before_registry_use(
    controller: type[object],
) -> None:
    with pytest.raises(HandlerCompilationError):
        compile_controller_message_handlers(MODULE_ID, controller)


def test_event_return_contract_and_payload_cardinality_are_validated() -> None:
    class BadEvent:
        @event_handler(
            SERVICE,
            "bad-event",
            schema_version=1,
            mode=EventDispatchMode.SERVICE_POOL,
            subscription="bad-event",
        )
        async def handle(self, payload: Annotated[object, Payload()]) -> str:
            return "bad"

    with pytest.raises(HandlerCompilationError):
        compile_controller_message_handlers(MODULE_ID, BadEvent)

    class TwoPayloads:
        @rpc("two-payloads")
        async def handle(
            self,
            first: Annotated[object, Payload()],
            second: Annotated[object, Payload()],
        ) -> object:
            return first

    with pytest.raises(HandlerCompilationError):
        compile_controller_message_handlers(MODULE_ID, TwoPayloads)


def test_positional_only_and_non_callable_shadowing_are_rejected() -> None:
    class PositionalOnly:
        @rpc("positional-only")
        async def handle(self, payload: Annotated[object, Payload()], /) -> object:
            return payload

    with pytest.raises(HandlerCompilationError):
        compile_controller_message_handlers(MODULE_ID, PositionalOnly)

    class Base:
        @rpc("shadowed")
        async def handle(self, payload: Annotated[object, Payload()]) -> object:
            return payload

    class Override(Base):
        handle = None

    with pytest.raises(HandlerCompilationError):
        compile_controller_message_handlers(MODULE_ID, Override)


def test_discovery_is_called_once_and_exact_provider_ref_is_retained() -> None:
    ref = ProviderRef(MODULE_ID, "controller-token")

    @dataclass
    class FakeDiscovery:
        calls: int = 0

        def get_controllers(self):
            self.calls += 1
            return (SimpleNamespace(ref=ref, implementation=MessageController),)

    discovery = FakeDiscovery()
    registry = compile_discovered_service_handlers(cast(DiscoveryService, discovery))

    assert discovery.calls == 1
    assert registry.rpc_handlers[0].controller_ref == ref
    assert registry.rpc_handlers[0].module_id == MODULE_ID

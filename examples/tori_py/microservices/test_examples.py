from __future__ import annotations

import pytest
from tori_py import DeferredModule, ModuleId, ModuleSpec, ValueProvider
from tori_py_microservices import (
    EventDispatchMode,
    MicroservicesRoot,
    compile_service_handler_registry,
)

from examples.tori_py.microservices.events import (
    RELIABLE_INSTANCE_OPTIONS,
    EventModesController,
    EventModesModule,
    reliable_broadcast_root,
)
from examples.tori_py.microservices.policies import demonstrate_offline_deadline
from examples.tori_py.microservices.replicas import (
    call_multiple_services,
    run_competing_replicas,
)
from examples.tori_py.microservices.rpc_service import (
    CalculatorController,
    CalculatorModule,
    HybridApplicationModule,
    HybridReportController,
    create_hybrid_application,
)


def test_controller_examples_compile_without_endpoint_modules() -> None:
    registry = compile_service_handler_registry(
        ((ModuleId(CalculatorModule), CalculatorController),)
    )
    assert [plan.method for plan in registry.rpc_handlers] == ["add", "multiply"]

    hybrid = compile_service_handler_registry(
        ((ModuleId(HybridApplicationModule), HybridReportController),)
    )
    assert [plan.method for plan in hybrid.rpc_handlers] == ["refresh"]


def test_event_examples_cover_all_delivery_modes() -> None:
    registry = compile_service_handler_registry(
        ((ModuleId(EventModesController), EventModesController),)
    )
    assert {plan.mode for plan in registry.event_handlers} == {
        EventDispatchMode.SERVICE_POOL,
        EventDispatchMode.SINGLETON,
        EventDispatchMode.BROADCAST,
    }
    assert {plan.metadata.reliable for plan in registry.event_handlers} == {
        False,
        True,
    }
    assert RELIABLE_INSTANCE_OPTIONS.instance_id == "cache-consumer-1"

    class Factory:
        def create(self, identity, options):
            del identity, options
            raise AssertionError("example factory must not open resources")

    root = reliable_broadcast_root(Factory())
    assert isinstance(root, DeferredModule)
    materialized = root.factory()
    assert isinstance(materialized, ModuleSpec)
    provider = tuple(materialized.providers)[0]
    assert isinstance(provider, ValueProvider)
    assert isinstance(provider.value, MicroservicesRoot)
    assert provider.value.options == RELIABLE_INSTANCE_OPTIONS
    assert tuple(materialized.imports) == (EventModesModule,)


@pytest.mark.asyncio
async def test_competing_replica_example() -> None:
    calls = await run_competing_replicas(("one", "two", "three"))
    assert sum(calls.values()) == 3
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_offline_deadline_example() -> None:
    assert await demonstrate_offline_deadline()


@pytest.mark.asyncio
async def test_shared_cluster_calls_multiple_services() -> None:
    assert await call_multiple_services() == {
        "workers": "workers:item-1",
        "audit": "audit:item-1",
    }


@pytest.mark.asyncio
async def test_hybrid_application_composes_http_and_rpc() -> None:
    class Factory:
        def create(self, identity, options):
            del identity, options
            raise AssertionError("example factory must not open resources")

    application = await create_hybrid_application(Factory())
    assert application.state.value == "compiled"

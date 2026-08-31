"""Executable three-application system test for the distributed task tutorial."""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from tori_py import ApplicationState
from tori_py.starlette import StarletteAdapter
from tori_py.testing import TestingApplication as ToriTestingApplication
from tori_py.testing import TestingModule
from tori_py_microservices import (
    EventDispatcher,
    InMemoryBroker,
    MicroservicesModule,
    ServiceCluster,
    ServiceRuntime,
    TransportStatus,
)

from .audit.app import (
    AuditAppModule,
    AuditLog,
    audit_rabbit,
    audit_transport,
)
from .gateway.app import (
    GatewayAppModule,
    gateway_pipeline,
    gateway_rabbit,
    gateway_transport,
)
from .tasks.app import (
    TaskAppModule,
    task_rabbit,
    task_transport,
)
from .tasks.state import TaskMetrics
from .testing import InMemoryTransportModule


@pytest.mark.asyncio
async def test_distributed_task_system_preserves_the_http_contract() -> None:
    broker = InMemoryBroker()
    applications: list[ToriTestingApplication] = []
    audit_runtime: ServiceRuntime | None = None
    task_runtime: ServiceRuntime | None = None
    gateway_cluster: ServiceCluster | None = None

    try:
        audit_builder = TestingModule.create(AuditAppModule)
        audit_builder.replace_module(
            audit_rabbit,
            InMemoryTransportModule.for_root(broker, audit_transport),
        )
        audit = await audit_builder.compile()
        applications.append(audit)

        task_builder = TestingModule.create(TaskAppModule)
        task_builder.replace_module(
            task_rabbit,
            InMemoryTransportModule.for_root(broker, task_transport),
        )
        tasks = await task_builder.compile()
        applications.append(tasks)

        gateway_builder = TestingModule.create(GatewayAppModule)
        gateway_builder.replace_module(
            gateway_rabbit,
            InMemoryTransportModule.for_root(broker, gateway_transport),
        )
        gateway = await gateway_builder.compile(
            adapter=StarletteAdapter(),
            pipeline=gateway_pipeline,
        )
        applications.append(gateway)

        audit_log = cast(AuditLog, await audit.resolve(AuditLog))
        metrics = cast(TaskMetrics, await tasks.resolve(TaskMetrics))
        task_events = cast(EventDispatcher, await tasks.resolve(EventDispatcher))
        audit_runtime = cast(
            ServiceRuntime,
            await audit.resolve(
                ServiceRuntime,
                module=(MicroservicesModule, "default"),
            ),
        )
        task_runtime = cast(
            ServiceRuntime,
            await tasks.resolve(
                ServiceRuntime,
                module=(MicroservicesModule, "default"),
            ),
        )
        gateway_cluster = cast(
            ServiceCluster,
            await gateway.resolve(ServiceCluster),
        )

        async with gateway.http_client() as client:
            empty = await client.get("/tasks")
            assert empty.status_code == 200
            assert empty.json() == []

            for title in ("   ", "x" * 121):
                invalid_title = await client.post("/tasks", json={"title": title})
                _assert_problem(
                    invalid_title,
                    status_code=400,
                    title="Bad Request",
                    detail=(
                        "After trimming, the task title must contain 1-120 characters."
                    ),
                    instance="/tasks",
                )

            malformed = await client.post(
                "/tasks",
                content=b'{"title":',
                headers={"content-type": "application/json"},
            )
            _assert_problem(
                malformed,
                status_code=400,
                title="Bad Request",
                detail="Request body contains malformed JSON.",
                instance="/tasks",
            )

            missing = await client.post("/tasks", json={})
            _assert_validation_problem(
                missing,
                parameter="body",
                source="body",
                message="Object missing required field `title`",
            )

            unknown = await client.post(
                "/tasks",
                json={"title": "Hidden metadata", "unexpected": True},
            )
            _assert_validation_problem(
                unknown,
                parameter="body",
                source="body",
                message="Object contains unknown field `unexpected`",
            )

            invalid_path = await client.get("/tasks/not-an-integer")
            _assert_validation_problem(
                invalid_path,
                parameter="task_id",
                source="path",
                message="invalid literal for int() with base 10: 'not-an-integer'",
                instance="/tasks/not-an-integer",
            )

            created = await client.post(
                "/tasks",
                json={"title": "  Ship the distributed tutorial  "},
            )
            assert created.status_code == 201
            assert created.json() == {
                "id": 1,
                "title": "Ship the distributed tutorial",
            }

            second = await client.post("/tasks", json={"title": "Verify order"})
            assert second.status_code == 201
            assert second.json() == {"id": 2, "title": "Verify order"}

            listed = await client.get("/tasks")
            assert listed.status_code == 200
            assert listed.json() == [created.json(), second.json()]

            found = await client.get("/tasks/1")
            assert found.status_code == 200
            assert found.json() == created.json()

            missing = await client.get("/tasks/999")
            _assert_problem(
                missing,
                status_code=404,
                title="Not Found",
                detail="Task was not found.",
                instance="/tasks/999",
            )

        await metrics.wait_for_created(2, timeout=1)
        await audit_log.wait_for_deliveries(2, timeout=1)
        assert metrics.created == 2
        assert len(audit_log.entries) == 2
        assert audit_log.entries[0].task_id == 1

        first_event = audit_log.entries[0]
        await task_events.publish(
            "task-created",
            1,
            first_event,
            require_route=True,
        )
        await audit_log.wait_for_deliveries(3, timeout=1)
        assert audit_log.deliveries == 3
        assert audit_log.entries[0] == first_event
        assert len(audit_log.entries) == 2
    finally:
        for application in reversed(applications):
            await application.close()
        await broker.close()

    assert applications
    assert all(
        application.application.state is ApplicationState.STOPPED
        for application in applications
    )
    assert audit_runtime is not None and audit_runtime.transport is None
    assert task_runtime is not None and task_runtime.transport is None
    assert gateway_cluster is not None
    assert gateway_cluster.transport.status is TransportStatus.CLOSED


def _assert_validation_problem(
    response: httpx.Response,
    *,
    parameter: str,
    source: str,
    message: str,
    instance: str = "/tasks",
) -> None:
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": "Bad Request",
        "status": 400,
        "detail": "Validation failed.",
        "instance": instance,
        "errors": {
            "parameter": parameter,
            "source": source,
            "message": message,
        },
    }


def _assert_problem(
    response: httpx.Response,
    *,
    status_code: int,
    title: str,
    detail: str,
    instance: str,
) -> None:
    assert response.status_code == status_code
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": instance,
    }

"""Deterministic four-application system test for the Part 4 snapshot."""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from tori_py import ApplicationState
from tori_py.starlette import StarletteAdapter
from tori_py.testing import TestingApplication as ToriTestingApplication
from tori_py.testing import TestingModule
from tori_py_cqrs_event_sourcing_core import InMemoryEventStore
from tori_py_microservices import (
    InMemoryBroker,
    MicroservicesModule,
    ServiceCluster,
    ServiceRuntime,
    TransportStatus,
)
from tori_py_persistent_streams import (
    StreamPublisher,
    StreamRuntime,
    StreamRuntimeState,
)
from tori_py_persistent_streams_core import PublishOutcome, StoredRecord

from .audit.app import (
    AUDIT_GROUP,
    AuditAppModule,
    TaskAuditLog,
    audit_stream_adapter,
)
from .gateway.app import (
    GatewayAppModule,
    gateway_pipeline,
    gateway_rabbit,
    gateway_transport,
)
from .projection.app import (
    PROJECTION_GROUP,
    ProjectionAppModule,
    projection_rabbit,
    projection_stream_adapter,
    projection_transport,
)
from .projection.state import ProjectionCorruption, TaskProjectionState
from .streams import (
    TASK_EVENTS_ALIAS,
    TASK_EVENTS_PHYSICAL,
    TaskEventCodec,
    TaskEventRecordV1,
)
from .tasks.app import (
    TaskAppModule,
    TaskPersistenceModule,
    task_rabbit,
    task_stream_adapter,
    task_transport,
)
from .tasks.schemas import TASK_CREATED_ALIAS, TASK_RENAMED_ALIAS
from .testing import (
    InMemoryTransportModule,
    SharedPersistentStreamsModule,
    SharedPersistentStreamTestContext,
)


@pytest.mark.asyncio
async def test_event_sourced_task_system_is_eventually_consistent() -> None:
    broker = InMemoryBroker()
    streams = SharedPersistentStreamTestContext()
    applications: list[ToriTestingApplication] = []
    service_runtimes: list[ServiceRuntime] = []
    stream_runtimes: list[StreamRuntime] = []
    gateway_cluster: ServiceCluster | None = None
    try:
        audit_builder = TestingModule.create(AuditAppModule)
        audit_builder.replace_module(
            audit_stream_adapter,
            SharedPersistentStreamsModule.for_root(
                streams.factory(),
                key="audit",
            ),
        )
        audit = await audit_builder.compile()
        applications.append(audit)

        projection_builder = TestingModule.create(ProjectionAppModule)
        projection_builder.replace_module(
            projection_rabbit,
            InMemoryTransportModule.for_root(broker, projection_transport),
        )
        projection_builder.replace_module(
            projection_stream_adapter,
            SharedPersistentStreamsModule.for_root(
                streams.factory(),
                key="projection",
            ),
        )
        projection = await projection_builder.compile()
        applications.append(projection)

        task_builder = TestingModule.create(TaskAppModule)
        task_builder.replace_module(
            task_rabbit,
            InMemoryTransportModule.for_root(broker, task_transport),
        )
        task_builder.replace_module(
            task_stream_adapter,
            SharedPersistentStreamsModule.for_root(
                streams.factory(),
                key="tasks",
            ),
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

        audit_log = cast(TaskAuditLog, await audit.resolve(TaskAuditLog))
        projection_state = cast(
            TaskProjectionState,
            await projection.resolve(TaskProjectionState),
        )
        event_store = cast(
            InMemoryEventStore,
            await tasks.resolve(
                InMemoryEventStore,
                module=TaskPersistenceModule,
            ),
        )
        publisher = cast(StreamPublisher, await tasks.resolve(StreamPublisher))

        task_service_runtime = cast(
            ServiceRuntime,
            await tasks.resolve(
                ServiceRuntime,
                module=(MicroservicesModule, "default"),
            ),
        )
        projection_service_runtime = cast(
            ServiceRuntime,
            await projection.resolve(
                ServiceRuntime,
                module=(MicroservicesModule, "default"),
            ),
        )
        service_runtimes.extend((task_service_runtime, projection_service_runtime))
        stream_runtimes.extend(
            (
                cast(StreamRuntime, await audit.resolve(StreamRuntime)),
                cast(StreamRuntime, await projection.resolve(StreamRuntime)),
                cast(StreamRuntime, await tasks.resolve(StreamRuntime)),
            )
        )
        gateway_cluster = cast(ServiceCluster, await gateway.resolve(ServiceCluster))

        async with gateway.http_client() as client:
            empty = await client.get("/tasks")
            assert empty.status_code == 200
            assert empty.json() == []

            for title in ("   ", "x" * 121):
                invalid = await client.post("/tasks", json={"title": title})
                _assert_problem(
                    invalid,
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
            _assert_validation_problem(
                await client.post("/tasks", json={}),
                parameter="body",
                source="body",
                message="Object missing required field `title`",
            )
            _assert_validation_problem(
                await client.post(
                    "/tasks",
                    json={"title": "Strict", "unexpected": True},
                ),
                parameter="body",
                source="body",
                message="Object contains unknown field `unexpected`",
            )
            _assert_validation_problem(
                await client.get("/tasks/not-an-integer"),
                parameter="task_id",
                source="path",
                message="invalid literal for int() with base 10: 'not-an-integer'",
                instance="/tasks/not-an-integer",
            )

            created = await client.post(
                "/tasks",
                json={"title": "  Ship the event-sourced tutorial  "},
            )
            assert created.status_code == 201
            assert created.json() == {
                "id": 1,
                "title": "Ship the event-sourced tutorial",
            }
            second = await client.post(
                "/tasks",
                json={"title": "Second partition candidate"},
            )
            assert second.status_code == 201
            assert second.json() == {
                "id": 2,
                "title": "Second partition candidate",
            }
            third = await client.post(
                "/tasks",
                json={"title": "Cross the physical partition"},
            )
            assert third.status_code == 201
            assert third.json() == {
                "id": 3,
                "title": "Cross the physical partition",
            }

            await projection_state.wait_for_version(1, 1, timeout=1)
            await projection_state.wait_for_version(2, 1, timeout=1)
            await projection_state.wait_for_version(3, 1, timeout=1)
            await audit_log.wait_for_deliveries(3, timeout=1)

            assert (await client.get("/tasks")).json() == [
                created.json(),
                second.json(),
                third.json(),
            ]
            assert (await client.get("/tasks/1")).json() == created.json()
            _assert_problem(
                await client.get("/tasks/999"),
                status_code=404,
                title="Not Found",
                detail="Task was not found.",
                instance="/tasks/999",
            )

            invalid_patch = await client.patch(
                "/tasks/1",
                json={"title": "   "},
            )
            _assert_problem(
                invalid_patch,
                status_code=400,
                title="Bad Request",
                detail=(
                    "After trimming, the task title must contain 1-120 characters."
                ),
                instance="/tasks/1",
            )
            _assert_validation_problem(
                await client.patch(
                    "/tasks/not-an-integer",
                    json={"title": "Valid"},
                ),
                parameter="task_id",
                source="path",
                message="invalid literal for int() with base 10: 'not-an-integer'",
                instance="/tasks/not-an-integer",
            )
            _assert_validation_problem(
                await client.patch(
                    "/tasks/1",
                    json={"title": "Strict patch", "unexpected": True},
                ),
                parameter="body",
                source="body",
                message="Object contains unknown field `unexpected`",
                instance="/tasks/1",
            )
            _assert_problem(
                await client.patch("/tasks/999", json={"title": "Missing"}),
                status_code=404,
                title="Not Found",
                detail="Task was not found.",
                instance="/tasks/999",
            )

            renamed = await client.patch(
                "/tasks/1",
                json={"title": "  Publish directly to the stream  "},
            )
            assert renamed.status_code == 200
            assert renamed.json() == {
                "id": 1,
                "title": "Publish directly to the stream",
            }

            await projection_state.wait_for_version(1, 2, timeout=1)
            await audit_log.wait_for_deliveries(4, timeout=1)
            assert (await client.get("/tasks/1")).json() == renamed.json()
            assert (await client.get("/tasks")).json() == [
                renamed.json(),
                second.json(),
                third.json(),
            ]

            stored_events = await event_store.read_all(limit=10)
            assert [event.event.encoded.event_type for event in stored_events] == [
                TASK_CREATED_ALIAS,
                TASK_CREATED_ALIAS,
                TASK_CREATED_ALIAS,
                TASK_RENAMED_ALIAS,
            ]
            assert [event.event.encoded.schema_version for event in stored_events] == [
                1,
                1,
                1,
                1,
            ]
            assert [event.stream_version for event in stored_events] == [1, 1, 1, 2]

            stream_records = await _all_stream_records(streams)
            assert {record.partition for record in stream_records} == {0, 1}
            decoded = [
                TaskEventCodec().decode(record.payload, TaskEventRecordV1)
                for record in stream_records
            ]
            decoded.sort(key=lambda record: (record.task_id, record.aggregate_version))
            assert [record.kind for record in decoded] == [
                "task-created",
                "task-renamed",
                "task-created",
                "task-created",
            ]
            assert [record.task_id for record in decoded] == [1, 1, 2, 3]
            assert [record.aggregate_version for record in decoded] == [1, 2, 1, 1]
            assert {record.event_id for record in decoded} == {
                event.event_id for event in stored_events
            }
            assert {record.record_id for record in stream_records} == {
                payload.event_id for payload in decoded
            }

            first = decoded[0]
            duplicate = await publisher.publish(
                TASK_EVENTS_ALIAS,
                first,
                record_id=first.event_id,
            )
            assert duplicate.outcome is PublishOutcome.CONFIRMED
            await projection_state.wait_for_deliveries(5, timeout=1)
            await audit_log.wait_for_deliveries(5, timeout=1)
            assert projection_state.event_count == 4
            assert projection_state.get(1).title == "Publish directly to the stream"
            assert len(audit_log.entries) == 4
            assert audit_log.deliveries == 5

            audit_groups = {
                status.consumer_group for status in stream_runtimes[0].statuses
            }
            projection_groups = {
                status.consumer_group for status in stream_runtimes[1].statuses
            }
            assert audit_groups == {AUDIT_GROUP}
            assert projection_groups == {PROJECTION_GROUP}

            conflicting = TaskEventRecordV1(
                first.event_id,
                first.kind,
                first.task_id,
                "Conflicting duplicate",
                first.aggregate_version,
                first.occurred_at,
            )
            with pytest.raises(ProjectionCorruption):
                await projection_state.apply(conflicting)
            _assert_problem(
                await client.get("/tasks"),
                status_code=503,
                title="Service Unavailable",
                detail="Task projection is unavailable.",
                instance="/tasks",
            )
    finally:
        for application in reversed(applications):
            await application.close()
        await broker.close()
        await streams.close()

    assert applications
    assert all(
        application.application.state is ApplicationState.STOPPED
        for application in applications
    )
    assert all(runtime.transport is None for runtime in service_runtimes)
    assert all(
        runtime.state is StreamRuntimeState.CLOSED for runtime in stream_runtimes
    )
    assert gateway_cluster is not None
    assert gateway_cluster.transport.status is TransportStatus.CLOSED
    assert streams.close_count == 1


async def _all_stream_records(
    context: SharedPersistentStreamTestContext,
) -> list[StoredRecord]:
    records: list[StoredRecord] = []
    for partition in range(2):
        page = await context.log.read(
            TASK_EVENTS_PHYSICAL,
            partition,
            0,
            100,
        )
        records.extend(page.records)
    return records


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

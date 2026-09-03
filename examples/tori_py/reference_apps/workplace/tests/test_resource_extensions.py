"""Specifications for resource metadata, lifecycle, and filtered discovery."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tori_py_microservices import PublicRpcError
from tori_py_sqlalchemy import EntityManager

from examples.tori_py.reference_apps.workplace.common.contracts import (
    CreateResource,
    CreateResourceRpc,
    OfficePolicyUpdate,
    Principal,
    UpdateResource,
    UpdateResourceRpc,
)
from examples.tori_py.reference_apps.workplace.spaces.app import (
    Base,
    CreateResourceCommand,
    CreateResourceHandler,
    GetOfficePolicyHandler,
    GetOfficePolicyQuery,
    GetResourcesHandler,
    GetResourcesQuery,
    ListResourcesHandler,
    ListResourcesQuery,
    OfficePolicyRepository,
    OfficePolicyRow,
    ResourceEquipmentRepository,
    ResourceEquipmentRow,
    ResourceRepository,
    ResourceRow,
    SpacesController,
    UpdateOfficePolicyCommand,
    UpdateOfficePolicyHandler,
    UpdateResourceCommand,
    UpdateResourceHandler,
)


@pytest.fixture
async def resource_components():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    entities = EntityManager(async_sessionmaker(engine, expire_on_commit=False))
    resources = ResourceRepository(ResourceRow, entities)
    resource_equipment = ResourceEquipmentRepository(ResourceEquipmentRow, entities)
    policies = OfficePolicyRepository(OfficePolicyRow, entities)
    try:
        yield (
            resources,
            resource_equipment,
            policies,
            CreateResourceHandler(entities, resources, resource_equipment),
            UpdateResourceHandler(entities, resources, resource_equipment),
            ListResourcesHandler(resources),
            UpdateOfficePolicyHandler(entities, policies),
            GetOfficePolicyHandler(policies),
        )
    finally:
        await engine.dispose()


def resource_command(
    *,
    tenant_id: str = "tenant-north",
    office_id: str = "office-north",
    floor_id: str = "floor-3",
    name: str = "Focus desk",
    kind: str = "desk",
    x: int = 100,
    y: int = 200,
    equipment: tuple[str, ...] = (),
    capacity: int = 1,
) -> CreateResourceCommand:
    return CreateResourceCommand(
        tenant_id,
        office_id,
        floor_id,
        name,
        kind,
        x,
        y,
        equipment,
        capacity,
    )


@pytest.mark.asyncio
async def test_create_normalizes_equipment_and_persists_metadata_defaults(
    resource_components,
) -> None:
    resources, _, _, create, _, _, _, _ = resource_components
    defaulted = await create.handle(
        CreateResourceCommand(
            "tenant-north",
            "office-north",
            "floor-3",
            "Default desk",
            "desk",
            10,
            20,
        )
    )

    created = await create.handle(
        resource_command(equipment=(" Monitor ", "WHITEBOARD", "monitor"), capacity=4)
    )
    row = await resources.tenant_resource("tenant-north", created.id)

    assert defaulted.equipment == ()
    assert defaulted.capacity == 1
    assert defaulted.active is True
    assert created.equipment == ("monitor", "whiteboard")
    assert created.capacity == 4
    assert created.active is True
    assert row is not None
    assert json.loads(row.equipment_json) == ["monitor", "whiteboard"]
    assert row.capacity == 4
    assert row.active is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("equipment", "capacity"),
    [(("",), 1), (("monitor",), 0)],
)
async def test_create_rejects_invalid_resource_metadata(
    resource_components, equipment: tuple[str, ...], capacity: int
) -> None:
    resources, _, _, create, _, _, _, _ = resource_components

    with pytest.raises(ValueError):
        await create.handle(resource_command(equipment=equipment, capacity=capacity))

    assert await resources.count() == 0


@pytest.mark.asyncio
async def test_list_combines_location_kind_equipment_and_capacity_filters_with_and(
    resource_components,
) -> None:
    _, _, _, create, _, list_resources, _, _ = resource_components
    boardroom = await create.handle(
        resource_command(
            name="Boardroom",
            kind="room",
            equipment=("screen", "whiteboard"),
            capacity=8,
        )
    )
    await create.handle(
        resource_command(
            name="Screen room", kind="room", equipment=("screen",), capacity=8
        )
    )
    await create.handle(
        resource_command(
            name="Small boardroom",
            kind="room",
            equipment=("whiteboard",),
            capacity=4,
        )
    )
    await create.handle(
        resource_command(
            name="Other office",
            office_id="office-south",
            kind="room",
            equipment=("screen", "whiteboard"),
            capacity=8,
        )
    )

    listed = await list_resources.handle(
        ListResourcesQuery(
            tenant_id="tenant-north",
            office_id="office-north",
            floor_id="floor-3",
            kind="room",
            equipment=("whiteboard", "screen"),
            min_capacity=8,
        )
    )

    assert [resource.id for resource in listed] == [boardroom.id]


@pytest.mark.asyncio
async def test_resource_batch_lookup_is_bounded_and_tenant_scoped(
    resource_components,
) -> None:
    resources, _, _, create, _, _, _, _ = resource_components
    north = await create.handle(resource_command(name="North desk"))
    south = await create.handle(
        resource_command(tenant_id="tenant-south", name="South desk")
    )
    lookup = GetResourcesHandler(resources)

    result = await lookup.handle(
        GetResourcesQuery("tenant-north", (south.id, north.id))
    )

    assert [resource.id for resource in result] == [north.id]
    with pytest.raises(ValueError, match="batch"):
        await lookup.handle(
            GetResourcesQuery(
                "tenant-north", tuple(f"resource-{index}" for index in range(101))
            )
        )


@pytest.mark.asyncio
async def test_deactivation_is_soft_and_hidden_unless_inactive_resources_are_requested(
    resource_components,
) -> None:
    resources, _, _, create, update, list_resources, _, _ = resource_components
    created = await create.handle(resource_command())

    await update.handle(
        UpdateResourceCommand(
            tenant_id="tenant-north",
            resource_id=created.id,
            name="Focus desk",
            kind="desk",
            x=100,
            y=200,
            equipment=(),
            capacity=1,
            active=False,
        )
    )

    assert (
        await list_resources.handle(ListResourcesQuery(tenant_id="tenant-north")) == []
    )
    inactive = await list_resources.handle(
        ListResourcesQuery(tenant_id="tenant-north", include_inactive=True)
    )
    row = await resources.tenant_resource("tenant-north", created.id)
    assert [resource.id for resource in inactive] == [created.id]
    assert row is not None
    assert row.active is False


@pytest.mark.asyncio
async def test_update_is_tenant_scoped_and_can_reactivate_a_resource(
    resource_components,
) -> None:
    _, _, _, create, update, list_resources, _, _ = resource_components
    created = await create.handle(resource_command())
    await update.handle(
        UpdateResourceCommand(
            tenant_id="tenant-north",
            resource_id=created.id,
            name="Focus desk",
            kind="desk",
            x=100,
            y=200,
            equipment=(),
            capacity=1,
            active=False,
        )
    )

    with pytest.raises(LookupError):
        await update.handle(
            UpdateResourceCommand(
                tenant_id="tenant-south",
                resource_id=created.id,
                name="Wrong tenant",
                kind="desk",
                x=100,
                y=200,
                equipment=(),
                capacity=1,
                active=True,
            )
        )

    restored = await update.handle(
        UpdateResourceCommand(
            tenant_id="tenant-north",
            resource_id=created.id,
            name="Restored desk",
            kind="desk",
            x=100,
            y=200,
            equipment=("Monitor",),
            capacity=2,
            active=True,
        )
    )

    assert restored.name == "Restored desk"
    assert restored.equipment == ("monitor",)
    listed = await list_resources.handle(ListResourcesQuery("tenant-north"))
    assert [resource.id for resource in listed] == [created.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ("create", "update"))
async def test_resource_rpc_maps_domain_validation_to_invalid_request(
    operation: str,
) -> None:
    class RejectingCommands:
        async def execute(self, command: object) -> None:
            del command
            raise ValueError("resource metadata is invalid")

    principal = Principal("tenant-north", "admin-1", ("facilities-admin",))
    controller = SpacesController(
        RejectingCommands(),
        object(),
        object(),  # type: ignore[arg-type]
    )

    with pytest.raises(PublicRpcError, match="metadata is invalid") as error:
        if operation == "create":
            await controller.create_resource(
                CreateResourceRpc(
                    principal,
                    CreateResource("office-north", "floor-3", "Desk", "desk", 10, 20),
                )
            )
        else:
            await controller.update_resource(
                UpdateResourceRpc(principal, "desk-17", UpdateResource(capacity=2))
            )

    assert error.value.code == "invalid_request"


@pytest.mark.asyncio
async def test_equipment_filtering_is_database_side_and_pages_are_stable(
    resource_components,
) -> None:
    resources, _, _, create, _, list_resources, _, _ = resource_components
    first = await create.handle(resource_command(name="A", equipment=("monitor",)))
    second = await create.handle(resource_command(name="B", equipment=("monitor",)))
    await create.handle(resource_command(name="C", equipment=("whiteboard",)))

    first_row = await resources.tenant_resource("tenant-north", first.id)
    assert first_row is not None
    first_row.equipment_json = "[]"

    listed = await list_resources.handle(
        ListResourcesQuery(tenant_id="tenant-north", equipment=("monitor",))
    )
    page = await list_resources.handle(
        ListResourcesQuery(
            tenant_id="tenant-north", equipment=("monitor",), offset=1, limit=1
        )
    )

    expected_ids = sorted((first.id, second.id))
    assert [resource.id for resource in listed] == expected_ids
    assert [resource.id for resource in page] == expected_ids[1:]
    with pytest.raises(ValueError, match="outside the supported range"):
        await list_resources.handle(
            ListResourcesQuery(tenant_id="tenant-north", offset=10_001)
        )


@pytest.mark.asyncio
async def test_office_policy_is_tenant_scoped_editable_and_validated(
    resource_components,
) -> None:
    _, _, policies, _, _, _, update_policy, get_policy = resource_components
    command = UpdateOfficePolicyCommand(
        tenant_id="tenant-north",
        office_id="office-north",
        policy=OfficePolicyUpdate(
            time_zone="Europe/London",
            opens_at="08:30",
            closes_at="18:00",
            weekdays=(0, 1, 2, 3, 4),
        ),
    )

    updated = await update_policy.handle(command)

    assert updated.office_id == "office-north"
    assert updated.opens_at == "08:30"
    assert (
        await get_policy.handle(GetOfficePolicyQuery("tenant-north", "office-north"))
        == updated
    )
    assert await policies.tenant_policy("tenant-south", "office-north") is None

    with pytest.raises(ValueError, match="time zone"):
        await update_policy.handle(
            UpdateOfficePolicyCommand(
                "tenant-north",
                "invalid-office",
                OfficePolicyUpdate("Mars/Olympus", "08:00", "18:00", (0,)),
            )
        )

    with pytest.raises(ValueError, match="hours"):
        await update_policy.handle(
            UpdateOfficePolicyCommand(
                "tenant-north",
                "invalid-office",
                OfficePolicyUpdate("UTC", "18:00", "08:00", (0,)),
            )
        )

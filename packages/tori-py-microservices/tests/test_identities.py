from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from typing import cast
from uuid import UUID, uuid4

import pytest
from tori_py_microservices import (
    EventIdentity,
    EventSubscription,
    IdentityValidationError,
    MessageLimits,
    MicroservicesOptions,
    ReplyRoute,
    RpcTarget,
    ServiceIdentity,
    WireValidationError,
    require_future_deadline,
    require_utc,
    require_uuid,
)


def test_service_and_message_identities_are_immutable_and_composable() -> None:
    service = ServiceIdentity("kinker", "members", 1)
    target = RpcTarget(service, "resolve-profile", 1)
    event = EventIdentity(service, "profile-created", 1)

    assert service.label == "kinker.members.v1"
    assert target.routing_key == "kinker.members.v1.resolve-profile"
    assert event.exchange_name == "tori_py.events.kinker.members.v1"
    assert event.routing_key == "profile-created.v1"
    with pytest.raises(FrozenInstanceError):
        attribute = "name"
        setattr(service, attribute, "other")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("namespace", "Kinker"),
        ("name", "members.all"),
        ("name", "#"),
        ("contract_version", 0),
        ("contract_version", True),
    ],
)
def test_service_identity_rejects_invalid_fields(field: str, value: object) -> None:
    values: dict[str, object] = {
        "namespace": "kinker",
        "name": "members",
        "contract_version": 1,
    }
    values[field] = value
    with pytest.raises(IdentityValidationError):
        ServiceIdentity(**values)  # type: ignore[arg-type]


def test_composed_names_and_reply_routes_are_bounded() -> None:
    long_service = "a" * 63
    with pytest.raises(IdentityValidationError):
        RpcTarget(ServiceIdentity(long_service, long_service, 10**200), "method", 1)

    generated = ReplyRoute.generate()
    assert len(generated.value) == 38
    assert generated.value.startswith("reply.")
    with pytest.raises(WireValidationError):
        ReplyRoute("reply.not-a-token")


@pytest.mark.parametrize("field", ["subscription", "instance_id"])
def test_event_route_aliases_use_the_canonical_grammar(field: str) -> None:
    values: dict[str, object] = {
        "identity": EventIdentity(
            ServiceIdentity("kinker", "members", 1), "profile-created", 1
        ),
        "mode": "broadcast",
        "subscription": "profile-cache",
        "destination": ServiceIdentity("kinker", "members", 1),
        "instance_id": "replica-a",
    }
    values[field] = "Invalid.Alias"

    with pytest.raises(IdentityValidationError):
        EventSubscription(**values)  # type: ignore[arg-type]

    generated = EventSubscription(
        values["identity"],
        "broadcast",
        "profile-cache",
        destination=values["destination"],
    )
    assert generated.instance_id is not None
    assert generated.instance_id.startswith("instance-")


def test_options_validate_instance_aliases() -> None:
    with pytest.raises(IdentityValidationError):
        MicroservicesOptions(instance_id="Replica.A")


def test_message_limits_and_time_values_are_explicitly_validated() -> None:
    assert MessageLimits().max_envelope_bytes == 1024 * 1024
    with pytest.raises(WireValidationError):
        MessageLimits(max_header_count=0)
    with pytest.raises(WireValidationError):
        require_utc(datetime.now())
    with pytest.raises(WireValidationError):
        require_utc(datetime.now(timezone(timedelta(hours=1))))

    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    deadline_at = created_at + timedelta(seconds=1)
    assert require_future_deadline(created_at, deadline_at) == (
        created_at,
        deadline_at,
    )
    with pytest.raises(WireValidationError):
        require_future_deadline(created_at, created_at)
    assert require_uuid(uuid4()).version in {1, 3, 4, 5, 6, 7, 8}
    with pytest.raises(WireValidationError):
        require_uuid(cast(UUID, "not-a-uuid"))

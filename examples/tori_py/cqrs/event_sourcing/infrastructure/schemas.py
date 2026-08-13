"""Stable JSON event schemas and a historical member-event upcaster."""

import json
from collections.abc import Callable

from tori_py_cqrs_core import Event
from tori_py_cqrs_event_sourcing_core import (
    EventSchema,
    EventSchemaRegistry,
    EventSourcingLimits,
)

from examples.tori_py.cqrs.event_sourcing.domain.group import (
    GroupCreated,
    MemberJoined,
    MembershipRejected,
    MembershipRequested,
    ModeratorGranted,
)
from examples.tori_py.cqrs.event_sourcing.domain.member import (
    DisplayNameChanged,
    MemberRegistered,
    MemberSuspended,
)
from examples.tori_py.cqrs.event_sourcing.domain.post import (
    PostEdited,
    PostHidden,
    PostPublished,
)
from examples.tori_py.cqrs.event_sourcing.domain.shared import GroupAccess, Visibility


def _encode(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _decode(payload: bytes) -> dict[str, object]:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("event payload must be an object")
    return value


def _int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("event field must be an integer")
    return value


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("event field must be a string")
    return value


def _schema[EventT: Event](
    alias: str,
    event_type: type[EventT],
    encoder: Callable[[EventT], dict[str, object]],
    decoder: Callable[[dict[str, object]], EventT],
    *,
    version: int = 1,
    upcasters=None,
) -> EventSchema[EventT]:
    return EventSchema(
        alias,
        version,
        event_type,
        lambda event: _encode(encoder(event)),
        lambda payload: decoder(_decode(payload)),
        upcasters={} if upcasters is None else upcasters,
    )


def _upcast_member_registered_v1(payload: bytes) -> bytes:
    value = _decode(payload)
    value["visibility"] = Visibility.MEMBERS.value
    return _encode(value)


def build_schemas(
    limits: EventSourcingLimits | None = None,
) -> EventSchemaRegistry:
    """Build and freeze every stable event schema used by the project."""

    registry = EventSchemaRegistry(limits=limits)
    registry.register(
        _schema(
            "community.member-registered",
            MemberRegistered,
            lambda event: {
                "handle": event.handle,
                "display_name": event.display_name,
                "visibility": event.visibility.value,
            },
            lambda value: MemberRegistered(
                handle=_str(value["handle"]),
                display_name=_str(value["display_name"]),
                visibility=Visibility(_str(value["visibility"])),
            ),
            version=2,
            upcasters={1: _upcast_member_registered_v1},
        )
    )
    registry.register(
        _schema(
            "community.member-display-name-changed",
            DisplayNameChanged,
            lambda event: {"display_name": event.display_name},
            lambda value: DisplayNameChanged(_str(value["display_name"])),
        )
    )
    registry.register(
        _schema(
            "community.member-suspended",
            MemberSuspended,
            lambda event: {"actor_id": event.actor_id, "reason": event.reason},
            lambda value: MemberSuspended(
                actor_id=_int(value["actor_id"]),
                reason=_str(value["reason"]),
            ),
        )
    )
    registry.register(
        _schema(
            "community.group-created",
            GroupCreated,
            lambda event: {
                "owner_id": event.owner_id,
                "name": event.name,
                "access": event.access.value,
            },
            lambda value: GroupCreated(
                owner_id=_int(value["owner_id"]),
                name=_str(value["name"]),
                access=GroupAccess(_str(value["access"])),
            ),
        )
    )
    registry.register(
        _schema(
            "community.membership-requested",
            MembershipRequested,
            lambda event: {"member_id": event.member_id},
            lambda value: MembershipRequested(_int(value["member_id"])),
        )
    )
    registry.register(
        _schema(
            "community.member-joined",
            MemberJoined,
            lambda event: {
                "member_id": event.member_id,
                "approved_by": event.approved_by,
            },
            lambda value: MemberJoined(
                member_id=_int(value["member_id"]),
                approved_by=(
                    None if value["approved_by"] is None else _int(value["approved_by"])
                ),
            ),
        )
    )
    registry.register(
        _schema(
            "community.membership-rejected",
            MembershipRejected,
            lambda event: {
                "member_id": event.member_id,
                "reviewed_by": event.reviewed_by,
                "reason": event.reason,
            },
            lambda value: MembershipRejected(
                member_id=_int(value["member_id"]),
                reviewed_by=_int(value["reviewed_by"]),
                reason=_str(value["reason"]),
            ),
        )
    )
    registry.register(
        _schema(
            "community.moderator-granted",
            ModeratorGranted,
            lambda event: {
                "member_id": event.member_id,
                "granted_by": event.granted_by,
            },
            lambda value: ModeratorGranted(
                member_id=_int(value["member_id"]),
                granted_by=_int(value["granted_by"]),
            ),
        )
    )
    registry.register(
        _schema(
            "community.post-published",
            PostPublished,
            lambda event: {
                "group_id": event.group_id,
                "author_id": event.author_id,
                "title": event.title,
                "content_ref": event.content_ref,
            },
            lambda value: PostPublished(
                group_id=_int(value["group_id"]),
                author_id=_int(value["author_id"]),
                title=_str(value["title"]),
                content_ref=_int(value["content_ref"]),
            ),
        )
    )
    registry.register(
        _schema(
            "community.post-edited",
            PostEdited,
            lambda event: {
                "actor_id": event.actor_id,
                "title": event.title,
                "content_ref": event.content_ref,
            },
            lambda value: PostEdited(
                actor_id=_int(value["actor_id"]),
                title=_str(value["title"]),
                content_ref=_int(value["content_ref"]),
            ),
        )
    )
    registry.register(
        _schema(
            "community.post-hidden",
            PostHidden,
            lambda event: {
                "moderator_id": event.moderator_id,
                "reason": event.reason,
            },
            lambda value: PostHidden(
                moderator_id=_int(value["moderator_id"]),
                reason=_str(value["reason"]),
            ),
        )
    )
    return registry.freeze()


__all__ = ["build_schemas"]

"""Group aggregate, membership policy, and moderation authority."""

from dataclasses import dataclass

from cqrs_core import Event
from cqrs_event_sourcing import AggregateRoot

from examples.nestpy.cqrs.event_sourcing.domain.shared import (
    AccessDeniedError,
    DomainValidationError,
    GroupAccess,
    require_text,
)


@dataclass(frozen=True, slots=True)
class GroupCreated(Event):
    owner_id: int
    name: str
    access: GroupAccess


@dataclass(frozen=True, slots=True)
class MembershipRequested(Event):
    member_id: int


@dataclass(frozen=True, slots=True)
class MemberJoined(Event):
    member_id: int
    approved_by: int | None


@dataclass(frozen=True, slots=True)
class MembershipRejected(Event):
    member_id: int
    reviewed_by: int
    reason: str


@dataclass(frozen=True, slots=True)
class ModeratorGranted(Event):
    member_id: int
    granted_by: int


class Group(AggregateRoot[int]):
    """Membership boundary used for posting and moderation authorization."""

    def __init__(self, group_id: int) -> None:
        super().__init__(group_id)
        self.owner_id = 0
        self.name = ""
        self.access = GroupAccess.PRIVATE
        self.members: set[int] = set()
        self.moderators: set[int] = set()
        self.pending_members: set[int] = set()

    def create(self, *, owner_id: int, name: str, access: GroupAccess) -> None:
        self.raise_event(
            GroupCreated(
                owner_id=owner_id,
                name=require_text(name, field="group name", maximum=100),
                access=access,
            )
        )

    def request_membership(self, *, member_id: int) -> None:
        if member_id in self.members:
            return
        if member_id in self.pending_members:
            raise DomainValidationError("membership request is already pending")
        if self.access is GroupAccess.PUBLIC:
            self.raise_event(MemberJoined(member_id, None))
        else:
            self.raise_event(MembershipRequested(member_id))

    def review_membership(
        self,
        *,
        actor_id: int,
        member_id: int,
        approve: bool,
        reason: str | None = None,
    ) -> None:
        self.require_moderator(actor_id)
        if member_id not in self.pending_members:
            raise DomainValidationError("membership request is not pending")
        if approve:
            self.raise_event(MemberJoined(member_id, actor_id))
            return
        self.raise_event(
            MembershipRejected(
                member_id=member_id,
                reviewed_by=actor_id,
                reason=require_text(
                    reason or "not approved",
                    field="rejection reason",
                    maximum=240,
                ),
            )
        )

    def require_pending(self, member_id: int) -> None:
        if member_id not in self.pending_members:
            raise DomainValidationError("membership request is not pending")

    def grant_moderator(self, *, actor_id: int, member_id: int) -> None:
        if actor_id != self.owner_id:
            raise AccessDeniedError("only the group owner can grant moderation")
        if member_id not in self.members:
            raise DomainValidationError("moderator must already be a member")
        if member_id not in self.moderators:
            self.raise_event(ModeratorGranted(member_id, actor_id))

    def require_member(self, member_id: int) -> None:
        if member_id not in self.members:
            raise AccessDeniedError("group membership is required")

    def require_moderator(self, member_id: int) -> None:
        if member_id not in self.moderators:
            raise AccessDeniedError("group moderator permission is required")

    def _apply(self, event: Event) -> None:
        match event:
            case GroupCreated(owner_id=owner_id, name=name, access=access):
                self.owner_id = owner_id
                self.name = name
                self.access = access
                self.members.add(owner_id)
                self.moderators.add(owner_id)
            case MembershipRequested(member_id=member_id):
                self.pending_members.add(member_id)
            case MemberJoined(member_id=member_id):
                self.pending_members.discard(member_id)
                self.members.add(member_id)
            case MembershipRejected(member_id=member_id):
                self.pending_members.discard(member_id)
            case ModeratorGranted(member_id=member_id):
                self.moderators.add(member_id)
            case _:
                raise AssertionError(f"unknown group event: {event!r}")


__all__ = [
    "Group",
    "GroupCreated",
    "MemberJoined",
    "MembershipRejected",
    "MembershipRequested",
    "ModeratorGranted",
]

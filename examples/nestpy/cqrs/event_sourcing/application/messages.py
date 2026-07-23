"""Typed command/query contracts and read-model DTOs."""

from dataclasses import dataclass

import msgspec
from cqrs_core import Command, Query

from examples.nestpy.cqrs.event_sourcing.domain.shared import GroupAccess, Visibility


class MemberView(msgspec.Struct, frozen=True):
    id: int
    handle: str
    display_name: str
    visibility: Visibility
    suspended: bool


class GroupView(msgspec.Struct, frozen=True):
    id: int
    owner_id: int
    name: str
    access: GroupAccess
    member_count: int
    pending_count: int
    members: tuple[int, ...]
    moderators: tuple[int, ...]
    pending_members: tuple[int, ...]


class PostView(msgspec.Struct, frozen=True):
    id: int
    group_id: int
    author_id: int
    title: str
    body: str | None
    hidden: bool
    moderation_reason: str | None


class MembershipRequestView(msgspec.Struct, frozen=True):
    group_id: int
    status: str


class RegisteredMemberView(msgspec.Struct, frozen=True):
    member: MemberView
    access_token: str


@dataclass(frozen=True, slots=True)
class RegisterMember(Command[MemberView]):
    handle: str
    display_name: str
    visibility: Visibility


@dataclass(frozen=True, slots=True)
class ChangeDisplayName(Command[MemberView]):
    actor_id: int
    member_id: int
    display_name: str


@dataclass(frozen=True, slots=True)
class SuspendMember(Command[MemberView]):
    actor_id: int
    member_id: int
    reason: str


@dataclass(frozen=True, slots=True)
class CreateGroup(Command[GroupView]):
    actor_id: int
    name: str
    access: GroupAccess


@dataclass(frozen=True, slots=True)
class JoinGroup(Command[GroupView | MembershipRequestView]):
    actor_id: int
    group_id: int


@dataclass(frozen=True, slots=True)
class ReviewMembership(Command[GroupView]):
    actor_id: int
    group_id: int
    member_id: int
    approve: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PublishPost(Command[PostView]):
    actor_id: int
    group_id: int
    title: str
    body: str


@dataclass(frozen=True, slots=True)
class HidePost(Command[PostView]):
    actor_id: int
    group_id: int
    post_id: int
    reason: str


@dataclass(frozen=True, slots=True)
class GetMember(Query[MemberView]):
    member_id: int
    viewer_id: int | None


@dataclass(frozen=True, slots=True)
class GetGroup(Query[GroupView]):
    group_id: int
    viewer_id: int


@dataclass(frozen=True, slots=True)
class ListGroupPosts(Query[list[PostView]]):
    group_id: int
    viewer_id: int
    after_id: int = 0
    limit: int = 50


__all__ = [
    "ChangeDisplayName",
    "CreateGroup",
    "GetGroup",
    "GetMember",
    "GroupView",
    "HidePost",
    "JoinGroup",
    "ListGroupPosts",
    "MemberView",
    "MembershipRequestView",
    "PostView",
    "PublishPost",
    "RegisteredMemberView",
    "RegisterMember",
    "ReviewMembership",
    "SuspendMember",
]

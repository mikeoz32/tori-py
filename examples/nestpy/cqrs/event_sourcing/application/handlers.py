"""CQRS handlers orchestrating aggregate decisions and committed writes."""

from typing import Annotated

from nestpy import Inject, Scope
from nestpy_cqrs import command_handler, query_handler
from nestpy_cqrs_event_sourcing import (
    CommandSynchronization,
    aggregate_repository,
    get_command_synchronization_token,
    use_event_sourcing,
)

from examples.nestpy.cqrs.event_sourcing.application.messages import (
    ChangeDisplayName,
    CreateGroup,
    GetGroup,
    GetMember,
    GroupView,
    HidePost,
    JoinGroup,
    ListGroupPosts,
    MembershipRequestView,
    MemberView,
    PostView,
    PublishPost,
    RegisterMember,
    ReviewMembership,
    SuspendMember,
)
from examples.nestpy.cqrs.event_sourcing.application.projection import (
    ProjectionService,
)
from examples.nestpy.cqrs.event_sourcing.domain.group import Group
from examples.nestpy.cqrs.event_sourcing.domain.member import Member
from examples.nestpy.cqrs.event_sourcing.domain.post import Post
from examples.nestpy.cqrs.event_sourcing.domain.shared import (
    AccessDeniedError,
    DomainNotFoundError,
)
from examples.nestpy.cqrs.event_sourcing.infrastructure.repositories import (
    GroupRepository,
    MemberRepository,
    PostRepository,
)
from examples.nestpy.cqrs.event_sourcing.infrastructure.services import (
    ContentVault,
    IdSequence,
    PlatformPolicy,
)


class _CommandHandlerBase:
    @staticmethod
    def _member_view(member: Member) -> MemberView:
        return MemberView(
            member.id,
            member.handle,
            member.display_name,
            member.visibility,
            member.suspended,
        )

    @staticmethod
    def _group_view(group: Group, *, viewer_id: int) -> GroupView:
        moderator = viewer_id in group.moderators
        return GroupView(
            group.id,
            group.owner_id,
            group.name,
            group.access,
            len(group.members),
            len(group.pending_members),
            tuple(sorted(group.members))[:100] if moderator else (),
            tuple(sorted(group.moderators))[:100] if moderator else (),
            tuple(sorted(group.pending_members))[:100] if moderator else (),
        )

    @staticmethod
    def _post_view(post: Post, *, body: str | None) -> PostView:
        return PostView(
            post.id,
            post.group_id,
            post.author_id,
            post.title,
            body,
            post.hidden,
            post.hidden_reason,
        )


@use_event_sourcing(key="community")
@command_handler(RegisterMember, scope=Scope.REQUEST)
class RegisterMemberHandler(_CommandHandlerBase):
    def __init__(
        self,
        members: Annotated[
            MemberRepository,
            aggregate_repository(MemberRepository),
        ],
        ids: IdSequence,
    ) -> None:
        self._members = members
        self._ids = ids

    async def handle(self, command: RegisterMember) -> MemberView:
        member = Member(self._ids.next())
        member.register(
            handle=command.handle,
            display_name=command.display_name,
            visibility=command.visibility,
        )
        self._members.save(member)
        return self._member_view(member)


@use_event_sourcing(key="community")
@command_handler(ChangeDisplayName, scope=Scope.REQUEST)
class ChangeDisplayNameHandler(_CommandHandlerBase):
    def __init__(
        self,
        members: Annotated[
            MemberRepository,
            aggregate_repository(MemberRepository),
        ],
    ) -> None:
        self._members = members

    async def handle(self, command: ChangeDisplayName) -> MemberView:
        if command.actor_id != command.member_id:
            raise AccessDeniedError("resource was not found")
        member = await self._members.get(command.member_id)
        member.change_display_name(
            actor_id=command.actor_id,
            display_name=command.display_name,
        )
        self._members.save(member)
        return self._member_view(member)


@use_event_sourcing(key="community")
@command_handler(SuspendMember, scope=Scope.REQUEST)
class SuspendMemberHandler(_CommandHandlerBase):
    def __init__(
        self,
        members: Annotated[
            MemberRepository,
            aggregate_repository(MemberRepository),
        ],
        policy: PlatformPolicy,
    ) -> None:
        self._members = members
        self._policy = policy

    async def handle(self, command: SuspendMember) -> MemberView:
        actor = await self._members.get(command.actor_id)
        actor.ensure_active()
        member = (
            actor
            if command.member_id == command.actor_id
            else await self._members.get(command.member_id)
        )
        member.suspend(
            actor_id=command.actor_id,
            reason=command.reason,
            authorized=self._policy.can_suspend(command.actor_id),
        )
        self._members.save(member)
        return self._member_view(member)


@use_event_sourcing(key="community")
@command_handler(CreateGroup, scope=Scope.REQUEST)
class CreateGroupHandler(_CommandHandlerBase):
    def __init__(
        self,
        members: Annotated[
            MemberRepository,
            aggregate_repository(MemberRepository),
        ],
        groups: Annotated[
            GroupRepository,
            aggregate_repository(GroupRepository),
        ],
        ids: IdSequence,
    ) -> None:
        self._members = members
        self._groups = groups
        self._ids = ids

    async def handle(self, command: CreateGroup) -> GroupView:
        owner = await self._members.get(command.actor_id)
        owner.ensure_active()
        group = Group(self._ids.next())
        group.create(
            owner_id=owner.id,
            name=command.name,
            access=command.access,
        )
        self._groups.save(group)
        return self._group_view(group, viewer_id=owner.id)


@use_event_sourcing(key="community")
@command_handler(JoinGroup, scope=Scope.REQUEST)
class JoinGroupHandler(_CommandHandlerBase):
    def __init__(
        self,
        members: Annotated[
            MemberRepository,
            aggregate_repository(MemberRepository),
        ],
        groups: Annotated[
            GroupRepository,
            aggregate_repository(GroupRepository),
        ],
    ) -> None:
        self._members = members
        self._groups = groups

    async def handle(self, command: JoinGroup) -> GroupView | MembershipRequestView:
        member = await self._members.get(command.actor_id)
        member.ensure_active()
        group = await self._groups.get(command.group_id)
        group.request_membership(member_id=member.id)
        self._groups.save(group)
        if member.id not in group.members:
            return MembershipRequestView(group.id, "pending")
        return self._group_view(group, viewer_id=member.id)


@use_event_sourcing(key="community")
@command_handler(ReviewMembership, scope=Scope.REQUEST)
class ReviewMembershipHandler(_CommandHandlerBase):
    def __init__(
        self,
        members: Annotated[
            MemberRepository,
            aggregate_repository(MemberRepository),
        ],
        groups: Annotated[
            GroupRepository,
            aggregate_repository(GroupRepository),
        ],
    ) -> None:
        self._members = members
        self._groups = groups

    async def handle(self, command: ReviewMembership) -> GroupView:
        actor = await self._members.get(command.actor_id)
        actor.ensure_active()
        group = await self._groups.get(command.group_id)
        group.require_pending(command.member_id)
        target = await self._members.get(command.member_id)
        if command.approve:
            target.ensure_active()
        group.review_membership(
            actor_id=command.actor_id,
            member_id=command.member_id,
            approve=command.approve,
            reason=command.reason,
        )
        self._groups.save(group)
        return self._group_view(group, viewer_id=command.actor_id)


@use_event_sourcing(key="community")
@command_handler(PublishPost, scope=Scope.REQUEST)
class PublishPostHandler(_CommandHandlerBase):
    def __init__(
        self,
        members: Annotated[
            MemberRepository,
            aggregate_repository(MemberRepository),
        ],
        groups: Annotated[
            GroupRepository,
            aggregate_repository(GroupRepository),
        ],
        posts: Annotated[
            PostRepository,
            aggregate_repository(PostRepository),
        ],
        ids: IdSequence,
        content: ContentVault,
        synchronization: Annotated[
            CommandSynchronization,
            Inject(get_command_synchronization_token(key="community")),
        ],
    ) -> None:
        self._members = members
        self._groups = groups
        self._posts = posts
        self._ids = ids
        self._content = content
        self._synchronization = synchronization

    async def handle(self, command: PublishPost) -> PostView:
        member = await self._members.get(command.actor_id)
        member.ensure_active()
        group = await self._groups.get(command.group_id)
        group.require_member(member.id)
        content_ref = self._content.put(command.body)
        self._synchronization.after_confirmed_non_commit(
            lambda: self._content.erase(content_ref)
        )
        post = Post(self._ids.next())
        post.publish(
            group_id=group.id,
            author_id=member.id,
            title=command.title,
            content_ref=content_ref,
        )
        self._posts.save(post)
        return self._post_view(post, body=command.body)


@use_event_sourcing(key="community")
@command_handler(HidePost, scope=Scope.REQUEST)
class HidePostHandler(_CommandHandlerBase):
    def __init__(
        self,
        members: Annotated[
            MemberRepository,
            aggregate_repository(MemberRepository),
        ],
        groups: Annotated[
            GroupRepository,
            aggregate_repository(GroupRepository),
        ],
        posts: Annotated[
            PostRepository,
            aggregate_repository(PostRepository),
        ],
    ) -> None:
        self._members = members
        self._groups = groups
        self._posts = posts

    async def handle(self, command: HidePost) -> PostView:
        actor = await self._members.get(command.actor_id)
        actor.ensure_active()
        group = await self._groups.get(command.group_id)
        group.require_moderator(command.actor_id)
        post = await self._posts.get(command.post_id)
        if post.group_id != group.id:
            raise DomainNotFoundError("post was not found")
        post.hide(moderator_id=command.actor_id, reason=command.reason)
        self._posts.save(post)
        return self._post_view(post, body=None)


class _QueryHandlerBase:
    def __init__(self, projections: ProjectionService) -> None:
        self._projections = projections


@query_handler(GetMember, scope=Scope.TRANSIENT)
class GetMemberHandler(_QueryHandlerBase):
    async def handle(self, query: GetMember) -> MemberView:
        projection = await self._projections.catch_up()
        return projection.member(query.member_id, viewer_id=query.viewer_id)


@query_handler(GetGroup, scope=Scope.TRANSIENT)
class GetGroupHandler(_QueryHandlerBase):
    async def handle(self, query: GetGroup) -> GroupView:
        projection = await self._projections.catch_up()
        return projection.group(query.group_id, viewer_id=query.viewer_id)


@query_handler(ListGroupPosts, scope=Scope.TRANSIENT)
class ListGroupPostsHandler(_QueryHandlerBase):
    async def handle(self, query: ListGroupPosts) -> list[PostView]:
        projection = await self._projections.catch_up()
        return projection.posts(
            query.group_id,
            viewer_id=query.viewer_id,
            after_id=query.after_id,
            limit=query.limit,
        )


__all__ = [
    "ChangeDisplayNameHandler",
    "CreateGroupHandler",
    "GetGroupHandler",
    "GetMemberHandler",
    "HidePostHandler",
    "JoinGroupHandler",
    "ListGroupPostsHandler",
    "PublishPostHandler",
    "RegisterMemberHandler",
    "ReviewMembershipHandler",
    "SuspendMemberHandler",
]

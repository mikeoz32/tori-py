"""Checkpointed projection over the committed global event feed."""

import asyncio
from bisect import bisect_left, bisect_right, insort
from dataclasses import dataclass, field
from typing import Annotated

from cqrs_event_sourcing import EventSchemaRegistry, EventStore, RecordedEvent
from nestpy import Inject, injectable
from nestpy_cqrs_event_sourcing import get_event_store_token, get_schema_registry_token

from examples.nestpy.cqrs.event_sourcing.application.messages import (
    GroupView,
    MemberView,
    PostView,
)
from examples.nestpy.cqrs.event_sourcing.domain.group import (
    GroupCreated,
    MemberJoined,
    MembershipRejected,
    MembershipRequested,
    ModeratorGranted,
)
from examples.nestpy.cqrs.event_sourcing.domain.member import (
    DisplayNameChanged,
    MemberRegistered,
    MemberSuspended,
)
from examples.nestpy.cqrs.event_sourcing.domain.post import (
    PostEdited,
    PostHidden,
    PostPublished,
)
from examples.nestpy.cqrs.event_sourcing.domain.shared import (
    DomainNotFoundError,
    DomainValidationError,
    GroupAccess,
    Visibility,
)
from examples.nestpy.cqrs.event_sourcing.infrastructure.services import ContentVault


class ProjectionUnavailableError(Exception):
    """Raised when the read model cannot safely reach the committed feed head."""


@dataclass(slots=True)
class _MemberState:
    id: int
    handle: str
    display_name: str
    visibility: Visibility
    suspended: bool = False


@dataclass(slots=True)
class _GroupState:
    id: int
    owner_id: int
    name: str
    access: GroupAccess
    members: set[int] = field(default_factory=set)
    moderators: set[int] = field(default_factory=set)
    pending_members: set[int] = field(default_factory=set)


@dataclass(slots=True)
class _PostState:
    id: int
    group_id: int
    author_id: int
    title: str
    content_ref: int
    hidden: bool = False
    moderation_reason: str | None = None


@injectable()
class CommunityProjection:
    """In-process read model with explicit privacy and moderation filtering."""

    def __init__(self, content: ContentVault) -> None:
        self._content = content
        self._members: dict[int, _MemberState] = {}
        self._groups: dict[int, _GroupState] = {}
        self._posts: dict[int, _PostState] = {}
        self._posts_by_group: dict[int, list[int]] = {}
        self._visible_posts_by_group: dict[int, list[int]] = {}
        self._checkpoint = 0
        self._lock = asyncio.Lock()

    @property
    def checkpoint(self) -> int:
        return self._checkpoint

    async def catch_up(
        self,
        store: EventStore,
        schemas: EventSchemaRegistry,
        *,
        max_pages: int = 8,
    ) -> None:
        async with self._lock:
            for _ in range(max_pages):
                page = await store.read_all(
                    after_position=self._checkpoint,
                    limit=schemas.limits.read_page_size,
                )
                if not page:
                    return
                for stored in page:
                    self._apply(schemas.decode(stored))
                    self._checkpoint = stored.global_position
                if len(page) < schemas.limits.read_page_size:
                    return
            remaining = await store.read_all(
                after_position=self._checkpoint,
                limit=1,
            )
            if remaining:
                raise ProjectionUnavailableError(
                    "projection catch-up budget was exhausted"
                )

    def member(self, member_id: int, *, viewer_id: int | None) -> MemberView:
        state = self._member(member_id)
        if viewer_id is not None and viewer_id != member_id:
            self._require_active_viewer(viewer_id)
        if state.visibility is Visibility.PRIVATE and viewer_id != member_id:
            raise DomainNotFoundError("member was not found")
        if state.visibility is Visibility.MEMBERS and viewer_id is None:
            raise DomainNotFoundError("member was not found")
        return MemberView(
            state.id,
            state.handle,
            state.display_name,
            state.visibility,
            state.suspended,
        )

    def group(self, group_id: int, *, viewer_id: int) -> GroupView:
        self._require_active_viewer(viewer_id)
        state = self._group(group_id)
        if state.access is GroupAccess.PRIVATE and viewer_id not in state.members:
            raise DomainNotFoundError("group was not found")
        visible_roster = viewer_id in state.moderators
        pending = (
            tuple(sorted(state.pending_members))
            if viewer_id in state.moderators
            else ()
        )
        return GroupView(
            state.id,
            state.owner_id,
            state.name,
            state.access,
            len(state.members),
            len(state.pending_members),
            tuple(sorted(state.members))[:100] if visible_roster else (),
            tuple(sorted(state.moderators))[:100] if visible_roster else (),
            pending,
        )

    def posts(
        self,
        group_id: int,
        *,
        viewer_id: int,
        after_id: int,
        limit: int,
    ) -> list[PostView]:
        self._require_active_viewer(viewer_id)
        if limit < 1 or limit > 100 or after_id < 0:
            raise DomainValidationError(
                "post page must use after_id >= 0 and limit 1-100"
            )
        group = self._group(group_id)
        if viewer_id not in group.members:
            raise DomainNotFoundError("group was not found")
        moderator = viewer_id in group.moderators
        post_ids = (
            self._posts_by_group if moderator else self._visible_posts_by_group
        ).get(group_id, ())
        start = bisect_right(post_ids, after_id)
        return [
            self._post_view(self._posts[post_id], moderator=moderator)
            for post_id in post_ids[start : start + limit]
        ]

    def post(self, post_id: int, *, viewer_id: int) -> PostView:
        self._require_active_viewer(viewer_id)
        try:
            post = self._posts[post_id]
        except KeyError as error:
            raise DomainNotFoundError("post was not found") from error
        group = self._group(post.group_id)
        if viewer_id not in group.members:
            raise DomainNotFoundError("post was not found")
        moderator = viewer_id in group.moderators
        if post.hidden and not moderator:
            raise DomainNotFoundError("post was not found")
        return self._post_view(post, moderator=moderator)

    def _post_view(self, post: _PostState, *, moderator: bool) -> PostView:
        body = None if post.hidden else self._content.get(post.content_ref)
        return PostView(
            post.id,
            post.group_id,
            post.author_id,
            post.title,
            body,
            post.hidden,
            post.moderation_reason if moderator else None,
        )

    def _member(self, member_id: int) -> _MemberState:
        try:
            return self._members[member_id]
        except KeyError as error:
            raise DomainNotFoundError("member was not found") from error

    def _group(self, group_id: int) -> _GroupState:
        try:
            return self._groups[group_id]
        except KeyError as error:
            raise DomainNotFoundError("group was not found") from error

    def _require_active_viewer(self, viewer_id: int) -> None:
        if self._member(viewer_id).suspended:
            raise DomainNotFoundError("resource was not found")

    def _apply(self, record: RecordedEvent) -> None:
        aggregate_id = int(record.stream_id.key)
        match record.event:
            case MemberRegistered(
                handle=handle,
                display_name=display_name,
                visibility=visibility,
            ):
                self._members[aggregate_id] = _MemberState(
                    aggregate_id,
                    handle,
                    display_name,
                    visibility,
                )
            case DisplayNameChanged(display_name=display_name):
                self._member(aggregate_id).display_name = display_name
            case MemberSuspended():
                self._member(aggregate_id).suspended = True
            case GroupCreated(owner_id=owner_id, name=name, access=access):
                self._groups[aggregate_id] = _GroupState(
                    id=aggregate_id,
                    owner_id=owner_id,
                    name=name,
                    access=access,
                    members={owner_id},
                    moderators={owner_id},
                )
            case MembershipRequested(member_id=member_id):
                self._group(aggregate_id).pending_members.add(member_id)
            case MemberJoined(member_id=member_id):
                group = self._group(aggregate_id)
                group.pending_members.discard(member_id)
                group.members.add(member_id)
            case MembershipRejected(member_id=member_id):
                self._group(aggregate_id).pending_members.discard(member_id)
            case ModeratorGranted(member_id=member_id):
                self._group(aggregate_id).moderators.add(member_id)
            case PostPublished(
                group_id=group_id,
                author_id=author_id,
                title=title,
                content_ref=content_ref,
            ):
                self._posts[aggregate_id] = _PostState(
                    aggregate_id,
                    group_id,
                    author_id,
                    title,
                    content_ref,
                )
                insort(self._posts_by_group.setdefault(group_id, []), aggregate_id)
                insort(
                    self._visible_posts_by_group.setdefault(group_id, []),
                    aggregate_id,
                )
            case PostEdited(title=title, content_ref=content_ref):
                post = self._posts[aggregate_id]
                post.title = title
                post.content_ref = content_ref
            case PostHidden(reason=reason):
                post = self._posts[aggregate_id]
                post.hidden = True
                post.moderation_reason = reason
                visible = self._visible_posts_by_group[post.group_id]
                index = bisect_left(visible, aggregate_id)
                if index < len(visible) and visible[index] == aggregate_id:
                    visible.pop(index)
            case _:
                raise AssertionError(f"unknown projection event: {record.event!r}")


@injectable()
class ProjectionService:
    """Application service that advances the read model after committed writes."""

    def __init__(
        self,
        store: Annotated[
            EventStore,
            Inject(get_event_store_token(key="community")),
        ],
        schemas: Annotated[
            EventSchemaRegistry,
            Inject(get_schema_registry_token(key="community")),
        ],
        projection: CommunityProjection,
    ) -> None:
        self._store = store
        self._schemas = schemas
        self.projection = projection

    async def catch_up(self) -> CommunityProjection:
        await self.projection.catch_up(self._store, self._schemas)
        return self.projection


__all__ = [
    "CommunityProjection",
    "ProjectionService",
    "ProjectionUnavailableError",
]
